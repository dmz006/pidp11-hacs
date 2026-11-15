"""LAMPS2 lamp stream on the real shim handler, with fakes for the panel and SimH.

Covers: the two-point rule on the wire, the keepalive, one shared sampler for two
clients (and its rate), +sr over the one SimH connection the stream owns, the
fallback to ``EVENT lamps`` when the GPIO device is missing, and a stream that
ends when the shared sampler fails. Loopback sockets only; no Docker, no SimH.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import authshim as shim
import pytest
from gpio_lamps import LampFeedFailed, LampSampler, SharedLampFeed

from ._lamp_fakes import FakeScan, scan_cycle

pytestmark = [pytest.mark.usefixtures("socket_enabled")]

SECRET = b"testsecret"
_PREFIX = b"LAMPS2 "


class ScriptedFeed:
    """Stands in for SharedLampFeed. Hands out scripted frames, one per poll."""

    def __init__(self, frames: list[dict[str, int]], *, repeat: bool = False) -> None:
        self._frames = frames
        self._repeat = repeat
        self._i = 0
        self.seq = 0
        self.cur: dict[str, int] | None = None
        self.subs = 0

    async def subscribe(self, fps: int | None = None) -> object:
        self.subs += 1
        return object()

    def unsubscribe(self, token: object) -> None:
        self.subs -= 1

    async def next_frame(self, after: int, timeout: float) -> tuple[int, dict[str, int]] | None:
        if self._i < len(self._frames):
            self.cur = self._frames[self._i]
            self._i += 1
        elif self._repeat and self.cur is not None:
            pass
        else:
            await asyncio.sleep(timeout)
            return None
        self.seq += 1
        await asyncio.sleep(0.02)
        assert self.cur is not None
        return self.seq, self.cur

    def latest(self) -> tuple[int, dict[str, int]] | None:
        return None if self.cur is None else (self.seq, self.cur)


class FailingFeed(ScriptedFeed):
    async def next_frame(self, after: int, timeout: float) -> tuple[int, dict[str, int]] | None:
        raise LampFeedFailed("device went away")


class CountingOpener:
    """Stands in for LampSampler(): each call makes a sampler over a fixed scan."""

    def __init__(self, levels: dict[str, int]) -> None:
        self._cycle = scan_cycle(levels)
        self.opened: list[LampSampler] = []

    def __call__(self) -> LampSampler:
        sampler = LampSampler(reader=FakeScan(self._cycle).read, burst_ms=0.2)
        self.opened.append(sampler)
        return sampler


def _use_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "secret"
    secret.write_text(SECRET.decode())
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret))


async def _serve_lamps() -> tuple[asyncio.Server, int]:
    server = await asyncio.start_server(shim._handle_lamp_stream, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _open(port: int, auth_line: bytes) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(auth_line)
    await writer.drain()
    ok = await asyncio.wait_for(reader.readline(), 2.0)
    assert ok.strip() == b"OK"
    return reader, writer


async def _lamps2(
    reader: asyncio.StreamReader, count: int, timeout: float
) -> list[tuple[float, dict]]:
    """Read up to ``count`` LAMPS2 lines within ``timeout``; (time, parsed) pairs."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    out: list[tuple[float, dict]] = []
    while len(out) < count:
        remaining = end - loop.time()
        if remaining <= 0:
            break
        try:
            line = await asyncio.wait_for(reader.readline(), remaining)
        except TimeoutError:
            break
        if not line:
            break
        if line.startswith(_PREFIX):
            out.append((loop.time(), json.loads(line[len(_PREFIX):])))
    return out


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()


async def _wait_until(pred: Callable[[], bool], timeout: float = 2.0) -> bool:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


def test_requested_fps_token() -> None:
    assert shim._requested_fps(frozenset({"+lamps", "fps=20"})) == 20
    assert shim._requested_fps(frozenset({"+lamps", "fps=99"})) == 20
    assert shim._requested_fps(frozenset({"+lamps", "fps=1"})) == 5
    assert shim._requested_fps(frozenset({"+lamps", "fps=abc"})) is None
    assert shim._requested_fps(frozenset({"+lamps"})) is None


