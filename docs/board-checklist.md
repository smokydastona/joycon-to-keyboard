# Board checklist (truth-first)

If you’re building the intended **one custom USB dongle** (two boards inside, one USB plug to the PC), read these first:

- `docs/wiring.md` (one-USB power model + UART wiring)
- `docs/firmware-install.md` (Windows flashing guide for both boards)

I cannot open Amazon product pages from a short link and I can’t see your listing.
To verify a board is right for this project, use **the chip marking on the board** or the exact product title/specs.

## What you need, functionally

You need **both**:

1) **Joy-Con wireless link** (very likely **Bluetooth Classic HID host**)
2) **PC-facing USB HID device** (keyboard + mouse + gamepad)

It is common that a single cheap board cannot do both reliably.

## Important: Joy-Con Bluetooth mode is often mis-stated online

You may see claims like: “Joy-Con uses Bluetooth LE, so ESP32-S3 can pair directly.”

Treat that as **unproven** until you have device-side evidence.

Quick way to get evidence: see `docs/ble-hid-check.md`.

- If your Joy-Con works with a **Bluetooth Classic HID host** (like the ESP32 firmware in this repo), then the two-chip design is the right direction.
- If you can prove your Joy-Con can be used as **BLE HID over GATT** with an ESP32-S3, then a one-chip ESP32-S3-only design may be possible (not implemented in this repo today).

## If your board is an ESP32-S3

- ✅ Great at being a **USB device** (so it can pretend to be a keyboard over USB).
- ⚠️ Not a safe bet for **Joy-Con** connectivity because Joy-Cons commonly use **Bluetooth Classic HID**.

The **Arduino Nano ESP32** (u-blox NORA-W106 / ESP32-S3) fits in this category: it’s excellent for the **USB keyboard** half.

So an ESP32-S3 board is usually **not sufficient by itself** for “Joy-Con → PC keyboard” unless you have a separate Bluetooth Classic host.

## If your board is an original ESP32 (WROOM-32 / ESP32-D0WD etc.)

- ✅ Supports **Bluetooth Classic** (good candidate for Joy-Con side).
- ❌ Does **not** have native USB device hardware, so it cannot directly be a USB keyboard.

So an original ESP32 is usually **not sufficient by itself** either — you still need a USB-HID-capable chip (like an ESP32-S3).

## How to identify what you bought

Look at the metal RF can/module or the main chip marking:

- Contains `ESP32-S3` → S3 family
- Contains `ESP32-C3` → C3 family (not what you want for Joy-Con Classic)
- Contains `ESP32` but not S3/C3 → original ESP32 family

If you can, send a photo of the board (top side, chip/module text visible) and I’ll tell you exactly which category it is.

## What this repo expects

This repo currently implements a **two-chip bridge**:

- ESP32 (Classic BT capable) → connects to Joy-Con and forwards HID reports over UART
- ESP32-S3 → enumerates as USB keyboard and converts UART events to USB HID

If you only bought an ESP32-S3 board, it can still be used in the overall build, but you will likely need an additional Classic-BT-capable device for Joy-Con.
