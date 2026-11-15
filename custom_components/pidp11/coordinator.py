"""Data update coordinator for PiDP-11 — polls SimH via the auth shim."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CPU_MODE_KERNEL,
    CPU_MODE_SUPERVISOR,
    CPU_MODE_USER,
    CPU_STATE_HALTED,
    CPU_STATE_RUNNING,
    CURRENT_SYSTEM_PATH,
    DOMAIN,
    EVENT_LAMPS,
    EVENT_SR_CHANGED,
    EVENT_SWITCH_CHANGED,
    LAMP_PORT_OFFSET,
    UPDATE_INTERVAL_SECONDS,
    WATCH_PORT_OFFSET,
)

_LOGGER = logging.getLogger(__name__)

_PROMPT = b"sim> "
_CONNECT_TIMEOUT = 5.0
_CMD_TIMEOUT = 8.0
# SimH buffers all prior remote-console output and replays it on new connections.
# We drain until quiet (no data for _DRAIN_QUIET seconds), then check only the
# last _STATE_TAIL bytes for "Simulator Running" to detect current CPU state.
_DRAIN_QUIET = 0.5
_STATE_TAIL = 300
_AUTH_TIMEOUT = 5.0
_RELEASE_TIMEOUT = 2.0

# ── Connection budget ─────────────────────────────────────────────────────────
# SimH only accepts a fixed number of remote-console connections: every boot.ini
# in this repo sets `set remote connections=4`. Past that it accepts the TCP
# connection, writes "All connections busy" and hangs up. A person on a console
# session needs one or two of those, so the integration keeps to a budget of 2:
#
#   1 long-lived stream  (lamps + switch register, one connection through the shim)
#   1 transient          (a poll or a service command, never two at once: _conn_lock)
#
# Every connection opened here is closed in a `finally`, the stream is cancelled
# on unload, and when SimH says it is busy we back off and keep the last values
# instead of flapping the entities to unavailable.
_BUSY_TEXT = b"All connections busy"
_BUSY_RETRIES = 3          # extra attempts after the first, within one poll/command
_BUSY_BACKOFF_BASE = 1.0   # seconds; doubles each attempt
_BUSY_BACKOFF_MAX = 8.0
_STREAM_BACKOFF_BASE = 10.0   # seconds before the first stream reconnect; doubles
_STREAM_BACKOFF_MAX = 120.0
_STREAM_AUTH_RETRY = 30.0
_STREAM_AUTH_SR = " +sr"      # ask the shim for SR events on the lamp stream too


class PiDP11Busy(UpdateFailed):
    """SimH has no free remote-console connection ("All connections busy")."""


@dataclass(slots=True)
class PiDP11State:
    """Snapshot of the running emulator."""

    cpu_state: str        # CPU_STATE_* constant
    pc: str | None        # octal string e.g. "000400"
    psw: str | None       # octal string
    sr: str | None        # switch register, octal (22-bit)
    cpu_mode: str | None  # CPU_MODE_* derived from PSW bits 15-14
    system: str | None    # "211bsd", "idled", etc.


class PiDP11Coordinator(DataUpdateCoordinator[PiDP11State]):
    """Polls the SimH remote console via the auth shim."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        secret: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.host = host
        self.port = port
        self._secret = secret
        self._prev_sr: str | None = None
        # Kept for compatibility; the shared stream below uses the lamp port.
        self._watch_port = port + WATCH_PORT_OFFSET
        self._lamp_port = port + LAMP_PORT_OFFSET
        # One long-lived stream carries both the lamps and the switch register.
        self._stream_task: asyncio.Task[None] | None = None
        self._stream_has_sr = False
        # At most one transient connection (poll or command) at a time.
        self._conn_lock = asyncio.Lock()
        self._busy_logged = False

    # ── Public command API ────────────────────────────────────────────────────

    async def async_send_command(self, cmd: str) -> str:
        """Open a connection, auth, send one SimH command, return text response.

        Waits for any poll or other command in flight (one transient connection
        at a time) and retries with backoff while SimH reports it is busy.
        """
        async with self._conn_lock:
            try:
                return await self._with_busy_retry(lambda: self._timed_command(cmd))
            except TimeoutError as exc:
                raise UpdateFailed(f"PiDP-11 command timed out: {cmd!r}") from exc

    # ── DataUpdateCoordinator hook ────────────────────────────────────────────

    async def _async_update_data(self) -> PiDP11State:
        system = _read_current_system()
        try:
            async with self._conn_lock:
                state = await self._with_busy_retry(lambda: self._timed_poll(system))
        except PiDP11Busy as exc:
            return self._keep_last_values(system, exc)
        except TimeoutError as exc:
            raise UpdateFailed("PiDP-11 connection timed out") from exc
        except UpdateFailed:
            raise
        except Exception as exc:
            raise UpdateFailed(f"PiDP-11 error: {exc}") from exc
        self._busy_logged = False

        # Fire SR-changed event when the switch register value changes.
        # Only fire from poll if watch task isn't active (legacy/fallback mode),
        # to avoid duplicate events when the watch stream is running.
        new_sr = state.sr
        if (
            new_sr is not None
            and self._prev_sr is not None
            and new_sr != self._prev_sr
            and not self._stream_carries_sr()
        ):
            self.hass.bus.async_fire(
                EVENT_SR_CHANGED,
                {"sr_old": self._prev_sr, "sr_new": new_sr},
            )
        if new_sr is not None:
            self._prev_sr = new_sr

        return state

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _keep_last_values(self, system: str | None, exc: PiDP11Busy) -> PiDP11State:
        """Console busy even after backoff: keep the entities on their last values."""
        if self.data is None:
            raise UpdateFailed(str(exc)) from exc
        if not self._busy_logged:
            _LOGGER.warning("%s; keeping the last values until a connection is free", exc)
            self._busy_logged = True
        else:
            _LOGGER.debug("%s; still keeping the last values", exc)
        return replace(self.data, system=system)

    def _stream_carries_sr(self) -> bool:
        task = self._stream_task
        return task is not None and not task.done() and self._stream_has_sr

    async def _with_busy_retry[T](self, op: Callable[[], Awaitable[T]]) -> T:
        """Run ``op``; while SimH is busy retry with exponential backoff."""
        delay = _BUSY_BACKOFF_BASE
        for attempt in range(_BUSY_RETRIES + 1):
            try:
                return await op()
            except PiDP11Busy:
                if attempt == _BUSY_RETRIES:
                    raise
                _LOGGER.debug("PiDP-11 console busy; retrying in %.2f s", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, _BUSY_BACKOFF_MAX)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _timed_poll(self, system: str | None) -> PiDP11State:
        async with asyncio.timeout(_CONNECT_TIMEOUT + _CMD_TIMEOUT * 3):
            return await self._poll(system)

    async def _timed_command(self, cmd: str) -> str:
        async with asyncio.timeout(_CONNECT_TIMEOUT + _CMD_TIMEOUT):
            return await self._do_command(cmd)

    async def _open_and_auth(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=_CONNECT_TIMEOUT,
        )
        try:
            writer.write(f"AUTH {self._secret}\n".encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=_AUTH_TIMEOUT)
            if not line.startswith(b"OK"):
                raise UpdateFailed(f"Auth rejected: {line!r}")
        except BaseException:
            # Timeout, cancellation, reset or rejection: never strand the socket.
            _close(writer)
            raise
        return reader, writer

    async def _read_to_prompt(self, reader: asyncio.StreamReader) -> bytes:
        return await asyncio.wait_for(reader.readuntil(_PROMPT), timeout=_CMD_TIMEOUT)

    async def _drain_banner(self, reader: asyncio.StreamReader) -> bytes:
        """Drain ALL buffered SimH output (history + current state).

        SimH replays its entire console buffer to every new remote connection.
        Strategy:
        1. readuntil(sim>) to wait for the initial banner (may take 1-2s after
           connection before SimH sends anything).
        2. Drain any remaining buffered data with a short quiet timeout — this
           consumes historical output from prior sessions that follows the first
           prompt.
        We inspect only the tail of the combined buffer for CPU state.
        """
        buf = bytearray()
        # Step 1: wait for at least the initial banner + first sim> prompt.
        try:
            initial = await asyncio.wait_for(
                reader.readuntil(_PROMPT), timeout=_CMD_TIMEOUT
            )
            buf.extend(initial)
        except TimeoutError:
            pass
        except asyncio.IncompleteReadError as exc:
            # EOF before a prompt: keep what arrived. A busy SimH sends only
            # "All connections busy" and hangs up.
            buf.extend(exc.partial)
        # Step 2: drain remaining history (0 bytes on a fresh session).
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=_DRAIN_QUIET)
                if not chunk:
                    break
                buf.extend(chunk)
            except TimeoutError:
                break
        return bytes(buf)

    async def _poll(self, system: str | None) -> PiDP11State:
        reader, writer = await self._open_and_auth()
        try:
            # Drain the full SimH output buffer (may contain many prior sessions).
            # CPU state is determined from the *tail* which reflects current state.
            banner = await self._drain_banner(reader)
            _raise_if_busy(banner)
            cpu_state = (
                CPU_STATE_RUNNING
                if b"Simulator Running" in banner[-_STATE_TAIL:]
                else CPU_STATE_HALTED
            )

            writer.write(b"EXAMINE PC\n")
            await writer.drain()
            raw = await self._read_to_prompt(reader)
            pc = _parse_register(raw[: -len(_PROMPT)].decode(errors="replace"))

            writer.write(b"EXAMINE PSW\n")
            await writer.drain()
            raw = await self._read_to_prompt(reader)
            psw = _parse_register(raw[: -len(_PROMPT)].decode(errors="replace"))

            writer.write(b"EXAMINE SR\n")
            await writer.drain()
            raw = await self._read_to_prompt(reader)
            sr = _parse_register(raw[: -len(_PROMPT)].decode(errors="replace"))

            return PiDP11State(
                cpu_state=cpu_state,
                pc=pc,
                psw=psw,
                sr=sr,
                cpu_mode=_parse_cpu_mode(psw),
                system=system,
            )
        finally:
            await _release(reader, writer)

    async def _do_command(self, cmd: str) -> str:
        reader, writer = await self._open_and_auth()
        try:
            _raise_if_busy(await self._drain_banner(reader))  # banner + all history
            writer.write(f"{cmd}\n".encode())
            await writer.drain()
            raw = await self._read_to_prompt(reader)
            text = raw[: -len(_PROMPT)].decode(errors="replace")
            return _strip_echo(cmd, text)
        finally:
            await _release(reader, writer)

    # ── Shared stream ─────────────────────────────────────────────────────────
    #
    # The SR watch and the lamp animation used to hold one SimH connection each.
    # They now share one: the lamp stream with the "+sr" option also carries the
    # switch register. start_sr_watch / start_lamp_watch / stop_* stay as the
    # public names; either start call makes sure the one stream is running.

    def start_sr_watch(self, task_name: str) -> None:
        """Make sure the shared stream is running (no-op if it already is)."""
        self._start_stream(task_name)

    def start_lamp_watch(self, task_name: str) -> None:
        """Make sure the shared stream is running (no-op if it already is)."""
        self._start_stream(task_name)

    def stop_sr_watch(self) -> None:
        """Cancel the shared stream."""
        self._cancel_stream()

    def stop_lamp_watch(self) -> None:
        """Cancel the shared stream."""
        self._cancel_stream()

    async def async_stop_streams(self) -> None:
        """Cancel the shared stream and wait until its connection is closed."""
        task = self._stream_task
        self._stream_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def async_shutdown(self) -> None:
        """Stop the stream along with the coordinator's own timers."""
        await self.async_stop_streams()
        await super().async_shutdown()

    def _start_stream(self, task_name: str) -> None:
        if self._stream_task and not self._stream_task.done():
            return
        self._stream_task = self.hass.async_create_background_task(
            self._run_stream(), name=task_name
        )

    def _cancel_stream(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()

    async def _run_stream(self) -> None:
        """The one long-lived stream. Reconnects with backoff; closes on every exit."""
        delay = _STREAM_BACKOFF_BASE
        auth_flags = _STREAM_AUTH_SR
        while True:
            writer: asyncio.StreamWriter | None = None
            got_line = False
            try:
                reader, conn = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self._lamp_port),
                    timeout=_CONNECT_TIMEOUT,
                )
                writer = conn
                _enable_keepalive(conn)
                conn.write(f"AUTH {self._secret}{auth_flags}\n".encode())
                await conn.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=_AUTH_TIMEOUT)
                if not line.startswith(b"OK"):
                    if auth_flags and line.startswith(b"DENY"):
                        # An add-on from before the shared stream: lamps only,
                        # and the poll fires the SR events.
                        _LOGGER.debug("Stream: shim refused %r; falling back", auth_flags)
                        auth_flags = ""
                        continue
                    _LOGGER.debug("Stream: auth failed on port %s", self._lamp_port)
                    await asyncio.sleep(_STREAM_AUTH_RETRY)
                    continue
                _LOGGER.debug("Stream connected on port %s", self._lamp_port)
                self._stream_has_sr = bool(auth_flags)
                # No read timeout: a quiet machine legitimately sends nothing, and
                # giving up on silence is what used to strand a SimH connection per
                # reconnect. Dead peers are caught by TCP keepalive and by the
                # shim's heartbeat/EOF handling.
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    got_line = True
                    await self._handle_stream_line(line.decode(errors="replace").strip())
            except Exception as exc:
                _LOGGER.debug("Stream disconnected: %s — retrying in %.1f s", exc, delay)
            finally:
                self._stream_has_sr = False
                if writer is not None:
                    _close(writer)
            if got_line:
                delay = _STREAM_BACKOFF_BASE
            await asyncio.sleep(delay)
            delay = min(delay * 2, _STREAM_BACKOFF_MAX)

    async def _handle_stream_line(self, msg: str) -> None:
        """Route one line from the shared stream; heartbeats and unknowns are ignored."""
        if msg.startswith("EVENT lamps "):
            self._handle_lamp_line(msg)
        elif msg.startswith("EVENT sr value="):
            await self._handle_watch_line(msg)

    def _handle_lamp_line(self, msg: str) -> None:
        """Fire pidp11_lamps event for each EVENT lamps line from the stream."""
        if not msg.startswith("EVENT lamps "):
            return
        m = re.match(r"EVENT lamps ADDRESS=([0-7]+) DATA=([0-7]+)", msg)
        if not m:
            return
        self.hass.bus.async_fire(
            EVENT_LAMPS,
            {"address": m.group(1), "data": m.group(2)},
        )

    async def _handle_watch_line(self, msg: str) -> None:
        """Process a line from the watch stream."""
        if not msg.startswith("EVENT sr value="):
            return
        sr_new = msg.removeprefix("EVENT sr value=")
        if not re.match(r"^[0-7]+$", sr_new):
            return
        sr_old = self._prev_sr
        self._prev_sr = sr_new
        if self.data is not None and sr_old is not None and sr_new != sr_old:
            old_int = int(sr_old, 8)
            new_int = int(sr_new, 8)
            changed = old_int ^ new_int
            for i in range(22):
                if changed & (1 << i):
                    self.hass.bus.async_fire(
                        EVENT_SWITCH_CHANGED,
                        {"switch": f"SR{i}", "state": bool(new_int & (1 << i))},
                    )
            self.hass.bus.async_fire(
                EVENT_SR_CHANGED,
                {"sr_old": sr_old, "sr_new": sr_new},
            )
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, sr=sr_new))


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_register(text: str) -> str | None:
    """Extract octal value from SimH register output.

    SimH re-emits the banner after each command, so the register line is not
    always last.  We scan all lines for 'REG:\\t<octal>' and return the first
    match (PSW has extra flag fields after the octal value, which a trailing
    anchor would reject).
    """
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        m = re.match(r"\S+:\s+([0-7]+)", line.strip())
        if m:
            return m.group(1)
    return None


