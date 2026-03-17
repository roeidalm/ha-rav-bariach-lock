"""Battery sensor for Rav-Bariach LockApp."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RavBariachCoordinator
from .const import CONF_LOCK_ID, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RavBariachCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([RavBariachBatterySensor(coordinator, entry)])


class RavBariachBatterySensor(CoordinatorEntity[RavBariachCoordinator], SensorEntity):
    """Battery level sensor."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: RavBariachCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{lock_id}_battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(lock_id))},
        )

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("battery")

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
        )
