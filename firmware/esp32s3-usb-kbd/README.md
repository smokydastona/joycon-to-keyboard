# esp32s3-usb-kbd (Arduino Nano ESP32 / ESP32-S3)

Use an **ESP32-S3** board (like Arduino Nano ESP32) as the **USB HID keyboard** device.
It reads UART frames from the Joy-Con receiver (a Classic-BT-capable board) and sends real USB keyboard reports to the PC.

This firmware also exposes a **USB CDC-ACM serial interface (COM port)** so the desktop helper app can upload/read profiles and monitor events.

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

### VS Code IntelliSense (includePath squiggles)

If VS Code shows `#include errors detected` in C files, build once so ESP-IDF generates:

- `firmware/esp32s3-usb-kbd/build/compile_commands.json`

Then reload VS Code. The workspace includes a `.vscode/settings.json` that points the C/C++ extension at that file.

## Helper app (USB serial)

When plugged into Windows, the board should enumerate as:

- a USB keyboard (HID)
- a USB serial device (CDC-ACM → COM port)

The serial protocol is NDJSON (one JSON object per line). See:

- `helper-app/protocol.md`

## UART settings

Configured via `menuconfig`:

- `Bridge UART TX GPIO`
- `Bridge UART RX GPIO`
- `Bridge UART baud`

On the Arduino Nano ESP32 you’ll likely wire UART to the header pins, then set the matching **GPIO numbers** in menuconfig.

## Mapping

The key IDs are the same as in `docs/keymap.md`.
