"""Fakes for the lamp tests: a synthetic panel scan. No hardware, no device.

A brightness cycle is built the way the panel daemon drives it: 31 phases, and
in each phase one switch-scan sample (no row high, ignored by the decoder)
followed by one sample per LED row with that row's lit columns driven LOW.
A lamp is lit in phase p when p < its level (0..31).
"""

from __future__ import annotations

from collections.abc import Mapping

from gpio_lamps import COL_PINS, LED_MAP, LEDROW_PINS

PHASES = 31
SAMPLES_PER_CYCLE = PHASES * (1 + len(LEDROW_PINS))  # 217
ALL_COLS_HIGH = sum(1 << pin for pin in COL_PINS)


def scan_cycle(levels: Mapping[str, int]) -> list[int]:
    """Raw SYNC_IN values for one brightness cycle, for the given lamp levels."""
    values: list[int] = []
    for phase in range(PHASES):
        values.append(0)  # switch-scan sample: no LED row high
        for r, row_pin in enumerate(LEDROW_PINS):
            v = (1 << row_pin) | ALL_COLS_HIGH
            for k, col_pin in enumerate(COL_PINS):
                name = LED_MAP.get((r, k))
                if name is not None and phase < levels.get(name, 0):
                    v &= ~(1 << col_pin)  # column LOW lights the lamp (gpio.c:190-193)
            values.append(v)
    return values


class FakeScan:
    """Replays a cycle as a register reader. With ``clock()``, each read is 1 us."""

    def __init__(self, cycle: list[int]) -> None:
        self._cycle = cycle
        self._i = 0
        self._t = 0.0

    def read(self) -> int:
        value = self._cycle[self._i % len(self._cycle)]
        self._i += 1
        self._t += 1e-6
        return value

    def clock(self) -> float:
        return self._t