def test_sends_only_on_two_point_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_secret(tmp_path, monkeypatch)
    monkeypatch.setattr(shim, "LAMPS_KEEPALIVE_S", 100.0)
    feed = ScriptedFeed([
        {"ADDRESS0": 50, "DATA0": 0},
        {"ADDRESS0": 51, "DATA0": 0},   # 1 point: not sent
        {"ADDRESS0": 53, "DATA0": 0},   # 3 points against the last sent (50): sent
        {"ADDRESS0": 54, "DATA0": 0},   # 1 point against 53: not sent
    ])
    monkeypatch.setattr(shim, "_lamp_feed", feed)

    async def run() -> list[dict]:
        server, port = await _serve_lamps()
        try:
            reader, writer = await _open(port, b"AUTH testsecret +lamps\n")
            try:
                lines = await _lamps2(reader, 3, timeout=1.0)
            finally:
                await _close(writer)
        finally:
            server.close()
            await server.wait_closed()
        return [obj for _, obj in lines]

    got = asyncio.run(run())
    assert [(o["seq"], o["leds"]["ADDRESS0"]) for o in got] == [(1, 50), (2, 53)]


def test_keepalive_repeats_unchanged_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_secret(tmp_path, monkeypatch)
    monkeypatch.setattr(shim, "LAMPS_KEEPALIVE_S", 0.3)
    frame = {"ADDRESS0": 50, "DATA0": 0}
    monkeypatch.setattr(shim, "_lamp_feed", ScriptedFeed([frame], repeat=True))

    async def run() -> list[tuple[float, dict]]:
        server, port = await _serve_lamps()
        try:
            reader, writer = await _open(port, b"AUTH testsecret +lamps fps=20\n")
            try:
                return await _lamps2(reader, 3, timeout=3.0)
            finally:
                await _close(writer)
        finally:
            server.close()
            await server.wait_closed()

    lines = asyncio.run(run())
    assert [obj["seq"] for _, obj in lines] == [1, 2, 3]
    assert all(obj["leds"] == frame for _, obj in lines)
    # Unchanged frames arrive every 20 ms; the lines themselves come only on the keepalive.
    gap = lines[1][0] - lines[0][0]
    assert 0.25 <= gap <= 1.0


def test_one_shared_sampler_for_two_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_secret(tmp_path, monkeypatch)
    opener = CountingOpener({"ADDRESS0": 31, "RUN": 16})
    feed = SharedLampFeed(opener)
    monkeypatch.setattr(shim, "_lamp_feed", feed)

    async def run() -> dict[str, Any]:
        server, port = await _serve_lamps()
        try:
            r1, w1 = await _open(port, b"AUTH testsecret +lamps fps=5\n")
            r2, w2 = await _open(port, b"AUTH testsecret +lamps fps=20\n")
            try:
                first = await _lamps2(r1, 1, timeout=2.0)
                second = await _lamps2(r2, 1, timeout=2.0)
                fps_both = feed.current_fps()
                opened_while_both = len(opener.opened)

                await _close(w1)
                await _wait_until(lambda: feed.subscriber_count() == 1)
                still_running = feed.running()
                fps_after_one = feed.current_fps()

                await _close(w2)
                gone = await _wait_until(lambda: feed.subscriber_count() == 0)
                return {
                    "first": first, "second": second, "fps_both": fps_both,
                    "opened_while_both": opened_while_both,
                    "still_running": still_running, "fps_after_one": fps_after_one,
                    "gone": gone, "running_after": feed.running(),
                }
            finally:
                await _close(w1)
                await _close(w2)
        finally:
            server.close()
            await server.wait_closed()

    out = asyncio.run(run())
    assert len(out["first"]) == 1 and len(out["second"]) == 1
    assert out["first"][0][1]["seq"] == 1
    assert out["second"][0][1]["seq"] == 1
    assert out["opened_while_both"] == 1                            # one device, one sampler
    assert out["fps_both"] == 20                                    # highest requested wins
    assert out["still_running"] is True
    assert out["fps_after_one"] == 20
    assert out["gone"] is True
    assert out["running_after"] is False
    assert opener.opened[0].closed                                  # released with the last client


