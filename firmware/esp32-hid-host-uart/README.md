# esp32-hid-host-uart

ESP-IDF app that acts as a **Bluetooth HID Host** and forwards key events over UART to the USB-keyboard-side device.

For full setup instructions:

- `docs/wiring.md` (one-USB dongle wiring + power)
- `docs/firmware-install.md` (Windows flashing guide for both boards)

## Reality check (important)

- Joy-Cons commonly use **Bluetooth Classic HID**.
- ESP32 (original) supports Bluetooth Classic.
- ESP32-S3 is often used for BLE-only designs.

So: for the best chance of Joy-Con compatibility, use an **ESP32** variant that explicitly supports **Bluetooth Classic**.

## Configure which controller to connect to

By default, this firmware connects to devices whose Bluetooth name contains `Joy-Con`.

For Binbok / third-party controllers, set this in:

`idf.py menuconfig` → `Bind Bandit (ESP32 Classic-BT Host)` → `Target device name substring`

Example values:

- `Binbok`
- `Pro Controller`

## Evidence-first report capture

To implement a correct mapper without guessing layouts:

- Enable logging (default): `Log HID input reports (on change)`
- Optionally forward reports over UART for offline capture: `Forward raw HID reports over UART (debug frames)`

## Build

Install ESP-IDF, then:

```powershell
idf.py set-target esp32
idf.py menuconfig
idf.py build
idf.py flash monitor
```

Tip: during development you’ll typically flash this ESP32 over its own USB. In the final “one custom USB dongle” build, this ESP32 is powered from the ESP32-S3’s USB 5V via `VIN/5V`.
## OTA firmware updates

This firmware uses an **A/B OTA partition layout** (`partitions.csv`). The helper app can push new firmware to this board via UART (relayed through the ESP32-S3), so both boards can be updated from a single USB connection.

### Integrity & rollback

- Downloaded firmware is verified against **SHA-256** checksums when available.
- **Rollback protection** is enabled (`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`). After an OTA update, the new firmware must call `fw_ota_mark_valid()` early in `app_main` — if it crashes before doing so, the bootloader automatically reverts to the previous partition.

OTA control commands and response frames are documented in `docs/serial-protocol.md`.
## UART (default)

- Baud: 921600
- TX pin: GPIO 17
- RX pin: GPIO 16 (optional helper-app control)

Set in `main/config.h`.

## What this firmware does today

- Initializes UART framing to match `docs/serial-protocol.md`.
- Scans + connects to a Classic-BT HID device and forwards input reports to `main/joycon_mapper.c`.
- Optionally accepts helper-app control commands over UART RX (requires the return UART wire).
- **Joy-Con setup FSM** (`joycon_setup.c`): after BT connection, sends subcommands to the Joy-Con — request device info, read SPI flash calibration, set full report mode (0x30), enable IMU, enable vibration, set player LEDs. This replaces the passive wait-for-reports approach with an active handshake.
- **SPI flash stick calibration**: reads factory and user calibration data from the Joy-Con's SPI flash. Sticks are accurate immediately after connection (no warm-up needed).
- **Controller type detection**: identifies Joy-Con (L), Joy-Con (R), or Pro Controller from the device info reply.
- **Serial number readback**: reads the controller serial number from SPI flash (0x6000).
- **Controller colors**: reads body and button RGB colors from SPI flash (0x6050).
- **Stick deadzone parameters**: reads deadzone and range ratio from SPI flash (0x6086).
- **IMU calibration**: reads factory (0x6020) and user (0x8026) accelerometer/gyroscope calibration data.
- **Controller info broadcast**: sends all discovered controller metadata (type, serial, colors, stick params, IMU cal) to the ESP32-S3 via UART marker `0xF9`.
- **Battery level reporting**: parses battery level (0–4) from 0x30 reports and forwards to the ESP32-S3 via UART marker `0xFA`.
- **HD Rumble**: accepts rumble commands from the helper app (frequency 41–1253 Hz, amplitude 0–100%). Full log2-based frequency/amplitude encoding per Nintendo specification.
- **Home LED control**: accepts brightness commands (0–15) for the Home button LED (right Joy-Con / Pro Controller only).
- **Player LED control**: sets Player 1 LEDs on the Joy-Con after setup completes.
- **BT RSSI polling**: periodically reads Bluetooth RSSI (every 5 s) for connected devices and forwards to the ESP32-S3 via UART marker `0xF8`.
- **BT auto-reconnect**: on disconnect, automatically attempts to reconnect with exponential backoff (2 s → 4 s → 8 s). Configurable via Kconfig (`JOYCON_HOST_AUTO_RECONNECT`, `JOYCON_HOST_AUTO_RECONNECT_MAX_RETRIES`). Falls back to discovery after max retries.
- **Nintendo 0x30 button + stick parsing** (when enabled via menuconfig): fully parses all Joy-Con buttons (A/B/X/Y, L/R, ZL/ZR, Plus/Minus, Home, Capture, stick clicks) and both sticks.
- **Stick auto-calibration**: per-axis min/center/max tracking adapts to individual controller characteristics. SPI flash calibration is preferred when available.
- **SOCD cleaning**: three modes (neutral / last-input / first-input) for simultaneous opposing cardinal direction handling. Configurable at runtime via UART control command or profile JSON.
- **Rapid trigger (stick hysteresis)**: separate activation/deactivation thresholds prevent flickering at the deadzone boundary. Configurable at runtime.
- **Analog stick data forwarding**: sends raw normalized stick values (±4096) over UART (marker `0xF7`) for mouse/scroll/sprint-zone on the USB side. Left stick = device_id `0x00`, right stick = device_id `0x80`.
- **35 key_ids**: all Joy-Con inputs (left stick WASD, face buttons, shoulders, triggers, system buttons, stick clicks, right stick directions, motion gestures, SL/SR rail buttons) are mapped to unique key_ids (1–35) and emitted over UART.

Next step is to capture real reports and verify the correct mappings in `main/joycon_mapper.c`.
