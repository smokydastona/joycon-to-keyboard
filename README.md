# Joy-Con → Hardware Keyboard (anti-cheat safe)

This workspace contains firmware for a **two-chip adapter**:

- **ESP32 (Classic BT capable)** connects wirelessly to a Joy-Con and outputs a small, fixed **UART protocol**.
- **RP2040 (Raspberry Pi Pico / Pico W / RP2040-Zero)** receives UART and exposes a **USB HID keyboard** to the PC.

Alternative keyboard side:

- **ESP32-S3 (e.g. Arduino Nano ESP32)** can be used instead of the RP2040 for the **USB HID keyboard** role. See `firmware/esp32s3-usb-kbd/`.
  - It also exposes a **USB CDC-ACM serial (COM port)** for the `helper-app/` protocol.

If you have an Arduino Nano ESP32 (ABX00083): see `docs/arduino-nano-esp32-setup.md`.

Why two chips?
- Many boards that do USB HID well (RP2040, ESP32-S3) don’t also do **Bluetooth Classic HID host** well.
- Joy-Cons commonly pair as **Bluetooth Classic HID** devices.

> Truth / constraint: Some online threads claim “Joy-Con uses BLE so an ESP32-S3 can do everything in one chip”. I can’t rely on that without evidence. This repo targets an ESP32 variant that supports **Bluetooth Classic** for the Joy-Con side.

If you want to try a **one-chip ESP32-S3-only** build anyway, first prove that your controller exposes **BLE HID over GATT**: see `docs/ble-hid-check.md`. If it cannot, the two-chip design here is the practical route.

Before buying parts, read `docs/board-checklist.md`.

## Folder layout

- `firmware/pico-usb-kbd/` — RP2040 firmware (USB HID keyboard)
- `firmware/esp32-hid-host-uart/` — ESP32 firmware (HID host → UART)
- `tools/` — optional offline helpers (log decoding)
- `helper-app/` — optional PC helper (serial UI for profiles/logs)
- `docs/` — wiring + notes

## Hardware assumptions (default)

- Joy-Con connects **wirelessly** to ESP32 over Bluetooth.
- Adapter connects to PC via **one USB cable** (RP2040 → PC). This is what makes the PC see a normal hardware keyboard.

## Next

1) Build and flash RP2040 firmware: see `firmware/pico-usb-kbd/README.md`
2) Build and flash ESP32 firmware: see `firmware/esp32-hid-host-uart/README.md`
3) Edit key mapping in `docs/keymap.md` (then update the ESP32 mapping table)
