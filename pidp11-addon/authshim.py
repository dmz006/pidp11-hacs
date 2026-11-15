#!/usr/bin/env python3
"""
Auth shim: accepts TCP on LISTEN_PORT (default 2223), requires
    AUTH <secret>\n
then proxies the byte stream to SimH's native remote console on SIMH_PORT (default 2224).

Also serves a watch stream on WATCH_PORT (default 2225) that streams SR register
changes in near-real-time by maintaining a single long-lived SimH connection.

Also serves a lamp stream on LAMP_PORT (default 2226) that streams PC/PSW register
values at ~20 Hz for the Lovelace live animation. A client that authenticates with
    AUTH <secret> +sr\n
gets the SR register on the same stream (``EVENT sr value=<octal>`` lines), so one
connection can carry everything the integration needs.

Connection budget: every client of this shim holds one SimH remote-console
connection, and SimH only accepts a fixed number of them. Every boot.ini in
this repo sets ``set remote connections=4``; past that SimH answers
"All connections busy" and hangs up. So the backend connection must be released
as soon as the client side is gone, whatever way it went (FIN, RST, silence).
Each handler therefore closes its backend connection in a ``finally`` block, the
stream handlers watch the client side for EOF instead of waiting for a write to
fail (they only write when a register changes, which on a quiet machine is
never), and the proxy closes sessions that have been idle for IDLE_TIMEOUT.

A client on the lamp port that sends ``AUTH <secret> +lamps`` (optionally with
``fps=N``) gets ``LAMPS2 <json>`` lines instead: front-panel lamp percentages
sampled from the Pi's GPIO by gpio_lamps.py, shared by every such client. Those
clients hold no SimH connection unless they also send ``+sr``. If the GPIO
device cannot be opened the shim serves the ``EVENT lamps`` stream as before.

Wire protocol is documented in docs/contracts/remote-console.md.
"""
import asyncio
import hmac
import json
import os
import re
import socket
import sys
from collections.abc import Awaitable, Callable

from gpio_lamps import (
    LampFeedFailed,
    LampUnavailable,
    SharedLampFeed,
    clamp_fps,
    lamps_changed,
)

LISTEN_PORT = int(os.environ.get("AUTHSHIM_PORT", "2223"))
SIMH_PORT   = int(os.environ.get("SIMH_PORT",     "2224"))
SECRET_FILE = os.environ.get("SECRET_FILE", "/data/remote_console.secret")
# Written by run.sh each time a system is booted; read for the SYSTEM answer.
CURRENT_SYSTEM_FILE = os.environ.get("CURRENT_SYSTEM_FILE", "/share/pidp11/current_system")
AUTH_TIMEOUT = 5.0
VERSION = "1.0.0"

_PROMPT = b"sim> "
_BUSY = b"All connections busy"  # what SimH says when `remote connections=N` is used up
_CONNECT_TIMEOUT = 5.0
_DRAIN_QUIET = 0.3
_CLOSE_TIMEOUT = 2.0
_WRITE_TIMEOUT = 10.0
WATCH_PORT = int(os.environ.get("WATCH_PORT", str(LISTEN_PORT + 2)))
WATCH_INTERVAL_MS = float(os.environ.get("WATCH_INTERVAL_MS", "250"))
LAMP_PORT = int(os.environ.get("LAMP_PORT", str(LISTEN_PORT + 3)))
LAMP_INTERVAL_MS = float(os.environ.get("LAMP_INTERVAL_MS", "50"))  # 20 Hz
# A proxied session with no traffic in either direction for this long is closed
# so a vanished client cannot hold a SimH connection forever.
IDLE_TIMEOUT = float(os.environ.get("IDLE_TIMEOUT", "3600"))
# Streams send a comment line when nothing else was written for this long. It
# lets the shim notice a dead client by the failed write, and tells the client
# the shim is alive.
HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", "15"))

