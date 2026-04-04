# Arduino Nano ESP32 (ABX00083 / ESP32-S3) setup

You bought: **Arduino Nano ESP32 with Headers (ABX00083)**, which uses an **ESP32-S3** (u-blox NORA-W106).

## What this board is good for in this project

- ✅ **USB HID keyboard** to the PC (anti-cheat sees a normal keyboard)
- ✅ Wi‑Fi/BLE for other projects
- ⚠️ Not the best bet for **Joy‑Con wireless** (Joy‑Cons commonly need **Bluetooth Classic HID host**; some sources claim BLE, but treat that as unproven until tested)

So use this board as the **keyboard half**, not the Joy‑Con receiver half.

## Recommended wiring (minimum)

For UART data, you only need 2 wires between the Joy‑Con receiver board (ESP32 Classic-BT host) and the Nano ESP32-S3:

- Receiver **TX** → Nano ESP32 **RX0**
- Receiver **GND** → Nano ESP32 **GND**

That’s enough to test data flow if both boards are powered.

### If you want a single USB dongle (one plug powers everything)

For the “one custom USB dongle” build, the Nano ESP32-S3 is the only board that plugs into the PC.
In that case you also need a **power wire** from the Nano’s USB 5V to the ESP32 dev board:

- Nano `5V/VUSB` → ESP32 `VIN/5V`

Full detailed wiring (including power model and pin defaults): see `docs/wiring.md`.

## Firmware to flash on the Nano ESP32

Use: `firmware/esp32s3-usb-kbd/`

Build target is `esp32s3`.

## Critical setting: RX0 is an Arduino pin label, ESP-IDF wants GPIO numbers

In ESP-IDF, `menuconfig` expects the **ESP32-S3 GPIO number**, not the silk-screen label.

For **Arduino Nano ESP32 (ABX00083)**, the official pinout maps:

- `RX0` = `GPIO44`
- `TX0` = `GPIO43`

So set:

`idf.py menuconfig` → `JoyCon Bridge (ESP32-S3 USB Keyboard)` → `Bridge UART RX GPIO` = `44`

Also set:
- `Bridge UART baud` to `115200`
- `UART port` to whichever UART you prefer (default `1` in this repo)

## If you paste the RX0 GPIO mapping

The repo defaults are already set for `RX0=GPIO44` / `TX0=GPIO43`.
