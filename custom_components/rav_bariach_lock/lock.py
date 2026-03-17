"""Lock entity for Rav-Bariach LockApp."""
from __future__ import annotations

import logging

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RavBariachCoordinator
from .const import CONF_LOCK_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RavBariachCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([RavBariachLock(coordinator, entry)])


class RavBariachLock(CoordinatorEntity[RavBariachCoordinator], LockEntity):
    """Rav-Bariach smart lock entity."""

    _attr_has_entity_name = True
    _attr_name = "Lock"

    def __init__(self, coordinator: RavBariachCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{self._lock_id}_lock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._lock_id))},
            name=f"Rav-Bariach Lock #{self._lock_id}",
            manufacturer="Rav-Bariach",
            model="LockApp 2 WiFi",
        )
        # Optimistic state: set after action, cleared on next coordinator update
        self._optimistic_locked: bool | None = None

    @property
    def is_locked(self) -> bool | None:
        if self._optimistic_locked is not None:
            return self._optimistic_locked
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("locked")

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.coordinator.data.get("available", False)
        )

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state when real data arrives."""
        self._optimistic_locked = None
        super()._handle_coordinator_update()

    async def async_lock(self, **kwargs) -> None:
        self._optimistic_locked = True
        self.async_write_ha_state()
        try:
            session = async_get_clientsession(self.hass)
            await self.coordinator.api.lock(session)
        except HomeAssistantError:
            self._optimistic_locked = None
            self.async_write_ha_state()
            raise
        # Schedule a refresh after a short delay to get real state
        self.hass.async_create_task(self._delayed_refresh())

    async def async_unlock(self, **kwargs) -> None:
        self._optimistic_locked = False
        self.async_write_ha_state()
        try:
            session = async_get_clientsession(self.hass)
            await self.coordinator.api.unlock(session)
        except HomeAssistantError:
            self._optimistic_locked = None
            self.async_write_ha_state()
            raise
        self.hass.async_create_task(self._delayed_refresh())

    async def _delayed_refresh(self) -> None:
        """Wait a moment, then fetch fresh state from the API."""
        import asyncio
        await asyncio.sleep(3)
        await self.coordinator.async_request_refresh()
