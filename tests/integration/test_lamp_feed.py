"""Coordinator side of the live lamp feed: the lamp stream against a fake add-on.

A fake shim on loopback speaks the lamp-port protocol (AUTH, OK, then lines the test
sends). The coordinator's shared stream connects to it. Checked here:

* the AUTH line asks for SR and the live feed at the option rate, clamped to 5-20 fps;
* a ``LAMPS2`` line fires ``pidp11_lamps2`` with the percent per lamp, clamped to 0-100;
* no more than ``lamp_fps`` events are fired in any one second;
* malformed ``LAMPS2`` lines are dropped without stopping the stream;
* the old ``EVENT lamps`` line still fires ``pidp11_lamps``;
* a shim that refuses the new flags is asked again with fewer (no lamp feed is lost);
* stopping the stream closes its connection.

No Home Assistant instance beyond the ``hass`` fixture, no Pi, no real SimH.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from custom_components.pidp11 import coordinator as coordinator_mod
from custom_components.pidp11.const import EVENT_LAMPS, EVENT_LAMPS2
from custom_components.pidp11.coordinator import PiDP11Coordinator

pytestmark = [pytest.mark.usefixtures("socket_enabled")]

SECRET = "d" * 64


class FakeLampShim:
    """Accepts lamp-stream clients, answers OK unless the AUTH line has a refused token."""

    def __init__(self, refused_tokens: tuple[str, ...] = ()) -> None:
        self.refused_tokens = refused_tokens
        self.auth_lines: list[str] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.open = 0
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.open += 1
        try:
            line = (await reader.readline()).decode(errors="replace").strip()
            self.auth_lines.append(line)
            if line.split()[:2] != ["AUTH", SECRET] or any(
                tok in line.split() for tok in self.refused_tokens
            ):
                writer.write(b"DENY bad-auth\n")
                await writer.drain()
                return
            writer.write(b"OK\n# fake lamp stream\n")
            await writer.drain()
            self.writers.append(writer)
            while await reader.read(1024):  # the client sends nothing; EOF means it left
                pass
        except (ConnectionError, OSError):
            pass
        finally:
            self.open -= 1
            writer.close()

    async def send(self, text: str) -> None:
        for writer in self.writers:
            writer.write(text.encode())
            await writer.drain()


async def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.fixture
async def shim_factory() -> AsyncIterator[Any]:
    made: list[FakeLampShim] = []

    async def make(refused_tokens: tuple[str, ...] = ()) -> FakeLampShim:
        shim = FakeLampShim(refused_tokens)
        await shim.start()
        made.append(shim)
        return shim

    yield make
    for shim in made:
        await shim.stop()


@pytest.fixture
def no_stream_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coordinator_mod, "_STREAM_BACKOFF_BASE", 0.05)
    monkeypatch.setattr(coordinator_mod, "_STREAM_BACKOFF_MAX", 0.2)


async def _started(
    hass: Any, shim: FakeLampShim, **kwargs: Any
) -> tuple[PiDP11Coordinator, list[dict[str, Any]], list[dict[str, Any]]]:
    coord = PiDP11Coordinator(hass, host="127.0.0.1", port=0, secret=SECRET, **kwargs)
    coord._lamp_port = shim.port  # the stream connects to port + 3 in production
    lamps2: list[dict[str, Any]] = []
    lamps: list[dict[str, Any]] = []
    hass.bus.async_listen(EVENT_LAMPS2, lambda e: lamps2.append(dict(e.data)))
    hass.bus.async_listen(EVENT_LAMPS, lambda e: lamps.append(dict(e.data)))
    coord.start_lamp_watch("test_lamp_feed")
    assert await wait_until(lambda: bool(shim.writers)), "the stream never authenticated"
    return coord, lamps2, lamps


# ── AUTH line and the fps option ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("requested", "sent"),
    [(10, 10), (5, 5), (20, 20), (99, 20), (1, 5), (0, 5)],
)
async def test_auth_line_carries_the_clamped_fps(
    hass: Any, shim_factory: Any, no_stream_backoff: None, requested: int, sent: int
) -> None:
    shim = await shim_factory()
    coord, _lamps2, _lamps = await _started(hass, shim, lamp_fps=requested)
    try:
        assert shim.auth_lines[0] == f"AUTH {SECRET} +sr +lamps fps={sent}"
        assert coord.lamp_fps == sent
    finally:
        await coord.async_stop_streams()


async def test_default_fps_is_ten(hass: Any, shim_factory: Any, no_stream_backoff: None) -> None:
    shim = await shim_factory()
    coord, _l2, _l = await _started(hass, shim)
    try:
        assert coord.lamp_fps == 10
        assert shim.auth_lines[0].endswith("+lamps fps=10")
    finally:
        await coord.async_stop_streams()


# ── LAMPS2 frames ────────────────────────────────────────────────────────────


async def test_live_frame_fires_lamps2_with_clamped_percent(
    hass: Any, shim_factory: Any, no_stream_backoff: None
) -> None:
    shim = await shim_factory()
    coord, lamps2, _ = await _started(hass, shim)
    try:
        await shim.send(
            'LAMPS2 {"seq": 7, "leds": {"ADDRESS21": 100, "DATA0": 150, "RUN": -5, '
            '"PAUSE": "x", "PARITY_HIGH": true, "ADDR_SEL_PPHY": 40.5}}\n'
        )
        assert await wait_until(lambda: len(lamps2) == 1), "no pidp11_lamps2 event"
        assert lamps2[0] == {
            "seq": 7,
            "leds": {"ADDRESS21": 100.0, "DATA0": 100.0, "RUN": 0.0, "ADDR_SEL_PPHY": 40.5},
        }
    finally:
        await coord.async_stop_streams()


async def test_fps_cap_drops_frames_over_the_rate(
    hass: Any, shim_factory: Any, no_stream_backoff: None
) -> None:
    shim = await shim_factory()
    coord, lamps2, _ = await _started(hass, shim, lamp_fps=5)
    try:
        burst = "".join(
            f'LAMPS2 {{"seq": {n}, "leds": {{"RUN": 100}}}}\n' for n in range(1, 31)
        )
        await shim.send(burst)
        assert await wait_until(lambda: len(lamps2) >= 5)
        await asyncio.sleep(0.3)
        assert len(lamps2) == 5, [e["seq"] for e in lamps2]  # 30 sent, 5 per second allowed
        assert [e["seq"] for e in lamps2] == [1, 2, 3, 4, 5]

        # Once the second has passed, frames are accepted again.
        await asyncio.sleep(1.05)
        await shim.send('LAMPS2 {"seq": 99, "leds": {"RUN": 100}}\n')
        assert await wait_until(lambda: len(lamps2) == 6)
        assert lamps2[-1]["seq"] == 99
    finally:
        await coord.async_stop_streams()


async def test_malformed_lamps2_lines_are_dropped_and_the_stream_survives(
    hass: Any, shim_factory: Any, no_stream_backoff: None
) -> None:
    shim = await shim_factory()
    coord, lamps2, _ = await _started(hass, shim)
    try:
        await shim.send(
            "LAMPS2 {not json\n"
            "LAMPS2 []\n"
            'LAMPS2 {"seq": "3", "leds": {}}\n'
            'LAMPS2 {"seq": 4}\n'
            'LAMPS2 {"seq": 5, "leds": []}\n'
            'LAMPS2 {"seq": 9, "leds": {"RUN": NaN, "PAUSE": 50}}\n'
            'LAMPS2 {"seq": 10, "leds": {"RUN": 100}}\n'
        )
        assert await wait_until(lambda: any(e["seq"] == 10 for e in lamps2))
        await asyncio.sleep(0.1)
        seqs = [e["seq"] for e in lamps2]
        assert seqs == [9, 10], seqs  # seq 9 keeps PAUSE and drops the NaN lamp
        assert lamps2[0]["leds"] == {"PAUSE": 50.0}
    finally:
        await coord.async_stop_streams()


# ── Old format and the fallback ──────────────────────────────────────────────


async def test_old_format_still_fires_pidp11_lamps(
    hass: Any, shim_factory: Any, no_stream_backoff: None
) -> None:
    shim = await shim_factory()
    coord, lamps2, lamps = await _started(hass, shim)
    try:
        await shim.send("EVENT lamps ADDRESS=000400 DATA=140246\n")
        assert await wait_until(lambda: len(lamps) == 1), "no pidp11_lamps event"
        assert lamps[0] == {"address": "000400", "data": "140246"}
        assert lamps2 == []
    finally:
        await coord.async_stop_streams()


async def test_refused_flags_fall_back_one_step_at_a_time(
    hass: Any, shim_factory: Any, no_stream_backoff: None
) -> None:
    # An add-on that does not know +lamps refuses the whole line; the stream asks
    # again with +sr only, and the old-format lamp events still arrive.
    shim = await shim_factory(refused_tokens=("+lamps",))
    coord, _lamps2, lamps = await _started(hass, shim)
    try:
        assert shim.auth_lines[0] == f"AUTH {SECRET} +sr +lamps fps=10"
        assert shim.auth_lines[1] == f"AUTH {SECRET} +sr"
        await shim.send("EVENT lamps ADDRESS=000200 DATA=000000\n")
        assert await wait_until(lambda: len(lamps) == 1)
    finally:
        await coord.async_stop_streams()


async def test_stopping_the_stream_closes_its_connection(
    hass: Any, shim_factory: Any, no_stream_backoff: None
) -> None:
    shim = await shim_factory()
    coord, _l2, _l = await _started(hass, shim)
    assert shim.open == 1
    await coord.async_stop_streams()
    assert await wait_until(lambda: shim.open == 0), "the shim still holds the stream"
