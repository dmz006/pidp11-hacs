"""Config flow for PiDP-11."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_HOST,
    CONF_REMOTE_CONSOLE_PORT,
    CONF_SHARED_SECRET,
    DEFAULT_HOST,
    DEFAULT_REMOTE_CONSOLE_PORT,
    DOMAIN,
    SHARED_SECRET_PATH,
)

_LOGGER = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 5.0


def _auto_detect_secret() -> str:
    """Try to read the secret from the shared path written by the add-on."""
    try:
        return open(SHARED_SECRET_PATH).read().strip()
    except OSError:
        return ""


async def _validate_connection(host: str, port: int, secret: str) -> str | None:
    """Try to connect and auth. Returns error key or None on success."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_CONNECT_TIMEOUT
        )
    except (OSError, TimeoutError):
        return "cannot_connect"

    try:
        writer.write(f"AUTH {secret}\n".encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not line.startswith(b"OK"):
            return "invalid_auth"
        return None
    except Exception:
        return "cannot_connect"
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


class PiDP11ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PiDP-11."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User-initiated setup step."""
        auto_secret = await self.hass.async_add_executor_job(_auto_detect_secret)

        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_REMOTE_CONSOLE_PORT]
            secret = user_input[CONF_SHARED_SECRET]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            error = await _validate_connection(host, port, secret)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"PiDP-11 ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_REMOTE_CONSOLE_PORT: port,
                        CONF_SHARED_SECRET: secret,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                vol.Required(
                    CONF_REMOTE_CONSOLE_PORT,
                    default=DEFAULT_REMOTE_CONSOLE_PORT,
                ): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Required(
                    CONF_SHARED_SECRET,
                    default=auto_secret,
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "secret_hint": (
                    "Auto-detected from /share/pidp11/" if auto_secret else
                    "Find in the add-on log on first boot"
                )
            },
        )
