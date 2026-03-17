"""Constants for Rav-Bariach LockApp integration."""

DOMAIN = "rav_bariach_lock"

# API — com-token is the Rav-Bariach app identifier embedded in the public APK.
# It is not a user secret; it identifies the white-label app to the DESI backend.
API_BASE_URL = "https://desismart.io/api/mobile/"
API_COM_TOKEN = "rb4ab7c2-d9e5-419d-8ef3-32728e01b940"
API_LOGIN_ENDPOINT = "v5/login"
API_REFRESH_ENDPOINT = "v4/login/user-token"
API_SYNC_ENDPOINT = "v9/devices/sync"      # returns full device list for account
API_LOCK_ENDPOINT = "v1/smart-lock/rav-bariach-lockapp/lock-unlock"
API_STATUS_ENDPOINT = "v2/smart-lock/rav-bariach-lockapp/get-status"

# Config entry keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_LOCK_ID = "lock_id"
CONF_DEVICE_ID = "device_id"
CONF_USER_TOKEN = "user_token"       # DESI long-lived token, stored in config entry
CONF_FCM_TOKEN = "fcm_token"         # Firebase registration token, stored in config entry
CONF_FCM_CREDENTIALS = "fcm_credentials"  # Full FCM credentials dict (for re-use on restart)

# Options keys
CONF_POLLING_ENABLED = "polling_enabled"
CONF_POLL_INTERVAL = "poll_interval"      # minutes

# Polling defaults
POLL_INTERVAL_DEFAULT = 5      # minutes
POLL_INTERVAL_MIN = 5
POLL_INTERVAL_MAX = 60
POLL_INTERVAL_STEP = 5

# JWT
JWT_EXPIRY_BUFFER_SECONDS = 300   # Re-auth 5 min before JWT expiry

# Lock state values (from API)
LOCK_STATE_LOCKED = 1
LOCK_STATE_UNLOCKED = 0

# ---------------------------------------------------------------------------
# Firebase / FCM — credentials extracted from the public APK (not user secrets)
# Source: jadx decompilation of com.rbsmartlockapp v1.1.32
#   res/values/strings.xml → gcm_defaultSenderId, google_app_id, google_api_key, project_id
# ---------------------------------------------------------------------------
FIREBASE_SENDER_ID = "916887001391"
FIREBASE_APP_ID = "1:916887001391:android:134b6e8b9ec5f1fdc169da"
FIREBASE_API_KEY = "AIzaSyD79V-Sy8Z3wbcgIrYqg2_ry2ohignEU9U"
FIREBASE_PROJECT_ID = "desiframework-21a17"

# FCM event types — discovered via strings analysis of libapp.so
# Published by the hub to STOMP and forwarded by DESI to FCM push notifications.
FCM_LOCK_EVENTS = {
    "NGP_LOCK_EVENT",       # physical or app lock
    "NGP_RF_LOCK_EVENT",    # RF key lock
}
FCM_UNLOCK_EVENTS = {
    "NGP_UNLOCK_EVENT",          # physical or app unlock
    "NGP_RF_UNLOCK_EVENT",       # RF key unlock
    "NGP_OTP_UNLOCK_EVENT",      # OTP code unlock
}
FCM_ALL_LOCK_EVENTS = FCM_LOCK_EVENTS | FCM_UNLOCK_EVENTS | {
    "NGP_FAIL_LOCK_EVENT",
    "NGP_FAIL_UNLOCK_EVENT",
    "NGP_OTP_FAIL_UNLOCK_EVENT",
}

# FCM reconnect settings
FCM_RECONNECT_DELAYS = [1, 5, 30, 300]   # seconds between reconnect attempts
FCM_MAX_FAILURES = 3                      # failures before falling back to polling
