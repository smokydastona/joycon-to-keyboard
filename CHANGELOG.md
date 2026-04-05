# Changelog

All notable changes to this project will be documented in this file.

Format is based on **Keep a Changelog**, and this project aims to follow **Semantic Versioning** once releases/tags start.
Until then, entries are grouped by date.

## Unreleased

- Capture real controller HID reports and implement evidence-based mapping in the ESP32 host mapper (no guessing report layouts).

### Changed

- **CI: Node.js 24 migration**: upgraded all GitHub Actions to Node 24-compatible versions to resolve deprecation warnings:
  - `actions/checkout` v4 → v5
  - `actions/setup-python` v5 → v6
  - `actions/upload-artifact` v4 → v6
  - `actions/download-artifact` v4 → v7

### Fixed

- **Firmware build: flash size mismatch**: both ESP32 and ESP32-S3 `sdkconfig.defaults` now set `CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y`. The OTA-enabled partition table requires ~3.6 MB, which exceeded the 2 MB default and caused CI build failures.
- **ESP32-S3 build: missing TinyUSB component**: `tinyusb` was removed from ESP-IDF v5.2 built-in components. Added `idf_component.yml` to pull `espressif/esp_tinyusb` from the component registry, and updated `PRIV_REQUIRES` from `tinyusb` to `esp_tinyusb`.
- **ESP32-S3 build: `tud_task` implicit declaration**: removed the manual `tud_task()` call from `app_main.c` — `esp_tinyusb` v1.x runs it in its own internal FreeRTOS task after `tinyusb_driver_install()`. Replaced with `vTaskDelay(1)` to yield the main loop.
- **ESP32-S3 link: undefined TinyUSB HID callbacks**: the TinyUSB HID device class requires application-defined callbacks (`tud_hid_descriptor_report_cb`, `tud_hid_get_report_cb`, `tud_hid_set_report_cb`) which are implemented in `tusb_desc.c`. The linker couldn't resolve them due to archive link ordering. Added `WHOLE_ARCHIVE` flag to `main` component's `CMakeLists.txt` so all callback implementations are always linked.

### Added

- **Unified click-to-bind** (helper app):
  - Single-click a hotspot: auto-enters learn mode (unbound) or bind mode (bound) — no separate Learn/Bind steps.
  - Right-click context menu on any hotspot: Learn, Bind, Reset to passthrough, Clear binding, Disable.
- **Pulse animation**: active controller hotspots pulse with a breathing glow effect (80 ms timer, phase 0.3–1.0).
- **Profile slot quick-select**: 4 slot buttons at top of Profile tab with names; "Read all names" to refresh.
- **Safe mode recovery**: one-click button resets the active device slot to defaults (with confirmation dialog).
- **Tap-hold mapping type**: single button produces different actions for quick tap vs long hold (`hold_ms` threshold, default 300 ms).
- **Chording**: define multi-button combos that trigger a single action when pressed simultaneously. New `chords` profile field.
- **Conflict auto-fix**: when duplicate output bindings are detected, a "Fix" button resolves by keeping the first and clearing the rest.
- **Visual event timeline** (Input Test tab): horizontal canvas showing the last 5 seconds of input events as colored marks with a time axis.
- Theme version 2 with new state color tokens: `active`, `conflict`, `modified`, `selected`, `pulse_bright`, `timeline_press`, `timeline_release`.

