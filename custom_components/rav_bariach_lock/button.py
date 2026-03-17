"""Manual refresh button for Rav-Bariach LockApp."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RavBariachCoordinator
from .const import CONF_LOCK_ID, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RavBariachCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([RavBariachRefreshButton(coordinator, entry)])


class RavBariachRefreshButton(ButtonEntity):
    """Button that triggers an immediate status refresh from the API."""

    _attr_has_entity_name = True
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(
        self, coordinator: RavBariachCoordinator, entry: ConfigEntry
    ) -> None:
        lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{lock_id}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(lock_id))},
        )
        self._coordinator = coordinator

    async def async_press(self) -> None:
        """Trigger an immediate coordinator refresh (ignores polling schedule)."""
        await self._coordinator.async_request_refresh()
