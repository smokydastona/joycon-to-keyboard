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

`idf.py menuconfig` → `JoyCon Bridge (ESP32 Classic-BT Host)` → `Target device name substring`

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

## UART (default)

- Baud: 115200
- TX pin: GPIO 17
- RX pin: GPIO 16 (unused)

Set in `main/config.h`.

## What this firmware does today

- Initializes UART framing to match `docs/serial-protocol.md`.
- Contains a stub that can be wired to a HID input callback.

Next step is to implement Joy-Con report parsing in `main/joycon_parser.c`.
