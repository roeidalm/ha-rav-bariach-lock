"""Polling enable/disable switch for Rav-Bariach LockApp."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RavBariachCoordinator
from .const import CONF_LOCK_ID, CONF_POLL_INTERVAL, CONF_POLLING_ENABLED, DOMAIN, POLL_INTERVAL_DEFAULT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RavBariachCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RavBariachPollingSwitch(coordinator, entry)])


class RavBariachPollingSwitch(CoordinatorEntity[RavBariachCoordinator], SwitchEntity, RestoreEntity):
    """Switch to enable/disable status polling."""

    _attr_has_entity_name = True
    _attr_name = "Status Polling"
    _attr_icon = "mdi:refresh-auto"

    def __init__(self, coordinator: RavBariachCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{self._lock_id}_polling"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._lock_id))},
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.update_interval is not None

    async def async_turn_on(self, **kwargs) -> None:
        minutes = self._entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_DEFAULT)
        _set_coordinator_interval(self.coordinator, timedelta(minutes=int(minutes)))
        _save_options(self.hass, self._entry, polling_enabled=True, poll_interval=minutes)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        _set_coordinator_interval(self.coordinator, None)
        minutes = self._entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_DEFAULT)
        _save_options(self.hass, self._entry, polling_enabled=False, poll_interval=minutes)
        self.async_write_ha_state()


def _set_coordinator_interval(coordinator: RavBariachCoordinator, interval: timedelta | None) -> None:
    """Update coordinator polling interval in-place without reloading."""
    if coordinator._unsub_refresh:
        coordinator._unsub_refresh()
        coordinator._unsub_refresh = None
    coordinator.update_interval = interval
    if interval is not None:
        coordinator._schedule_refresh()


def _save_options(hass: HomeAssistant, entry: ConfigEntry, *, polling_enabled: bool, poll_interval: float) -> None:
    """Persist polling settings to config entry options (survives restart)."""
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_POLLING_ENABLED: polling_enabled, CONF_POLL_INTERVAL: poll_interval},
    )
