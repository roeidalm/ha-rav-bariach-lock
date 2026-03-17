"""Lock event entity for Rav-Bariach LockApp.

Fires a HA event each time the lock state changes (locked / unlocked).
Enables automations like "send notification when door is unlocked".
HA stores full history of all fired events.
"""
from __future__ import annotations

from homeassistant.components.event import EventEntity
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
    async_add_entities([RavBariachLockEvent(coordinator, entry)])


class RavBariachLockEvent(EventEntity):
    """Fires a HA event each time the lock is locked or unlocked.

    event_type values:
      "locked"         — locked (any source)
      "unlocked"       — unlocked (any source)

    Extra state attributes on each event:
      raw_event_type   — e.g. NGP_RF_UNLOCK_EVENT
      source           — "fcm" or "poll"
    """

    _attr_has_entity_name = True
    _attr_name = "Lock Event"
    _attr_event_types = ["locked", "unlocked"]
    _attr_icon = "mdi:lock-clock"

    def __init__(
        self, coordinator: RavBariachCoordinator, entry: ConfigEntry
    ) -> None:
        lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{lock_id}_lock_event"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(lock_id))},
        )
        self._coordinator = coordinator
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator lock change events."""
        self._unsubscribe = self._coordinator.async_add_lock_change_listener(
            self._handle_lock_change
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe on removal."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _handle_lock_change(self, locked: bool, event_type: str, source: str) -> None:
        """Called by the coordinator when the lock state changes."""
        ha_event_type = "locked" if locked else "unlocked"
        self._trigger_event(
            ha_event_type,
            {
                "raw_event_type": event_type,
                "source": source,
            },
        )
        self.async_write_ha_state()
