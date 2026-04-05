# Helper app (Windows, Python + Tkinter)

This helper app talks to the bridge over a **serial (COM) port**.

That COM port is provided by the **ESP32-S3 USB keyboard firmware** (USB CDC-ACM). If you haven’t flashed the ESP32-S3 yet, start with:

- `docs/firmware-install.md`

Minimum goals:

- Select a COM port and connect
- View live text/JSON coming from the device
- Upload a profile JSON (slot 0–3)
- Set the active profile slot
- One-click "Upload + Activate" for the selected slot

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
- **Input Test**: live event log showing controller button presses/releases with timestamps, a summary of currently active keys, and a **visual event timeline** showing the last 5 seconds of input events as colored marks

The Controller tab keymap artwork switches between four Joy-Con states based on BT status: disconnected (`joycons-none.png`), left only, right only, and both connected.

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
python -m PyInstaller --noconfirm --clean --onefile --windowed --name JoyConBridgeHelper joycon_helper\__main__.py --paths . --distpath dist --workpath build --add-data "..\.ui-bundle;.ui-bundle" --add-data "..\.ui-bundle-dark;.ui-bundle-dark" --version-file build\pyinstaller-version-info.txt --hidden-import serial.tools.list_ports_windows
```

The executable is written to `helper-app\dist\JoyConBridgeHelper.exe`.

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
