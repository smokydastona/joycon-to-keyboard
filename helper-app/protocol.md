# Serial protocol (helper app)

Transport: USB serial (COM port), 115200 8N1 unless you changed it.

Encoding: UTF-8 text.

Framing: **one JSON object per line** (newline-delimited JSON / NDJSON).

## Commands (PC -> device)

All commands are JSON objects containing a `cmd`.

### Ping

```json
{"cmd":"ping"}
```

### Write profile slot

`profile` is a JSON object.

Current expectation (v1): the keyboard-side device receives `key_id` up/down events from UART.
Profiles may:

- remap an input `key_id` to a different output `key_id`
- disable an input `key_id`
- trigger a macro on press

Unknown fields should be ignored (forward compatibility).

Profile schema (expected by the ESP32-S3 keyboard-side firmware):

```json
{
	"ver": 1,
	"name": "default",
	"mappings": {
		"1": {"type": "disable"},
		"2": {"type": "remap", "to": 10},
		"3": {"type": "macro", "id": "jump"}
	},
	"macros": [
		{
			"id": "jump",
			"steps": [
				{"type": "key", "key_id": 44, "pressed": true},
				{"type": "delay", "ms": 50},
				{"type": "key", "key_id": 44, "pressed": false}
			]
		}
	],
	"stick": {
		"deadzone": 0.15,
		"shape": "circle",
		"curve": "linear",
		"exp": 1.0
	},
	"ui": {
		"hotspots": {
			"A": 130,
			"ZL": 7
		}
	}
}
```

Notes:

- `mappings` keys are strings (input `key_id`), for easier JSON interoperability.
- `stick` is stored for future analog support; it may be ignored by current firmware.
- `ui.hotspots` is helper-app-only UI state (Controller tab). It maps a visual control name to an observed input `key_id`.
- Firmware ignores unknown profile fields.

```json
{"cmd":"write_profile","slot":0,"profile":{}}
```

### Read profile slot

```json
{"cmd":"read_profile","slot":0}
```

### Set active slot

```json
{"cmd":"set_active_profile","slot":0}
```

### BT set target (runtime)

Sets the target device name substring used by the ESP32 Classic-BT HID host while scanning.

```json
{"cmd":"bt_set_target","name_substr":"Joy-Con"}
```

Notes:

- This is runtime-only (not persisted).
- Requires the *return UART* wire so the ESP32-S3 can send UART frames back to the ESP32 host.

### BT connect / scan

Triggers an inquiry scan on the ESP32 BT host. If a discovered device name matches the current target substring, the host will attempt to connect.

```json
{"cmd":"bt_connect"}
```

Optional fields:

- `both` (bool): when true, requests the ESP32 BT host to connect to both Joy-Con (L) and Joy-Con (R).

Example:

```json
{"cmd":"bt_connect","both":true}
```

## Firmware version & OTA update commands

### Query firmware version

Returns the firmware version of either the ESP32-S3 (default) or the ESP32 BT host.

```json
{"cmd":"fw_version"}
```

```json
{"cmd":"fw_version","board":"esp32"}
```

Response:

```json
{"rsp":"fw_version","ok":true,"board":"esp32s3","version":"0.1.42"}
```

### Begin firmware update

Start an OTA update session. `size` is the total firmware image size in bytes.

```json
{"cmd":"fw_update_begin","size":524288}
```

For the ESP32 BT host (relayed via ESP32-S3):

```json
{"cmd":"fw_update_begin","board":"esp32","size":1048576}
```

Response:

```json
{"rsp":"fw_update_begin","ok":true}
```

### Send firmware data chunk

Send a base64-encoded chunk of firmware binary data. Recommended chunk size: 3072 bytes raw (4096 chars base64).

```json
{"cmd":"fw_update_data","data":"<base64>"}
```

For ESP32 relay:

```json
{"cmd":"fw_update_data","board":"esp32","data":"<base64>"}
```

Response:

```json
{"rsp":"fw_update_data","ok":true,"written":3072}
```

### Finalize firmware update

Validate the image and set the boot partition. The device reboots after responding.

```json
{"cmd":"fw_update_end"}
```

For ESP32 relay:

```json
{"cmd":"fw_update_end","board":"esp32"}
```

Response:

```json
{"rsp":"fw_update_end","ok":true}
```

### Abort firmware update

Cancel an in-progress OTA session.

```json
{"cmd":"fw_update_abort"}
```

For ESP32 relay:

```json
{"cmd":"fw_update_abort","board":"esp32"}
```

## Events (device -> PC)

The device may emit events for:

- input reports
- mapped key events
- diagnostic status

Example:

```json
{"evt":"mapped_key","pressed":true,"key_id":1}
```

Notes:

- `key_id` is an *input key id*.
- Single-controller mode uses `key_id` 0..127.
- Dual Joy-Con mode uses:
	- left Joy-Con: `key_id` 0..127
	- right Joy-Con: `key_id` 128..255 (base + 128)

Macro execution events (optional):

```json
{"evt":"macro","id":"jump","state":"start"}
```

```json
{"evt":"macro","id":"jump","state":"end"}
```

This helper app is tolerant of non-JSON log lines; it will display them as text.

BT host status events (optional):

```json
{"evt":"bt_status","state":"discovering","name":"Joy-Con"}
```

```json
{"evt":"bt_status","state":"connected","bda":"aa:bb:cc:dd:ee:ff"}
```

## Share codes (helper app only)

The helper app can export/import a single-string **profile share code** for offline sharing.

- Format: `JCB1:<base64url(zlib(profile_json))>`
- This is not sent to the device directly; it is just a helper-side encoding.
