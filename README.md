# Rav-Bariach LockApp — Home Assistant Custom Component

A Home Assistant custom component for controlling Rav-Bariach LockApp 2 WiFi smart locks via the DESI cloud API.

## Features

- 🔒 Lock / unlock via Home Assistant
- 🔋 Battery level sensor
- 🔄 Automatic token refresh (no manual re-auth needed)
- ⚙️ Setup via UI config flow (no YAML needed)
- ☁️ Cloud polling every 5 minutes

## Installation

### Manual

1. Copy `custom_components/rav_bariach_lock/` into your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration**
4. Search for **Rav-Bariach LockApp**
5. Enter your email, password, and Lock ID

### HACS (coming soon)

Add this repository as a custom HACS repository.

## Configuration

| Field | Description |
|-------|-------------|
| Email | Your DESI / LockApp account email |
| Password | Your DESI / LockApp account password |
| Lock | Auto-discovered from your account — select from a dropdown |

## Entities Created

| Entity | Type | Description |
|--------|------|-------------|
| `lock.rav_bariach_lock` | Lock | Lock / unlock control |
| `sensor.rav_bariach_battery` | Sensor | Battery level (%) |

## Architecture

```
Home Assistant  →  DESI Cloud API (desismart.io)  →  Rav-Bariach Smart Lock
```

Authentication uses JWT tokens (40 min expiry). The component re-authenticates automatically using stored credentials — no user action needed.

## Notes

- Cloud polling only — no local API available
- Real-time state (physical lock events) requires MQTT integration (future work)
- Lock ID can be found in the LockApp mobile app under lock settings

## License

MIT
