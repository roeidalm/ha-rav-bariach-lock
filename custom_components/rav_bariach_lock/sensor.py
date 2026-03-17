"""Sensors for Rav-Bariach LockApp.

Entities:
  RavBariachBatterySensor     — battery percentage (from API)
  RavBariachLastActionSensor  — last lock/unlock action with metadata
  RavBariachConnectionSensor  — FCM push vs REST polling mode
"""
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
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RavBariachCoordinator
from .const import CONF_LOCK_ID, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RavBariachCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        RavBariachBatterySensor(coordinator, entry),
        RavBariachLastActionSensor(coordinator, entry),
        RavBariachConnectionSensor(coordinator, entry),
    ])


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


class RavBariachLastActionSensor(SensorEntity, RestoreEntity):
    """Sensor showing the last lock/unlock action.

    State: "locked" | "unlocked" | None (no action recorded yet)

    Attributes:
      raw_event_type  — e.g. "NGP_RF_UNLOCK_EVENT"
      source          — "fcm" or "poll"
      timestamp       — ISO-8601 UTC timestamp of the last action
    """

    _attr_has_entity_name = True
    _attr_name = "Last Action"
    _attr_icon = "mdi:history"

    def __init__(
        self, coordinator: RavBariachCoordinator, entry: ConfigEntry
    ) -> None:
        lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{lock_id}_last_action"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(lock_id))},
        )
        self._coordinator = coordinator
        self._unsubscribe = None
        self._state: str | None = None
        self._extra: dict = {}

    async def async_added_to_hass(self) -> None:
        """Restore previous state and subscribe to lock change events."""
        # Restore last known value across HA restarts
        if (last := await self.async_get_last_state()) is not None:
            if last.state in ("locked", "unlocked"):
                self._state = last.state
                self._extra = dict(last.attributes)

        self._unsubscribe = self._coordinator.async_add_lock_change_listener(
            self._handle_lock_change
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _handle_lock_change(self, locked: bool, event_type: str, source: str) -> None:
        action = self._coordinator.last_action or {}
        self._state = "locked" if locked else "unlocked"
        self._extra = {
            "raw_event_type": event_type,
            "source": source,
            "timestamp": action.get("timestamp"),
        }
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        return self._extra

    @property
    def available(self) -> bool:
        return True  # always available — shows last known action even when hub is offline


class RavBariachConnectionSensor(SensorEntity):
    """Sensor showing the current update mode: FCM push or REST polling.

    State:
      "Push (FCM)"        — real-time FCM is active, polling is off
      "Polling"           — REST polling is active (manual or FCM fallback)
      "Initializing"      — just started, FCM not yet connected
    """

    _attr_has_entity_name = True
    _attr_name = "Connection Mode"
    _attr_icon = "mdi:antenna"

    def __init__(
        self, coordinator: RavBariachCoordinator, entry: ConfigEntry
    ) -> None:
        lock_id = entry.data[CONF_LOCK_ID]
        self._attr_unique_id = f"rav_bariach_{lock_id}_connection_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(lock_id))},
        )
        self._coordinator = coordinator
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to connection mode changes."""
        self._unsubscribe = self._coordinator.async_add_connection_change_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    @property
    def native_value(self) -> str:
        if self._coordinator.fcm_active:
            return "Push (FCM)"
        if self._coordinator.update_interval is not None:
            return "Polling"
        return "Initializing"

    @property
    def available(self) -> bool:
        return True  # always available — reflects internal mode, not hub connectivity
