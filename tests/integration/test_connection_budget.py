"""Connection budget: the integration must never exhaust the emulator console.

SimH's remote console accepts a fixed number of simultaneous connections; every
``boot.ini`` in this repo sets ``remote connections=4``. Past that SimH accepts
the TCP connection, writes ``All connections busy`` and closes it. Home
Assistant used to run into that wall: every stream and every poll holds one
SimH connection (through the auth shim), and connections were leaking.

Where the leak was (found by reading the code and confirmed by these tests):

* **Shim side (the leak).** ``_handle_watch`` and ``_handle_lamp_stream`` only
  write to the client when a register changes, and the only liveness check was
  ``writer.is_closing()``. A client that closes gracefully (FIN) leaves the
  shim-side transport open (half-close), so on a quiet machine the shim never
  noticed and kept its SimH connection forever.
* **Coordinator side (the trigger).** The stream read had a 60 s timeout, but a
  quiet machine sends nothing for longer than that, so every ~70 s the stream
  gave up, closed with a FIN and reconnected: one stranded SimH connection per
  minute until all four were gone. The integration also held up to three
  connections at once (SR watch, lamp stream and a poll).

Everything here is in-process: a fake console that accepts at most 4 connections
(and answers ``All connections busy`` beyond that), the real auth shim handlers
on loopback ports, throwaway data directories and no real Home Assistant, Pi or
network beyond localhost.
"""

from __future__ import annotations

import asyncio
import itertools
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.pidp11 import coordinator as coordinator_mod
from custom_components.pidp11.const import EVENT_LAMPS, EVENT_SR_CHANGED
from custom_components.pidp11.coordinator import PiDP11Coordinator

pytestmark = [pytest.mark.usefixtures("socket_enabled")]

_ADDON_DIR = Path(__file__).resolve().parent.parent.parent / "pidp11-addon"
if str(_ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(_ADDON_DIR))

import authshim as shim

SECRET = "b" * 64
CONSOLE_LIMIT = 4  # `set remote connections=4` in every boot.ini
INTEGRATION_BUDGET = 2  # stream + one transient poll/command, never more


# ── Fake emulator console ─────────────────────────────────────────────────────


