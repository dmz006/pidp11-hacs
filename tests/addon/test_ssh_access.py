"""SSH console. S0: xfail until S2."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.addon


@pytest.mark.xfail(reason="pending S2", strict=True)
def test_ssh_accepts_password() -> None:
    raise NotImplementedError("pending S2")


@pytest.mark.xfail(reason="pending S2", strict=True)
def test_ssh_rejects_bad_password() -> None:
    raise NotImplementedError("pending S2")


@pytest.mark.xfail(reason="pending S2", strict=True)
def test_ssh_lands_in_screen() -> None:
    raise NotImplementedError("pending S2")


@pytest.mark.xfail(reason="pending S2", strict=True)
def test_detach_preserves_simh() -> None:
    raise NotImplementedError("pending S2")


@pytest.mark.xfail(reason="pending S2", strict=True)
def test_second_user_shares_screen() -> None:
    raise NotImplementedError("pending S2")
