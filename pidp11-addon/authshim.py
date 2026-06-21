#!/usr/bin/env python3
"""
Auth shim: accepts TCP on LISTEN_PORT (default 2223), requires
    AUTH <secret>\n
then proxies the byte stream to SimH's native remote console on SIMH_PORT (default 2224).

Also serves a watch stream on WATCH_PORT (default 2225) that streams SR register
changes in near-real-time by maintaining a single long-lived SimH connection.

Wire protocol is documented in docs/contracts/remote-console.md.
"""
import asyncio
import os
import re
import sys

LISTEN_PORT = int(os.environ.get("AUTHSHIM_PORT", "2223"))
SIMH_PORT   = int(os.environ.get("SIMH_PORT",     "2224"))
SECRET_FILE = os.environ.get("SECRET_FILE", "/data/remote_console.secret")
AUTH_TIMEOUT = 5.0
VERSION = "1.0.0"

_PROMPT = b"sim> "
_CONNECT_TIMEOUT = 5.0
_DRAIN_QUIET = 0.3
WATCH_PORT = int(os.environ.get("WATCH_PORT", str(LISTEN_PORT + 2)))
WATCH_INTERVAL_MS = float(os.environ.get("WATCH_INTERVAL_MS", "250"))


def _load_secret() -> str:
    with open(SECRET_FILE) as fh:
        return fh.read().strip()


def _parse_sr(text: str) -> str | None:
    """Extract octal value from SimH SR register output.

    Scans all lines for 'REG:\\t<octal>' pattern and returns the first match.
    """
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        m = re.match(r"\S+:\s+([0-7]+)", line.strip())
        if m:
            return m.group(1)
    return None


async def _drain_simh_banner(reader: asyncio.StreamReader) -> None:
    """Read until sim> prompt, then drain until quiet."""
    try:
        await asyncio.wait_for(reader.readuntil(_PROMPT), timeout=_CONNECT_TIMEOUT)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError):
        pass
    # Drain remaining buffered data until quiet
    while True:
        try:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=_DRAIN_QUIET)
            if not chunk:
                break
        except asyncio.TimeoutError:
            break


async def _handle_watch(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Handle a watch stream connection.

    Protocol:
    1. Client sends AUTH <secret>\\n
    2. Server responds OK\\n
    3. Server opens dedicated SimH connection, drains banner
    4. Server polls EXAMINE SR every WATCH_INTERVAL_MS ms, streams
       EVENT sr value=<octal>\\n on initial connect and on change
    5. Connection kept alive until client disconnects
    """
    peer = writer.get_extra_info("peername")
    try:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=AUTH_TIMEOUT)
        except asyncio.TimeoutError:
            writer.write(b"DENY auth-timeout\n")
            await writer.drain()
            return

        parts = raw.decode(errors="replace").rstrip("\r\n").split(" ", 1)
        if len(parts) != 2 or parts[0] != "AUTH" or parts[1] != _load_secret():
            writer.write(b"DENY bad-auth\n")
            await writer.drain()
            return

        writer.write(b"OK\n")
        await writer.drain()

        try:
            simh_r, simh_w = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", SIMH_PORT),
                timeout=_CONNECT_TIMEOUT,
            )
        except (ConnectionRefusedError, asyncio.TimeoutError):
            # SimH not available — close silently
            return

        try:
            await _drain_simh_banner(simh_r)

            prev_sr: str | None = None
            interval_s = WATCH_INTERVAL_MS / 1000.0

            while True:
                # Check if client disconnected
                if writer.is_closing():
                    break

                simh_w.write(b"EXAMINE SR\n")
                await simh_w.drain()

                # Read response up to the next sim> prompt
                try:
                    raw_resp = await asyncio.wait_for(
                        simh_r.readuntil(_PROMPT), timeout=_CONNECT_TIMEOUT
                    )
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                text = raw_resp[: -len(_PROMPT)].decode(errors="replace")
                sr = _parse_sr(text)

                if sr is not None and (prev_sr is None or sr != prev_sr):
                    event_line = f"EVENT sr value={sr}\n".encode()
                    writer.write(event_line)
                    await writer.drain()
                    prev_sr = sr

                await asyncio.sleep(interval_s)

        finally:
            try:
                simh_w.close()
                await simh_w.wait_closed()
            except Exception:
                pass

    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    except Exception as exc:
        print(f"[authshim] watch error from {peer}: {exc}", file=sys.stderr, flush=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(4096)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            dst.close()
            await dst.wait_closed()
        except Exception:
            pass


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    try:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=AUTH_TIMEOUT)
        except asyncio.TimeoutError:
            writer.write(b"DENY auth-timeout\n")
            await writer.drain()
            return

        parts = raw.decode(errors="replace").rstrip("\r\n").split(" ", 1)
        if len(parts) != 2 or parts[0] != "AUTH" or parts[1] != _load_secret():
            writer.write(b"DENY bad-auth\n")
            await writer.drain()
            return

        writer.write(b"OK\n")
        writer.write(f"# pidp11-authshim {VERSION}\n".encode())
        await writer.drain()

        try:
            simh_r, simh_w = await asyncio.open_connection("127.0.0.1", SIMH_PORT)
        except ConnectionRefusedError:
            writer.write(b"# SimH remote console not available yet -- is SimH running?\n")
            await writer.drain()
            return

        await asyncio.gather(_pipe(reader, simh_w), _pipe(simh_r, writer))

    except Exception as exc:
        print(f"[authshim] error from {peer}: {exc}", file=sys.stderr, flush=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _main() -> None:
    server = await asyncio.start_server(_handle, "0.0.0.0", LISTEN_PORT)
    watch_server = await asyncio.start_server(_handle_watch, "0.0.0.0", WATCH_PORT)
    print(
        f"[authshim] :{LISTEN_PORT} → SimH :{SIMH_PORT}  |  watch :{WATCH_PORT}",
        flush=True,
    )
    async with server, watch_server:
        await asyncio.gather(server.serve_forever(), watch_server.serve_forever())


if __name__ == "__main__":
    asyncio.run(_main())
