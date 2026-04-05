# UART protocol (ESP32 ↔ USB keyboard device)

This is a tiny framing format so the USB-keyboard-side firmware (ESP32-S3) can act as the only USB device.

It is also used in the reverse direction (ESP32-S3 → ESP32) for optional helper-app control commands.

## Frame format

All bytes are unsigned.

```
AA 55 <len> <payload...> <checksum>
```

- `AA 55` — sync
- `<len>` — payload length (1..255)
- `<payload...>` — payload bytes
- `<checksum>` — XOR of `len` and payload bytes

## Key event byte

```
bit 7: pressed (1=down, 0=up)
bits 6..0: key_id (0-127)
```

`key_id` is mapped to a USB HID keycode + modifier inside the USB-keyboard-side firmware.

## Optional status frames (BT host → ESP32-S3 → helper app)

The ESP32 Classic-BT HID host can emit status frames (payload length `> 1`) so the helper app can display connection state.

Status payload format:

- `0xFD` — status marker
- `status_id` — currently:
	- `1` discovering
	- `2` found
	- `3` connecting
	- `4` connected
	- `5` disconnected
- `bda[6]` — Bluetooth device address (or `00:00:00:00:00:00` if unknown)
- `name_len` — 0..48
- `name bytes` — UTF-8 device name (truncated)

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

## Optional control frames (ESP32-S3 → ESP32 BT host)

If you wire the *return UART* line (ESP32-S3 TX → ESP32 RX), the helper app can send NDJSON commands to the ESP32-S3, which forwards them as UART control frames.

Control payload format:

- `0xFE` — control marker
- `cmd_id`
- `cmd payload...`

Current control commands:

- `cmd_id=0x01` — set target name substring
	- payload: ASCII/UTF-8 bytes of the substring (not null-terminated)
- `cmd_id=0x02` — start discovery
	- payload: empty

## Why this design

- Keeps ESP32 code simple: it only needs to emit key_id up/down.
- Keeps USB HID logic deterministic and fast.
