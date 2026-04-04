# Arduino Nano ESP32 (ABX00083 / ESP32-S3) setup

You bought: **Arduino Nano ESP32 with Headers (ABX00083)**, which uses an **ESP32-S3** (u-blox NORA-W106).

## What this board is good for in this project

- ✅ **USB HID keyboard** to the PC (anti-cheat sees a normal keyboard)
- ✅ Wi‑Fi/BLE for other projects
- ⚠️ Not the best bet for **Joy‑Con wireless** (Joy‑Cons commonly need **Bluetooth Classic HID host**; some sources claim BLE, but treat that as unproven until tested)

So use this board as the **keyboard half**, not the Joy‑Con receiver half.

## Recommended wiring (minimum)

You only need 2 wires between the Joy‑Con receiver board and the Nano ESP32:

- Receiver **TX** → Nano ESP32 **RX0**
- Receiver **GND** → Nano ESP32 **GND**

That’s it. The Nano ESP32’s **TX1** pin is not required for this direction.

## Firmware to flash on the Nano ESP32

Use: `firmware/esp32s3-usb-kbd/`

Build target is `esp32s3`.

## Critical setting: RX0 is an Arduino pin label, ESP-IDF wants GPIO numbers

In ESP-IDF, `menuconfig` expects the **ESP32-S3 GPIO number**, not the silk-screen label.

Do this:

1) Open Arduino’s pinout PDF for Nano ESP32 (ABX00083) and find the row for **RX0**.
2) Note the **GPIO number** (it will be written as something like `GPIO44` / `GPIOxx`).
3) Set that value in:

`idf.py menuconfig` → `JoyCon Bridge (ESP32-S3 USB Keyboard)` → `Bridge UART RX GPIO`

Also set:
- `Bridge UART baud` to `115200`
- `UART port` to whichever UART you prefer (default `1` in this repo)

## If you paste the RX0 GPIO mapping

If you reply with just: `RX0 = GPIO__` (from the pinout PDF), I’ll update the repo defaults so you don’t have to.
