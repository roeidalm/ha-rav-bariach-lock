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
    CONF_LOCK_ID,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_POLLING_ENABLED,
    CONF_USER_TOKEN,
    DOMAIN,
    POLL_INTERVAL_DEFAULT,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.LOCK, Platform.SENSOR]


def _get_update_interval(entry: ConfigEntry) -> timedelta | None:
    """Return polling interval from options, or None if polling is disabled."""
    enabled = entry.options.get(CONF_POLLING_ENABLED, True)
    if not enabled:
        return None
    minutes = entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_DEFAULT)
    return timedelta(minutes=int(minutes))


class RavBariachCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches lock status on a configurable schedule."""

    def __init__(self, hass: HomeAssistant, api: RavBariachAPI, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=_get_update_interval(entry),
        )
        self.api = api
        self.entry = entry

    async def _async_update_data(self) -> dict:
        session = async_get_clientsession(self.hass)
        try:
            return await self.api.get_status(session)
        except RavBariachAuthError:
            await self.hass.config_entries.async_initiate_reauth(self.entry)
            raise UpdateFailed("Authentication failed — reauth required")
        except Exception as err:
            raise UpdateFailed(f"Error fetching lock status: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = RavBariachAPI(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        lock_id=entry.data[CONF_LOCK_ID],
        device_id=entry.data[CONF_DEVICE_ID],
        user_token=entry.data.get(CONF_USER_TOKEN),
    )

    # Migration: entries created before v1.0.1 don't have userToken stored.
    # Do a silent full login and persist the token so future startups use refresh only.
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload when options change (polling toggle / interval)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
