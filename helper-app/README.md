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

- **Profile**: JSON editor, load/save/validate
- **Macros**: macro list + step editor, optional record mode from incoming `mapped_key` events, and a small mapping helper
- **Stick**: stores deadzone/curve settings into the profile JSON (not applied by firmware yet unless analog data exists)
- **Share**: offline-only export/import of a compressed “profile code” string
- **Overlay**: a safe always-on-top status window (no hooking/injection)
- **Controller**: set target name substring and trigger BT scan/connect via the device (requires return UART wiring); includes a keymap editor that lets you bind controller hotspots to observed input `key_id`s (Learn) and edit the mapping

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
python -m PyInstaller --noconfirm --clean --onefile --windowed --name JoyConBridgeHelper joycon_helper\__main__.py --paths . --distpath dist --workpath build --add-data "..\.ui-bundle;.ui-bundle" --version-file build\pyinstaller-version-info.txt --hidden-import serial.tools.list_ports_windows
```

The executable is written to `helper-app\dist\JoyConBridgeHelper.exe`.

The repo version in `..\version.json` increments on each commit. CI adds the push/run number on top of that when it builds the downloadable `.exe` artifact.

On GitHub, `.github/workflows/build-release-bundle.yml` builds that executable and bundles it together with both firmware outputs into one downloadable artifact.

## Protocol

This app assumes the device understands **newline-delimited JSON** commands and may emit newline-delimited JSON events.
See `protocol.md`.
