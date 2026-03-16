"""Poll interval number entity for Rav-Bariach LockApp."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RavBariachCoordinator
from .const import (
    CONF_LOCK_ID,
    CONF_POLL_INTERVAL,
    CONF_POLLING_ENABLED,
    DOMAIN,
    POLL_INTERVAL_DEFAULT,
    POLL_INTERVAL_MAX,
    POLL_INTERVAL_MIN,
    POLL_INTERVAL_STEP,
)
from .switch import _save_options, _set_coordinator_interval


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RavBariachCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RavBariachPollInterval(coordinator, entry)])


class RavBariachPollInterval(CoordinatorEntity[RavBariachCoordinator], NumberEntity):
    """Number entity to set status polling interval."""

    _attr_has_entity_name = True
    _attr_name = "Poll Interval"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = POLL_INTERVAL_MIN
    _attr_native_max_value = POLL_INTERVAL_MAX
    _attr_native_step = POLL_INTERVAL_STEP

    def __init__(self, coordinator: RavBariachCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{self._lock_id}_poll_interval"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._lock_id))},
        )

    @property
    def native_value(self) -> float:
        return float(self._entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_DEFAULT))

    async def async_set_native_value(self, value: float) -> None:
        polling_enabled = self._entry.options.get(CONF_POLLING_ENABLED, True)
        # Only update the coordinator interval if polling is currently enabled
        if polling_enabled and self.coordinator.update_interval is not None:
            _set_coordinator_interval(self.coordinator, timedelta(minutes=int(value)))
        _save_options(self.hass, self._entry, polling_enabled=polling_enabled, poll_interval=value)
