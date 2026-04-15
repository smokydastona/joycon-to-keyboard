# Bind Bandit (Windows, Python + PyQt6)

Bind Bandit is a standalone desktop app for configuring gaming peripherals. **No specific hardware is required to launch it** — use whichever features match your setup:

| Use case | What you need | Sections you'll use |
|---|---|---|
| **Joy-Con → keyboard bridge** | ESP32 + ESP32-S3 boards (flashed) | Dashboard, Mapping, Macros & Stick, Profiles, Diagnostics |
| **M913 mouse configuration** | Redragon M913 mouse (USB) | Devices → M913 |
| **Razer mouse configuration** | Razer Basilisk X HyperSpeed (USB) | Devices → Razer |
| **Both** | All of the above | All sections |

### Joy-Con bridge features (requires ESP32-S3 serial connection)

The bridge talks over a **serial (COM) port** provided by the **ESP32-S3 USB keyboard firmware** (USB CDC-ACM). If you haven't flashed the ESP32-S3 yet, start with `docs/firmware-install.md`.

- Select a COM port and connect
- View live text/JSON coming from the device
- Upload a loadout JSON (slot 0–3)
- Set the active loadout slot
- One-click "Upload + Activate" for the selected slot

### M913 mouse features (no serial connection needed)

The Mouse tab communicates directly with Redragon M913 mice over USB HID (`hidapi`). No ESP32 hardware or COM port is needed — just plug in the mouse.

### Razer mouse features (no serial connection needed)

The Razer tab communicates directly with Razer Basilisk X HyperSpeed mice (and other supported Razer mice) over USB HID Feature Reports. No ESP32 hardware, no Razer Synapse required — just plug in the mouse's USB dongle.

- **Battery level**: live readback with charging indicator
- **DPI stages**: read/write up to 5 DPI stages (X/Y independent, clamped to per-model max), active stage selector
- **Polling rate**: 125 / 500 / 1000 Hz
- **Idle/sleep timeout**: 60–900 seconds
- **Button remapping**: remap all 7 buttons (left, right, middle, back, forward, scroll up/down) to keyboard keys (including F13–F24), other mouse buttons, DPI cycle, or disable — **all stored on the mouse's onboard memory** (anti-cheat safe)
- **Hypershift layer**: each button can have a separate binding on the hypershift layer
- **CRC validation**: response packets verified via XOR checksum + transaction ID check
- **Firmware version** and **serial number** readback
- **Loadout system**: save/load/delete named loadouts, auto-link loadouts to specific devices
- Profile format versioned (v2) for forward compatibility
- Requires `hidapi` (`pip install hidapi`)

Current UI sections (sidebar navigation, PyQt6):

