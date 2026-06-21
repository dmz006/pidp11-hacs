"""PiDP-11 Home Assistant integration."""

from __future__ import annotations

import logging
from pathlib import Path
import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_HOST,
    CONF_REMOTE_CONSOLE_PORT,
    CONF_SHARED_SECRET,
    DOMAIN,
    SERVICE_BOOT,
    SERVICE_CONTINUE,
    SERVICE_DEPOSIT,
    SERVICE_EXAMINE,
    SERVICE_HALT,
)
from .coordinator import PiDP11Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "switch"]

_CARD_URL = "/pidp11-hacs/pidp11-panel-card.js"
_CARD_FILE = Path(__file__).parent / "www" / "pidp11-panel-card.js"
_DATA_FRONTEND = f"{DOMAIN}_frontend_registered"

type PiDP11ConfigEntry = ConfigEntry[PiDP11Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PiDP11ConfigEntry) -> bool:
    """Set up PiDP-11 from a config entry."""
    coordinator = PiDP11Coordinator(
        hass,
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_REMOTE_CONSOLE_PORT],
        secret=entry.data[CONF_SHARED_SECRET],
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, coordinator)

    # Serve the Lovelace card JS once per HA instance (not per config entry).
    # The extra_module_url tells HA to load the script in every frontend session,
    # which makes "type: custom:pidp11-panel-card" available in Lovelace.
    if not hass.data.get(_DATA_FRONTEND):
        hass.data[_DATA_FRONTEND] = True
        hass.http.register_static_path(_CARD_URL, str(_CARD_FILE), cache_headers=False)
        add_extra_js_url(hass, _CARD_URL)
        _LOGGER.debug("Registered Lovelace card at %s", _CARD_URL)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: PiDP11ConfigEntry) -> bool:
    """Unload a config entry."""
    if hass.services.has_service(DOMAIN, SERVICE_HALT):
        hass.services.async_remove(DOMAIN, SERVICE_HALT)
        hass.services.async_remove(DOMAIN, SERVICE_CONTINUE)
        hass.services.async_remove(DOMAIN, SERVICE_BOOT)
        hass.services.async_remove(DOMAIN, SERVICE_DEPOSIT)
        hass.services.async_remove(DOMAIN, SERVICE_EXAMINE)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# ── Service registration ──────────────────────────────────────────────────────

def _register_services(hass: HomeAssistant, coordinator: PiDP11Coordinator) -> None:

    async def _send(cmd: str) -> None:
        try:
            await coordinator.async_send_command(cmd)
        except Exception as exc:
            raise HomeAssistantError(str(exc)) from exc

    async def handle_halt(_call: ServiceCall) -> None:
        await _send("HALT")
        await coordinator.async_request_refresh()

    async def handle_continue(_call: ServiceCall) -> None:
        await _send("CONT")
        await coordinator.async_request_refresh()

    async def handle_boot(call: ServiceCall) -> None:
        target = call.data["target"]
        await _send(f"DO {target}/boot.ini")
        await coordinator.async_request_refresh()

    async def handle_deposit(call: ServiceCall) -> None:
        addr = call.data["address"]
        value = call.data["value"]
        await _send(f"DEPOSIT {addr} {value}")

    async def handle_examine(call: ServiceCall) -> dict[str, str]:
        addr = call.data["address"]
        try:
            result = await coordinator.async_send_command(f"EXAMINE {addr}")
        except Exception as exc:
            raise HomeAssistantError(str(exc)) from exc
        return {"value": result}

    hass.services.async_register(DOMAIN, SERVICE_HALT, handle_halt)
    hass.services.async_register(DOMAIN, SERVICE_CONTINUE, handle_continue)
    hass.services.async_register(
        DOMAIN,
        SERVICE_BOOT,
        handle_boot,
        schema=vol.Schema({vol.Required("target"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DEPOSIT,
        handle_deposit,
        schema=vol.Schema(
            {
                vol.Required("address"): cv.string,
                vol.Required("value"): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXAMINE,
        handle_examine,
        schema=vol.Schema({vol.Required("address"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
