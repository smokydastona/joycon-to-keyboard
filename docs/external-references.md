# External references (how we use them)

This repo is intentionally **anti-cheat-safe**: the PC must see a **real USB HID keyboard** from hardware.
We do **not** rely on PC-side remappers/injectors.

Sometimes it’s useful to read other projects to learn *what to look for* in Joy-Con style HID reports.
This document explains what we can safely take from external projects and what we do **not** take.

## Projects

- https://github.com/Armag3ddonDev/joycon
- https://github.com/antimicroX/antimicroX
- https://github.com/Brikwerk/nxbt

## What we take (safe and useful)

### Concepts / workflows

- Evidence-first HID mapping workflow:
  - capture raw reports
  - press one control at a time
  - identify toggling bytes/bits
  - only then implement parsing/mapping

### Public protocol knowledge

- Common Nintendo-style report signatures (example: reports starting with `0x30` and length around 49 bytes).

We treat these only as **hints** and always verify against your captured bytes.

### UX ideas (helper app)

- Profile/mapping UI patterns (slots, remaps, macros)

## What we do NOT take

- We do not copy/paste source code.
- We do not import these repos as dependencies.
- We do not ship PC-side input injection/remapping as the primary solution.

## Where this repo uses these ideas

- `tools/analyze_hid_reports.py`: analyzes captured HID report streams to find the byte offsets that change most.
- `firmware/esp32-hid-host-uart/`: can optionally enable a **candidate parser** for a known Nintendo report signature.
  - It stays disabled by default.
  - If the report doesn’t match the signature, it does nothing.

## Next step

To make progress safely, capture reports first:

- Wire and flash the adapter (see `docs/wiring.md` and `docs/firmware-install.md`)
- Enable report logging and/or UART debug frames on the ESP32 host
- Capture a short sequence where you press ONE control at a time

Then we can implement the real mapper without guessing.
