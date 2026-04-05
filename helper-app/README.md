# Bind Bandit (Windows, Python + Tkinter)

Bind Bandit is a standalone desktop app for configuring gaming peripherals. **No specific hardware is required to launch it** — use whichever features match your setup:

| Use case | What you need | Tabs you'll use |
|---|---|---|
| **Joy-Con → keyboard bridge** | ESP32 + ESP32-S3 boards (flashed) | Profile, Controller, Macros, Stick, Overlay, Input Test |
| **M913 mouse configuration** | Redragon M913 mouse (USB) | Mouse |
| **Both** | All of the above | All tabs |

### Joy-Con bridge features (requires ESP32-S3 serial connection)

The bridge talks over a **serial (COM) port** provided by the **ESP32-S3 USB keyboard firmware** (USB CDC-ACM). If you haven't flashed the ESP32-S3 yet, start with `docs/firmware-install.md`.

- Select a COM port and connect
- View live text/JSON coming from the device
- Upload a profile JSON (slot 0–3)
- Set the active profile slot
- One-click "Upload + Activate" for the selected slot

### M913 mouse features (no serial connection needed)

The Mouse tab communicates directly with Redragon M913 mice over USB HID (`hidapi`). No ESP32 hardware or COM port is needed — just plug in the mouse.

Current UI tabs:

- **Profile**: JSON editor, load/save/validate; profile rename/duplicate/reset-to-defaults buttons; **slot quick-select** (4 slot buttons with names for fast switching) and **safe mode** recovery button
- **Macros**: macro list + step editor, optional record mode from incoming `mapped_key` events, and a small mapping helper
- **Stick**: stores deadzone/curve settings into the profile JSON (not applied by firmware yet unless analog data exists)
- **Share**: offline-only export/import of a compressed "profile code" string
- **Overlay**: a safe always-on-top status window (no hooking/injection)
- **Controller**: set target name substring and trigger BT scan/connect via the device (requires return UART wiring); includes a keymap editor with:
  - **Unified click-to-bind**: click a controller hotspot to instantly enter learn mode (if unbound) or bind mode (if bound) — press a key and you're done
  - **Right-click context menu**: Learn, Bind, Reset to passthrough, Clear binding, or Disable on any hotspot
  - **Live input visualization**: hotspots light up green and pulse when the corresponding controller button is physically pressed
  - **Conflict detection + auto-fix**: hotspots that produce the same output key are highlighted red; a one-click auto-fix button resolves duplicates
  - **Color-coded hotspots**: green = active, red = conflict, blue = selected, yellow = has custom mapping
  - **Layer system**: select Base or Layer 1–4 to edit overlay mappings; layers are activated by holding/toggling a controller button
  - **Tap-hold mapping**: a single button can produce different actions for quick tap vs long hold
  - **Chording**: define multi-button combos that trigger a single action when pressed simultaneously
  - Learn mode, clear binding, and reset-to-passthrough
  - **Undo / Redo** (Ctrl+Z / Ctrl+Y): up to 50 levels of profile change history
  - **Guided Setup wizard**: step-by-step walkthrough that auto-binds WASD/Space/Shift/Ctrl by pressing controller buttons
  - **Intent-based mapping**: right-click → "What should this button do?" with 14 common game actions
  - **Smart Defaults**: auto-applies sensible WASD mappings when a controller connects and profile is empty
  - **Smart Search**: filter hotspots by name, output, or mapping type with highlighted matches on the diagram
  - **Sandbox mode**: temporary playground mode — try changes without saving, then keep or discard
  - **Ghost labels**: hover over the diagram to see faint tooltips with hotspot name and current mapping
  - **Visual layer stack**: badges below the layer selector showing each layer's name, mode, and mapping count
  - **Explain mapping**: right-click → full input→output chain dialog showing conflicts and layer overrides
  - **Lock critical inputs**: prevent accidental unbinding with a right-click lock; locked buttons require confirmation
  - **Feedback sounds**: optional Windows beep on bind/unbind/undo for tactile feedback
  - **Adaptive UI**: toggle between Simple and Advanced modes; Simple hides layers, chords, macros tabs
  - **Mode indicator**: always-visible status bar showing slot, layer, mode, sandbox, and undo depth
- **Input Test**: live event log showing controller button presses/releases with timestamps, a summary of currently active keys, a **visual event timeline** showing the last 5 seconds of input events as colored marks, and an optional **latency profiling** display (toggle checkbox) showing real-time redraw and input processing stats
- **Mouse** (M913 Impact Elite): configure Redragon M913 mice over USB HID — button remapping (16 buttons), DPI (5 slots, 100–16000), LED modes, polling rate. Supports **multiple mice** simultaneously with independent profiles. **Sister profiles** link M913 configs to Joy-Con slots so mouse and controller settings travel together. All settings are written to the mouse's onboard memory (anti-cheat safe). **Layout mode** selector lets users switch between "Stock M913" (Side 1–12) and "IncediusMod" (Thumb 1–6 / Finger 1–6) button labels for the [Incedius M913 physical mod](https://www.printables.com/model/1191307-red-dragon-m913-mod). Because each IncediusMod rewiring is unique, the **"Edit Map…"** button lets users reassign which M913 side button corresponds to each Thumb/Finger position (saved per-profile, with duplicate detection). The tab displays a sketchbook-ink M913 overlay image that switches between connected and disconnected states (matching the Joy-Con overlay style). Requires `hidapi` (`pip install hidapi`).
- **Help**: scrollable board pinout reference diagram (`pinouts.png`) for the Arduino Nano ESP32-S3 and NodeMCU ESP32-WROOM-32.

The Controller tab keymap artwork switches between four Joy-Con states based on BT status: disconnected (`joycons-none.png`), left only, right only, and both connected. The Mouse tab displays an M913 overlay that switches between connected (`m913.png`) and disconnected (`m913-none.png`) states based on device scan results.

The app displays a **full-window background image** (`background.png` / `background-dark.png`) behind all content, automatically selected based on the active theme (light/dark). The image scales to cover the window on resize using Pillow.

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
