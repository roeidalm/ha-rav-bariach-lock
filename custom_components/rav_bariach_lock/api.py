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
    """Build device info payload using a per-install device_id."""
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
    """Raised when credentials are invalid (triggers reauth flow)."""


class RavBariachAPI:
    """Async DESI API client.

    Auth flow:
      1. Full login (email + password) → JWT + userToken
      2. JWT refresh (/v4/login/user-token, no password) every ~35 min
         REQUIRED fields in refresh payload: userToken, application, registrationToken:"", deviceInfo
         (omitting registrationToken causes random 500 errors)
      3. If refresh fails → full login fallback
      4. If full login fails → raise RavBariachAuthError (triggers HA reauth)
    """

    def __init__(self, email: str, password: str, lock_id: int, device_id: str) -> None:
        self._email = email
        self._password = password
        self._lock_id = lock_id
        self._device_id = device_id
        self._jwt: str | None = None
        self._user_token: str | None = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _full_login(self, session: ClientSession) -> None:
        """Full login with email + password."""
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
        _LOGGER.debug("Rav-Bariach: full login successful")

    async def _refresh_jwt(self, session: ClientSession) -> bool:
        """Try to refresh JWT using stored userToken (no password needed)."""
        if not self._user_token:
            return False
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
                if resp.status != 200:
                    return False
                jwt = resp.headers.get("authorization", "").replace("Bearer ", "")
                if not jwt:
                    return False
                self._jwt = jwt
                _LOGGER.debug("Rav-Bariach: JWT refreshed (no password)")
                return True
        except Exception as err:
            _LOGGER.debug("Rav-Bariach: JWT refresh failed: %s", err)
            return False

    async def _ensure_auth(self, session: ClientSession) -> None:
        if self._jwt and not _is_jwt_expired(self._jwt):
            return
        _LOGGER.debug("Rav-Bariach: JWT expired, refreshing")
        if not await self._refresh_jwt(session):
            _LOGGER.debug("Rav-Bariach: refresh failed, doing full login")
            await self._full_login(session)

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    async def get_smart_locks(self, session: ClientSession) -> list[dict[str, Any]]:
        """Return list of smart locks on this account.

        Each entry: {"id": int, "name": str, "mac": str}
        Uses /v9/devices/sync with empty devices list.
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
        """Return dict: {locked: bool|None, battery: int|None, available: bool}"""
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
