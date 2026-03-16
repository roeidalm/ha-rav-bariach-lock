"""DESI API client for Rav-Bariach LockApp."""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

from aiohttp import ClientSession

from .const import (
    API_BASE_URL,
    API_COM_TOKEN,
    API_LOCK_ENDPOINT,
    API_LOGIN_ENDPOINT,
    API_REFRESH_ENDPOINT,
    API_STATUS_ENDPOINT,
    API_SYNC_ENDPOINT,
    JWT_EXPIRY_BUFFER_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

HEADERS_BASE = {
    "com-token": API_COM_TOKEN,
    "Content-Type": "application/json",
    "User-Agent": "Dart/3.10 (dart:io)",
    "accept": "application/json",
    "accept-language": "he-IL",
}


def _decode_jwt_exp(token: str) -> int | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        padding = 4 - (len(payload) % 4)
        if padding != 4:
            payload += "=" * padding
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None


def _is_jwt_expired(token: str) -> bool:
    exp = _decode_jwt_exp(token)
    if exp is None:
        return True
    return time.time() >= (exp - JWT_EXPIRY_BUFFER_SECONDS)


def _device_info(device_id: str) -> dict:
    return {
        "isPhysicalDevice": "true",
        "systemVersion": "15",
        "model": "Seeker",
        "operatingSystem": "android",
        "manufacturer": "Solana Mobile Inc.",
        "deviceId": device_id,
        "appVersion": "1.1.32+671",
    }


class RavBariachAuthError(Exception):
    """Raised when authentication fails — triggers HA reauth flow."""


class RavBariachAPI:
    """Async DESI API client.

    Auth strategy (post-setup):
      - userToken is long-lived and stored in HA config entry.
      - JWT is short-lived (~40 min); refreshed via /v4/login/user-token (no password).
      - If refresh fails → RavBariachAuthError → HA reauth (user re-enters password).
      - Full login (email+password) is ONLY used during initial config flow setup.

    IMPORTANT quirks discovered via reverse engineering:
      - registrationToken:"" is REQUIRED in refresh payload — omitting causes 500 errors.
      - deviceInfo is REQUIRED in refresh payload — omitting causes 403.
      - JWT is in the 3rd word of the authorization header (index 2), not index 1.
    """

    def __init__(
        self,
        email: str,
        password: str,
        lock_id: int,
        device_id: str,
        user_token: str | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._lock_id = lock_id
        self._device_id = device_id
        self._jwt: str | None = None
        self._user_token: str | None = user_token

    @property
    def user_token(self) -> str | None:
        return self._user_token

    # ------------------------------------------------------------------
    # Auth — initial setup only
    # ------------------------------------------------------------------

    async def full_login(self, session: ClientSession) -> None:
        """Full login with email + password. Only called during config flow setup."""
        payload = {
            "userLoginText": self._email,
            "password": self._password,
            "userToken": "",
            "application": 4,
            "registrationToken": "",
            "deviceInfo": _device_info(self._device_id),
        }
        async with session.post(
            f"{API_BASE_URL}{API_LOGIN_ENDPOINT}",
            json=payload,
            headers=HEADERS_BASE,
        ) as resp:
            if resp.status in (401, 403):
                raise RavBariachAuthError("Invalid credentials")
            resp.raise_for_status()
            data = await resp.json()
            jwt = resp.headers.get("authorization", "").replace("Bearer ", "")
            user_token = data.get("data", {}).get("userToken")

        if not jwt or not user_token:
            raise RavBariachAuthError("Login response missing JWT or userToken")

        self._jwt = jwt
        self._user_token = user_token
        _LOGGER.debug("Rav-Bariach: full login successful, userToken obtained")

    # ------------------------------------------------------------------
    # Auth — normal operation (refresh only, no password)
    # ------------------------------------------------------------------

    async def _refresh_jwt(self, session: ClientSession) -> None:
        """Refresh JWT using stored userToken. Raises RavBariachAuthError on failure."""
        if not self._user_token:
            raise RavBariachAuthError("No userToken available — reauth required")
        try:
            payload = {
                "userToken": self._user_token,
                "application": 4,
                "registrationToken": "",   # required — omitting causes 500
                "deviceInfo": _device_info(self._device_id),
            }
            async with session.post(
                f"{API_BASE_URL}{API_REFRESH_ENDPOINT}",
                json=payload,
                headers=HEADERS_BASE,
            ) as resp:
                if resp.status in (401, 403):
                    raise RavBariachAuthError("userToken rejected — reauth required")
                resp.raise_for_status()
                jwt = resp.headers.get("authorization", "").replace("Bearer ", "")
                if not jwt:
                    raise RavBariachAuthError("Refresh returned no JWT")
                self._jwt = jwt
                _LOGGER.debug("Rav-Bariach: JWT refreshed successfully")
        except RavBariachAuthError:
            raise
        except Exception as err:
            raise RavBariachAuthError(f"JWT refresh failed: {err}") from err

    async def _ensure_auth(self, session: ClientSession) -> None:
        """Ensure a valid JWT exists. Refresh if expired. No password fallback."""
        if self._jwt and not _is_jwt_expired(self._jwt):
            return
        _LOGGER.debug("Rav-Bariach: JWT expired or missing, refreshing via userToken")
        await self._refresh_jwt(session)

    # ------------------------------------------------------------------
    # Device discovery (used in config flow)
    # ------------------------------------------------------------------

    async def get_smart_locks(self, session: ClientSession) -> list[dict[str, Any]]:
        """Return list of smart locks on this account.

        Each entry: {"id": int, "name": str, "mac": str}
        """
        await self._ensure_auth(session)
        headers = {**HEADERS_BASE, "authorization": f"Bearer {self._jwt}"}
        async with session.post(
            f"{API_BASE_URL}{API_SYNC_ENDPOINT}",
            json={"userToken": self._user_token, "devices": []},
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            result = await resp.json()

        locks = []
        for lock in result.get("data", {}).get("smartLocks", []):
            locks.append({
                "id": lock["idSmartLock"],
                "name": lock.get("name", f"Lock {lock['idSmartLock']}"),
                "mac": lock.get("macId", ""),
            })
        return locks

    # ------------------------------------------------------------------
    # Lock actions
    # ------------------------------------------------------------------

    async def unlock(self, session: ClientSession) -> None:
        await self._lock_action(session, "OPEN")

    async def lock(self, session: ClientSession) -> None:
        await self._lock_action(session, "CLOSE")

    async def _lock_action(self, session: ClientSession, operation: str) -> None:
        from homeassistant.exceptions import HomeAssistantError

        await self._ensure_auth(session)
        payload = {
            "userToken": self._user_token,
            "idSmartLock": self._lock_id,
            "operation": operation,
        }
        headers = {**HEADERS_BASE, "authorization": f"Bearer {self._jwt}"}
        async with session.post(
            f"{API_BASE_URL}{API_LOCK_ENDPOINT}",
            json=payload,
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            result = await resp.json()

        if result.get("status") != "success":
            raise HomeAssistantError(
                f"Lock {operation} failed: {result.get('message', 'unknown error')}"
            )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_status(self, session: ClientSession) -> dict[str, Any]:
        """Return dict: {locked: bool|None, battery: int|None}"""
        await self._ensure_auth(session)
        payload = {
            "userToken": self._user_token,
            "idSmartLock": self._lock_id,
        }
        headers = {**HEADERS_BASE, "authorization": f"Bearer {self._jwt}"}
        async with session.post(
            f"{API_BASE_URL}{API_STATUS_ENDPOINT}",
            json=payload,
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            result = await resp.json()

        if result.get("status") != "success":
            raise ValueError(f"Status fetch failed: {result}")

        raw = result.get("data", {})
        raw_status = raw.get("status")
        try:
            locked = int(raw_status) == 1
        except (TypeError, ValueError):
            locked = None

        return {
            "locked": locked,
            "battery": raw.get("batteryLevel"),
            "available": raw.get("isAvailable") == 1,
        }
