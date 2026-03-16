"""Config flow for Rav-Bariach LockApp integration."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from .api import RavBariachAPI, RavBariachAuthError
from .const import CONF_DEVICE_ID, CONF_EMAIL, CONF_LOCK_ID, CONF_PASSWORD, CONF_USER_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step setup: credentials → pick lock from discovered list."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._device_id: str = ""
        self._api: RavBariachAPI | None = None
        self._discovered_locks: list[dict] = []

    # ------------------------------------------------------------------
    # Step 1: credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            self._device_id = str(uuid.uuid4())
            self._api = RavBariachAPI(
                email=self._email,
                password=self._password,
                lock_id=0,
                device_id=self._device_id,
            )
            session = async_get_clientsession(self.hass)
            try:
                await self._api.full_login(session)
                self._discovered_locks = await self._api.get_smart_locks(session)
            except RavBariachAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Error during device discovery")
                errors["base"] = "cannot_connect"
            else:
                if not self._discovered_locks:
                    errors["base"] = "no_locks_found"
                else:
                    return await self.async_step_pick_lock()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2: pick lock
    # ------------------------------------------------------------------

    async def async_step_pick_lock(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            lock_id = int(user_input[CONF_LOCK_ID])
            lock_name = next(
                (l["name"] for l in self._discovered_locks if l["id"] == lock_id),
                f"Lock #{lock_id}",
            )
            await self.async_set_unique_id(f"rav_bariach_{lock_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Rav-Bariach {lock_name}",
                data={
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_LOCK_ID: lock_id,
                    CONF_DEVICE_ID: self._device_id,
                    CONF_USER_TOKEN: self._api.user_token,
                },
            )

        options = [
            SelectOptionDict(
                value=str(lock["id"]),
                label=f"{lock['name']} ({lock['mac']})" if lock["mac"] else lock["name"],
            )
            for lock in self._discovered_locks
        ]

        return self.async_show_form(
            step_id="pick_lock",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCK_ID): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    # ------------------------------------------------------------------
    # Reauth
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            entry = self._reauth_entry
            api = RavBariachAPI(
                email=entry.data[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                lock_id=entry.data[CONF_LOCK_ID],
                device_id=entry.data[CONF_DEVICE_ID],
            )
            session = async_get_clientsession(self.hass)
            try:
                await api.full_login(session)
            except RavBariachAuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_USER_TOKEN: api.user_token,
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
        )
