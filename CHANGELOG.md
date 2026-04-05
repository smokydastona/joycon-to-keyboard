# Changelog

All notable changes to this project will be documented in this file.

Format is based on **Keep a Changelog**, and this project aims to follow **Semantic Versioning** once releases/tags start.
Until then, entries are grouped by date.

## Unreleased

- Capture real controller HID reports and implement evidence-based mapping in the ESP32 host mapper (no guessing report layouts).

### Added

- **Mouse tab: IncediusMod custom button map editor** — since the IncediusMod is a physical rewiring mod, each user's button IDs may differ. The "Edit Map…" button (visible when IncediusMod layout is selected) opens a dialog where users can reassign which M913 side button corresponds to each Thumb/Finger position, with duplicate detection. The custom map is saved per-profile.

### Changed

- **Performance: diff-based keymap canvas**: hotspot redraws now update items in-place via `itemconfigure`/`coords` instead of `canvas.delete("all")` + full rebuild. Full rebuilds only happen on resize or profile change.
- **Performance: dirty-flag batched redraw**: incoming `mapped_key` events set a dirty flag; the 80 ms pulse tick coalesces redraws instead of redrawing on every single input event.
- **Performance: cached conflict detection**: `_detect_conflicts()` result is cached and only invalidated on profile/mapping changes, not on every redraw.
- **Performance: cached reverse lookup**: `key_id → hotspot name` mapping is cached with explicit invalidation instead of rebuilding a dict on every input event.
- **Performance: lazy tab loading**: only Profile and Controller tabs are built at startup; Macros, Stick, Share, Overlay, and Input Test tabs are deferred until first selection.
- **Performance: O(1) firmware layer override lookup**: `find_layer_override()` now uses a per-layer `override_index[256]` array instead of linear scan (+1 KB RAM total for 4 layers).
- **Performance: timeline skip-if-unchanged**: timeline canvas skips redraw when event count hasn't changed and less than 1 second has elapsed.

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
- **ESP32 build: missing `driver` component + Bluetooth not enabled**: `driver/uart.h` required adding `driver` to `PRIV_REQUIRES` in `CMakeLists.txt`. Additionally, `sdkconfig.defaults` had no Bluetooth config, so the `bt` component didn't export its headers in CI (clean builds). Added `CONFIG_BT_ENABLED`, `CONFIG_BTDM_CTRL_MODE_BR_EDR_ONLY`, `CONFIG_BT_BLUEDROID_ENABLED`, `CONFIG_BT_CLASSIC_ENABLED`, and `CONFIG_BT_HID_HOST_ENABLED`.
- **ESP32 build: cast-to-array-type + undeclared Kconfig macros**: `esp_bt_hid_host_connect((esp_bd_addr_t)bda)` failed because `esp_bd_addr_t` is `uint8_t[6]` — C forbids casting to array types. Changed to `(uint8_t *)bda`. Additionally, `CONFIG_JOYCON_HOST_UART_DEBUG_REPORTS` (default `n`) and `CONFIG_JOYCON_HOST_UART_DEBUG_MAX_BYTES` are not defined as C macros when disabled; switched from runtime `if()` to `#if` preprocessor guards.
- **ESP32-S3 link: multiple-definition of TinyUSB descriptor callbacks**: `espressif__esp_tinyusb` v1.7.6 provides strong (non-weak) implementations of `tud_descriptor_device_cb`, `tud_descriptor_configuration_cb`, and `tud_descriptor_string_cb` in `descriptors_control.c`. Our `tusb_desc.c` also defined them, causing linker errors with the `WHOLE_ARCHIVE` flag. Removed the three conflicting callbacks from `tusb_desc.c` and instead pass our custom descriptors through `tinyusb_config_t` to `tinyusb_driver_install()`, which makes `esp_tinyusb`'s callbacks serve our descriptor data.
- **ESP32 link: missing Kconfig parent for HID Host**: `CONFIG_BT_HID_HOST_ENABLED=y` was set in `sdkconfig.defaults` but its parent menuconfig `CONFIG_BT_HID_ENABLED=y` was missing. Without the parent, Kconfig silently ignored the child option, so `BTC_HH_INCLUDED` evaluated to `FALSE` and all `esp_bt_hid_host_*` function bodies were compiled out of `libbt.a`, causing undefined reference linker errors. Added the missing `CONFIG_BT_HID_ENABLED=y`.

