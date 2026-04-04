# What to send (so I can say YES/NO)

If you only give me an Amazon link, I cannot see the listing.
To confirm your board and make firmware changes that match it, send ONE of these:

## Option A (best): photo

A clear photo of the board with the chip/module text readable.

If you’re debugging a build issue, also include a photo of the **wiring between boards** (especially GND, TX→RX, and any VIN/5V power wire). For the expected layout, see `docs/wiring.md`.

## Option B: copy/paste from the listing

Copy/paste these lines from the Amazon page:

- Product title
- Chip/module (e.g. `ESP32-S3-WROOM-1`, `ESP32-WROOM-32`, `ESP32-S3FH4R2`)
- Whether it says **Bluetooth Classic** or only **BLE**
- Whether it says **native USB / USB-OTG / USB HID**

## Option C: what Windows sees

Plug the board in and tell me what device name appears in Device Manager (or copy its VID/PID).

If you’re not sure you flashed the right thing, follow `docs/firmware-install.md` and tell me which step failed (and paste the last ~50 lines of `idf.py` output).

## Option D: BLE HID check (controller side)

If you’re using a third-party controller (or you’re unsure), run the quick BLE check in `docs/ble-hid-check.md` and send:

- Screenshot of the Services list (showing whether UUID `0x1812` exists)
- Exact controller model name

Once I have that, I can:
- confirm if it can be the USB keyboard side
- confirm if it can be the Joy-Con Bluetooth host side
- tell you what additional board (if any) is required