_FLAG_SR = "+sr"
# `AUTH <secret> +lamps [fps=N]` on the lamp port asks for sampled LAMPS2 lines.
_FLAG_LAMPS = "+lamps"
# A LAMPS2 client is sent its current lamp frame at least this often.
LAMPS_KEEPALIVE_S = 2.0
# How long a LAMPS2 stream waits for a new frame before it looks at the client
# again (so a vanished client is noticed) and polls SR when that is due.
_LAMPS_POLL_S = 0.25
# One sampler for all LAMPS2 clients; it runs only while a client is subscribed.
_lamp_feed = SharedLampFeed()
# `AUTH <secret> +system` on the main port asks for the current system name.
# The shim answers `SYSTEM <name>` and closes, without opening a SimH connection.
_FLAG_SYSTEM = "+system"
_UNKNOWN_SYSTEM = "unknown"
_SYSTEM_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


class _BackendGone(Exception):
    """SimH stopped answering (closed, reset or timed out)."""


def _load_secret() -> str:
    with open(SECRET_FILE) as fh:
        return fh.read().strip()


def _read_system_name() -> str:
    """Name of the system last booted, or "unknown" if missing, empty or odd."""
    try:
        with open(CURRENT_SYSTEM_FILE, encoding="utf-8", errors="replace") as fh:
            name = fh.read().strip()
    except OSError:
        return _UNKNOWN_SYSTEM
    return name if _SYSTEM_NAME_RE.match(name) else _UNKNOWN_SYSTEM


def _parse_sr(text: str) -> str | None:
    """Extract octal value from SimH register output.

    Scans all lines for 'REG:\\t<octal>' pattern and returns the first match.
    Works for SR, PC, PSW — they all use the same format.
    """
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        m = re.match(r"\S+:\s+([0-7]+)", line.strip())
        if m:
            return m.group(1)
    return None


# ── Connection hygiene ────────────────────────────────────────────────────────

def _enable_keepalive(writer: asyncio.StreamWriter) -> None:
    """Make the kernel notice a client that vanished without a FIN or RST."""
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for name, value in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
            opt = getattr(socket, name, None)
            if opt is not None:
                sock.setsockopt(socket.IPPROTO_TCP, opt, value)
    except OSError:
        pass


async def _close(writer: asyncio.StreamWriter | None) -> None:
    """Close a stream and give the transport a moment to finish; never raises."""
    if writer is None:
        return
    try:
        writer.close()
    except Exception:
        return
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=_CLOSE_TIMEOUT)
    except Exception:
        try:
            writer.transport.abort()
        except Exception:
            pass


def _client_gone(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    """True once the client has closed (FIN), reset (RST) or been closed by us.

    ``writer.is_closing()`` alone misses a graceful FIN: asyncio keeps the
    transport open for a half-close, so the only sign is EOF on the reader.
    """
    return writer.is_closing() or reader.at_eof() or reader.exception() is not None


async def _open_simh() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.wait_for(
        asyncio.open_connection("127.0.0.1", SIMH_PORT),
        timeout=_CONNECT_TIMEOUT,
    )


async def _authenticate(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> frozenset[str] | None:
    """Read and check the AUTH line.

    Returns the ``+flag`` options and ``fps=N`` tokens the client asked for
    (usually empty), or None after answering DENY. ``AUTH <secret>`` is the whole
    protocol for old clients; flags follow the secret after a space.
    """
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=AUTH_TIMEOUT)
    except TimeoutError:
        writer.write(b"DENY auth-timeout\n")
        await writer.drain()
        return None

    line = raw.decode(errors="replace").rstrip("\r\n")
    if line.startswith("AUTH "):
        rest = line[len("AUTH "):].encode()
        secret = _load_secret().encode()
        if hmac.compare_digest(rest, secret):
            return frozenset()
        n = len(secret)
        if rest[n : n + 1] == b" " and hmac.compare_digest(rest[:n], secret):
            flags = rest[n + 1 :].decode(errors="replace").split()
            return frozenset(w for w in flags if w.startswith(("+", "fps=")))
    writer.write(b"DENY bad-auth\n")
    await writer.drain()
    return None


# ── SimH helpers ──────────────────────────────────────────────────────────────

async def _drain_simh_banner(reader: asyncio.StreamReader) -> bytes:
    """Read until sim> prompt, then drain until quiet. Returns everything read."""
    buf = bytearray()
    try:
        buf.extend(await asyncio.wait_for(reader.readuntil(_PROMPT), timeout=_CONNECT_TIMEOUT))
    except (TimeoutError, asyncio.IncompleteReadError) as exc:
        if isinstance(exc, asyncio.IncompleteReadError):
            buf.extend(exc.partial)
    # Drain remaining buffered data until quiet
    while True:
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=_DRAIN_QUIET)
            if not chunk:
                break
            buf.extend(chunk)
        except TimeoutError:
            break
    return bytes(buf)


