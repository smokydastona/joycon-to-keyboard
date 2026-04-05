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

OTA control commands and response frames are documented in `docs/serial-protocol.md`.
## UART (default)

- Baud: 115200
- TX pin: GPIO 17
- RX pin: GPIO 16 (optional helper-app control)

Set in `main/config.h`.

## What this firmware does today

- Initializes UART framing to match `docs/serial-protocol.md`.
- Scans + connects to a Classic-BT HID device and forwards input reports to `main/joycon_mapper.c`.
- Optionally accepts helper-app control commands over UART RX (requires the return UART wire).

Next step is to capture real reports and implement correct mappings in `main/joycon_mapper.c`.
