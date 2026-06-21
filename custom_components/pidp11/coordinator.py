"""Data update coordinator for PiDP-11 — polls SimH via the auth shim."""

from __future__ import annotations

import asyncio
import logging
import re
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
        self._watch_port = port + WATCH_PORT_OFFSET
        self._watch_task: asyncio.Task[None] | None = None
        self._lamp_port = port + LAMP_PORT_OFFSET
        self._lamp_task: asyncio.Task[None] | None = None

    # ── Public command API ────────────────────────────────────────────────────

    async def async_send_command(self, cmd: str) -> str:
        """Open a connection, auth, send one SimH command, return text response."""
        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT + _CMD_TIMEOUT):
                return await self._do_command(cmd)
        except TimeoutError as exc:
            raise UpdateFailed(f"PiDP-11 command timed out: {cmd!r}") from exc

    # ── DataUpdateCoordinator hook ────────────────────────────────────────────

    async def _async_update_data(self) -> PiDP11State:
        system = _read_current_system()
        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT + _CMD_TIMEOUT * 3):
                state = await self._poll(system)
        except TimeoutError as exc:
            raise UpdateFailed("PiDP-11 connection timed out") from exc
        except UpdateFailed:
            raise
        except Exception as exc:
            raise UpdateFailed(f"PiDP-11 error: {exc}") from exc

        # Fire SR-changed event when the switch register value changes.
        # Only fire from poll if watch task isn't active (legacy/fallback mode),
        # to avoid duplicate events when the watch stream is running.
        new_sr = state.sr
        if new_sr is not None and self._prev_sr is not None and new_sr != self._prev_sr:
            if self._watch_task is None or self._watch_task.done():
                self.hass.bus.async_fire(
                    EVENT_SR_CHANGED,
                    {"sr_old": self._prev_sr, "sr_new": new_sr},
                )
        if new_sr is not None:
            self._prev_sr = new_sr

        return state

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _open_and_auth(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=_CONNECT_TIMEOUT,
        )
        writer.write(f"AUTH {self._secret}\n".encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not line.startswith(b"OK"):
            _close(writer)
            raise UpdateFailed(f"Auth rejected: {line!r}")
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
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        # Step 2: drain remaining history (0 bytes on a fresh session).
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=_DRAIN_QUIET)
                if not chunk:
                    break
                buf.extend(chunk)
            except asyncio.TimeoutError:
                break
        return bytes(buf)

    async def _poll(self, system: str | None) -> PiDP11State:
        reader, writer = await self._open_and_auth()
        try:
            # Drain the full SimH output buffer (may contain many prior sessions).
            # CPU state is determined from the *tail* which reflects current state.
            banner = await self._drain_banner(reader)
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
            _close(writer)

    async def _do_command(self, cmd: str) -> str:
        reader, writer = await self._open_and_auth()
        try:
            await self._drain_banner(reader)  # consume banner + all history
            writer.write(f"{cmd}\n".encode())
            await writer.drain()
            raw = await self._read_to_prompt(reader)
            text = raw[: -len(_PROMPT)].decode(errors="replace")
            return _strip_echo(cmd, text)
        finally:
            _close(writer)

    # ── Watch stream ──────────────────────────────────────────────────────────

    def start_sr_watch(self, task_name: str) -> None:
        """Start the long-lived SR watch task (no-op if already running)."""
        if self._watch_task and not self._watch_task.done():
            return
        self._watch_task = self.hass.async_create_background_task(
            self._run_sr_watch(), name=task_name
        )

    def stop_sr_watch(self) -> None:
        """Cancel the SR watch task."""
        if self._watch_task:
            self._watch_task.cancel()
            self._watch_task = None

    # ── Lamp stream ───────────────────────────────────────────────────────────

    def start_lamp_watch(self, task_name: str) -> None:
        """Start the long-lived lamp watch task (no-op if already running)."""
        if self._lamp_task and not self._lamp_task.done():
            return
        self._lamp_task = self.hass.async_create_background_task(
            self._run_lamp_watch(), name=task_name
        )

    def stop_lamp_watch(self) -> None:
        """Cancel the lamp watch task."""
        if self._lamp_task:
            self._lamp_task.cancel()
            self._lamp_task = None

    async def _run_lamp_watch(self) -> None:
        """Long-lived lamp stream connection. Reconnects on failure."""
        while True:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self._lamp_port),
                    timeout=_CONNECT_TIMEOUT,
                )
                try:
                    writer.write(f"AUTH {self._secret}\n".encode())
                    await writer.drain()
                    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                    if not line.startswith(b"OK"):
                        _LOGGER.debug(
                            "Lamp watch: auth failed on port %s", self._lamp_port
                        )
                        await asyncio.sleep(30.0)
                        continue
                    _LOGGER.debug("Lamp watch connected on port %s", self._lamp_port)
                    while True:
                        line = await asyncio.wait_for(reader.readline(), timeout=60.0)
                        if not line:
                            break
                        self._handle_lamp_line(line.decode(errors="replace").strip())
                finally:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.debug(
                    "Lamp watch disconnected: %s — retrying in 10 s", exc
                )
            await asyncio.sleep(10.0)

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

    async def _run_sr_watch(self) -> None:
        """Long-lived watch stream connection. Reconnects on failure."""
        while True:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self._watch_port),
                    timeout=_CONNECT_TIMEOUT,
                )
                try:
                    writer.write(f"AUTH {self._secret}\n".encode())
                    await writer.drain()
                    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                    if not line.startswith(b"OK"):
                        _LOGGER.debug(
                            "SR watch: auth failed on port %s", self._watch_port
                        )
                        await asyncio.sleep(30.0)
                        continue
                    _LOGGER.debug("SR watch connected on port %s", self._watch_port)
                    while True:
                        line = await asyncio.wait_for(reader.readline(), timeout=60.0)
                        if not line:
                            break
                        await self._handle_watch_line(
                            line.decode(errors="replace").strip()
                        )
                finally:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _LOGGER.debug(
                    "SR watch disconnected: %s — retrying in 10 s", exc
                )
            await asyncio.sleep(10.0)

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
        val = open(CURRENT_SYSTEM_PATH).read().strip()
        return val or None
    except OSError:
        return None


def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
    except Exception:
        pass
