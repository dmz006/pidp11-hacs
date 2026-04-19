"""Coordinator behavior. S0: stubs expected to fail until S3."""

from __future__ import annotations

import pytest


def test_construct() -> None:
    from custom_components.pidp11.coordinator import PiDP11Coordinator

    # Constructing should succeed even at S0 — no network yet.
    coord = PiDP11Coordinator(hass=None, host="h", port=2223, secret="s")  # type: ignore[arg-type]
    assert coord.host == "h"
    assert coord.port == 2223


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_polls_show_cpu() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_reconnects_on_drop() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_parses_halted_state() -> None:
    raise NotImplementedError("pending S3")
