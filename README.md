# VIP Parker (by TEZ) integration for Home Assistant

![hacs](https://img.shields.io/badge/HACS-Custom-orange) ![license](https://img.shields.io/badge/license-MIT-blue)
[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=chaldron&repository=hass-vip-parker&category=integration)

A 100% vibe-coded Home Assistant integration for the VIP Parker app by TEZ Technology (SMS Valet). Request your vehicle and see its status from Home Assistant.

The reverse-engineered API is documented in [VIP_PARKER_API.md](VIP_PARKER_API.md). It was pulled from the app statically using [extract_api.sh](extract_api.sh), which can be re-run when the app is updated.

## Features

- Show request status for a vehicle (parked / requested / on the way / ready)
- Request the vehicle to the pickup area
- Cancel a request

## Requirements

- A VIP Parker account (the phone number you log in with)
- Home Assistant 2024.1+

## Installation

HACS (automatic):
1. Click the "Add to HACS" button at the top of the README.

HACS (custom repo):
1. HACS → ⋮ → Custom repositories.
2. Add `https://github.com/chaldron/hass-vip-parker`, category Integration.
3. Install "VIP Parker" and restart Home Assistant.

Manually:
1. Copy `custom_components/vip_parker` into `<config>/custom_components/` and restart Home Assistant.

## Configuration

Settings → Devices & Services → Add Integration → VIP Parker. Enter your phone number, get an SMS code, and enter it. Authentication tokens are stored and auto-refreshed.

## Disclaimer

Unofficial. Not affiliated with or endorsed by TEZ Technology / SMS Valet. For personal use with your own account. The app key in this repo is the app-level key baked into the public Android APK (extractable with `extract_api.sh`) — it's not a user secret. Don't hammer the API. Use at your own risk.

## License

MIT. See [LICENSE](LICENSE).
