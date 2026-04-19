"""Boot-selector service. S0: xfail until S1/S4."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.addon


@pytest.mark.xfail(reason="pending S1", strict=True)
def test_default_from_options() -> None:
    raise NotImplementedError("pending S1")


@pytest.mark.xfail(reason="pending S4", strict=True)
def test_encoder_position_wins_when_moved() -> None:
    raise NotImplementedError("pending S4 — per R10 decision")
