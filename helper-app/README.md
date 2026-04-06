# Bind Bandit (Windows, Python + Tkinter)

Bind Bandit is a standalone desktop app for configuring gaming peripherals. **No specific hardware is required to launch it** — use whichever features match your setup:

| Use case | What you need | Tabs you'll use |
|---|---|---|
| **Joy-Con → keyboard bridge** | ESP32 + ESP32-S3 boards (flashed) | Loadout, Controller, Tricks, Stick, Overlay, Input Test |
| **M913 mouse configuration** | Redragon M913 mouse (USB) | Mouse |
| **Razer mouse configuration** | Razer Basilisk X HyperSpeed (USB) | Razer |
| **Both** | All of the above | All tabs |

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
- **DPI stages**: read/write up to 5 DPI stages (X/Y independent), active stage selector
- **Polling rate**: 125 / 500 / 1000 Hz
- **Idle/sleep timeout**: 60–900 seconds
- **Button remapping**: remap all 7 buttons (left, right, middle, back, forward, scroll up/down) to keyboard keys, other mouse buttons, DPI cycle, or disable — **all stored on the mouse's onboard memory** (anti-cheat safe)
- **Firmware version** and **serial number** readback
- **Loadout system**: save/load/delete named loadouts, auto-link loadouts to specific devices
- Requires `hidapi` (`pip install hidapi`)

Current UI tabs:

- **Loadout**: JSON editor, load/save/validate; loadout rename/duplicate/reset-to-defaults buttons; **slot quick-select** (4 slot buttons with names for fast switching) and **safe mode** recovery button
- **Tricks**: trick list + step editor, optional record mode from incoming `mapped_key` events, and a small heist plan helper
- **Stick**: stores deadzone/curve settings into the loadout JSON (not applied by firmware yet unless analog data exists)
- **Share**: offline-only export/import of a compressed "loadout code" string
- **Overlay**: a safe always-on-top status window (no hooking/injection)
- **Controller**: 3-panel "Heist Table" layout — **Heist Library** (left, 4 loadout cards for one-click slot switching + Import/Export), **Controller Canvas** (center, dominant device diagram with hotspots), and **Heist Tools** (right, context-sensitive panel with current mapping + action buttons + Disguises mask quick-switch). Set target name substring and trigger BT scan/connect via the device (requires return UART wiring); includes a keymap editor with a **dominant device canvas** (the Joy-Con diagram fills the center panel) and **popup panels** for heist planning, masks, chords, and keyboard preview — opened via compact toolbar buttons:
  - **Unified click-to-steal**: click a controller hotspot to instantly enter case mode (if unbound) or steal mode (if bound) — press a key and you're done
  - **Right-click context menu**: Case, Steal, Reset to passthrough, Clear steal, or Disable on any hotspot
  - **Live input visualization**: hotspots light up green and pulse when the corresponding controller button is physically pressed
  - **Conflict detection + auto-fix**: hotspots that produce the same output key are highlighted red; a one-click auto-fix button resolves duplicates
  - **Color-coded hotspots**: green = active, red = conflict, blue = selected; custom mappings use the user's chosen rainbow colour (default violet)
  - **Rainbow colour picker**: 🎨 dropdown in the toolbar — choose from red, orange, yellow, green, blue, indigo, or violet for hotspot highlights
  - **Mask system**: select Base or Mask 1–4 to edit overlay heist plans; masks are activated by holding/toggling a controller button
  - **Tap-hold heist plan**: a single button can produce different actions for quick tap vs long hold
  - **Double-tap heist plan**: single-tap sends one key, quick double-tap sends another (configurable timeout)
  - **Chording**: define multi-button combos that trigger a single action when pressed simultaneously
  - Case mode, clear steal, and reset-to-passthrough
  - **Undo / Redo** (Ctrl+Z / Ctrl+Y): up to 50 levels of loadout change history
  - **Guided Setup wizard**: step-by-step walkthrough that auto-steals WASD/Space/Shift/Ctrl by pressing controller buttons
  - **Calibration wizard**: 3-step guided stick calibration (center, sweep edges, save/clear) with quick deadzone/curve adjustment
  - **Intent-based heist plan**: right-click → "What should this button do?" with 14 common game actions
  - **Quick Job**: auto-applies sensible WASD heist plans when a controller connects and loadout is empty
  - **Smart Search**: filter hotspots by name, output, or heist plan type with highlighted matches on the diagram
  - **Practice Run**: temporary playground mode — try changes without saving, then keep or discard
  - **Ghost labels**: hover over the diagram to see faint tooltips with hotspot name and current mapping
  - **Hover glow**: a hand-drawn ink ring highlights hotspots as you move the mouse over the diagram
  - **Steal overlay + ink stamp**: a floating card shows during press-to-steal, and an expanding ring with STOLEN confirms a successful steal
  - **Visual mask stack**: badges below the mask selector showing each mask's name, mode, and heist plan count
  - **Mask tab bar**: visible sketch-style tabs below the controller diagram for quick mask switching
  - **Inline Trick Builder**: the Heist Tools panel includes a toggleable trick editor — pick or create tricks, add/remove key and delay steps, and assign directly to the selected hotspot without leaving the Controller tab
  - **Explain heist plan**: right-click → full input→output chain dialog showing conflicts and mask overrides
  - **Lock critical inputs**: prevent accidental unstealing with a right-click lock; locked buttons require confirmation
  - **Restore last config**: revert to the last loadout successfully written to the device if something goes wrong
  - **Feedback sounds**: optional Windows beep on steal/unsteal/undo for tactile feedback
  - **Adaptive UI**: toggle between Simple and Advanced modes; Simple hides masks, chords, tricks tabs
  - **Mode indicator**: always-visible status bar showing slot, mask, mode, practice run, and undo depth
