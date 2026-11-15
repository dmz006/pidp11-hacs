"""System-name query: the coordinator's file read and the add-on fallback.

Covers both sides of `AUTH <secret> +system` (see docs/contracts/remote-console.md):

* the auth shim answers `SYSTEM <name>` and never opens a SimH connection;
* the coordinator reads /share/pidp11/current_system in the executor, falls back
  to the add-on when that file is missing or empty, and treats an add-on that
  does not answer the query as "unknown" without an error.

Everything runs in-process on loopback with fakes: a fake add-on that speaks the
main-port protocol (with a tiny SimH behind it), the real shim handler for the
shim tests, and no Home Assistant instance beyond the `hass` test fixture, no
Pi, no real SimH.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from custom_components.pidp11 import coordinator as coordinator_mod
from custom_components.pidp11.coordinator import PiDP11Coordinator

pytestmark = [pytest.mark.usefixtures("socket_enabled")]

_ADDON_DIR = Path(__file__).resolve().parent.parent.parent / "pidp11-addon"
if str(_ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(_ADDON_DIR))

import authshim as shim

SECRET = "c" * 64
BANNER = b"PDP-11 simulator\r\nSimulator Running...\r\nsim> "
REGISTERS = {
    "EXAMINE PC": "PC:\t000400",
    "EXAMINE PSW": "PSW:\t140246",
    "EXAMINE SR": "SR:\t000005",
}


# ── Fake add-on (main port, with a tiny SimH behind it) ──────────────────────


class FakeAddOn:
    """Speaks the main-port protocol.

    ``system_answer`` is what ``+system`` gets back. ``None`` models an older add-on
    that does not know the query: it proxies the connection to SimH instead, so the
    client sees the banner and then nothing it can parse as SYSTEM.
    """

    def __init__(self, system_answer: str | None) -> None:
        self.system_answer = system_answer
        self.system_queries = 0
        self.polls = 0
        self.open = 0
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.open += 1
        try:
            parts = (await reader.readline()).decode(errors="replace").split()
            if len(parts) < 2 or parts[0] != "AUTH" or parts[1] != SECRET:
                writer.write(b"DENY bad-auth\n")
                await writer.drain()
                return
            writer.write(b"OK\n# pidp11-authshim 1.0.0\n")
            if "+system" in parts[2:]:
                self.system_queries += 1
                if self.system_answer is not None:
                    writer.write(f"SYSTEM {self.system_answer}\n".encode())
                    await writer.drain()
                    return
                writer.write(BANNER)  # old add-on: proxied to SimH, waits for input
                await writer.drain()
                await reader.read()
                return
            self.polls += 1
            writer.write(BANNER)
            await writer.drain()
            while True:
                cmd = await reader.readline()
                if not cmd:
                    break
                reply = REGISTERS.get(cmd.decode(errors="replace").strip(), "")
                writer.write(f"{reply}\r\nsim> ".encode())
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self.open -= 1
            writer.close()


@pytest.fixture
async def addon_factory() -> AsyncIterator[Any]:
    servers: list[FakeAddOn] = []

    async def make(system_answer: str | None) -> FakeAddOn:
        fake = FakeAddOn(system_answer)
        await fake.start()
        servers.append(fake)
        return fake

    yield make
    for fake in servers:
        fake.stop()


@pytest.fixture
def quick_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coordinator_mod, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(coordinator_mod, "_SYSTEM_QUERY_TIMEOUT", 0.5)


def _system_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None) -> Path:
    """Point the coordinator at a local current_system file (or a missing one)."""
    path = tmp_path / "current_system"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(coordinator_mod, "CURRENT_SYSTEM_PATH", str(path))
    return path


def _coord(hass: Any, port: int) -> PiDP11Coordinator:
    return PiDP11Coordinator(hass, host="127.0.0.1", port=port, secret=SECRET)


# ── Coordinator: executor read and add-on fallback ───────────────────────────


async def test_current_system_is_read_in_the_executor(
    hass: Any, addon_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    quick_timings: None,
) -> None:
    """The file read leaves the event loop: it runs on a worker thread."""
    _system_file(tmp_path, monkeypatch, "211bsd")
    addon = await addon_factory("idled")
    loop_thread = threading.get_ident()
    seen: list[int] = []
    real_read = coordinator_mod._read_current_system

    def spy() -> str | None:
        seen.append(threading.get_ident())
        return real_read()

    monkeypatch.setattr(coordinator_mod, "_read_current_system", spy)
    coord = _coord(hass, addon.port)
    try:
        await coord.async_refresh()
    finally:
        await coord.async_shutdown()

    assert seen, "the file was never read"
    assert seen[0] != loop_thread, "the file was read on the event loop thread"
    assert coord.last_update_success
    assert coord.data.system == "211bsd"  # the local file wins, no query needed
    assert addon.system_queries == 0


async def test_missing_file_falls_back_to_the_add_on(
    hass: Any, addon_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    quick_timings: None,
) -> None:
    _system_file(tmp_path, monkeypatch, None)  # file does not exist here
    addon = await addon_factory("211bsd")
    coord = _coord(hass, addon.port)
    try:
        await coord.async_refresh()
    finally:
        await coord.async_shutdown()

    assert coord.last_update_success
    assert coord.data.system == "211bsd"
    assert addon.system_queries == 1
    assert addon.open == 0, "the query connection was not released"


async def test_empty_file_falls_back_to_the_add_on(
    hass: Any, addon_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    quick_timings: None,
) -> None:
    _system_file(tmp_path, monkeypatch, "  \n")
    addon = await addon_factory("rsx11mp")
    coord = _coord(hass, addon.port)
    try:
        await coord.async_refresh()
    finally:
        await coord.async_shutdown()

    assert coord.data.system == "rsx11mp"
    assert addon.system_queries == 1


async def test_add_on_reporting_unknown_leaves_the_sensor_unknown(
    hass: Any, addon_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    quick_timings: None,
) -> None:
    _system_file(tmp_path, monkeypatch, None)
    addon = await addon_factory("unknown")
    coord = _coord(hass, addon.port)
    try:
        await coord.async_refresh()
        await coord.async_refresh()
    finally:
        await coord.async_shutdown()

    assert coord.last_update_success
    assert coord.data.system is None
    # "unknown" is an answer, not a missing query, so the file is asked for again each poll.
    assert addon.system_queries == 2


async def test_old_add_on_keeps_the_sensor_unknown_without_an_error(
    hass: Any, addon_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    quick_timings: None,
) -> None:
    _system_file(tmp_path, monkeypatch, None)
    addon = await addon_factory(None)  # does not know +system
    coord = _coord(hass, addon.port)
    try:
        await coord.async_refresh()
        assert coord.last_update_success, "an old add-on must not fail the update"
        assert coord.data.system is None
        assert addon.open == 0, "the query connection to the old add-on was not closed"

        # Not asked again on every poll; the poll itself still works.
        await coord.async_refresh()
        assert coord.last_update_success
        assert coord.data.system is None
        assert addon.system_queries == 1
        assert addon.polls == 2
    finally:
        await coord.async_shutdown()


async def test_old_add_on_is_asked_again_after_the_retry_interval(
    hass: Any, addon_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    quick_timings: None,
) -> None:
    _system_file(tmp_path, monkeypatch, None)
    addon = await addon_factory(None)
    coord = _coord(hass, addon.port)
    try:
        await coord.async_refresh()
        assert addon.system_queries == 1
        # Pretend the retry interval has passed.
        coord._system_query_after = 0.0
        await coord.async_refresh()
        assert addon.system_queries == 2
    finally:
        await coord.async_shutdown()


# ── Auth shim: the SYSTEM answer ─────────────────────────────────────────────


@pytest.fixture
def shim_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    secret_file = tmp_path / "secret"
    secret_file.write_text(SECRET)
    system_file = tmp_path / "current_system"
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))
    monkeypatch.setattr(shim, "CURRENT_SYSTEM_FILE", str(system_file))
    opened: list[int] = []

    async def no_simh() -> Any:
        opened.append(1)
        raise OSError("this test must not reach SimH")

    monkeypatch.setattr(shim, "_open_simh", no_simh)
    return {"system_file": system_file, "opened": opened}


async def _ask_shim(line: bytes) -> list[bytes]:
    """Start the real shim handler, send one line, return every line the server sent."""
    server = await asyncio.start_server(shim._handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(line)
        await writer.drain()
        lines: list[bytes] = []
        while True:
            got = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not got:
                break
            lines.append(got)
    finally:
        writer.close()
        server.close()
    return lines


async def test_shim_answers_system_without_opening_simh(shim_env: dict[str, Any]) -> None:
    shim_env["system_file"].write_text("211bsd\n")
    lines = await _ask_shim(f"AUTH {SECRET} +system\n".encode())
    assert lines == [b"OK\n", f"# pidp11-authshim {shim.VERSION}\n".encode(), b"SYSTEM 211bsd\n"]
    assert shim_env["opened"] == []


async def test_shim_answers_unknown_when_the_file_is_missing(shim_env: dict[str, Any]) -> None:
    lines = await _ask_shim(f"AUTH {SECRET} +system\n".encode())
    assert lines[-1] == b"SYSTEM unknown\n"
    assert shim_env["opened"] == []


@pytest.mark.parametrize("content", ["2 1 1", "../../etc/passwd", "x" * 33, "a\tb"])
async def test_shim_refuses_odd_names(shim_env: dict[str, Any], content: str) -> None:
    shim_env["system_file"].write_text(content)
    lines = await _ask_shim(f"AUTH {SECRET} +system\n".encode())
    assert lines[-1] == b"SYSTEM unknown\n"


async def test_shim_denies_a_wrong_secret_on_the_system_query(shim_env: dict[str, Any]) -> None:
    shim_env["system_file"].write_text("211bsd")
    lines = await _ask_shim(b"AUTH wrong-secret +system\n")
    assert lines == [b"DENY bad-auth\n"]
    assert shim_env["opened"] == []


async def test_plain_auth_still_proxies_to_simh(
    shim_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordinary connection is unchanged: it reaches SimH and the banner comes through."""

    async def fake_simh(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(BANNER)
        await writer.drain()
        await reader.read()
        writer.close()

    simh = await asyncio.start_server(fake_simh, "127.0.0.1", 0)
    simh_port = simh.sockets[0].getsockname()[1]
    monkeypatch.setattr(shim, "SIMH_PORT", simh_port)
    monkeypatch.setattr(shim, "_open_simh", _open_simh_for(simh_port))
    server = await asyncio.start_server(shim._handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(f"AUTH {SECRET}\n".encode())
        await writer.drain()
        got = b""
        while b"sim> " not in got:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if not chunk:
                break
            got += chunk
        assert got.startswith(b"OK\n")
        assert b"SYSTEM" not in got
        assert b"sim> " in got
    finally:
        writer.close()
        server.close()
        simh.close()
        # The proxy session ends when the client leaves; cancel any handler still waiting.
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def _open_simh_for(port: int) -> Any:
    async def open_it() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection("127.0.0.1", port)

    return open_it


# ── Coordinator against the real shim ────────────────────────────────────────


async def test_coordinator_gets_the_name_from_the_real_shim(
    hass: Any, shim_env: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    quick_timings: None,
) -> None:
    """End to end with the real shim handler: the query needs no SimH at all."""
    shim_env["system_file"].write_text("idled")
    _system_file(tmp_path, monkeypatch, None)
    server = await asyncio.start_server(shim._handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    coord = _coord(hass, port)
    try:
        name = await coord._system_from_add_on()
    finally:
        await coord.async_shutdown()
        server.close()
    assert name == "idled"
    assert shim_env["opened"] == []