- **Undo / Redo** (Ctrl+Z / Ctrl+Y): stack-based profile change history (up to 50 levels); buttons in the status bar.
- **Guided Setup wizard**: step-by-step Toplevel dialog learns 7 controller buttons and auto-binds WASD/Space/Shift/Ctrl.
- **Intent-based mapping**: right-click "What should X do?" menu with 14 common game actions (Jump/Space, Sprint/Shift, etc.).
- **Smart Defaults**: auto-applies WASD/Space/Shift/Ctrl/E/R/V to D-pad + face buttons when a controller connects and profile is mostly empty.
- **Smart Search**: search bar in keymap editor filters hotspots by name, output, or mapping type; matching hotspots get a dashed highlight ring.
- **Sandbox mode**: checkbox to enter temporary playground mode; on exit, user chooses to keep or discard changes.
- **Ghost labels on hover**: faint italic tooltip follows cursor over the controller diagram showing hotspot name + current output.
- **Visual layer stack**: row of badges below layer radio buttons displaying each layer's name, mode, and mapping count.
- **Explain mapping dialog**: right-click → shows full input→output chain, conflicts, and layer overrides in a scrollable Toplevel.
- **Lock critical inputs**: right-click Lock/Unlock prevents accidental unbinding; locked hotspots require yes/no confirmation.
- **Feedback sounds**: optional Windows beep on bind (800 Hz), unbind (400 Hz), error (300 Hz), undo (600 Hz); background thread, graceful fallback.
- **Adaptive UI (Simple/Advanced)**: toggle hides layers, chords, Macros/Stick/Share tabs in simple mode for cleaner first-time experience.
- **Mode indicator**: always-visible status bar showing active slot, layer, bind/learn mode, sandbox, UI mode, undo depth; refreshes every 300 ms.
- **Community presets** (Share tab): three built-in mapping presets (FPS/Shooter, Platformer, RPG/Action) with one-click apply.

- **Press-to-bind remapping** (helper app + firmware):
  - New `remap_hid` mapping type: bypasses compiled `keymap.c` entirely, sends arbitrary USB HID modifier + keycode directly.
  - Controller tab "Bind key" button: click a hotspot, press any keyboard key, instantly mapped.
  - `hid_keycodes.py` module: ~100 tkinter keysym → USB HID keycode mappings with reverse lookup.
- **Layer system** (firmware + helper app):
  - Profiles can define up to 4 overlay layers, each activated by a controller button (hold or toggle mode).
  - Layer overrides are sparse: only listed key_ids are overridden, others fall through to base.
  - Firmware emits `{"evt":"layer","name":"...","active":true/false}` events over CDC serial.
  - Controller tab has layer selector (Base + Layer 1–4), activation key_id/mode/name configuration.
- **Live input visualization**: controller hotspots light up green when the corresponding button is physically pressed.
- **Conflict detection**: hotspots producing the same output key are highlighted red, with a conflict summary below the editor.
- **Color-coded hotspots**: green = active, red = conflict, blue = selected, yellow = has custom mapping.
- **Input Test tab**: real-time event log showing controller button presses/releases with timestamps and active-key summary.
- **Profile management**: rename, duplicate, and reset-to-defaults buttons on the Profile tab.
- **Reset button**: per-hotspot "Reset button" reverts individual mappings to passthrough.

- **Logging & crash-log infrastructure** (`helper-app/joycon_helper/logger.py`):
  - `logs/` folder with daily rotating `helper.log` (kept 15 days).
  - `crash-logs/` folder with timestamped crash dumps for unhandled exceptions (main thread + worker threads).
  - Auto-cleanup: files older than 15 days deleted on each startup.
  - No personal data collected — only app-level events, serial traffic, and platform info.
- Logging integrated into `app.py` (serial connect/disconnect, command TX/RX, profile load/save, theme loading, startup/shutdown) and `serial_client.py` (port open/close, read errors, RX thread lifecycle).
- `_log_line()` now writes to both the UI log widget and the file logger.
- **Auto-update** (`helper-app/joycon_helper/updater.py`):
  - On startup (and on manual click), checks GitHub Releases API for a newer version.
  - When running as a frozen `.exe`: downloads, swaps in place (rename dance), and prompts restart.
  - Version displayed in the sidebar; update button changes to show available version.
  - No personal data sent — unauthenticated GET to the public GitHub API only.
- **Runtime version** (`helper-app/joycon_helper/_version.py`):
  - Auto-generated by `tools/versioning.py write-app-version`.
  - Pre-commit hook and CI both keep it in sync with `version.json`.
- **Release workflow**: `build-release-bundle.yml` now supports `create_release: true` dispatch input.
  - Validates that the new version strictly increments over the latest GitHub Release tag.
  - Creates a GitHub Release tagged `v{version}` with `JoyConBridgeHelper.exe` as a downloadable asset.
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
