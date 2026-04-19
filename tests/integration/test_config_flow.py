"""Config-flow behavior. S0: stub that is expected to FAIL until S3."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_user_step_creates_entry() -> None:
    from custom_components.pidp11.config_flow import PiDP11ConfigFlow

    flow = PiDP11ConfigFlow()
    flow.async_step_user({})  # raises NotImplementedError


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_duplicate_host_aborts() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_reauth_on_bad_secret() -> None:
    raise NotImplementedError("pending S3")
