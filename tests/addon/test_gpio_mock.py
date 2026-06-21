"""GPIO lamp/switch driver tests. Requires PIDP11_GPIO_MOCK=1 container env."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.addon


@pytest.mark.xfail(reason="pending S4 — requires PIDP11_GPIO_MOCK=1 container", strict=True)
def test_driver_writes_lamp_register() -> None:
    """Blinkenlight server writes expected bytes to the lamp register in /dev/mem."""
    raise NotImplementedError("pending S4")


@pytest.mark.xfail(reason="pending S4 — requires PIDP11_GPIO_MOCK=1 container", strict=True)
def test_driver_reads_switch_register() -> None:
    """scansw returns a value matching the SR register address written to /dev/mem mock."""
    raise NotImplementedError("pending S4")