def test_plus_sr_uses_one_simh_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_secret(tmp_path, monkeypatch)
    monkeypatch.setattr(shim, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(shim, "_lamp_feed", SharedLampFeed(CountingOpener({"ADDRESS0": 31})))

    async def run() -> tuple[list[bytes], int, bool]:
        simh, simh_port, stats = await _fake_simh({b"EXAMINE SR": "SR:\t000007"})
        monkeypatch.setattr(shim, "SIMH_PORT", simh_port)
        server, port = await _serve_lamps()
        try:
            reader, writer = await _open(port, b"AUTH testsecret +lamps +sr fps=10\n")
            lines: list[bytes] = []
            loop = asyncio.get_running_loop()
            end = loop.time() + 2.0
            while len(lines) < 2 and loop.time() < end:
                try:
                    line = await asyncio.wait_for(reader.readline(), end - loop.time())
                except TimeoutError:
                    break
                if line.startswith((_PREFIX, b"EVENT sr")):
                    lines.append(line)
            open_during = stats["open"]
            await _close(writer)
            closed = await _wait_until(lambda: stats["open"] == 0)
            return lines, open_during, closed
        finally:
            server.close()
            await server.wait_closed()
            simh.close()
            await simh.wait_closed()

    lines, open_during, closed = asyncio.run(run())
    assert any(line.startswith(_PREFIX) for line in lines)
    assert b"EVENT sr value=000007\n" in lines
    assert open_during == 1          # one SimH connection, owned by this stream
    assert closed                    # released when the client left


def test_falls_back_to_event_lamps_when_device_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_secret(tmp_path, monkeypatch)
    monkeypatch.setattr(shim, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(shim, "LAMP_INTERVAL_MS", 10.0)
    missing = tmp_path / "no-such-gpiomem0"
    monkeypatch.setattr(shim, "_lamp_feed", SharedLampFeed(lambda: LampSampler(device=str(missing))))

    async def run() -> tuple[list[bytes], list[tuple[float, dict]]]:
        simh, simh_port, _ = await _fake_simh({
            b"EXAMINE PC": "PC:\t001400",
            b"EXAMINE PSW": "PSW:\t004000",
            b"EXAMINE SR": "SR:\t000000",
        })
        monkeypatch.setattr(shim, "SIMH_PORT", simh_port)
        server, port = await _serve_lamps()
        try:
            reader, writer = await _open(port, b"AUTH testsecret +lamps\n")
            try:
                event = await asyncio.wait_for(reader.readline(), 2.0)
                more = await _lamps2(reader, 1, timeout=0.5)
            finally:
                await _close(writer)
            return [event], more
        finally:
            server.close()
            await server.wait_closed()
            simh.close()
            await simh.wait_closed()

    events, more = asyncio.run(run())
    assert events[0].strip() == b"EVENT lamps ADDRESS=001400 DATA=004000"
    assert more == []


def test_stream_ends_when_shared_sampler_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_secret(tmp_path, monkeypatch)
    monkeypatch.setattr(shim, "_lamp_feed", FailingFeed([]))

    async def run() -> bytes:
        server, port = await _serve_lamps()
        try:
            reader, writer = await _open(port, b"AUTH testsecret +lamps\n")
            try:
                return await asyncio.wait_for(reader.read(), 2.0)   # EOF = stream ended
            finally:
                await _close(writer)
        finally:
            server.close()
            await server.wait_closed()

    assert asyncio.run(run()) == b""


async def _fake_simh(
    values: dict[bytes, str],
) -> tuple[asyncio.Server, int, dict[str, int]]:
    """A SimH stand-in: prompt on connect, one reply per known EXAMINE line."""
    stats = {"open": 0}

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        stats["open"] += 1
        try:
            writer.write(b"PDP-11 Remote Console\nsim> ")
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    break
                reply = values.get(line.strip())
                if reply is not None:
                    writer.write(f"{reply}\nsim> ".encode())
                    await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            stats["open"] -= 1
            writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], stats