- **Profiles** (sidebar: **Profiles**): JSON editor, load/save/validate; profile rename/duplicate/reset-to-defaults buttons; **slot quick-select** (4 slot buttons with names for fast switching); **community presets** (5 genre categories: FPS/Shooter, Racing, Platformer, RPG, Strategy); **share codes** (offline-only export/import of compressed profile code strings); **app switcher** (auto-switch profile by foreground window, supports basename and absolute path matching, max 100 rules); undo/redo (up to 50 levels)
- **Macros & Stick** (sidebar: **Macros & Stick**): macro list + step editor with JSON step editing, record mode from incoming `mapped_key` events; layers (mask configuration); chords (multi-button combos); stick config (deadzone inner/outer, response curve type, sensitivity, SOCD resolution mode) with live curve preview — all saved to the active profile
- **Mapping** (sidebar: **Mapping**): **Controller Canvas** (center, tabbed layouts for Joy-Con, M913, Mouse, and Gamepad hotspots) and **Profile Quick-Edit Panel** (right, profile slot selector, name editor, quick actions — new/duplicate/upload/read/save/load/reset, mapping summary, undo/redo, clear all). **Mapping Popup** for full binding configuration (keyboard/mouse/gamepad/macro/advanced tabs). The popup keyboard picker now uses the updated default keyboard hotspot positions and key-shaped outlines instead of generic circles. If `hotspot_positions.json` is present next to the app or working directory, the saved Joy-Con, mouse, gamepad, and keyboard hotspot coordinates are loaded automatically on startup. Hotspot highlight textures are now generated from the live hotspot geometry itself, so dragging positions or switching shaped layouts keeps the overlay art locked to the current hotspot position, size, and shape instead of using stale pre-rendered layers. The generated overlay art now also includes handwritten button legends that match the represented physical control, so the sketch overlays stay intuitive instead of acting like unlabeled blobs. **Learn Mode** captures controller button presses. **Search** filters hotspots by name. **Right-click context menu**: Edit, Learn, Unbind, Disable, Copy/Paste Binding, Swap With…, Lock/Unlock, Toggle Turbo, Info. **Color-coded hotspots**: green = mapped, blue = selected. **Rainbow colour picker**: dropdown for hotspot highlight colours.
- **Dashboard** (sidebar: **Dashboard** / **Mission Control** in the themed nav): connection overview cards (serial port, Bluetooth status, **per-side battery state**, latency), quick action buttons (ping, read profile, upload profile, toggle overlay), an **Active Loadout** briefing that shows the current slot, profile name/icon, mapping composition, tags, stick-curve mode, and a short mapped-input preview, plus a live input visualizer that highlights the active Joy-Con controls from the incoming hardware event stream. It also shows current layers, recent macro activity, per-side battery, RSSI, a device-aware active-controls summary for multi-device key spaces, badge-style indicators for abstract actions such as Jump/Sprint/Crouch or multi-device key spaces, and a short recent-activity feed split into Input / Layer / Macro lanes whose older entries fade back automatically and collapse into `+N older` summaries when one lane gets noisy.
- **Diagnostics** (sidebar: **Diagnostics** / **Forensics** in the themed nav): live input test event log showing controller button presses/releases with timestamps, a summary of currently active keys using human-readable labels, a **visual event timeline** showing the last 5 seconds of input events as colored marks, a compact live visualizer of the controller state board with a device-aware active-controls summary, action badges and an age-fading recent-activity feed split into Input / Layer / Macro lanes, with noisy lanes compacted into `+N older` summaries, and a real telemetry strip for session duration, total events, throughput, active/peak keys, average hold time, and latency. Controller information (type, serial, deadzone, range ratio, body/button color) now includes a **calibration assessment** that grades the reported stick deadzone/range and explains whether recalibration is advisable. **Copy Summary** copies a human-readable forensic snapshot to the clipboard, and **Export Report** writes a JSON diagnostics bundle with telemetry, controller metadata, calibration status, and recent log lines. **Firmware OTA** update with progress bar. **Web Flasher link** for first-time board flashing.
- **Devices — M913** (sidebar: **Devices**, M913 tab): configure Redragon M913 mice over USB HID — device scanner/selector, button remapping (16 buttons), DPI (5 stages, 100–16000, with enable checkboxes), LED modes (off/steady/respiration/rainbow/wave/reactive/ripple/starlight/breath_single + color picker + brightness 0–255 + speed), polling rate (125/250/500/1000 Hz), layout mode selector (Stock M913 / IncediusMod with Edit Map dialog). Supports **multiple mice** simultaneously with independent profiles. **Wireless support**: detects both wired (PID 0xFA07) and wireless dongle (PID 0xFA08). **Snipe button**: assign "snipe" to any button for temporary DPI switch while held. **Hardware macros**: 15 macro slots (up to 67 key events each) via the Macro Builder popup — visual sequence editor for press/release events. **INI import/export**: compatible with m913-ctl INI format for sharing configs. **Diagnostics popup**: raw HID packet viewer for debugging device communication. **Sister slot** links M913 profiles to Joy-Con slots so mouse and controller settings travel together.
- **Devices — Razer** (sidebar: **Devices**, Razer tab): configure Razer Basilisk X HyperSpeed mice (and other supported Razer mice) over USB HID Feature Reports — device scanner/selector, read state button with battery/FW/serial info, DPI stages (5 levels, X/Y independent with active stage radio selector), button remapping (7 buttons including F13–F24 keys), **hypershift layer** (separate binding per button), polling rate (125/500/1000 Hz), idle timeout (60–900 sec), and profile CRUD. **CRC validation**: response packets verified via XOR checksum + transaction ID. **Sister slot** links Razer profiles to Joy-Con slots.
- **Help**: comprehensive setup & usage guide with 15 collapsible sections — project overview, hardware requirements, wiring diagrams, pinout image (scrollable `pinouts.png`), firmware installation walkthrough, first end-to-end test procedure, app usage guide (all tabs), default key mapping reference, serial protocol summary, mouse configuration guide, OTA firmware updates, troubleshooting, app install/update instructions, settings & system tray guide, and a quick reference card. Includes a search bar that filters sections by keyword.

