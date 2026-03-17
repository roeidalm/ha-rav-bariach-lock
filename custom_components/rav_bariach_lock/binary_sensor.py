"""Hub online/offline binary sensor for Rav-Bariach LockApp."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    async_add_entities([RavBariachHubOnline(coordinator, entry)])


class RavBariachHubOnline(CoordinatorEntity[RavBariachCoordinator], BinarySensorEntity):
    """Binary sensor that reflects whether the lock hub is reachable.

    State: ON = hub is online and responding.
           OFF = hub is offline or unreachable.

    Source: the `isAvailable` field in the DESI API /get-status response.
    Updated with every coordinator refresh (polling or initial fetch).
    """

    _attr_has_entity_name = True
    _attr_name = "Hub Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:wifi"

    def __init__(
        self, coordinator: RavBariachCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{lock_id}_hub_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(lock_id))},
        )

    @property
    def is_on(self) -> bool | None:
        """True when the hub reports itself as available."""
        if self.coordinator.data is None:
            return None
        return bool(self.coordinator.data.get("available", False))

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
        )