class FakeConsole:
    """In-process stand-in for SimH's remote console.

    Accepts at most ``limit`` connections at a time. Past that it behaves like
    SimH: writes ``All connections busy`` and closes. It has no idle timeout of
    its own (neither does SimH), so a connection only goes away when the peer
    closes it. That is what makes a leak visible as ``open > 0``.
    """

    def __init__(self, limit: int = CONSOLE_LIMIT) -> None:
        self.limit = limit
        self.open = 0
        self.peak = 0
        self.rejected = 0
        self.reject_times: list[float] = []
        self.regs: dict[str, str] = {
            "PC": "000400",
            "PSW": "140246",
            "SR": "000005",
        }
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return int(self._server.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        self.drop_all()

    def drop_all(self) -> None:
        """Close every open console connection from the emulator side."""
        for w in list(self._writers):
            w.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.open >= self.limit:
            self.rejected += 1
            self.reject_times.append(time.monotonic())
            writer.write(b"All connections busy\r\n")
            try:
                await writer.drain()
            except ConnectionError:
                pass
            writer.close()
            return
        self.open += 1
        self.peak = max(self.peak, self.open)
        self._writers.add(writer)
        try:
            writer.write(b"PDP-11 simulator\r\nSimulator Running...\r\nsim> ")
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    break
                writer.write(self._answer(line.decode(errors="replace").strip()))
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self.open -= 1
            self._writers.discard(writer)
            writer.close()

    def _answer(self, cmd: str) -> bytes:
        words = cmd.upper().split()
        if len(words) == 2 and words[0] == "EXAMINE":
            value = self.regs.get(words[1], "000123")
            return f"{cmd}\r\n{words[1]}:\t{value}\r\nsim> ".encode()
        return f"{cmd}\r\nsim> ".encode()


# ── Fake client ───────────────────────────────────────────────────────────────


class FakeClient:
    """A raw TCP client of the auth shim that can vanish abruptly."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, port: int, auth_suffix: str = "") -> FakeClient:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"AUTH {SECRET}{auth_suffix}\n".encode())
        await writer.drain()
        client = cls(reader, writer)
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert line.strip() == b"OK", line
        return client

    def vanish(self, how: str) -> None:
        if how == "rst":
            self.writer.transport.abort()  # RST, as when a process is killed
        else:
            self.writer.close()  # graceful FIN, as when a client gives up and reconnects

    async def sees_eof(self, timeout: float = 2.0) -> bool:
        async def _drain() -> None:
            while await self.reader.read(4096):
                pass

        try:
            await asyncio.wait_for(_drain(), timeout=timeout)
        except TimeoutError:
            return False
        except ConnectionError:
            return True
        return True


async def wait_until(
    predicate: Callable[[], bool], timeout: float = 3.0, step: float = 0.02
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step)
    return predicate()


# ── Rig: fake console + the real shim handlers on loopback ────────────────────


@dataclass
class Rig:
    console: FakeConsole
    main_port: int
    watch_port: int
    lamp_port: int
    ports: dict[str, int] = field(default_factory=dict)


@pytest.fixture
async def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    secret_file = tmp_path / "remote_console.secret"
    secret_file.write_text(SECRET)
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))
    monkeypatch.setattr(shim, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(shim, "WATCH_INTERVAL_MS", 10.0)
    monkeypatch.setattr(shim, "LAMP_INTERVAL_MS", 10.0)

    console = FakeConsole()
    simh_port = await console.start()
    monkeypatch.setattr(shim, "SIMH_PORT", simh_port)

    handler_tasks: set[asyncio.Task[Any]] = set()

    def tracked(
        fn: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
    ) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
        async def run(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            task = asyncio.current_task()
            assert task is not None
            handler_tasks.add(task)
            try:
                await fn(reader, writer)
            finally:
                handler_tasks.discard(task)

        return run

    servers = [
        await asyncio.start_server(tracked(shim._handle), "127.0.0.1", 0),
        await asyncio.start_server(tracked(shim._handle_watch), "127.0.0.1", 0),
        await asyncio.start_server(tracked(shim._handle_lamp_stream), "127.0.0.1", 0),
    ]
    main_port, watch_port, lamp_port = (int(s.sockets[0].getsockname()[1]) for s in servers)
    try:
        yield Rig(
            console,
            main_port,
            watch_port,
            lamp_port,
            {"main": main_port, "watch": watch_port, "lamp": lamp_port},
        )
    finally:
        for s in servers:
            s.close()
        # A leaked handler never ends by itself; cancel so the test run stays clean.
        for t in list(handler_tasks):
            t.cancel()
        await asyncio.gather(*handler_tasks, return_exceptions=True)
        await console.stop()


# ── Shim: a client that goes away must release its SimH connection ────────────


@pytest.mark.parametrize("how", ["fin", "rst"])
@pytest.mark.parametrize("port_name", ["watch", "lamp", "main"])
async def test_shim_releases_backend_when_client_vanishes(
    rig: Rig, port_name: str, how: str
) -> None:
    """Fails on the old shim for watch/lamp + FIN: a quiet stream never noticed."""
    client = await FakeClient.connect(rig.ports[port_name])
    assert await wait_until(lambda: rig.console.open == 1), "shim never opened its backend"

    client.vanish(how)

    assert await wait_until(lambda: rig.console.open == 0), (
        f"{port_name} stream leaked a SimH connection after the client sent {how}"
    )


@pytest.mark.parametrize("port_name", ["watch", "lamp", "main"])
async def test_shim_closes_client_when_emulator_drops(rig: Rig, port_name: str) -> None:
    client = await FakeClient.connect(rig.ports[port_name])
    assert await wait_until(lambda: rig.console.open == 1)

    rig.console.drop_all()

    assert await client.sees_eof(), "client side of the shim stayed open after SimH closed"
    assert await wait_until(lambda: rig.console.open == 0)
    client.vanish("fin")


async def test_main_port_idle_timeout_closes_backend(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proxied session with no traffic in either direction is eventually closed."""
    monkeypatch.setattr(shim, "IDLE_TIMEOUT", 0.4, raising=False)
    client = await FakeClient.connect(rig.main_port)
    assert await wait_until(lambda: rig.console.open == 1)

    # SimH sends its banner once; after that nothing moves in either direction.
    assert await wait_until(lambda: rig.console.open == 0, timeout=3.0), (
        "idle proxied connection was never closed"
    )
    assert await client.sees_eof()
    client.vanish("fin")


async def test_many_abrupt_clients_never_exceed_console_limit(rig: Rig) -> None:
    """Repeated connect/vanish cycles (the 70 s reconnect loop, compressed)."""
    for _ in range(8):
        client = await FakeClient.connect(rig.lamp_port)
        assert await wait_until(lambda: rig.console.open == 1)
        client.vanish("fin")
        assert await wait_until(lambda: rig.console.open == 0), (
            f"leaked connections pile up: open={rig.console.open}"
        )
    assert rig.console.rejected == 0
    assert rig.console.peak <= 1


# ── Coordinator + shim + fake console ─────────────────────────────────────────


@pytest.fixture
async def coord(
    hass: Any, rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[PiDP11Coordinator]:
    system_file = tmp_path / "current_system"
    system_file.write_text("211bsd")
    monkeypatch.setattr(coordinator_mod, "CURRENT_SYSTEM_PATH", str(system_file))
    monkeypatch.setattr(coordinator_mod, "_DRAIN_QUIET", 0.05)
    # Fast backoff so the busy/retry tests run in well under a second. These
    # names are new; on the old code the setattr is a no-op and the old fixed
    # delays apply, so the tests still fail on their assertions.
    monkeypatch.setattr(coordinator_mod, "_BUSY_BACKOFF_BASE", 0.05, raising=False)
    monkeypatch.setattr(coordinator_mod, "_BUSY_BACKOFF_MAX", 0.2, raising=False)
    monkeypatch.setattr(coordinator_mod, "_BUSY_RETRIES", 3, raising=False)
    monkeypatch.setattr(coordinator_mod, "_STREAM_BACKOFF_BASE", 0.05, raising=False)
    monkeypatch.setattr(coordinator_mod, "_STREAM_BACKOFF_MAX", 0.4, raising=False)

    c = PiDP11Coordinator(hass, host="127.0.0.1", port=rig.main_port, secret=SECRET)
    # The ports are ephemeral, so the +2/+3 offsets do not apply here.
    c._watch_port = rig.watch_port
    c._lamp_port = rig.lamp_port
    try:
        yield c
    finally:
        await stop_streams(c)


async def stop_streams(c: PiDP11Coordinator) -> None:
    c.stop_sr_watch()
    c.stop_lamp_watch()
    stopper = getattr(c, "async_stop_streams", None)
    if stopper is not None:
        await stopper()
    await asyncio.sleep(0)


async def test_integration_never_holds_more_than_its_budget(
    coord: PiDP11Coordinator, rig: Rig
) -> None:
    """Streams plus polls plus commands at once must stay within 2 connections.

    Old code: SR watch + lamp stream + a poll = 3 at the same time.
    """
    await coord.async_refresh()
    assert coord.last_update_success
    coord.start_sr_watch("t_sr")
    coord.start_lamp_watch("t_lamp")
    assert await wait_until(lambda: rig.console.open >= 1)

    for _ in range(5):
        await asyncio.gather(
            coord.async_refresh(),
            coord.async_refresh(),
            coord.async_send_command("EXAMINE 400"),
            coord.async_send_command("HALT"),
        )
        await asyncio.sleep(0.05)

    assert rig.console.peak <= INTEGRATION_BUDGET, (
        f"integration held {rig.console.peak} console connections at once"
    )
    assert rig.console.rejected == 0
    assert coord.last_update_success


async def test_one_shared_stream_carries_lamps_and_switch_register(
    coord: PiDP11Coordinator, rig: Rig
) -> None:
    """One long-lived SimH connection feeds both the lamp and the SR events."""
    await coord.async_refresh()
    assert coord.last_update_success
    lamps: list[dict[str, str]] = []
    sr_changes: list[dict[str, str]] = []
    coord.hass.bus.async_listen(EVENT_LAMPS, lambda e: lamps.append(dict(e.data)))
    coord.hass.bus.async_listen(EVENT_SR_CHANGED, lambda e: sr_changes.append(dict(e.data)))

    coord.start_sr_watch("t_sr")
    coord.start_lamp_watch("t_lamp")
    assert await wait_until(lambda: len(lamps) >= 1), "no lamp event arrived"
    assert rig.console.open == 1, f"expected one shared stream, got {rig.console.open}"

    rig.console.regs["SR"] = "000007"
    assert await wait_until(lambda: len(sr_changes) >= 1), "no SR event arrived"
    assert sr_changes[0] == {"sr_old": "000005", "sr_new": "000007"}
    assert rig.console.open == 1


async def test_connections_return_to_zero_after_streams_are_cancelled(
    coord: PiDP11Coordinator, rig: Rig
) -> None:
    """Unload path: cancelling the streams must free every SimH connection."""
    await coord.async_refresh()
    coord.start_sr_watch("t_sr")
    coord.start_lamp_watch("t_lamp")
    assert await wait_until(lambda: rig.console.open >= 1)

    await stop_streams(coord)

    assert await wait_until(lambda: rig.console.open == 0), (
        f"{rig.console.open} console connection(s) still held after unload"
    )
    assert rig.console.rejected == 0


async def test_poll_leaves_no_connection_open(coord: PiDP11Coordinator, rig: Rig) -> None:
    for _ in range(5):
        await coord.async_refresh()
        assert coord.last_update_success
    assert await wait_until(lambda: rig.console.open == 0)
    assert rig.console.peak == 1


async def test_poll_closes_its_connection_when_auth_stalls(
    coord: PiDP11Coordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server that accepts but never answers AUTH must not strand the socket."""

    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.read()  # never answers
        except ConnectionError:
            pass

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    coord.port = port
    monkeypatch.setattr(coordinator_mod, "_AUTH_TIMEOUT", 0.2, raising=False)

    opened: list[asyncio.StreamWriter] = []
    real_open = asyncio.open_connection

    async def recording_open(*args: Any, **kwargs: Any) -> Any:
        reader, writer = await real_open(*args, **kwargs)
        opened.append(writer)
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", recording_open)
    try:
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert opened, "the poll never connected"
        assert all(w.is_closing() for w in opened), "poll left its socket open after a failure"
    finally:
        server.close()
        for w in opened:
            w.close()


# ── Busy console: back off, keep the last values ──────────────────────────────


async def _hog(rig: Rig, count: int) -> list[FakeClient]:
    """Occupy ``count`` console connections as another user (e.g. a telnet session)."""
    hogs = []
    for _ in range(count):
        hogs.append(await FakeClient.connect(rig.main_port))
    assert await wait_until(lambda: rig.console.open == count)
    return hogs


async def test_busy_console_keeps_entities_available_with_last_values(
    coord: PiDP11Coordinator, rig: Rig
) -> None:
    await coord.async_refresh()
    assert coord.last_update_success
    before = coord.data
    assert before is not None and before.pc == "000400"

    hogs = await _hog(rig, CONSOLE_LIMIT)
    rig.console.regs["PC"] = "001000"
    await coord.async_refresh()

    assert coord.last_update_success, "entities flapped to unavailable on 'All connections busy'"
    assert coord.data is not None
    assert coord.data.pc == before.pc, "last known values were not kept"
    assert rig.console.rejected >= 2, "poll gave up without retrying"
    gaps = [b - a for a, b in itertools.pairwise(rig.console.reject_times)]
    assert len(gaps) >= 2 and gaps[-1] > gaps[0], f"retries are not backing off: {gaps}"

    for h in hogs:
        h.vanish("fin")
    assert await wait_until(lambda: rig.console.open == 0)

    await coord.async_refresh()
    assert coord.last_update_success
    assert coord.data is not None
    assert coord.data.pc == "001000", "did not recover once a connection was free"


async def test_busy_console_on_first_refresh_is_a_clean_failure(
    coord: PiDP11Coordinator, rig: Rig
) -> None:
    """With no last values to keep, the first refresh fails (setup will retry)."""
    hogs = await _hog(rig, CONSOLE_LIMIT)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    for h in hogs:
        h.vanish("fin")
    assert await wait_until(lambda: rig.console.open == 0)


async def test_command_retries_when_console_busy(coord: PiDP11Coordinator, rig: Rig) -> None:
    hogs = await _hog(rig, CONSOLE_LIMIT)

    async def free_one_soon() -> None:
        await asyncio.sleep(0.12)
        hogs[0].vanish("fin")

    freer = asyncio.create_task(free_one_soon())
    text = await coord.async_send_command("EXAMINE 400")
    await freer

    assert "400" in text
    assert rig.console.rejected >= 1
    for h in hogs[1:]:
        h.vanish("fin")


async def test_stream_backs_off_while_console_is_busy_then_recovers(
    coord: PiDP11Coordinator, rig: Rig
) -> None:
    await coord.async_refresh()
    lamps: list[dict[str, str]] = []
    coord.hass.bus.async_listen(EVENT_LAMPS, lambda e: lamps.append(dict(e.data)))

    hogs = await _hog(rig, CONSOLE_LIMIT)
    coord.start_sr_watch("t_sr")
    coord.start_lamp_watch("t_lamp")

    assert await wait_until(lambda: rig.console.rejected >= 3, timeout=3.0), (
        "stream is not retrying quickly enough while busy"
    )
    await asyncio.sleep(0.5)
    attempts = list(rig.console.reject_times)
    gaps = [b - a for a, b in itertools.pairwise(attempts)]
    assert gaps[-1] > gaps[0], f"stream reconnects are not backing off: {gaps}"
    assert len(attempts) < 20, f"stream is hammering the console: {len(attempts)} attempts"

    for h in hogs:
        h.vanish("fin")
    assert await wait_until(lambda: len(lamps) >= 1, timeout=3.0), "stream never recovered"
    assert rig.console.open == 1
