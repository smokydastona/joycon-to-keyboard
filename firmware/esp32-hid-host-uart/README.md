# esp32-hid-host-uart

ESP-IDF app that acts as a **Bluetooth HID Host** and forwards key events over UART to the USB-keyboard-side device.

## Reality check (important)

- Joy-Cons commonly use **Bluetooth Classic HID**.
- ESP32 (original) supports Bluetooth Classic.
- ESP32-S3 is often used for BLE-only designs.

So: for the best chance of Joy-Con compatibility, use an **ESP32** variant that explicitly supports **Bluetooth Classic**.

## Build

Install ESP-IDF, then:

```powershell
idf.py set-target esp32
idf.py menuconfig
idf.py build
idf.py flash monitor
```

## UART (default)

- Baud: 115200
- TX pin: GPIO 17
- RX pin: GPIO 16 (unused)

Set in `main/config.h`.

## What this firmware does today

- Initializes UART framing to match `docs/serial-protocol.md`.
- Contains a stub that can be wired to a HID input callback.

Next step is to implement Joy-Con report parsing in `main/joycon_parser.c`.
