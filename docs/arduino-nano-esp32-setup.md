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

## Recommended wiring for the host-first Web Flasher

If you want the easiest first-time install path, add the two installer wires as well:

- ESP32 `GPIO21` → Nano `B1 / GPIO0`
- ESP32 `GPIO22` → Nano `RESET`

The host firmware uses those pins to put the Nano into ROM download mode and flash it over the normal bridge UART.

## Firmware to flash on the Nano ESP32

Use: `firmware/esp32s3-usb-kbd/`

Build target is `esp32s3`.

## Critical setting: bridge UART GPIO numbers

In ESP-IDF, `menuconfig` expects the **ESP32-S3 GPIO number**, not the silk-screen label.

For **Arduino Nano ESP32 (ABX00083)**, the bridge UART uses:

- Bridge `RX` = **D2** = `GPIO5`
- Bridge `TX` = **D3** = `GPIO6`

> **Why not D0/D1 (GPIO44/43)?** Those are the I/O-MUX default pins for
> the hardware UART0 console.  Even with `CONFIG_ESP_CONSOLE_NONE`, the
> bootloader briefly drives UART0 on those pins and the I/O-MUX assignment
> can shadow GPIO-matrix routing for UART1.  GPIO5/6 avoid the conflict.

So set:

`idf.py menuconfig` → `Bind Bandit (ESP32-S3 USB Keyboard)` → `Bridge UART RX GPIO` = `5`

Also set:
- `Bridge UART baud` to `921600`
- `UART port` to whichever UART you prefer (default `1` in this repo)

## If you paste the RX GPIO mapping

The repo defaults are already set for `RX=GPIO5` / `TX=GPIO6`.
