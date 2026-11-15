"""PiDP-11 Home Assistant integration."""

from __future__ import annotations

import logging
import json
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
    LAMP_FPS_DEFAULT,
    OPT_LAMP_FPS,
    OPT_POLL_INTERVAL,
    POLL_INTERVAL_DEFAULT,
    SERVICE_BOOT,
    SERVICE_CONTINUE,
    SERVICE_DEPOSIT,
    SERVICE_EXAMINE,
    SERVICE_HALT,
)
from .coordinator import PiDP11Coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["binary_sensor", "sensor", "switch"]

_CARD_URL = "/pidp11-hacs/pidp11-panel-card.js"
# The browser keeps a script for its URL; carrying the integration version in the query string makes
# every update load the new card instead of the cached one ("setConfig is not a function" from an old script).
_CARD_VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
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
        poll_interval=entry.options.get(OPT_POLL_INTERVAL, POLL_INTERVAL_DEFAULT),
        lamp_fps=entry.options.get(OPT_LAMP_FPS, LAMP_FPS_DEFAULT),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # Options are read when the coordinator is built (poll interval, stream fps), so a
    # change reloads the entry: the new values apply without restarting Home Assistant.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # One long-lived stream carries the lamps and the switch register: together
    # with a poll the integration holds at most 2 of SimH's 4 console connections
    # (boot.ini: `set remote connections=4`), so a poll always finds a free one.
    coordinator.start_sr_watch(f"{DOMAIN}_stream")
    coordinator.start_lamp_watch(f"{DOMAIN}_stream")

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_stop_streams()
        raise
    _register_services(hass, coordinator)

    # Serve the Lovelace card JS once per HA instance (not per config entry).
    # The extra_module_url tells HA to load the script in every frontend session,
    # which makes "type: custom:pidp11-panel-card" available in Lovelace.
    if not hass.data.get(_DATA_FRONTEND):
        hass.data[_DATA_FRONTEND] = True
        from homeassistant.components.http import StaticPathConfig
        await hass.http.async_register_static_paths([
            StaticPathConfig(_CARD_URL, str(_CARD_FILE), cache_headers=False)
        ])
        add_extra_js_url(hass, f"{_CARD_URL}?v={_CARD_VERSION}")
        _LOGGER.debug("Registered Lovelace card at %s", _CARD_URL)

    return True


async def _async_options_updated(hass: HomeAssistant, entry: PiDP11ConfigEntry) -> None:
    """Apply changed options: reload the entry so the coordinator is rebuilt with them."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PiDP11ConfigEntry) -> bool:
    """Unload a config entry."""
    # Cancel the stream and wait for its SimH connection to be released.
    await entry.runtime_data.async_stop_streams()
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
