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
CONF_USER_TOKEN = "user_token"   # generated per install, stored in config entry

# Timing
SCAN_INTERVAL_SECONDS = 300       # Poll status every 5 minutes
JWT_EXPIRY_BUFFER_SECONDS = 300   # Re-auth 5 min before JWT expiry

# Lock state values (from API)
LOCK_STATE_LOCKED = 1
LOCK_STATE_UNLOCKED = 0
