"""Config flow for PiDP-11. Skeleton — implementation lands in S3."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class PiDP11ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PiDP-11."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User-initiated setup step."""
        raise NotImplementedError("pending S3")
