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
from .const import CONF_DEVICE_ID, CONF_EMAIL, CONF_LOCK_ID, CONF_PASSWORD, DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.LOCK, Platform.SENSOR]


class RavBariachCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches lock status on a schedule."""

    def __init__(self, hass: HomeAssistant, api: RavBariachAPI, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
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
    )
    coordinator = RavBariachCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
