"""Add-on container boot. Marked `addon` — only runs where Docker is available.

S0: all tests xfail until S1 builds a real image.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.addon


@pytest.mark.xfail(reason="pending S1", strict=True)
def test_image_builds() -> None:
    raise NotImplementedError("pending S1")


@pytest.mark.xfail(reason="pending S1", strict=True)
def test_healthy_within_30s() -> None:
    raise NotImplementedError("pending S1")


@pytest.mark.xfail(reason="pending S1", strict=True)
def test_refuses_empty_ssh_password() -> None:
    raise NotImplementedError("pending S2")
