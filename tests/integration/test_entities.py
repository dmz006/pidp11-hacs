"""Entity platform registration. S0: stubs expected to fail until S3."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_sensor_registered() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_switch_registered() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_state_reflects_coordinator() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_turn_on_sends_boot() -> None:
    raise NotImplementedError("pending S3")
