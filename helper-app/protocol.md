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
	}
}
```

Notes:

- `mappings` keys are strings (input `key_id`), for easier JSON interoperability.
- `stick` is stored for future analog support; it may be ignored by current firmware.

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

## Events (device -> PC)

The device may emit events for:

- input reports
- mapped key events
- diagnostic status

Example:

```json
{"evt":"mapped_key","pressed":true,"key_id":1}
```

Macro execution events (optional):

```json
{"evt":"macro","id":"jump","state":"start"}
```

```json
{"evt":"macro","id":"jump","state":"end"}
```

This helper app is tolerant of non-JSON log lines; it will display them as text.

## Share codes (helper app only)

The helper app can export/import a single-string **profile share code** for offline sharing.

- Format: `JCB1:<base64url(zlib(profile_json))>`
- This is not sent to the device directly; it is just a helper-side encoding.
