"""gpio_lamps: decoding, burst sampling, fps clamp, fallback, read-only mapping.

Fakes only: a synthetic register scan replayed through the real decoder, and a
temporary file standing in for the GPIO device. No hardware is touched.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from gpio_lamps import (
    COL_PINS,
    LAMP_CHANGE_POINTS,
    LED_MAP,
    LEDROW_PINS,
    LampSampler,
    LampUnavailable,
    clamp_fps,
    decode,
    env_fps,
    lamps_changed,
    open_readonly,
)

from ._lamp_fakes import FakeScan, scan_cycle

# Burst length that covers exactly 20 full cycles of the fake scan at 1 us/read.
BURST_MS_20_CYCLES = 4.34


def _value(row: int | None = None, lit_cols: tuple[int, ...] = ()) -> int:
    """One raw sample: ``row`` high (or none), and the given columns lit (LOW)."""
    v = sum(1 << pin for pin in COL_PINS)
    if row is not None:
        v |= 1 << LEDROW_PINS[row]
    for k in lit_cols:
        v &= ~(1 << COL_PINS[k])
    return v


def test_decode_exact_percentages_and_mode_aliases() -> None:
    counter = {
        _value(0, (0,)): 3,      # ADDRESS0 lit in 3 of 4 row-0 samples
        _value(0, (1,)): 1,      # ADDRESS1 lit in 1 of 4
        _value(2, (6, 5)): 2,    # MMR0 bits 2 and 1 lit: USER (code 11)
        _value(2, (5,)): 1,      # code 01: SUPER
        _value(2, ()): 1,        # code 00: KERNEL
        _value(0, (0,)) | (1 << LEDROW_PINS[1]): 50,  # two rows high: ignored
    }
    out = decode(counter)
    assert out["ADDRESS0"] == 75
    assert out["ADDRESS1"] == 25
    assert out["ADDRESS2"] == 0
    assert out["MMR0_MODE_BIT2"] == 50
    assert out["USER"] == 50
    assert out["SUPER"] == 25
    assert out["KERNEL"] == 25
    assert all(0 <= v <= 100 and isinstance(v, int) for v in out.values())


def test_decode_keeps_probe_lamp_names() -> None:
    out = decode({})
    for name in LED_MAP.values():
        assert name in out
    for alias in ("USER", "SUPER", "KERNEL"):
        assert alias in out


def test_burst_sampling_matches_synthetic_scan() -> None:
    levels = {
        "ADDRESS0": 31,          # always lit
        "DATA3": 16,             # 16/31 of phases
        "ADDRESS1": 8,           # 8/31
        "RUN": 0,                # never
        "MMR0_MODE_BIT2": 31,    # USER: both mode bits lit
        "MMR0_MODE_BIT1": 31,
    }
    scan = FakeScan(scan_cycle(levels))
    sampler = LampSampler(reader=scan.read, clock=scan.clock, burst_ms=BURST_MS_20_CYCLES)
    out = sampler.frame()

    assert out["ADDRESS0"] == 100
    assert abs(out["DATA3"] - 52) <= 1          # 16/31 = 51.6 %
    assert abs(out["ADDRESS1"] - 26) <= 1       # 8/31 = 25.8 %
    assert out["RUN"] == 0
    assert out["USER"] == 100
    assert out["SUPER"] == 0
    assert out["KERNEL"] == 0
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in out.values())


def test_fps_clamp() -> None:
    assert clamp_fps(1) == 5
    assert clamp_fps(4) == 5
    assert clamp_fps(99) == 20
    assert clamp_fps("7") == 7
    assert clamp_fps("abc") == 10
    assert clamp_fps(None, default=12) == 12


def test_env_fps_reads_lamp_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAMP_FPS", raising=False)
    assert env_fps() == 10
    monkeypatch.setenv("LAMP_FPS", "3")
    assert env_fps() == 5
    monkeypatch.setenv("LAMP_FPS", "40")
    assert env_fps() == 20
    monkeypatch.setenv("LAMP_FPS", "fast")
    assert env_fps() == 10


def test_sampler_rate_is_clamped() -> None:
    scan = FakeScan(scan_cycle({}))
    assert LampSampler(reader=scan.read, fps=50).fps == 20
    assert LampSampler(reader=scan.read, fps=2).fps == 5


def test_missing_device_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(LampUnavailable):
        LampSampler(device=str(tmp_path / "no-such-gpiomem0"))


def test_empty_device_is_unavailable(tmp_path: Path) -> None:
    empty = tmp_path / "gpiomem0"
    empty.write_bytes(b"")
    with pytest.raises(LampUnavailable):
        LampSampler(device=str(empty))


def test_device_is_mapped_read_only(tmp_path: Path) -> None:
    window = tmp_path / "gpiomem0"
    window.write_bytes(b"\x00" * 0x20000)
    mm = open_readonly(str(window))
    try:
        with pytest.raises((TypeError, ValueError)):
            mm[0] = 1
    finally:
        mm.close()

    sampler = LampSampler(str(window), burst_ms=0.1)
    try:
        out = sampler.frame()          # all-zero window: no row ever high
        assert out and all(v == 0 for v in out.values())
    finally:
        sampler.close()
    assert sampler.closed


def test_lamps_changed_uses_two_point_threshold() -> None:
    assert LAMP_CHANGE_POINTS == 2
    assert lamps_changed(None, {"A": 0})
    assert not lamps_changed({"A": 10}, {"A": 10})
    assert not lamps_changed({"A": 10}, {"A": 11})
    assert lamps_changed({"A": 10}, {"A": 12})
    assert lamps_changed({"A": 10}, {"A": 8})
    assert lamps_changed({"A": 10}, {"A": 10, "B": 0})


def test_frames_follow_the_configured_rate() -> None:
    async def count(rate: int, seconds: float) -> int:
        scan = FakeScan(scan_cycle({}))
        sampler = LampSampler(reader=scan.read, burst_ms=0.1)
        n = 0

        async def consume() -> None:
            nonlocal n
            async for _ in sampler.frames(rate=rate):
                n += 1

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(seconds)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return n

    async def main() -> tuple[int, int]:
        return await count(5, 0.5), await count(20, 0.5)

    slow, fast = asyncio.run(main())
    assert 1 <= slow <= 4        # about 3 frames at 5 fps in 0.5 s
    assert fast >= 6             # about 10 frames at 20 fps in 0.5 s
