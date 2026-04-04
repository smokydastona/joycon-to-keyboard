# UART protocol (ESP32 → USB keyboard device)

This is a tiny framing format so the USB-keyboard-side firmware (ESP32-S3) can act as the only USB device.

## Frame format

All bytes are unsigned.

```
AA 55 01 <event> <checksum>
```

- `AA 55` — sync
- `01` — payload length (currently always 1)
- `<event>` — packed key event
- `<checksum>` — XOR of `len` and payload bytes

## Key event byte

```
bit 7: pressed (1=down, 0=up)
bits 6..0: key_id (0-127)
```

`key_id` is mapped to a USB HID keycode + modifier inside the USB-keyboard-side firmware.

## Optional debug frames (raw HID report capture)

For evidence-based development, the Classic-BT host ESP32 can optionally send **debug frames**
with payload length `> 1`. The ESP32-S3 keyboard firmware ignores these frames.

Debug payload format:

- `0xFF` — debug marker
- `N` — number of HID report bytes included
- `N bytes` — raw HID report bytes (truncated)

Offline tools that understand these debug frames:

- `tools/decode_uart_log.py` (decodes frames into readable text)
- `tools/analyze_hid_reports.py` (summarizes which byte offsets change most)

## Why this design

- Keeps ESP32 code simple: it only needs to emit key_id up/down.
- Keeps USB HID logic deterministic and fast.
