# UART protocol (ESP32 ↔ USB keyboard device)

This is a tiny framing format so the USB-keyboard-side firmware (ESP32-S3) can act as the only USB device.

It is also used in the reverse direction (ESP32-S3 → ESP32) for optional helper-app control commands.

## Frame format

All bytes are unsigned.

```
AA 55 <len> <payload...> <checksum>
```


## Key event byte

```
bit 7: pressed (1=down, 0=up)
bits 6..0: key_id (0-127)
```

`key_id` is mapped to a USB HID keycode + modifier inside the USB-keyboard-side firmware.


### Extended key event (`0xFC`)

To support multiple controller devices without breaking legacy receivers, key events can also be sent as a multi-byte payload.

- `len == 4`
- `payload[0] == 0xFC`

Payload:

- `payload[0]`: `0xFC` (key event ex marker)
- `payload[1]`: `device_id` (0 = left, 1 = right)
- `payload[2]`: `pressed` (0/1)
- `payload[3]`: `base_key_id` (0..127)

Receivers should map `(device_id, base_key_id)` into an input key id space. Recommended mapping:

- `device_id == 0` (left): input `key_id = base_key_id` (0..127)
- `device_id == 1` (right): input `key_id = 128 + base_key_id` (128..255)
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
	- payload: optional 1-byte flags
		- bit 0 (`0x01`): dual-connect mode (try connect both Joy-Con (L) and Joy-Con (R))

### OTA update control commands (ESP32-S3 → ESP32)

These use the same control frame format (`0xFE` + `cmd_id` + payload):

- `cmd_id=0x10` — OTA begin
	- payload: 4-byte total size (little-endian uint32)
- `cmd_id=0x11` — OTA data
	- payload: raw firmware bytes (up to 218 bytes per frame)
- `cmd_id=0x12` — OTA end (finalize + reboot)
	- no payload
- `cmd_id=0x13` — OTA abort
	- no payload
- `cmd_id=0x14` — firmware version query
	- no payload

## OTA response frames (ESP32 → ESP32-S3)

The ESP32 sends OTA responses back via UART using marker `0xFB`:

- `payload[0]`: `0xFB` (OTA response marker)
- `payload[1]`: response ID
- `payload[2]`: status (`0x00` = OK, `0x01` = error)
- `payload[3..]`: optional data

Response IDs:

- `0x01` — OTA begin ACK
- `0x03` — OTA end ACK
- `0x04` — firmware version (data = UTF-8 version string)

## Why this design

- Keeps ESP32 code simple: it only needs to emit key_id up/down.
- Keeps USB HID logic deterministic and fast.