def _strip_echo(cmd: str, text: str) -> str:
    """Remove SimH's command echo from the response text."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, skipped = [], False
    for line in lines:
        if not skipped and line.strip().upper() == cmd.strip().upper():
            skipped = True
            continue
        out.append(line)
    return "\n".join(out).strip()


def _parse_cpu_mode(psw: str | None) -> str | None:
    """Derive CPU mode (kernel/supervisor/user) from PSW bits 15-14."""
    if psw is None:
        return None
    try:
        mode = (int(psw, 8) >> 14) & 0b11
        return {0: CPU_MODE_KERNEL, 1: CPU_MODE_SUPERVISOR, 3: CPU_MODE_USER}.get(mode)
    except ValueError:
        return None


def _read_current_system() -> str | None:
    try:
        with open(CURRENT_SYSTEM_PATH) as fh:
            val = fh.read().strip()
        return val or None
    except OSError:
        return None


def _raise_if_busy(banner: bytes) -> None:
    """SimH at its connection limit sends only "All connections busy" and hangs up.

    A real session always shows the sim> prompt, so the text alone in a banner
    (even one that replays old console output) is not mistaken for it.
    """
    if _BUSY_TEXT in banner and _PROMPT not in banner:
        raise PiDP11Busy("PiDP-11 console busy: all remote connections are in use")


def _enable_keepalive(writer: asyncio.StreamWriter) -> None:
    """Have the kernel notice a dead peer on the long-lived stream."""
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


async def _release(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Close a transient connection and wait for the shim to confirm it is gone.

    Half-close, then read to EOF: the shim answers by closing its SimH connection
    and then ours. Only then is SimH's slot actually free, so the next poll or
    command cannot overlap with this one and push the integration past its budget.
    The wait is bounded, and the socket is closed whatever happens.
    """
    try:
        if not writer.is_closing():
            writer.write_eof()
            async with asyncio.timeout(_RELEASE_TIMEOUT):
                while await reader.read(4096):
                    pass
    except Exception:
        pass
    finally:
        _close(writer)


def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
    except Exception:
        pass
