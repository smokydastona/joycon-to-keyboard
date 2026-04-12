# UART protocol (ESP32 ↔ USB keyboard device)

This is a tiny framing format so the USB-keyboard-side firmware (ESP32-S3) can act as the only USB device.

It is also used in the reverse direction (ESP32-S3 → ESP32) for optional helper-app control commands.

**Default baud rate: 921600 8N1** (both boards must match).

## Quick-reference: frame markers

| Marker | Direction | Description |
|--------|-----------|-------------|
| (none) | ESP32→S3 | Key event (1-byte payload, bit 7=pressed) |
| `0xFC` | ESP32→S3 | Extended key event (multi-device) |
| `0xFD` | ESP32→S3 | BT status (discovery/connect/disconnect) |
| `0xFE` | S3→ESP32 | Control command (target, stick, OTA, etc.) |
| `0xFF` | ESP32→S3 | Debug HID report capture |
| `0xFB` | ESP32→S3 | OTA response (begin/end/version ACK) |
| `0xFA` | ESP32→S3 | Battery level |
| `0xF9` | ESP32→S3 | Controller info (type/serial/colors/IMU) |
| `0xF8` | ESP32→S3 | RSSI (signal strength) |
| `0xF7` | ESP32→S3 | Analog stick data |
| `0xF6` | ESP32→S3 | Gyro data (angular velocity) |

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
- `payload[1]`: `device_id` (0..4)
- `payload[2]`: `pressed` (0/1)
- `payload[3]`: `base_key_id` (0..127)

Receivers should map `(device_id, base_key_id)` into an input key id space. Recommended mapping:

- input `key_id = device_id * 128 + base_key_id` (0..639)

For Joy-Con dual-connect specifically, the conventional assignment is:

- `device_id == 0`: left Joy-Con
- `device_id == 1`: right Joy-Con

Other connected devices (mice, controllers, etc.) may occupy `device_id` 2..4.

Status payload format:

- `0xFD` — status marker
- `status_id` — currently:
	- `1` discovering
	- `2` found
	- `3` connecting
	- `4` connected
	- `5` disconnected
	- `6` reconnecting
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
- `cmd_id=0x03` — set stick response curve
	- payload: 2 bytes
		- `[0]`: curve type (`0`=linear, `1`=exponential, `2`=quadratic)
		- `[1]`: exponent * 100 (only used for exponential; e.g. `150` = 1.5)
- `cmd_id=0x04` — calibration management
	- payload: 1 byte
		- `0x01`: save current auto-calibration to NVS
		- `0x02`: clear saved calibration from NVS
- `cmd_id=0x05` — HD rumble
	- payload: 4 bytes
		- `[0]`: device_id (0 or 1)
		- `[1..2]`: frequency in Hz (uint16 LE, clamped 41–1253)
		- `[3]`: amplitude percentage (0–100)
- `cmd_id=0x06` — Home LED brightness
	- payload: 2 bytes
		- `[0]`: device_id (0 or 1)
		- `[1]`: brightness (0–15; 0 = off)
- `cmd_id=0x07` — set SOCD cleaning mode
	- payload: 1 byte
		- `0` = neutral (opposing directions cancel)
		- `1` = last input wins
		- `2` = first input wins
- `cmd_id=0x08` — set rapid trigger (stick hysteresis thresholds)
	- payload: 2 bytes
		- `[0]`: activation threshold (stick → key on; default 30)
		- `[1]`: deactivation threshold (key off; default 20; must be ≤ activation)

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

## Battery level frames (ESP32 → ESP32-S3)

The ESP32 sends Joy-Con battery level updates using marker `0xFA`:

- `payload[0]`: `0xFA` (battery marker)
- `payload[1]`: `device_id` (0..4)
- `payload[2]`: battery level (0–4)

Battery levels:

- `0` — empty
- `1` — critical
- `2` — low
- `3` — medium
- `4` — full

The ESP32-S3 forwards this to the helper app as an NDJSON event over CDC (see `helper-app/protocol.md`).

## Controller info frames (ESP32 → ESP32-S3)

The ESP32 sends detailed controller information after the Joy-Con setup FSM reaches READY, using marker `0xF9`:

- `payload[0]`: `0xF9` (controller info marker)
- `payload[1]`: `device_id` (0..4)
- `payload[2]`: `ctrl_type` (1 = Joy-Con (L), 2 = Joy-Con (R), 3 = Pro Controller)
- `payload[3]`: `serial_len` (0–15)
- `payload[4 .. 4+serial_len-1]`: serial number (ASCII)

Then optional tagged sections (presence gated by `has_*` flag byte):

- `has_colors` (1 byte: 0 or 1)
  - If 1: 6 bytes — body R, G, B, button R, G, B
- `has_stick_params` (1 byte: 0 or 1)
  - If 1: 4 bytes — deadzone (uint16 LE), range_ratio (uint16 LE)
- `has_imu_cal` (1 byte: 0 or 1)
  - If 1: 24 bytes — acc_origin[3] (int16 LE), acc_sens[3] (int16 LE), gyro_origin[3] (int16 LE), gyro_sens[3] (int16 LE)

The ESP32-S3 forwards this to the helper app as an NDJSON `controller_info` event over CDC.

## RSSI frames (ESP32 → ESP32-S3)

The ESP32 periodically polls Bluetooth RSSI and sends signal strength using marker `0xF8`:

- `payload[0]`: `0xF8` (RSSI marker)
- `payload[1]`: `device_id` (0..4)
- `payload[2]`: `rssi` (int8, dBm, transmitted as uint8)

The poll timer fires every 5 seconds for each connected device. The ESP32-S3 forwards this to the helper app as an NDJSON `rssi` event: `{"evt":"rssi","device_id":N,"rssi":N}`.

## Analog stick frames (ESP32 → ESP32-S3)

The ESP32 sends raw analog stick values (after curve + calibration) using marker `0xF7`:

- `payload[0]`: `0xF7` (analog marker)
- `payload[1]`: `device_id`
  - `0x00` = left stick
  - `0x80` = right stick (bit 7 set)
- `payload[2..3]`: x value (int16 LE, normalized −4096 to +4096)
- `payload[4..5]`: y value (int16 LE, normalized −4096 to +4096)

The ESP32-S3 uses these values for:

- Right stick → mouse cursor movement (in `STICK_MODE_MOUSE`)
- Right stick → scroll wheel (in `STICK_MODE_SCROLL`)
- Left stick → sprint zone detection (magnitude vs threshold)

These frames are sent every report cycle alongside the digital key events.

## Gyro frames (ESP32 → ESP32-S3)

The ESP32 sends IMU angular-velocity data using marker `0xF6`:

- `payload[0]`: `0xF6` (gyro marker)
- `payload[1]`: `device_id` (`0x00` = left, `0x01` = right)
- `payload[2..3]`: gyro X (int16 LE, raw units from IMU)
- `payload[4..5]`: gyro Y (int16 LE)
- `payload[6..7]`: gyro Z (int16 LE)

The ESP32-S3 uses gyro data for gyro-aim mouse mapping (sensitivity, deadzone, and invert configured per profile).

## Why this design

- Keeps ESP32 code simple: it only needs to emit key_id up/down.
- Keeps USB HID logic deterministic and fast.
