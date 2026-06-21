"""Container startup ordering — /dev/mem wait, blinkenlightd before SimH."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.addon


@pytest.mark.xfail(reason="pending S4 — requires Docker", strict=True)
def test_waits_for_dev_mem() -> None:
    """Container loops up to 5 s for /dev/mem; disables GPIO and boots idled if unavailable."""
    raise NotImplementedError("pending S4")


@pytest.mark.xfail(reason="pending S4 — requires Docker", strict=True)
def test_blinkenlightd_starts_before_simh() -> None:
    """rpcbind and pidp1170_blinkenlightd are fully up before SimH connects realcons."""
    raise NotImplementedError("pending S4")
