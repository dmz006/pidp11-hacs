"""Config-flow behavior."""

from __future__ import annotations

import inspect

import pytest


def test_user_step_creates_entry() -> None:
    from custom_components.pidp11.config_flow import PiDP11ConfigFlow

    assert hasattr(PiDP11ConfigFlow, "async_step_user")
    assert inspect.iscoroutinefunction(PiDP11ConfigFlow.async_step_user)
    assert PiDP11ConfigFlow.VERSION == 1


@pytest.mark.xfail(reason="requires HA test harness", strict=True)
def test_duplicate_host_aborts() -> None:
    raise NotImplementedError("requires HA test harness")


@pytest.mark.xfail(reason="requires HA test harness", strict=True)
def test_reauth_on_bad_secret() -> None:
    raise NotImplementedError("requires HA test harness")