- **Input Test**: live event log showing controller button presses/releases with timestamps, a summary of currently active keys, a **visual event timeline** showing the last 5 seconds of input events as colored marks, and an optional **latency profiling** display (toggle checkbox) showing real-time redraw and input processing stats
- **Status bar diagnostics**: BT signal strength (RSSI with signal bars), round-trip latency (auto-pinged every 10 s), battery level
- **Community presets**: 5 built-in profiles (FPS/Shooter, Platformer, RPG/Action, Minecraft, Racing) for one-click setup
- **Mouse** (M913 Impact Elite): configure Redragon M913 mice over USB HID — the tab shows a **dominant M913 device canvas** (fills available space for easy button selection) with controls in **popup panels**: button remapping (16 buttons), DPI (5 slots, 100–16000), LED modes, polling rate — each opened via toolbar buttons. Supports **multiple mice** simultaneously with independent loadouts. **Sister loadouts** link M913 configs to Joy-Con slots so mouse and controller settings travel together. All settings are written to the mouse's onboard memory (anti-cheat safe). **Layout mode** selector lets users switch between "Stock M913" (Side 1–12) and "IncediusMod" (Thumb 1–6 / Finger 1–6) button labels for the [Incedius M913 physical mod](https://www.printables.com/model/1191307-red-dragon-m913-mod). Because each IncediusMod rewiring is unique, the **"Edit Heist Plan…"** button lets users reassign which M913 side button corresponds to each Thumb/Finger position (saved per-loadout, with duplicate detection). The tab displays a sketchbook-ink M913 overlay image that switches between connected and disconnected states (matching the Joy-Con overlay style). Requires `hidapi` (`pip install hidapi`).
- **Razer** (Basilisk X HyperSpeed): configure Razer mice over USB HID Feature Reports — **dominant device canvas** with compact toolbar and **popup panels** for DPI stages (5 levels, X/Y independent), button remapping, polling rate, idle timeout, and loadouts.
- **Help**: comprehensive setup & usage guide with 14 collapsible sections — project overview, hardware requirements, wiring diagrams, pinout image (scrollable `pinouts.png`), firmware installation walkthrough, first end-to-end test procedure, app usage guide (all tabs), default key mapping reference, serial protocol summary, mouse configuration guide, OTA firmware updates, troubleshooting, app install/update instructions, and a quick reference card. Includes a search bar that filters sections by keyword.

### First-time firmware flashing (no ESP-IDF needed)

The app includes a built-in **esptool** integration for flashing brand-new/blank boards:

- **"Download & flash latest"**: auto-detects the connected chip (ESP32 or ESP32-S3), downloads the latest firmware from GitHub Releases, erases flash, and writes everything in one click.
- **"Flash files…"**: pick local `.bin` file(s) — the app auto-classifies bootloader, partition table, and app binary by filename.
- Boards must be in **download mode** (hold BOOT + press RESET, then release BOOT) for initial flashing. Some boards auto-enter download mode via USB.
- After first-time flash, future updates can use the **OTA** path (no download mode needed).

The Controller tab keymap artwork switches between four Joy-Con states based on BT status: disconnected (`joycons-none.png`), left only, right only, and both connected. The Mouse tab displays an M913 overlay that switches between connected (`m913.png`) and disconnected (`m913-none.png`) states based on device scan results.

The app displays a **full-window background image** (`background.png` / `background-dark.png`) behind all content, automatically selected based on the active theme (light/dark). The image scales to cover the window on resize using Pillow.

The UI uses heist/thief themed terminology throughout: Loadouts (profiles), Masks (layers), Tricks (macros), Heist Plans (mappings), Steal (bind), Case (learn), Execute (apply), Practice Run (sandbox), and Quick Job (defaults).

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
| `logs/` | Daily rotating application log (`helper.log`). Records serial traffic, errors, theme loading, connect/disconnect events. |
| `crash-logs/` | Timestamped crash dumps (`crash_YYYYMMDD_HHMMSS.log`) written on unhandled exceptions. |

Both folders are created next to the installed application (next to the `.exe` when frozen, or next to the `helper-app/` package when running from source).

- **Auto-cleanup**: files older than 15 days are deleted on each startup.
- **No personal data**: logs contain only application-level events (serial traffic, errors, platform info). No user paths, environment variables, or identifying data are recorded.

## Auto-update

When running as a packaged `.exe`, the app checks the [GitHub Releases](https://github.com/smokydastona/joycon-to-keyboard/releases) for a newer version on startup.

- If an update is available, the version label in the sidebar changes to **"Update to X.Y.Z"**.
- Clicking updates downloads the new `.exe`, swaps it in place, and prompts you to restart.
- When running from source (not frozen), only a notification is shown — no auto-install.
- The check uses an unauthenticated GET to the public GitHub API. No personal data is sent.