async def _poll_register(
    simh_r: asyncio.StreamReader,
    simh_w: asyncio.StreamWriter,
    cmd: str,
) -> str | None:
    """Send one EXAMINE command, read to sim>, return parsed register value.

    Returns None when the reply had no register in it; raises _BackendGone when
    SimH is no longer there to answer.
    """
    try:
        simh_w.write(f"{cmd}\n".encode())
        await simh_w.drain()
        raw = await asyncio.wait_for(simh_r.readuntil(_PROMPT), timeout=_CONNECT_TIMEOUT)
    except (TimeoutError, OSError, asyncio.IncompleteReadError) as exc:
        raise _BackendGone(cmd) from exc
    text = raw[: -len(_PROMPT)].decode(errors="replace")
    return _parse_sr(text)


# ── Streams (watch + lamps) ───────────────────────────────────────────────────

# One polling step: returns the lines to send (possibly none) or None to end the stream.
_Step = Callable[[], Awaitable[list[bytes] | None]]
_StepFactory = Callable[[asyncio.StreamReader, asyncio.StreamWriter, frozenset[str]], _Step]


def _requested_fps(flags: frozenset[str]) -> int | None:
    """The ``fps=N`` a client asked for, clamped; None when absent or not a number."""
    for word in sorted(flags):
        if word.startswith("fps="):
            try:
                return clamp_fps(int(word[len("fps="):]))
            except ValueError:
                return None
    return None


async def _lamps2_body(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    flags: frozenset[str],
    feed: SharedLampFeed,
) -> None:
    """Send ``LAMPS2`` lines from the shared sampler until the client leaves.

    A line goes out when a lamp moved by two points or more since the last line
    sent on this connection, and at least every LAMPS_KEEPALIVE_S seconds (the
    keepalive repeats the current frame). ``seq`` counts the lines sent on this
    connection. With ``+sr`` the stream also polls SR on the watch cadence, over
    a SimH connection this stream owns and closes.
    """
    loop = asyncio.get_running_loop()
    simh_r: asyncio.StreamReader | None = None
    simh_w: asyncio.StreamWriter | None = None
    try:
        if _FLAG_SR in flags:
            simh_r, simh_w = await _open_simh()
            banner = await _drain_simh_banner(simh_r)
            if _BUSY in banner:
                print(
                    "[authshim] lamp stream from "
                    f"{writer.get_extra_info('peername')}: SimH has no free remote connection",
                    file=sys.stderr,
                    flush=True,
                )
                return

        seen = 0
        sent = 0
        last_sent: dict[str, int] | None = None
        last_sent_at: float | None = None
        sr_prev: str | None = None
        sr_due = 0.0
        while not _client_gone(reader, writer):
            now = loop.time()
            if simh_r is not None and simh_w is not None and now >= sr_due:
                sr = await _poll_register(simh_r, simh_w, "EXAMINE SR")
                sr_due = now + WATCH_INTERVAL_MS / 1000.0
                if sr is not None and sr != sr_prev:
                    sr_prev = sr
                    writer.write(f"EVENT sr value={sr}\n".encode())
                    await asyncio.wait_for(writer.drain(), timeout=_WRITE_TIMEOUT)

            try:
                got = await feed.next_frame(seen, _LAMPS_POLL_S)
            except LampFeedFailed:
                return
            now = loop.time()

            out: dict[str, int] | None = None
            if got is not None:
                seen, frame = got
                if last_sent_at is None or lamps_changed(last_sent, frame):
                    out = frame
            if out is None and last_sent_at is not None and now - last_sent_at >= LAMPS_KEEPALIVE_S:
                latest = feed.latest()
                out = latest[1] if latest is not None else None
            if out is not None:
                sent += 1
                last_sent = out
                last_sent_at = now
                body = json.dumps({"seq": sent, "leds": out}, sort_keys=True, separators=(",", ":"))
                writer.write(f"LAMPS2 {body}\n".encode())
                await asyncio.wait_for(writer.drain(), timeout=_WRITE_TIMEOUT)
    finally:
        await _close(simh_w)


