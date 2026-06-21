"""Data update coordinator for PiDP-11 — polls SimH via the auth shim."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CPU_STATE_HALTED,
    CPU_STATE_RUNNING,
    CURRENT_SYSTEM_PATH,
    DOMAIN,
    UPDATE_INTERVAL_SECONDS,
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

    cpu_state: str       # CPU_STATE_* constant
    pc: str | None       # octal string e.g. "000400"
    psw: str | None      # octal string
    system: str | None   # "211bsd", "idled", etc.


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
            async with asyncio.timeout(_CONNECT_TIMEOUT + _CMD_TIMEOUT * 2):
                return await self._poll(system)
        except TimeoutError as exc:
            raise UpdateFailed("PiDP-11 connection timed out") from exc
        except UpdateFailed:
            raise
        except Exception as exc:
            raise UpdateFailed(f"PiDP-11 error: {exc}") from exc

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

            return PiDP11State(cpu_state=cpu_state, pc=pc, psw=psw, system=system)
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
