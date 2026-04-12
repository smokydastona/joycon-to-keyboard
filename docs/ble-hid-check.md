# BLE HID check (5 minutes, no guessing)

This project is **USB HID (keyboard + mouse + gamepad) to the PC**. The only open question is the **wireless controller → board** link.

Many people claim “Joy-Con is BLE HID so ESP32-S3 can host it.” Treat that as **unproven** until you can observe BLE HID services on the controller.

## What you need

- A phone (Android or iOS)
- A BLE scanner app (example: **nRF Connect**)

## Steps

1) Put your controller in pairing mode.
2) In the BLE scanner, find the device and try to **Connect**.
3) After connecting, open the **Services** view.

### Notes that prevent false negatives

- If the controller is already paired to a Switch/PC/phone, it may not accept a new connection.
- Some controllers have multiple pairing modes (Switch / iOS / Android / PC). Use the mode intended for BLE.
- A single “Connect failed” does **not** mathematically prove “Classic-only”, but it’s a strong signal that you’re not looking at a BLE GATT-peripheral HID device in the current mode.

## What you’re looking for

### If you see this

- **HID Service** with UUID `0x1812` (Human Interface Device)

…and it exposes HID-related characteristics, then the controller may be usable as **BLE HID over GATT (HOGP)**.

Common HID-over-GATT characteristic UUIDs:

- `0x2A4A` — HID Information
- `0x2A4B` — Report Map
- `0x2A4C` — HID Control Point
- `0x2A4D` — Report (often the one you enable **Notify** on)
- `0x2A4E` — Protocol Mode

Other commonly present (not HID, but often appears on controllers):

- `0x180A` — Device Information
- `0x180F` — Battery Service

That means a **one-chip ESP32-S3-only** design *might* be possible.

### If you do NOT see this

- No `0x1812` HID service, or
- You cannot connect as a normal BLE peripheral, or
- The device doesn’t show usable HID report characteristics

…then you should assume the controller is **not** BLE HID-over-GATT.

In that case, an **ESP32-S3 cannot be the wireless host**. For a Nintendo Joy-Con, the practical path is:

- **Classic-BT-capable ESP32** (Joy-Con host) → UART → **USB-HID keyboard device** (ESP32-S3)

## What to send back (so I can answer YES/NO)

- A screenshot of the Services list (showing whether `0x1812` exists)
- If `0x1812` exists: screenshot(s) of the HID characteristics list
- The exact controller model name (Joy-Con vs Binbok model)

## Binbok / third-party Joy-Con clone quick tips

Binbok-style controllers may advertise under generic names. When scanning, don’t rely only on the name — tap likely candidates and check services.

If you can connect and you see `0x1812`, do this decisive test:

1) Open the `0x1812` HID service
2) Tap a `0x2A4D` Report characteristic
3) Enable **Notify**
4) Press buttons / move stick

If notifications stream while you press inputs, that’s strong evidence the controller is BLE HID-over-GATT and an ESP32-S3-only host might be viable.
