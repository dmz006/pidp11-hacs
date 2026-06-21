"""CPU halt/continue switch for PiDP-11."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CPU_STATE_RUNNING
from .coordinator import PiDP11Coordinator
from .sensor import _device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PiDP-11 switch."""
    coordinator: PiDP11Coordinator = entry.runtime_data
    async_add_entities([PiDP11CpuSwitch(coordinator, entry)])


class PiDP11CpuSwitch(CoordinatorEntity[PiDP11Coordinator], SwitchEntity):
    """Switch: ON = CPU running, OFF = CPU halted."""

    _attr_has_entity_name = True
    _attr_translation_key = "cpu_running"
    _attr_icon = "mdi:play-pause"

    def __init__(self, coordinator: PiDP11Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_cpu_running"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        return data is not None and data.cpu_state == CPU_STATE_RUNNING

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume the PDP-11 CPU (CONT)."""
        try:
            await self.coordinator.async_send_command("CONT")
        except Exception as exc:
            raise HomeAssistantError(f"Failed to CONT: {exc}") from exc
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Halt the PDP-11 CPU (HALT)."""
        try:
            await self.coordinator.async_send_command("HALT")
        except Exception as exc:
            raise HomeAssistantError(f"Failed to HALT: {exc}") from exc
        await self.coordinator.async_request_refresh()
