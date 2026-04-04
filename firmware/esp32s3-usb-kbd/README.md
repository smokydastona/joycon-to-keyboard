# esp32s3-usb-kbd (Arduino Nano ESP32 / ESP32-S3)

Use an **ESP32-S3** board (like Arduino Nano ESP32) as the **USB HID keyboard** device.
It reads UART frames from the Joy-Con receiver (a Classic-BT-capable board) and sends real USB keyboard reports to the PC.

## Why this exists

Your Arduino Nano ESP32 is an **ESP32-S3** (u-blox NORA-W106 module). That makes it a great fit for the **PC-facing keyboard** side.

However, Joy-Cons commonly require **Bluetooth Classic HID host** to connect wirelessly.
ESP32-S3 is not the safest choice for that part.

So the practical setup is:

- Joy-Con (wireless) → **ESP32 (Classic BT capable)** → UART → **ESP32-S3 (USB keyboard)** → PC

## Build / flash

Install ESP-IDF, then:

```powershell
idf.py set-target esp32s3
idf.py build
idf.py flash monitor
```

## UART settings

Configured via `menuconfig`:

- `Bridge UART TX GPIO`
- `Bridge UART RX GPIO`
- `Bridge UART baud`

On the Arduino Nano ESP32 you’ll likely wire UART to the header pins, then set the matching **GPIO numbers** in menuconfig.

## Mapping

The key IDs are the same as in `docs/keymap.md`.
