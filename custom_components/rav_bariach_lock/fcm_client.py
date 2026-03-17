"""FCM (Firebase Cloud Messaging) client for Rav-Bariach LockApp.

Responsibilities:
  - Register as an FCM client using DESI's Firebase project credentials
  - Maintain a persistent connection and receive push notifications
  - Parse lock/unlock events and notify the coordinator immediately
  - Automatically refresh credentials and persist them to config entry
  - Fall back to REST polling if FCM fails repeatedly

Flow:
  1. On HA startup: load saved FCM credentials (if any) → checkin_or_register()
  2. Send received FCM token to DESI in registrationToken field (via api.set_fcm_token)
  3. Start persistent listener — runs as an asyncio background task
  4. On push notification: parse event type → call on_lock_event(locked=True/False)
  5. On credentials update: persist to config entry + notify DESI
  6. On repeated failures: call on_fcm_failed() → coordinator enables polling fallback

NOTE: The Firebase credentials here (sender ID, API key, etc.) are embedded in the
public APK and are not user secrets. They identify DESI's Firebase project.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FCM_CREDENTIALS,
    CONF_FCM_TOKEN,
    FIREBASE_API_KEY,
    FIREBASE_APP_ID,
    FIREBASE_PROJECT_ID,
    FIREBASE_SENDER_ID,
    FCM_ALL_LOCK_EVENTS,
    FCM_LOCK_EVENTS,
    FCM_MAX_FAILURES,
    FCM_RECONNECT_DELAYS,
    FCM_UNLOCK_EVENTS,
)

_LOGGER = logging.getLogger(__name__)


class RavBariachFcmClient:
    """Manages FCM registration and push notification listening for one lock entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        on_lock_event: Callable[[bool], None],
        on_fcm_failed: Callable[[], None],
        on_token_updated: Callable[[str], None],
        on_fcm_connected: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the FCM client.

        Args:
            hass: Home Assistant instance
            entry: Config entry (used to read/write FCM credentials)
            on_lock_event: Called with locked=True/False on NGP lock events
            on_fcm_failed: Called when FCM fails too many times → enables polling
            on_token_updated: Called with new FCM token so API can send it to DESI
            on_fcm_connected: Called once after successful FCM registration (optional)
        """
        self._hass = hass
        self._entry = entry
        self._on_lock_event = on_lock_event
        self._on_fcm_failed = on_fcm_failed
        self._on_token_updated = on_token_updated
        self._on_fcm_connected = on_fcm_connected
        self._task: asyncio.Task | None = None
        self._push_client = None
        self._failures = 0
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the FCM listener as a background HA task."""
        self._running = True
        self._failures = 0
        self._task = self._hass.async_create_task(
            self._run_with_reconnect(),
            name=f"rav_bariach_fcm_{self._entry.entry_id}",
        )
        _LOGGER.debug("Rav-Bariach FCM: listener task started")

    async def stop(self) -> None:
        """Stop the FCM listener. Called on HA unload."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

        if self._push_client is not None:
            try:
                await self._push_client.stop()
            except Exception:
                pass
            self._push_client = None

        _LOGGER.debug("Rav-Bariach FCM: listener stopped")

    # ------------------------------------------------------------------
    # Internal — reconnect loop
    # ------------------------------------------------------------------

    async def _run_with_reconnect(self) -> None:
        """Outer loop: connect → listen → reconnect on failure."""
        delay_idx = 0
        while self._running:
            try:
                await self._connect_and_listen()
                delay_idx = 0  # clean exit (e.g., stop() called)
            except asyncio.CancelledError:
                return
            except Exception as err:
                if not self._running:
                    return
                self._failures += 1
                _LOGGER.warning(
                    "Rav-Bariach FCM: connection error (%d/%d): %s",
                    self._failures,
                    FCM_MAX_FAILURES,
                    err,
                )
                if self._failures >= FCM_MAX_FAILURES:
                    _LOGGER.error(
                        "Rav-Bariach FCM: %d consecutive failures — "
                        "falling back to REST polling",
                        self._failures,
                    )
                    self._on_fcm_failed()
                    return

                delay = FCM_RECONNECT_DELAYS[
                    min(delay_idx, len(FCM_RECONNECT_DELAYS) - 1)
                ]
                delay_idx += 1
                _LOGGER.debug(
                    "Rav-Bariach FCM: reconnecting in %ds (attempt %d)",
                    delay,
                    self._failures + 1,
                )
                await asyncio.sleep(delay)

    async def _connect_and_listen(self) -> None:
        """Register with FCM and start persistent listener."""
        try:
            from firebase_messaging import FcmPushClient, FcmRegisterConfig
        except ImportError as err:
            raise RuntimeError(
                "firebase-messaging is not installed. "
                "This is a bug — it should be in manifest.json requirements."
            ) from err

        # Build config using DESI's Firebase project credentials (from public APK)
        fcm_config = FcmRegisterConfig(
            FIREBASE_PROJECT_ID,
            FIREBASE_APP_ID,
            FIREBASE_API_KEY,
            FIREBASE_SENDER_ID,
        )

        # Load saved credentials (avoids re-registration on every HA restart)
        saved_credentials = self._entry.data.get(CONF_FCM_CREDENTIALS)

        # firebase-messaging API:
        #   FcmPushClient(callback, fcm_config, credentials, credentials_updated_callback, ...)
        self._push_client = FcmPushClient(
            self._handle_notification,
            fcm_config,
            credentials=saved_credentials,
            credentials_updated_callback=self._handle_credentials_updated,
            received_persistent_ids=[],
        )

        # Register (or re-use saved creds) → get FCM token
        fcm_token = await self._push_client.checkin_or_register()

        if fcm_token:
            _LOGGER.debug(
                "Rav-Bariach FCM: registered, token: %s...", fcm_token[:12]
            )
            # Persist token + notify API to send it to DESI
            if fcm_token != self._entry.data.get(CONF_FCM_TOKEN):
                await self._persist_token(fcm_token)
            self._on_token_updated(fcm_token)
            # Notify coordinator that FCM is live (disables polling)
            if self._on_fcm_connected is not None:
                self._hass.loop.call_soon_threadsafe(self._on_fcm_connected)
        else:
            _LOGGER.warning("Rav-Bariach FCM: checkin_or_register returned no token")

        # start() creates background asyncio tasks (_listen + _do_monitor)
        # and returns immediately. We must await those tasks to block until
        # the listener actually stops (either cleanly or due to errors).
        await self._push_client.start()

        # Wait for the library's internal tasks to finish.
        tasks = getattr(self._push_client, "tasks", None)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # If the library terminated itself (abort_on_sequential_error_count
        # or connection retries exhausted), do_listen will be False.
        # Raise so our reconnect loop can count this as a failure.
        if not getattr(self._push_client, "do_listen", True):
            raise RuntimeError(
                "FCM library terminated — connection retries exhausted "
                "or sequential errors exceeded threshold"
            )

    # ------------------------------------------------------------------
    # Internal — FCM callbacks
    # ------------------------------------------------------------------

    def _handle_notification(
        self, notification: dict, persistent_id: str, obj: Any | None
    ) -> None:
        """Handle incoming FCM push — called by the firebase_messaging library.

        Args:
            notification: dict with the FCM message data
            persistent_id: unique message ID from FCM
            obj: optional raw object (usually None)
        """
        # Log everything on first few messages to understand DESI's payload format
        _LOGGER.debug(
            "Rav-Bariach FCM raw push — notification=%s | persistent_id=%s | obj=%s",
            notification,
            persistent_id,
            obj,
        )

        event_type = self._extract_event_type(notification, obj)

        if event_type is None:
            _LOGGER.debug(
                "Rav-Bariach FCM: received push but could not extract event type "
                "(payload format unknown — check debug logs above)"
            )
            return

        _LOGGER.info("Rav-Bariach FCM: event received — %s", event_type)

        # Reset failure counter on successful message
        self._failures = 0

        if event_type in FCM_LOCK_EVENTS:
            # firebase-messaging may call this from a non-asyncio thread.
            # Use call_soon_threadsafe to safely hand off to the HA event loop.
            self._hass.loop.call_soon_threadsafe(self._on_lock_event, True, event_type)
        elif event_type in FCM_UNLOCK_EVENTS:
            self._hass.loop.call_soon_threadsafe(self._on_lock_event, False, event_type)
        elif event_type in FCM_ALL_LOCK_EVENTS:
            # Failed events (NGP_FAIL_LOCK_EVENT etc.) — log only, state unchanged
            _LOGGER.info(
                "Rav-Bariach FCM: lock operation failed event: %s", event_type
            )
        else:
            _LOGGER.debug(
                "Rav-Bariach FCM: ignoring non-lock event: %s", event_type
            )

    @staticmethod
    def _extract_event_type(notification: Any, data_message: Any) -> str | None:
        """Try to extract event type from FCM payload.

        DESI payload format is not fully documented — we try common field names.
        The exact structure will be confirmed on first live push.
        """
        # Try data_message (FCM data payload) — most likely location
        for source in (data_message, notification):
            if not source:
                continue
            if not isinstance(source, dict):
                continue
            for field in ("command", "eventType", "event_type", "type", "event"):
                val = source.get(field)
                if val and isinstance(val, str):
                    return val

        return None

    def _handle_credentials_updated(self, credentials: dict) -> None:
        """Called by firebase_messaging when FCM credentials are refreshed."""
        _LOGGER.debug("Rav-Bariach FCM: credentials refreshed, persisting")
        self._hass.async_create_task(self._persist_credentials(credentials))

    # ------------------------------------------------------------------
    # Internal — persistence
    # ------------------------------------------------------------------

    async def _persist_token(self, token: str) -> None:
        self._hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_FCM_TOKEN: token},
        )

    async def _persist_credentials(self, credentials: dict) -> None:
        self._hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_FCM_CREDENTIALS: credentials},
        )