### First-time firmware flashing

First-time flashing uses the **[Web Flasher](https://smokydastona.github.io/joycon-to-keyboard/)** — a browser-based tool (Chrome/Edge) that programs blank boards directly over USB with no toolchain required.

- Open the Diagnostics tab → **"Open Web Flasher"** button to launch it.
- Flash the ESP32 host first, then let the page flash the ESP32-S3 through the already-wired host bridge.
- The host-assisted flow expects the extra installer wires from `docs/wiring.md`: `GPIO21` -> Nano `B1 / GPIO0` and `GPIO22` -> Nano `RESET`.
- The Web Flasher still includes a direct Nano fallback for recovery.
- After first-time flash, future updates use the **OTA** path in the Diagnostics tab (no download mode needed).

The Mapping view's Joy-Con canvas switches between four states based on BT status: disconnected (`joycons-none.png`), left only, right only, and both connected.

The UI is built with **PyQt6** using a sidebar navigation layout with 7 sections (Dashboard, Mapping, Macros & Stick, Profiles, Devices, Diagnostics, Help). A permanent ↑ Update button and the light/dark theme toggle sit in the toolbar, and both header icons are intentionally oversized for quick access.

### System tray & background mode

Bind Bandit places a **system tray icon** (Windows notification area) on launch. Features:

- **Minimize to tray**: when enabled in Settings, closing the window hides it to the tray instead of quitting. The app keeps running in the background.
- **Start minimized**: launch the app hidden to the tray (no main window). Also available via `--minimized` CLI flag.
- **Start with Windows**: registers the app to run automatically on login (HKCU Run registry key).
- **Tray context menu**: right-click the tray icon for Show/Hide, **Profiles ►** (switch active slot), **Toggle Overlay**, **Auto-Switch** toggle, Settings, and Quit.
- **Double-click** the tray icon to toggle window visibility.

### Polished UX features

- **Visual Macro Builder**: drag-to-reorder step list with inline key/delay editing, plus a raw JSON toggle for advanced users.
- **App Auto-Switch Table**: browse for `.exe` files or detect the active app, assign each to a profile slot — all in a clean table layout.
- **First-Run Onboarding Wizard**: 5-page guided setup on first launch (USB connection, controller pairing, input test). Re-run from Settings → Developer.
- **Enhanced Overlay**: shows profile name, layer, and turbo state. Right-click for opacity presets and compact mode; double-click toggles compact.
- **Centralized Settings Dialog**: 4-tab dialog (General, Overlay, Theme, Developer) replaces the old simple checkbox list.
- **Toast Notifications**: non-blocking slide-in alerts for connect/disconnect and quick warnings — click to dismiss.
- **Comprehensive Tooltips**: every toolbar button, dropdown, and control has a descriptive tooltip.

## UI pack

Design artifacts (mockup/background/theme/generator/bundle example/layout snippet/architecture diagram):

- `docs/ui/README.md`

## Install

Create a venv (recommended) and install deps:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python -m joycon_helper
```

## Build a Windows `.exe`

Install the build-time dependency set and generate the UI bundle first:

```powershell
pip install -r requirements-build.txt
python ..\tools\generate_ui_artifacts.py
python ..\tools\versioning.py write-pyinstaller-version-file --repo-version ..\version.json --output build\pyinstaller-version-info.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name BindBandit joycon_helper\__main__.py --paths . --distpath dist --workpath build --add-data "..\.\.ui-bundle;.ui-bundle" --add-data "..\.\.ui-bundle-dark;.ui-bundle-dark" --version-file build\pyinstaller-version-info.txt --hidden-import serial.tools.list_ports_windows
```

The executable is written to `helper-app\dist\BindBandit.exe`.

The repo version in `..\version.json` increments on each commit. CI adds the push/run number on top of that when it builds the downloadable `.exe` artifact.

On GitHub, `.github/workflows/build-release-bundle.yml` builds that executable and bundles it together with both firmware outputs into one downloadable artifact.

## Protocol

This app assumes the device understands **newline-delimited JSON** commands and may emit newline-delimited JSON events.
See `protocol.md`.

## Logging

The helper app writes structured logs to disk for debugging.

| Folder | Contents |
|---|---|
| `logs/` | Daily rotating application log (`helper.log`). Records serial traffic, OTA activity, retries/timeouts, errors, theme loading, and connect/disconnect events. Failed firmware flashes also write `ota_failure_*.json` reports here with board, stage, offset, and recent serial history. Log output is sanitized before writing to disk. |
| `crash-logs/` | Timestamped crash dumps (`crash_YYYYMMDD_HHMMSS.log`) written on unhandled exceptions. Crash reports are sanitized before being saved. |

Both folders are created inside the same Bind Bandit app-data root that stores device cache, saved profiles, and session state:

- Windows: `%APPDATA%\\BindBandit\\`
- Linux/macOS: `~/.config/BindBandit/`

Older installs that wrote logs next to the `.exe` or `helper-app/` folder are migrated into this app-data location on startup.

- **Auto-cleanup**: files older than 15 days are deleted on each startup.
- **No personal data**: logs contain only application-level events (serial traffic, errors, platform info). No user paths, environment variables, or identifying data are recorded.
- **Anonymized debug bundle**: Settings → Export Anonymized Debug Bundle writes a ZIP with sanitized settings, profile state, diagnostics, application logs, crash logs, and a prebuilt GitHub issue summary.
- **GitHub issue flow**: Settings → Open GitHub Debug Issue creates the same anonymized bundle, then opens the repo's dedicated debug-report issue template with the generated summary prefilled so the user can choose whether to submit it.

## Auto-update

When running as a packaged `.exe`, the app checks the [GitHub Releases](https://github.com/smokydastona/joycon-to-keyboard/releases) for a newer version on startup.

- The toolbar always shows an ↑ Update button next to the theme toggle.
- If an update is available, the ↑ button blinks until you click it.
- Clicking ↑ with no cached update performs an immediate check. If a release is found, the normal install flow starts right away; otherwise the app shows an up-to-date popup.
- Clicking ↑ when an update is already known downloads the new `.exe`, swaps it in place, and relaunches the app automatically.
- After relaunch, the app blocks normal use and auto-connects to the ESP32-S3 bridge so it can flash both boards to the matching release firmware before continuing.
- The post-relaunch firmware stage is mandatory: it shows a non-closeable progress popup and retries automatically until flashing completes.
- When running from source (not frozen), only a notification is shown — no auto-install.
- The check uses an unauthenticated GET to the public GitHub API. No personal data is sent.
