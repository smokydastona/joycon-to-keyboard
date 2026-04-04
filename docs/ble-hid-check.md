# BLE HID check (5 minutes, no guessing)

This project is **USB HID keyboard to the PC**. The only open question is the **wireless controller → board** link.

Many people claim “Joy-Con is BLE HID so ESP32-S3 can host it.” Treat that as **unproven** until you can observe BLE HID services on the controller.

## What you need

- A phone (Android or iOS)
- A BLE scanner app (example: **nRF Connect**)

## Steps

1) Put your controller in pairing mode.
2) In the BLE scanner, find the device and try to **Connect**.
3) After connecting, open the **Services** view.

## What you’re looking for

### If you see this

- **HID Service** with UUID `0x1812` (Human Interface Device)

…and it exposes HID-related characteristics (for example `Protocol Mode`, `HID Information`, `Report Map`, `Report`), then the controller may be usable as **BLE HID over GATT (HOGP)**.

That means a **one-chip ESP32-S3-only** design *might* be possible.

### If you do NOT see this

- No `0x1812` HID service, or
- You cannot connect as a normal BLE peripheral, or
- The device doesn’t show usable HID report characteristics

…then you should assume the controller is **not** BLE HID-over-GATT.

In that case, an **ESP32-S3 cannot be the wireless host**. For a Nintendo Joy-Con, the practical path is:

- **Classic-BT-capable ESP32** (Joy-Con host) → UART → **USB-HID keyboard device** (RP2040 or ESP32-S3)

## What to send back (so I can answer YES/NO)

- A screenshot of the Services list (showing whether `0x1812` exists)
- If `0x1812` exists: screenshot(s) of the HID characteristics list
- The exact controller model name (Joy-Con vs Binbok model)
