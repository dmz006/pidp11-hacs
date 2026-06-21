"""Binary sensors for PiDP-11."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CPU_STATE_HALTED, DOMAIN
from .coordinator import PiDP11Coordinator
from .sensor import _device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PiDP-11 binary sensors."""
    coordinator: PiDP11Coordinator = entry.runtime_data
    async_add_entities([PiDP11HaltedSensor(coordinator, entry)])


class PiDP11HaltedSensor(CoordinatorEntity[PiDP11Coordinator], BinarySensorEntity):
    """True when the PDP-11 CPU is halted."""

    _attr_has_entity_name = True
    _attr_translation_key = "halted"
    _attr_icon = "mdi:pause-circle"

    def __init__(self, coordinator: PiDP11Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_halted"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        return data is not None and data.cpu_state == CPU_STATE_HALTED

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None
