# Changelog

All notable changes to this project will be documented in this file.

Format is based on **Keep a Changelog**, and this project aims to follow **Semantic Versioning** once releases/tags start.
Until then, entries are grouped by date.

## Unreleased

- Capture real controller HID reports and implement evidence-based mapping in the ESP32 host mapper (no guessing report layouts).

## 2026-04-04

### Added

- Two-board “anti-cheat-safe” architecture documentation: ESP32 (Bluetooth Classic HID host) → UART → ESP32-S3 (USB HID keyboard).
- Detailed one-USB-dongle setup docs:
  - `docs/wiring.md` (power + UART wiring, one-USB power model, exact pin-to-pin table matching `pinouts.png`)
  - `docs/firmware-install.md` (Windows + ESP-IDF flashing guide for both boards)
- Arduino Nano ESP32-S3 (ABX00083) setup notes with GPIO mapping:
  - `RX0 = GPIO44`, `TX0 = GPIO43`
- Helper app (Windows, Python + Tkinter): tabbed UI for profiles/macros/share/overlay + NDJSON serial protocol documentation.
- ESP32 Classic-BT host improvements for evidence-first input capture:
  - Configurable target name substring for discovery (Joy-Con/Binbok/third-party)
  - Report logging “on change”
  - Optional UART debug frames forwarding raw HID reports (ESP32-S3 ignores them)
- Offline UART log decoder updates to understand both key-event frames and optional debug frames.

### Changed

- Repo documentation aligned around the **one USB dongle** flow (ESP32-S3 is the only board that plugs into the PC).
- VS Code IntelliSense improvements by exporting and using `compile_commands.json` for ESP-IDF projects.

### Removed

- Legacy USB keyboard/device firmware path (project is ESP32-S3-only on the USB keyboard/device side).

### Docs / repo presentation

- `pinouts.png` used as the banner image at the top of the repository `README.md`.
