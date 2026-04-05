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
- **Controller**: set target name substring and trigger BT scan/connect via the device (requires return UART wiring)

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

## Protocol

This app assumes the device understands **newline-delimited JSON** commands and may emit newline-delimited JSON events.
See `protocol.md`.
