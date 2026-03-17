"""Rav-Bariach LockApp integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RavBariachAPI, RavBariachAuthError
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_LOCK_ID,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_POLLING_ENABLED,
    CONF_USER_TOKEN,
    DOMAIN,
    POLL_INTERVAL_DEFAULT,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [
    Platform.LOCK,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.EVENT,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]


def _get_update_interval(entry: ConfigEntry) -> timedelta | None:
    """Return polling interval from options, or None if polling is disabled."""
    enabled = entry.options.get(CONF_POLLING_ENABLED, True)
    if not enabled:
        return None
    minutes = entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_DEFAULT)
    return timedelta(minutes=int(minutes))


class RavBariachCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches lock status via REST polling on a configurable schedule."""

    def __init__(self, hass: HomeAssistant, api: RavBariachAPI, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=_get_update_interval(entry),
        )
        self.api = api
        self.entry = entry
        # last_action: dict with keys locked, event_type, source, timestamp — or None
        self._last_action: dict | None = None
        # listeners notified on every lock state change (from poll)
        self._lock_change_listeners: list[Callable] = []

    # ------------------------------------------------------------------
    # Listener registration
    # ------------------------------------------------------------------

    def async_add_lock_change_listener(self, listener: Callable) -> Callable:
        """Register a callback for lock state changes (locked/unlocked).

        listener(locked: bool, event_type: str, source: str) -> None
        Returns an unsubscribe callable.
        """
        self._lock_change_listeners.append(listener)
        def _remove() -> None:
            self._lock_change_listeners.remove(listener)
        return _remove

    def _fire_lock_changed(self, locked: bool, event_type: str, source: str) -> None:
        """Record last action and notify all lock change listeners."""
        self._last_action = {
            "locked": locked,
            "event_type": event_type,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for listener in list(self._lock_change_listeners):
            try:
                listener(locked, event_type, source)
            except Exception:
                _LOGGER.exception("Rav-Bariach: error in lock change listener")

    @property
    def last_action(self) -> dict | None:
        """Last recorded lock/unlock action with metadata."""
        return self._last_action

    @property
    def polling_active(self) -> bool:
        """Whether polling is currently enabled."""
        return self.update_interval is not None

    # ------------------------------------------------------------------
    # REST polling (used when FCM is off, or as fallback)
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        session = async_get_clientsession(self.hass)
        old_locked = (self.data or {}).get("locked")
        try:
            result = await self.api.get_status(session)
            # Persist new userToken if full_login() was silently triggered
            if self.api.user_token != self.entry.data.get(CONF_USER_TOKEN):
                _LOGGER.debug("Rav-Bariach: persisting new userToken after re-login")
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_USER_TOKEN: self.api.user_token},
                )
            # Detect state change — fire lock change listeners
            new_locked = result.get("locked")
            if old_locked is not None and new_locked != old_locked:
                event_type = "NGP_LOCK_EVENT" if new_locked else "NGP_UNLOCK_EVENT"
                self._fire_lock_changed(new_locked, event_type, "poll")
            return result
        except RavBariachAuthError:
            await self.hass.config_entries.async_initiate_reauth(self.entry)
            raise UpdateFailed("Authentication failed — reauth required")
        except Exception as err:
            raise UpdateFailed(f"Error fetching lock status: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rav-Bariach from a config entry.

    Startup sequence:
      1. Create API client with stored credentials
      2. Migration: if no userToken stored → silent full login
      3. Create coordinator and do first REST fetch (establishes baseline state)
      4. Register platform entities
    """
    api = RavBariachAPI(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        lock_id=entry.data[CONF_LOCK_ID],
        device_id=entry.data[CONF_DEVICE_ID],
        user_token=entry.data.get(CONF_USER_TOKEN),
    )

    # Migration: entries created before v1.0.1 don't have userToken stored.
    if not entry.data.get(CONF_USER_TOKEN):
        _LOGGER.debug("Rav-Bariach: no userToken in config entry, running migration login")
        session = async_get_clientsession(hass)
        try:
            await api.full_login(session)
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_USER_TOKEN: api.user_token},
            )
            _LOGGER.debug("Rav-Bariach: migration complete, userToken stored")
        except RavBariachAuthError:
            _LOGGER.error("Rav-Bariach: migration login failed — check credentials")
            return False

    coordinator = RavBariachCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
