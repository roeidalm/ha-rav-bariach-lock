# Rav-Bariach LockApp — Home Assistant Custom Component

A Home Assistant custom component for controlling Rav-Bariach LockApp 2 WiFi smart locks via the DESI cloud API.

## Features

- 🔒 Lock / unlock via Home Assistant
- 🔋 Battery level sensor
- 🔄 Automatic JWT refresh — no manual re-auth needed
- 🔁 Polling on/off toggle — control directly from the device page
- ⏱️ Configurable poll interval — slider 5–60 minutes (step 5)
- ☁️ Auto-discovery — locks are fetched from your account, no Lock ID needed
- ⚙️ Setup via UI config flow (no YAML)

## Installation via HACS

1. In HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add: `https://github.com/roeidalm/ha-rav-bariach-lock` → Category: **Integration**
3. Install **Rav-Bariach LockApp**
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search **Rav-Bariach LockApp**

## Manual Installation

1. Copy `custom_components/rav_bariach_lock/` into your HA `config/custom_components/`
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration** → search **Rav-Bariach LockApp**

## Setup

Two-step setup wizard:

| Step | What happens |
|------|-------------|
| 1. Sign in | Enter your DESI / LockApp account email + password |
| 2. Choose lock | Locks on your account are fetched automatically — pick from a dropdown |

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `lock.rav_bariach_X_lock` | Lock | Lock / unlock control with optimistic state |
| `sensor.rav_bariach_X_battery` | Sensor | Battery level (%) |
| `switch.rav_bariach_X_status_polling` | Switch | Enable / disable background polling |
| `number.rav_bariach_X_poll_interval` | Number (slider) | Polling interval — 5 to 60 minutes |

All entities appear on the device page. Changes to the polling switch and interval take effect immediately — no restart needed.

## Authentication

| Stage | Method |
|-------|--------|
| Initial setup | Email + password (once, via config flow) |
| Normal operation | JWT refresh using stored `userToken` — no password |
| Token rejected | Silent full re-login with stored credentials |
| Credentials invalid | HA reauth prompt |

JWT lifetime is ~40 minutes. The component refreshes it automatically before it expires. The `userToken` is long-lived and persisted across HA restarts.

## Polling vs. Real-Time

This integration uses **cloud polling** (REST API). The lock state is updated:
- On the configured schedule (5–60 min, or disabled)
- Immediately after a lock/unlock command (3-second confirmation refresh)

For real-time push updates (physical lock/unlock events), MQTT support is planned for a future release.

## Architecture

```
Home Assistant  →  DESI Cloud API (desismart.io)  →  Hub (WiFi)  →  Rav-Bariach Lock (BLE)
```

## License

MIT
