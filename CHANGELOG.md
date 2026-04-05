# Changelog

All notable changes to this project will be documented in this file.

Format is based on **Keep a Changelog**, and this project aims to follow **Semantic Versioning** once releases/tags start.
Until then, entries are grouped by date.

## Unreleased

- Capture real controller HID reports and implement evidence-based mapping in the ESP32 host mapper (no guessing report layouts).

### Added

- **Logging & crash-log infrastructure** (`helper-app/joycon_helper/logger.py`):
  - `logs/` folder with daily rotating `helper.log` (kept 15 days).
  - `crash-logs/` folder with timestamped crash dumps for unhandled exceptions (main thread + worker threads).
  - Auto-cleanup: files older than 15 days deleted on each startup.
  - No personal data collected — only app-level events, serial traffic, and platform info.
- Logging integrated into `app.py` (serial connect/disconnect, command TX/RX, profile load/save, theme loading, startup/shutdown) and `serial_client.py` (port open/close, read errors, RX thread lifecycle).
- `_log_line()` now writes to both the UI log widget and the file logger.
- **Dark controller overlay artwork**: `joycons-dark.png` + `joycons-dark-grey.png` source PNGs for the dark theme.
  - Artifact pipeline now generates 4 dark inspection copies (`joycons-dark-none/left/right/both.png`) alongside the 4 light copies.
  - Dark UI bundle (`.ui-bundle-dark/`) now uses the dark overlay PNGs instead of the light ones.
  - `background-dark.svg` updated to reference `joycons-dark.png`.
- **Dark theme restyle — dark blue ballpoint pen**: all dark SVGs, theme tokens, and helper-app colors shifted from warm sepia/gold to a cool dark-blue-on-dark-paper aesthetic matching `joycons-dark-grey.png`.
- **Dark mode UI bundle**: complete dark-mode variant of the torn-parchment theme.
  - `docs/ui/background-dark.svg` — dark parchment on very dark desk surface.
  - `docs/ui/assets/components-dark.svg` — dark-inverted component sheet (same shapes/paths as light).
  - `docs/ui/assets/icons-dark.svg` — dark-inverted icon sheet (same shapes/paths as light).
  - `DARK_THEME` tokens in `tools/generate_ui_bundle.py` with inverted color palette.
  - `DARK_UI_THEME` in `helper-app/joycon_helper/app.py` with auto-detect support.
- Bundle generator now produces **two** bundles by default: `.ui-bundle/` (light) and `.ui-bundle-dark/` (dark). Use `--no-dark` to skip the dark bundle.
- Dark mode auto-detection: `JOYCON_THEME=dark` env var, `--dark` CLI flag, or Windows 10+ `AppsUseLightTheme` registry check.
- CI workflow and PyInstaller command updated to include dark bundle in builds.

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
