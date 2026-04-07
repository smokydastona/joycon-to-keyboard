# esp32s3-usb-kbd (Arduino Nano ESP32 / ESP32-S3)

Use an **ESP32-S3** board (like Arduino Nano ESP32) as the **USB HID keyboard** device.
It reads UART frames from the Joy-Con receiver (a Classic-BT-capable board) and sends real USB keyboard reports to the PC.

This firmware also exposes a **USB CDC-ACM serial interface (COM port)** so the desktop helper app can upload/read profiles and monitor events.

## Why this exists

Your Arduino Nano ESP32 is an **ESP32-S3** (u-blox NORA-W106 module). That makes it a great fit for the **PC-facing keyboard** side.

However, Joy-Cons commonly require **Bluetooth Classic HID host** to connect wirelessly.
ESP32-S3 is not the safest choice for that part.

So the practical setup is:

- Joy-Con (wireless) → **ESP32 (Classic BT capable)** → UART → **ESP32-S3 (USB keyboard)** → PC

For full setup instructions:

- `docs/wiring.md` (one-USB dongle wiring + power)
- `docs/firmware-install.md` (Windows flashing guide for both boards)

## Build / flash

Install ESP-IDF, then:

```powershell
idf.py set-target esp32s3
idf.py build
idf.py flash monitor
```

### VS Code IntelliSense (includePath squiggles)

If VS Code shows `#include errors detected` in C files, build once so ESP-IDF generates:

- `firmware/esp32s3-usb-kbd/build/compile_commands.json`

Then reload VS Code. The workspace includes a `.vscode/settings.json` that points the C/C++ extension at that file.

## Helper app (USB serial)

When plugged into Windows, the board should enumerate as:

- a USB keyboard (HID)
- a USB serial device (CDC-ACM → COM port)

The serial protocol is NDJSON (one JSON object per line). See:

- `helper-app/protocol.md`

If you wire the *return UART* line (ESP32-S3 TX → ESP32 RX), the helper app can also send BT control commands (set target substring + trigger scan/connect) and receive BT status events.

The ESP32-S3 also forwards **battery level** events from the ESP32 BT host as `{"evt":"battery","device_id":N,"level":N}` NDJSON events over CDC serial.

The ESP32-S3 also forwards **controller info** events (type, serial, colors, stick params, IMU calibration) as `{"evt":"controller_info",...}` NDJSON events. The helper app receives these to display controller details, color swatches, and calibration data.

The helper app can also send **rumble** and **home LED** commands, which are forwarded via UART to the ESP32 BT host.

The ESP32-S3 also forwards **RSSI** (Bluetooth signal strength) events as `{"evt":"rssi","device_id":N,"rssi":N}` NDJSON events, polled every 5 seconds per connected device.

## UART settings

Configured via `menuconfig`:

- `Bridge UART TX GPIO`
- `Bridge UART RX GPIO`
- `Bridge UART baud`

On the Arduino Nano ESP32 you’ll likely wire UART to the header pins, then set the matching **GPIO numbers** in menuconfig.

## OTA firmware updates

This firmware uses an **A/B OTA partition layout** (`partitions.csv`). The helper app can flash new firmware over the USB CDC serial link (no need to re-flash manually with `idf.py`).

The same mechanism also relays OTA data to the ESP32 side over UART, so both boards can be updated from a single USB connection.

### Integrity & rollback

- Downloaded firmware is verified against **SHA-256** checksums (`sha256sums.txt` in the GitHub release) when available.
- Downloads automatically **retry up to 3 times** with exponential backoff on network errors.
- **Rollback protection** is enabled (`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`). After an OTA update, the new firmware must call `fw_ota_mark_valid()` early in `app_main` — if it crashes before doing so, the bootloader automatically reverts to the previous partition.
- Users can also **flash local `.bin` files** from the helper app UI ("Flash from file…" button).

See `helper-app/protocol.md` (firmware OTA commands) and `docs/serial-protocol.md` (OTA UART frames).

## Mapping

The key IDs are the same as in `docs/keymap.md`.

The profile system supports these mapping modes:

- **passthrough** — looks up the incoming key_id in the compiled `keymap.c` table (WASD + modifiers)
- **remap** — remaps one key_id to another, then uses `keymap.c`
- **remap_hid** — bypasses `keymap.c` entirely, sending an arbitrary USB HID modifier + keycode
- **macro** — triggers a macro sequence
- **disable** — silently drops the input
- **double_tap** — single tap sends one key, quick double-tap sends another
- **turbo** — rapid-fire auto-repeat while held (configurable interval)
- **sticky** — toggle key: first press activates, second press deactivates
- **tap_hold** — different actions for quick tap vs long hold
- **oneshot** — one-shot modifier: arms on press, applies to the next key, then auto-releases
- **chords** — multi-button combos that fire a single action when pressed simultaneously

### Timing humanization

Macros and turbo repeat use random jitter (±15% on macro delays, ±10% on turbo intervals) to avoid perfectly regular patterns detectable by anti-cheat. Controlled by the profile `"humanize"` field (default true) or the `set_humanize` serial command.

### Layers

Profiles may include up to 4 **overlay layers**. Each layer is activated by a controller button (hold or toggle mode). While active, a layer's sparse mapping overrides replace the base mappings for the listed key_ids; unlisted keys fall through to the base. See `helper-app/protocol.md` for the JSON schema.

### Chords

Profiles may include up to 8 **chord combos**. Each chord defines 2–4 keys that, when pressed simultaneously, fire a single action (and suppress the individual key mappings). Chords are evaluated before individual mappings. See `helper-app/protocol.md` for the JSON schema.
