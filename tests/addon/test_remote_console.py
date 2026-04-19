"""SimH remote-console + auth shim. S0: xfail until S1/S3."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.addon


@pytest.mark.xfail(reason="pending S1", strict=True)
def test_requires_auth() -> None:
    raise NotImplementedError("pending S1")


@pytest.mark.xfail(reason="pending S1", strict=True)
def test_show_cpu_responds() -> None:
    raise NotImplementedError("pending S1")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_halted_state_reported() -> None:
    raise NotImplementedError("pending S3")
