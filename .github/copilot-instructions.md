# Copilot Instructions — Joy-Con → Hardware Keyboard Bridge

This repo is an **anti-cheat-safe hardware input bridge**:

- Wireless controller side (Joy-Con / compatible) connects to a **Bluetooth Classic capable ESP32** (host).
- It outputs a tiny **UART key event protocol**.
- An **ESP32-S3 USB-device board** turns those events into a **real USB HID keyboard** as seen by the PC.

Non-negotiables:

- The PC must see a **real hardware keyboard** (USB HID), not a virtual driver / injected input.
- Be “truth-first”: do not assume Joy-Con is BLE HID-over-GATT unless proven (see `docs/ble-hid-check.md`).

## Where things live

- `firmware/esp32-hid-host-uart/` — ESP32 Bluetooth HID host → UART framing
- `firmware/esp32s3-usb-kbd/` — ESP32-S3 USB HID keyboard + USB CDC serial (UART → HID + helper COM port)
- `helper-app/` — Python + Tkinter helper app (serial UI)
- `docs/` — wiring, protocols, keymap

## Protocols (do not break casually)

- UART framing is documented in `docs/serial-protocol.md`.
  - Any changes must update both ends (ESP32 sender + ESP32-S3 receiver) and the doc.
- Helper-app serial protocol is documented in `helper-app/protocol.md`.
  - Framing: NDJSON (one JSON object per line).
  - Prefer backward-compatible changes (add new fields/events; don’t rename existing fields without a transition).

## Firmware constraints / conventions

- USB side must remain a standards-compliant **HID keyboard** (boot keyboard report is fine).
- If you touch TinyUSB descriptors/endpoints, re-check the endpoint map and configuration total length.
- VID/PID values may be placeholders in dev; do not claim production compliance.
- Keep host-side (ESP32) Joy-Con parsing conservative: do not “guess” report layouts; capture real bytes and implement based on evidence.

## Workflow After Every Code Change (STRICT)

After **any** code/resource/doc change, follow this exact workflow:

1) Scan all files first
   - Run workspace-wide diagnostics (VS Code Problems / `get_errors` across the repo).
   - Then do an “impact radius” scan (see checklists below).
   - Immediately update any relevant docs to match final behavior:
     - `README.md`
     - impacted firmware `README.md`
     - impacted `docs/*.md` / `helper-app/*.md`

2) Fix errors systematically
   - Don’t stop after fixing one file; iterate until diagnostics are clean for what you touched.

3) Re-validate after each fix
   - Re-run the diagnostics scan.
   - If behavior changed, refresh docs again.

4) Explain every change
   - State what was wrong, what changed, and why.

5) Version control discipline
  - Default: **after every change set**, make a commit and run `git push` (no tags/releases).
  - Only skip commit/push if the user explicitly asks you not to.
   - Do not commit generated outputs (`build/`, `.gradle/`, `managed_components/`, `.pio/`, etc.).

6) Only stop when shippable
   - Working tree clean and repo state consistent (docs match code).

### “Scan likely impact radius” (do this before committing)

Identify what the change touches and proactively scan the connected files that must stay consistent.

### Impact radius checklists

- USB descriptors / TinyUSB changes (`firmware/**/tusb_desc.c`, `sdkconfig.defaults`)
  - Verify endpoint numbers don’t collide.
  - Verify `CONFIG_TOTAL_LEN` matches descriptors.
  - Verify class enable flags exist for any new interfaces (CDC/HID/etc.).
  - Verify Windows enumeration expectations (HID keyboard + CDC ACM COM port when enabled).

- UART protocol changes (`docs/serial-protocol.md`, `firmware/esp32-hid-host-uart/**`, `firmware/*-usb-kbd/**`)
  - Ensure sender + receiver implement the same frame format.
  - Ensure checksums/length assumptions match.
  - Ensure key_id semantics remain stable or are versioned.

- Key mapping changes (`docs/keymap.md`, `firmware/**/keymap.*`)
  - Keep IDs stable if possible; if you change them, update docs and any mappers.
  - Confirm modifier/keycode mapping remains valid for HID boot keyboard.

- Helper app protocol changes (`helper-app/protocol.md`, `helper-app/joycon_helper/**`, `firmware/esp32s3-usb-kbd/main/bridge_serial.*`)
  - Ensure NDJSON framing remains one-object-per-line.
  - Ensure device tolerates unknown commands gracefully.
  - Ensure the helper app is tolerant of non-JSON lines (logs).

- Help tab content changes (`helper-app/joycon_helper/app.py` → `_build_help_tab`)
  - The Help tab is the **single source of truth** for end-user setup & usage docs inside the app.
  - Any change to wiring, pin assignments, firmware flash steps, key mappings, serial protocol, helper-app commands, OTA workflow, troubleshooting, or app install procedure **must** be reflected in the corresponding Help tab section.
  - Sections to check: What Is This?, What You Need, Wiring & Connections, Board Pinout Diagram, Firmware Installation, First End-to-End Test, Using Bind Bandit, Default Key Mapping, Serial Protocol, Mouse Configuration, OTA Firmware Updates, Troubleshooting, Installing / Updating the Helper App, Quick Reference.
  - Keep section count and order stable; add new sections at the end if needed.
  - Do not remove the search-filter feature.

## CI-first default (IMPORTANT)

- If CI exists in this repo, treat CI as the authoritative clean build.
- If CI does not exist (or isn’t configured yet), still keep the “push after commit” discipline when the user asks to ship/test.
- Do not create releases/tags automatically.

## Repo-specific behavior rules

- Never propose or implement software input injection / virtual HID drivers as the primary solution (anti-cheat constraint).
- Prefer evidence-based Bluetooth decisions:
  - Classic HID host for Joy-Con side unless BLE HID-over-GATT is proven.
- Keep changes minimal and reversible; avoid inventing new protocols when existing ones suffice.

## Common commands (reference)

- ESP32 (Classic BT host): `idf.py set-target esp32`, `idf.py menuconfig`, `idf.py build`, `idf.py flash monitor`
- ESP32-S3 (USB keyboard + CDC): `idf.py set-target esp32s3`, `idf.py build`, `idf.py flash monitor`
- Helper app: see `helper-app/README.md`

