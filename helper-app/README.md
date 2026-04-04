# Helper app (Windows, Python + Tkinter)

This helper app talks to the bridge over a **serial (COM) port**.

Minimum goals:

- Select a COM port and connect
- View live text/JSON coming from the device
- Upload a profile JSON (slot 0–3)
- Set the active profile slot

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
