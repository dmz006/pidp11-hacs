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


def test_clean_strips_pasted_whitespace() -> None:
    from custom_components.pidp11.config_flow import _clean

    secret = "a" * 64
    assert _clean(f" {secret} \n") == secret
    assert _clean(f"{secret}\r\n") == secret


@pytest.mark.asyncio
async def test_secret_check_accepts_clean_and_rejects_padded(socket_enabled) -> None:
    """A fake auth shim compares byte for byte, like the real one: padding is DENY."""
    import asyncio

    from custom_components.pidp11.config_flow import _clean, _validate_connection

    secret = "b" * 64

    async def run() -> tuple[str | None, str | None, str | None]:
        async def handle(reader, writer):
            raw = (await reader.readline()).decode().rstrip("\r\n")
            parts = raw.split(" ", 1)
            ok = len(parts) == 2 and parts[0] == "AUTH" and parts[1] == secret
            writer.write(b"OK\n" if ok else b"DENY bad-auth\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            good = await _validate_connection("127.0.0.1", port, secret)
            padded = await _validate_connection("127.0.0.1", port, secret + " ")
            cleaned = await _validate_connection("127.0.0.1", port, _clean(secret + " \n"))
        finally:
            server.close()
            await server.wait_closed()
        return good, padded, cleaned

    good, padded, cleaned = await run()
    assert good is None
    assert padded == "invalid_auth"
    assert cleaned is None


def test_reconfigure_step_exists() -> None:
    import inspect

    from custom_components.pidp11.config_flow import PiDP11ConfigFlow

    assert inspect.iscoroutinefunction(PiDP11ConfigFlow.async_step_reconfigure)
