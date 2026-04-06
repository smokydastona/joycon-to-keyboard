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
		"3": {"type": "macro", "id": "jump"},
		"4": {"type": "remap_hid", "mod": 0, "keycode": 26}
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
	"layers": [
		{
			"name": "alt",
			"key_id": 6,
			"mode": "hold",
			"mappings": {
				"1": {"type": "remap_hid", "mod": 0, "keycode": 30}
			}
		}
	],
	"chords": [
		{
			"keys": [1, 2],
			"action": {"type": "remap_hid", "mod": 0, "keycode": 40}
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

### Mapping types

| type | description |
|------|-------------|
| `passthrough` | Input key_id is looked up in the static `keymap.c` table (default). Not stored in JSON — absence of a mapping means passthrough. |
| `disable` | Input is ignored. |
| `remap` | Input key_id is remapped to a different output key_id, then looked up in `keymap.c`. |
| `macro` | A macro is triggered on press. |
| `remap_hid` | **Bypasses keymap.c entirely.** Sends an arbitrary HID modifier+keycode. `mod` is a bitmask (0x01=LCtrl, 0x02=LShift, 0x04=LAlt, 0x08=LGUI). `keycode` is a USB HID usage code (e.g. 0x04=A, 0x1A=W, 0x2C=Space). |
| `tap_hold` | Differentiates tap (quick press) from hold (long press). Contains `tap` and `hold` sub-mappings plus a `hold_ms` threshold. See below. |
| `double_tap` | Single-tap sends one key, quick double-tap sends another. Contains `single_mod`/`single_keycode`, `double_mod`/`double_keycode`, and `timeout_ms`. See below. |

### Tap-hold mapping

The `tap_hold` type lets a single button produce different actions for a quick tap versus a long hold:

```json
{
	"type": "tap_hold",
	"tap": {"type": "passthrough"},
	"hold": {"type": "remap_hid", "mod": 0, "keycode": 40},
	"hold_ms": 300
}
```

| field | type | description |
|-------|------|-------------|
| `tap` | object | Mapping applied on quick press (< hold_ms). Any mapping type except `tap_hold`. |
| `hold` | object | Mapping applied on long press (>= hold_ms). Any mapping type except `tap_hold`. |
| `hold_ms` | int | Threshold in milliseconds. Default 300. |

### Double-tap mapping

The `double_tap` type sends one key on a single tap and a different key when double-tapped quickly:

```json
{
	"type": "double_tap",
	"single_mod": 0,
	"single_keycode": 4,
	"double_mod": 2,
	"double_keycode": 22,
	"timeout_ms": 300
}
```

| field | type | description |
|-------|------|-------------|
| `single_mod` | int | HID modifier bitmask for single-tap action. |
| `single_keycode` | int | HID keycode for single-tap action. |
| `double_mod` | int | HID modifier bitmask for double-tap action. |
| `double_keycode` | int | HID keycode for double-tap action. |
| `timeout_ms` | int | Maximum gap between taps to register as double-tap. Default 300. |

State machine: first press starts tracking → first release arms the timer → second press within `timeout_ms` fires the double-tap action → if the timer expires without a second press, the single-tap action fires.

### Chords (optional)

The `chords` array defines multi-button combos that produce a single action when pressed simultaneously.

```json
{
	"chords": [
		{
			"keys": [1, 2],
			"action": {"type": "remap_hid", "mod": 0, "keycode": 40}
		}
	]
}
```

| field | type | description |
|-------|------|-------------|
| `keys` | int[] | List of input key_ids that must be pressed together (order doesn't matter). |
| `action` | object | Mapping to execute when the chord is detected. Any mapping type. |

Chords are evaluated before individual key mappings. When a chord fires, its constituent keys are suppressed from individual processing.

### Layers (optional)

The `layers` array defines overlay mapping layers activated by a controller button.

Each layer:

| field | type | description |
|-------|------|-------------|
| `name` | string | Display name for the layer. |
| `key_id` | int | The input key_id that activates this layer. This key is **consumed** (not passed through to the base mapping). |
| `mode` | string | `"hold"` (active while held) or `"toggle"` (press to activate, press again to deactivate). |
| `mappings` | object | Sparse overrides — only listed key_ids are overridden. Unlisted keys fall through to the base `mappings`. |

Maximum 4 layers. When multiple layers are active, higher-index layers take priority.

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

### Set stick response curve

Configure the stick-to-key response curve on the ESP32 BT host.

```json
{"cmd":"set_stick_curve","curve":"exponential","exp":1.5}
```

- `curve`: `"linear"` (default), `"exponential"`, or `"quadratic"`
- `exp`: exponent for the exponential curve (0.1..2.5, default 1.0)

Response:

```json
{"rsp":"set_stick_curve","ok":true}
```

### Calibration management

Save or clear the stick auto-calibration data stored in NVS on the ESP32.

```json
{"cmd":"calibration","action":"save"}
```

```json
{"cmd":"calibration","action":"clear"}
```

- `action`: `"save"` persists current auto-calibration, `"clear"` erases it

Response:

```json
{"rsp":"calibration","ok":true}
```

### HD Rumble

Trigger a rumble pulse on the connected controller. Forwarded via UART to the ESP32 BT host.

```json
{"cmd":"rumble","device_id":0,"freq":160,"amp":50}
```

- `device_id`: `0` or `1` (left / right controller)
- `freq`: vibration frequency in Hz (41–1253)
- `amp`: amplitude percentage (0–100)

### Home LED brightness

Set the brightness of the Home button LED (right Joy-Con / Pro Controller only; left Joy-Con has no Home button).

```json
{"cmd":"home_led","device_id":0,"brightness":8}
```

- `device_id`: `0` or `1`
- `brightness`: 0–15 (0 = off, 15 = max)

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

Layer state events (emitted when a layer is activated/deactivated):

```json
{"evt":"layer","name":"alt","active":true}
```

```json
{"evt":"layer","name":"alt","active":false}
```

This helper app is tolerant of non-JSON log lines; it will display them as text.

BT host status events (optional):

```json
{"evt":"bt_status","state":"discovering","name":"Joy-Con"}
```

```json
{"evt":"bt_status","state":"connected","bda":"aa:bb:cc:dd:ee:ff"}
```

Battery level events (emitted when the Joy-Con reports its battery level):

```json
{"evt":"battery","device_id":0,"level":3}
```

- `device_id`: `0` = left, `1` = right
- `level`: `0` = empty, `1` = critical, `2` = low, `3` = medium, `4` = full

Controller info events (emitted once per controller after the setup FSM completes):

```json
{"evt":"controller_info","device_id":0,"type":"joycon_l","serial":"XKJN402719474",
 "body_color":"#0AB9E6","button_color":"#001E1E",
 "stick_deadzone":200,"stick_range_ratio":3500,
 "imu_cal":{"acc_origin":[0,0,16384],"acc_sens":[16384,16384,16384],
            "gyro_origin":[0,0,0],"gyro_sens":[13371,13371,13371]}}
```

- `type`: `"joycon_l"`, `"joycon_r"`, `"pro"`, or `"unknown"`
- `serial`: controller serial number (may be empty)
- `body_color`, `button_color`: `#RRGGBB` hex strings (present when colors are available)
- `stick_deadzone`, `stick_range_ratio`: raw SPI stick parameters (present when available)
- `imu_cal`: accelerometer/gyroscope calibration data (present when available)
  - `acc_origin`, `acc_sens`, `gyro_origin`, `gyro_sens`: arrays of 3 int16 values each

### RSSI events

Bluetooth signal strength, polled every 5 seconds per connected device:

```json
{"evt":"rssi","device_id":0,"rssi":-55}
```

- `device_id`: `0` = left, `1` = right
- `rssi`: RSSI in dBm (int8, typically -30 to -100; higher = stronger)

## Share codes (helper app only)

The helper app can export/import a single-string **profile share code** for offline sharing.

- Format: `JCB1:<base64url(zlib(profile_json))>`
- This is not sent to the device directly; it is just a helper-side encoding.