### Added

- **IncediusMod layout mode** (Mouse tab): optional alternative button label set for the [Red Dragon M913 mod by Incedius](https://www.printables.com/model/1191307-red-dragon-m913-mod). A "Layout" dropdown in the Device section switches between "Stock M913" (Side 1–12) and "IncediusMod" (Thumb 1–6, Finger 1–6). The layout choice is saved per-profile and labels update instantly.

- **App icon**: converted `icon.png` (1024×1024 sketchbook-ink artwork) to a multi-size `icon.ico` (16–256 px) at `helper-app/icon.ico`. Used as the window icon at runtime and embedded in the PyInstaller `.exe`.

- **Help tab with pinout diagram**: new "Help" tab (lazy-loaded) displays the `pinouts.png` board pinout reference for the Arduino Nano ESP32-S3 and NodeMCU ESP32-WROOM-32 in a scrollable canvas with horizontal/vertical scroll and mouse-wheel support. Image is bundled through the UI bundle pipeline.

- **M913 mouse overlay artwork**: four sketchbook-ink themed M913 overlay PNGs (light connected/disconnected, dark connected/disconnected) wired into the Mouse tab, matching the Joy-Con overlay pattern in the Controller tab. The UI bundle generator and artifact generator now include M913 images alongside Joy-Con overlays.

- **Redragon M913 Impact Elite mouse support** (helper app):
  - New `m913_device.py` module: full USB HID protocol ported from C++ (`m913-ctl` by Qehbr / `mouse_m908` by dokutan) to Python using `hidapi`.
  - Anti-cheat safe: all button remapping is written to the mouse's onboard microcontroller memory — no software injection.
  - 16-button remapping: mouse actions, keyboard keys/combos (Ctrl+C etc.), multimedia keys, DPI controls, fire mode.
  - 5-slot DPI configuration (100–16000 in steps of 100) with per-slot enable/disable.
  - LED modes: off, steady (color + brightness), respiration (color + speed), rainbow.
  - Polling rate: 125 / 250 / 500 / 1000 Hz.
  - **Multi-device support**: auto-detects all connected M913 mice (via wireless receiver VID `0x25a7` / PID `0xfa07`); each device configurable independently.
  - **Sister profiles**: link an M913 profile to a Joy-Con slot (1–4) so mouse config can travel with controller mappings.
  - M913 profiles saved as JSON to `%APPDATA%/BindBandit/m913/` with per-device registry.
  - New "Mouse" tab (lazy-loaded) with device scanner, button mapping grid, DPI editor, LED picker, polling rate selector, and profile save/load/delete.
  - Graceful fallback when `hidapi` is not installed (tab shows install hint, rest of app unaffected).
  - Added `hidapi>=0.14` to `requirements.txt` and `hid` to PyInstaller hidden imports.

- **Auto-advance unbound hotspot**: after binding a hotspot, the editor automatically selects the next unbound hotspot in layout order for faster mapping.
- **Latency profiling mode** (Input Test tab): toggle checkbox displays real-time redraw frame time and input processing latency (avg/max over last 50 samples).
- **Faster guided wizard**: auto-advance delay reduced from 600 ms to 300 ms for snappier step-by-step flow.

- **Auto-update date guard**: both the helper-app updater and the firmware updater now compare the GitHub release `published_at` timestamp against a build date (`__build_date__`) embedded at CI time. If the running build is newer than the latest release, the update is skipped even if version numbers would suggest otherwise. Local dev builds (empty `__build_date__`) fall back to version-only comparison.

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
  - Creates a GitHub Release tagged `v{version}` with `BindBandit.exe` as a downloadable asset.
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