async def _stream_session(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    label: str,
    interval_s: float,
    make_step: _StepFactory,
    *,
    lamps: bool = False,
) -> None:
    """Common life cycle of a watch or lamp stream.

    1. Client sends AUTH <secret>[ +flags]\\n
    2. Server responds OK\\n
    3. Server opens one dedicated SimH connection, drains the banner
    4. Server polls on an interval and streams EVENT lines; sends a comment
       heartbeat when quiet
    5. Ends when the client goes away (EOF, reset, write failure) or SimH does;
       the SimH connection is always closed on the way out

    With ``lamps`` and a ``+lamps`` flag, step 3 is replaced by the shared GPIO
    sampler (``_lamps2_body``) when the sampler opens; otherwise the stream is
    the ``EVENT`` stream above.
    """
    peer = writer.get_extra_info("peername")
    simh_w: asyncio.StreamWriter | None = None
    feed = _lamp_feed
    token: object | None = None
    try:
        _enable_keepalive(writer)
        flags = await _authenticate(reader, writer)
        if flags is None:
            return

        if lamps and _FLAG_LAMPS in flags:
            try:
                token = await feed.subscribe(_requested_fps(flags))
            except LampUnavailable as exc:
                print(
                    f"[authshim] {label} sampler unavailable, serving EVENT lamps: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

        writer.write(b"OK\n")
        await writer.drain()

        if token is not None:
            await _lamps2_body(reader, writer, flags, feed)
            return

        try:
            simh_r, simh_w = await _open_simh()
        except (TimeoutError, OSError):
            # SimH not available — close silently
            return

        banner = await _drain_simh_banner(simh_r)
        if _BUSY in banner:
            print(
                f"[authshim] {label} stream from {peer}: SimH has no free remote connection",
                file=sys.stderr,
                flush=True,
            )
            return

        step = make_step(simh_r, simh_w, flags)
        loop = asyncio.get_running_loop()
        last_write = loop.time()
        while not _client_gone(reader, writer):
            lines = await step()
            if lines is None:
                break
            now = loop.time()
            wrote = bool(lines)
            for line in lines:
                writer.write(line)
            if not wrote and now - last_write >= HEARTBEAT_INTERVAL:
                writer.write(b"# keepalive\n")
                wrote = True
            if wrote:
                last_write = now
                await asyncio.wait_for(writer.drain(), timeout=_WRITE_TIMEOUT)
            await asyncio.sleep(interval_s)

    except (OSError, asyncio.IncompleteReadError, _BackendGone):
        pass
    except Exception as exc:
        print(f"[authshim] {label} error from {peer}: {exc}", file=sys.stderr, flush=True)
    finally:
        if token is not None:
            feed.unsubscribe(token)
        await _close(simh_w)
        await _close(writer)


def _watch_step(
    simh_r: asyncio.StreamReader, simh_w: asyncio.StreamWriter, _flags: frozenset[str]
) -> _Step:
    prev_sr: str | None = None

    async def step() -> list[bytes] | None:
        nonlocal prev_sr
        sr = await _poll_register(simh_r, simh_w, "EXAMINE SR")
        if sr is not None and sr != prev_sr:
            prev_sr = sr
            return [f"EVENT sr value={sr}\n".encode()]
        return []

    return step


def _lamp_step(
    simh_r: asyncio.StreamReader, simh_w: asyncio.StreamWriter, flags: frozenset[str]
) -> _Step:
    with_sr = _FLAG_SR in flags
    # SR changes at human speed; look at it on the watch cadence, not the lamp one.
    sr_every = max(1, round(WATCH_INTERVAL_MS / LAMP_INTERVAL_MS))
    prev_pc: str | None = None
    prev_ps: str | None = None
    prev_sr: str | None = None
    cycle = 0

    async def step() -> list[bytes] | None:
        nonlocal prev_pc, prev_ps, prev_sr, cycle
        out: list[bytes] = []

        pc = await _poll_register(simh_r, simh_w, "EXAMINE PC")
        if pc is None:
            return None
        ps = await _poll_register(simh_r, simh_w, "EXAMINE PSW")
        if ps is None:
            return None

        if with_sr and cycle % sr_every == 0:
            sr = await _poll_register(simh_r, simh_w, "EXAMINE SR")
            if sr is not None and sr != prev_sr:
                prev_sr = sr
                out.append(f"EVENT sr value={sr}\n".encode())
        cycle += 1

        if prev_pc is None or pc != prev_pc or ps != prev_ps:
            out.append(f"EVENT lamps ADDRESS={pc} DATA={ps}\n".encode())
            prev_pc = pc
            prev_ps = ps
        return out

    return step


async def _handle_watch(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Handle a watch stream connection.

    Streams ``EVENT sr value=<octal>`` on initial connect and on change.
    """
    await _stream_session(reader, writer, "watch", WATCH_INTERVAL_MS / 1000.0, _watch_step)


async def _handle_lamp_stream(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Handle a lamp stream connection.

    Streams ``EVENT lamps ADDRESS=<pc> DATA=<psw>`` on change, and with the
    ``+sr`` flag also ``EVENT sr value=<octal>`` on change.
    """
    await _stream_session(
        reader, writer, "lamp", LAMP_INTERVAL_MS / 1000.0, _lamp_step, lamps=True
    )


# ── Plain proxy ───────────────────────────────────────────────────────────────

async def _pipe(
    src: asyncio.StreamReader, dst: asyncio.StreamWriter, activity: list[float]
) -> None:
    """Copy src to dst until EOF, error or IDLE_TIMEOUT without traffic either way.

    ``activity`` is shared by both directions: one holds the timestamp of the last
    byte moved by either, so a session that is only receiving is not idle.
    """
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                data = await asyncio.wait_for(src.read(4096), timeout=IDLE_TIMEOUT)
            except TimeoutError:
                if loop.time() - activity[0] >= IDLE_TIMEOUT:
                    return
                continue
            if not data:
                return
            activity[0] = loop.time()
            dst.write(data)
            await dst.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    simh_w: asyncio.StreamWriter | None = None
    try:
        _enable_keepalive(writer)
        flags = await _authenticate(reader, writer)
        if flags is None:
            return

        writer.write(b"OK\n")
        writer.write(f"# pidp11-authshim {VERSION}\n".encode())
        if _FLAG_SYSTEM in flags:
            # Answered here, before any SimH connection: the console has four
            # slots and the integration's budget is two.
            name = await asyncio.to_thread(_read_system_name)
            writer.write(f"SYSTEM {name}\n".encode())
            await writer.drain()
            return
        await writer.drain()

        try:
            simh_r, simh_w = await _open_simh()
        except (TimeoutError, OSError):
            writer.write(b"# SimH remote console not available yet -- is SimH running?\n")
            await writer.drain()
            return

        # Either direction ending (EOF, reset, error, idle) ends the session, and
        # the other direction is cancelled; both ends are closed below, so neither a
        # vanished client nor a vanished SimH can leave the other half open.
        activity = [asyncio.get_running_loop().time()]
        pumps = [
            asyncio.ensure_future(_pipe(reader, simh_w, activity)),
            asyncio.ensure_future(_pipe(simh_r, writer, activity)),
        ]
        try:
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for p in pumps:
                p.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)

    except OSError:
        pass
    except Exception as exc:
        print(f"[authshim] error from {peer}: {exc}", file=sys.stderr, flush=True)
    finally:
        await _close(simh_w)
        await _close(writer)


async def _main() -> None:
    server = await asyncio.start_server(_handle, "0.0.0.0", LISTEN_PORT)
    watch_server = await asyncio.start_server(_handle_watch, "0.0.0.0", WATCH_PORT)
    lamp_server = await asyncio.start_server(_handle_lamp_stream, "0.0.0.0", LAMP_PORT)
    print(
        f"[authshim] :{LISTEN_PORT} → SimH :{SIMH_PORT}"
        f"  |  watch :{WATCH_PORT}  |  lamps :{LAMP_PORT}",
        flush=True,
    )
    async with server, watch_server, lamp_server:
        await asyncio.gather(
            server.serve_forever(),
            watch_server.serve_forever(),
            lamp_server.serve_forever(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
