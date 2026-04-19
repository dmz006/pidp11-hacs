"""PiDP-11 HACS integration. Skeleton — implementation lands in S3."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS: list[str] = ["sensor", "switch"]


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Set up PiDP-11 from a config entry."""
    raise NotImplementedError("pending S3")


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Unload a config entry."""
    raise NotImplementedError("pending S3")
