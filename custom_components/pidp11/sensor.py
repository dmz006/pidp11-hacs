"""Sensors for PiDP-11."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CPU_STATE_OFFLINE, DOMAIN
from .coordinator import PiDP11Coordinator, PiDP11State


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PiDP-11 sensors."""
    coordinator: PiDP11Coordinator = entry.runtime_data
    async_add_entities(
        [
            PiDP11StatusSensor(coordinator, entry),
            PiDP11RegisterSensor(coordinator, entry, "PC", "pc"),
            PiDP11RegisterSensor(coordinator, entry, "PSW", "psw"),
            PiDP11SystemSensor(coordinator, entry),
        ]
    )


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="PiDP-11",
        manufacturer="Oscar Vermeulen / obsolescence",
        model="PDP-11/70 (SimH)",
    )


class _PiDP11Base(CoordinatorEntity[PiDP11Coordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PiDP11Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = _device_info(entry)

    @property
    def _state_data(self) -> PiDP11State | None:
        return self.coordinator.data


class PiDP11StatusSensor(_PiDP11Base):
    """CPU state: running / halted / offline."""

    _attr_translation_key = "cpu_state"
    _attr_icon = "mdi:cpu-64-bit"

    def __init__(self, coordinator: PiDP11Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_cpu_state"

    @property
    def native_value(self) -> str:
        if not self.coordinator.last_update_success or self._state_data is None:
            return CPU_STATE_OFFLINE
        return self._state_data.cpu_state

    @property
    def available(self) -> bool:
        return True  # always show; offline is a valid state


class PiDP11RegisterSensor(_PiDP11Base):
    """An octal register value (PC or PSW)."""

    _attr_icon = "mdi:register"

    def __init__(
        self,
        coordinator: PiDP11Coordinator,
        entry: ConfigEntry,
        register: str,
        field: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._register = register
        self._field = field
        self._attr_unique_id = f"{entry.entry_id}_{field}"
        self._attr_name = register
        self._attr_native_unit_of_measurement = "oct"

    @property
    def native_value(self) -> str | None:
        if self._state_data is None:
            return None
        return getattr(self._state_data, self._field)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._state_data is not None


class PiDP11SystemSensor(_PiDP11Base):
    """The OS currently loaded (idled, 211bsd, unix6, …)."""

    _attr_icon = "mdi:server"
    _attr_translation_key = "system"

    def __init__(self, coordinator: PiDP11Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_system"

    @property
    def native_value(self) -> str | None:
        if self._state_data is None:
            return None
        return self._state_data.system

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._state_data is not None
