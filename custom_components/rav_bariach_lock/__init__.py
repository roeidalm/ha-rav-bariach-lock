"""Rav-Bariach LockApp integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RavBariachAPI, RavBariachAuthError
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_FCM_TOKEN,
    CONF_LOCK_ID,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_POLLING_ENABLED,
    CONF_USER_TOKEN,
    DOMAIN,
    POLL_INTERVAL_DEFAULT,
)
from .fcm_client import RavBariachFcmClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.LOCK, Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]


def _get_update_interval(entry: ConfigEntry) -> timedelta | None:
    """Return polling interval from options, or None if polling is disabled."""
    enabled = entry.options.get(CONF_POLLING_ENABLED, True)
    if not enabled:
        return None
    minutes = entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_DEFAULT)
    return timedelta(minutes=int(minutes))


class RavBariachCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches lock status on a configurable schedule.

    Also receives real-time FCM push events via handle_fcm_event().
    When FCM is active, polling is disabled and state updates come from push.
    When FCM fails, polling is re-enabled as a fallback.
    """

    def __init__(self, hass: HomeAssistant, api: RavBariachAPI, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=_get_update_interval(entry),
        )
        self.api = api
        self.entry = entry
        self._fcm_active = False

    # ------------------------------------------------------------------
    # FCM integration
    # ------------------------------------------------------------------

    def handle_fcm_event(self, locked: bool) -> None:
        """Handle a real-time FCM push event — update state without API call.

        Called by RavBariachFcmClient when NGP_LOCK_EVENT / NGP_UNLOCK_EVENT arrives.
        Uses async_set_updated_data() to push new state to all entities immediately.
        """
        _LOGGER.info(
            "Rav-Bariach FCM: lock state update → %s",
            "locked" if locked else "unlocked",
        )
        current = self.data or {}
        self.async_set_updated_data({
            **current,
            "locked": locked,
            "available": True,
        })

    def enable_polling_fallback(self) -> None:
        """Re-enable polling when FCM fails repeatedly."""
        _LOGGER.warning(
            "Rav-Bariach: FCM unavailable — switching to REST polling fallback"
        )
        self._fcm_active = False
        if self.update_interval is None:
            # FCM was suppressing polling; re-enable with default interval
            minutes = self.entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_DEFAULT)
            self.update_interval = timedelta(minutes=int(minutes))
            self.hass.async_create_task(self.async_request_refresh())

    def set_fcm_active(self, active: bool) -> None:
        """Track whether FCM is providing real-time updates.

        When active=True, REST polling is disabled — FCM is the sole state source.
        When active=False, polling is NOT re-enabled here; use enable_polling_fallback().
        """
        self._fcm_active = active
        if active:
            _LOGGER.info(
                "Rav-Bariach: FCM connected — disabling REST polling (push-only mode)"
            )
            self.update_interval = None

    @property
    def fcm_active(self) -> bool:
        return self._fcm_active

    # ------------------------------------------------------------------
    # REST polling (used when FCM is off, or as fallback)
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        session = async_get_clientsession(self.hass)
        try:
            result = await self.api.get_status(session)
            # Persist new userToken if full_login() was silently triggered
            if self.api.user_token != self.entry.data.get(CONF_USER_TOKEN):
                _LOGGER.debug("Rav-Bariach: persisting new userToken after re-login")
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_USER_TOKEN: self.api.user_token},
                )
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
      4. Start FCM client in background (non-blocking)
         - FCM registers with Firebase → gets token → notifies DESI
         - Once connected, coordinator switches to push-only mode
         - If FCM fails → coordinator falls back to polling
      5. Register platform entities
    """
    api = RavBariachAPI(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        lock_id=entry.data[CONF_LOCK_ID],
        device_id=entry.data[CONF_DEVICE_ID],
        user_token=entry.data.get(CONF_USER_TOKEN),
        fcm_token=entry.data.get(CONF_FCM_TOKEN, ""),
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

    # ------------------------------------------------------------------
    # FCM client — start in background, non-blocking
    # ------------------------------------------------------------------
    def _on_fcm_token_updated(token: str) -> None:
        """FCM token received/refreshed → tell DESI about it."""
        api.set_fcm_token(token)
        _LOGGER.debug("Rav-Bariach: FCM token updated, DESI will receive it on next API call")

    def _on_lock_event(locked: bool) -> None:
        """FCM push received → update entity state immediately."""
        coordinator.handle_fcm_event(locked)

    def _on_fcm_failed() -> None:
        """FCM failed too many times → fall back to polling."""
        coordinator.enable_polling_fallback()

    def _on_fcm_connected() -> None:
        """FCM registered and listening — disable REST polling (FCM is now primary)."""
        coordinator.set_fcm_active(True)

    fcm_client = RavBariachFcmClient(
        hass=hass,
        entry=entry,
        on_lock_event=_on_lock_event,
        on_fcm_failed=_on_fcm_failed,
        on_token_updated=_on_fcm_token_updated,
        on_fcm_connected=_on_fcm_connected,
    )

    # Store coordinator + FCM client (no dead intermediate assignment)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "fcm_client": fcm_client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start FCM listener after platforms are set up (non-blocking)
    await fcm_client.start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        fcm_client: RavBariachFcmClient = entry_data.get("fcm_client")
        if fcm_client:
            await fcm_client.stop()
    return unload_ok
