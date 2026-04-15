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

### Enable / disable gamepad reports

This does **not** change USB enumeration; it only stops/starts sending HID gamepad reports.
Useful if a game is listening to both keyboard/mouse and controller at the same time.

```json
{"cmd":"set_gamepad_enabled","enabled":true}
```

```json
{"cmd":"set_gamepad_enabled","enabled":false}
```

### Write profile slot

`profile` is a JSON object.

Current expectation (v1): the keyboard-side device receives `key_id` up/down events from UART.
The input `key_id` space is `device_id*128 + base_key_id` and currently ranges 0..639.
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
				{"type": "key", "key_id": 44, "pressed": false},
				{"type": "mouse_button", "button": 1, "pressed": true},
				{"type": "delay", "ms": 30},
				{"type": "mouse_button", "button": 1, "pressed": false}
			]
		},
		{
			"id": "chain_target",
			"steps": [
				{"type": "key", "key_id": 10, "pressed": true},
				{"type": "delay", "ms": 20},
				{"type": "key", "key_id": 10, "pressed": false}
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
		"exp": 1.0,
		"socd_mode": "neutral",
		"rapid_trigger": {
			"activation": 30,
			"deactivation": 20
		}
	},
	"humanize": true,
	"right_stick_mode": "keys",
	"mouse_sensitivity": 10,
	"sprint_zone": {
		"enabled": false,
		"threshold": 90,
		"key": {"mod": 0, "keycode": 225}
	},
	"leader_sequences": [
		{
			"keys": [8, 9],
			"action": {"mod": 0, "keycode": 40}
		}
	],
	"humanize": true,
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
- `stick` configures analog stick behavior on the ESP32 BT host. All sub-fields are forwarded on profile load: `deadzone`, `shape`, `curve`, `exp`, `socd_mode`, and `rapid_trigger`.
- `humanize` enables ±15% timing jitter on macro delays and ±10% on turbo repeats (default true).
- `right_stick_mode` controls right analog stick behavior: `"keys"` (default), `"mouse"`, or `"scroll"`.
- `mouse_sensitivity` scales mouse cursor movement when `right_stick_mode` is `"mouse"` (1–50, default 10).
- `sprint_zone` configures automatic sprint key activation when the left stick deflection exceeds the threshold percentage. `key` specifies the HID modifier+keycode to press (e.g. Left Shift = keycode 0xE1).
- `leader_sequences` defines an array of key sequences that fire after a leader key is pressed. Each sequence has `keys` (array of key_ids) and `action` (HID mod+keycode). Max 8 sequences, 4 keys each. 1-second timeout.
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
| `turbo` | Rapid-fire (auto-repeat) key while held. Contains `mod`, `keycode`, and `delay_ms` (repeat interval). See below. |
| `sticky` | Toggle modifier: first press activates, second press deactivates. Contains `mod` and `keycode`. See below. |
| `oneshot` | One-shot modifier: press once to arm, next key press applies the modifier once, then auto-releases. Contains `mod` and `keycode`. See below. |
| `auto_shift` | Quick tap sends normal key, hold past threshold sends shifted key. Contains `normal` and `shifted` sub-objects plus `hold_ms`. See below. |
| `mouse_button` | Maps to a real USB HID mouse button. Contains `button` (1=left, 2=right, 4=middle). See below. |
| `gamepad_button` | Maps to a real USB HID gamepad control. Contains `button` (`"A"`, `"B"`, `"X"`, `"Y"`, `"LB"`, `"RB"`, `"LT"`, `"RT"`, `"View"`, `"Menu"`, `"Xbox"`, `"Share"`, `"LS"`, `"RS"`, `"DUp"`, `"DDown"`, `"DLeft"`, `"DRight"`, `"P1"`, `"P2"`, `"P3"`, `"P4"`). See below. |
| `sequential` | Cycles through a list of outputs on each press. Contains `outputs` array. See below. |
| `leader` | Activates leader key mode: buffers subsequent presses and matches against `leader_sequences`. No extra fields. |
| `profile_switch` | Switches the active profile slot and reloads. Contains `slot` (0–3). See below. |

### Macro step types

Each step in a `macros[].steps` array has a `type` field:

| type | fields | description |
|------|--------|-------------|
| `key` | `key_id` (0–127), `pressed` (bool) | Press or release a keyboard key. |
| `delay` | `ms` (0–5000) | Wait with humanized jitter (±15%). |
| `mouse_button` | `button` (1–31), `pressed` (bool) | Press or release a USB HID mouse button. |
| `macro_chain` | `id` (string) | Enqueue another macro to run after the current one finishes. |

Mouse button values: 1=left, 2=right, 4=middle, 8=back, 16=forward.

Macro chaining is **non-recursive** — chained macros are enqueued and executed sequentially by the macro task, not inlined. Circular chains will eventually drain the 8-entry macro queue.

### Turbo mapping

The `turbo` type auto-repeats a key while held, toggling press/release at a fixed interval:

```json
{
	"type": "turbo",
	"mod": 0,
	"keycode": 44,
	"delay_ms": 50
}
```

| field | type | description |
|-------|------|-------------|
| `mod` | int | HID modifier bitmask for the repeated key. |
| `keycode` | int | HID keycode for the repeated key. |
| `delay_ms` | int | Interval in milliseconds between toggles. Default 50. Range: 10–500. |

### Sticky mapping

The `sticky` type makes a key toggle on/off. First press sends key-down, second press sends key-up:

```json
{
	"type": "sticky",
	"mod": 2,
	"keycode": 0
}
```

| field | type | description |
|-------|------|-------------|
| `mod` | int | HID modifier bitmask to toggle. |
| `keycode` | int | HID keycode to toggle. 0 if modifier-only. |

### One-shot mapping

The `oneshot` type arms a modifier on press. The next non-oneshot key press automatically applies the armed modifier, then releases it:

```json
{
	"type": "oneshot",
	"mod": 2,
	"keycode": 0
}
```

| field | type | description |
|-------|------|-------------|
| `mod` | int | HID modifier bitmask to apply once. |
| `keycode` | int | HID keycode to apply once. 0 if modifier-only. |

State machine: press the oneshot key → modifier is armed → press any other key → modifier is applied for that key → modifier auto-releases. Arms expire after 3 seconds if no other key is pressed.

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

### Auto-shift mapping

Quick tap sends normal key, holding past a threshold sends the shifted variant:

```json
{
	"type": "auto_shift",
	"normal": {"mod": 0, "keycode": 4},
	"shifted": {"mod": 2, "keycode": 4},
	"hold_ms": 200
}
```

| field | type | description |
|-------|------|-------------|
| `normal` | object | `mod` + `keycode` for quick tap. |
| `shifted` | object | `mod` + `keycode` for hold action. |
| `hold_ms` | int | Threshold in milliseconds. Default 200. Range: 50–1000. |

### Mouse button mapping

Maps a controller button to a real USB HID mouse button:

```json
{
	"type": "mouse_button",
	"button": 1
}
```

| field | type | description |
|-------|------|-------------|
| `button` | int | Mouse button bitmask: 1=left, 2=right, 4=middle. |

### Sequential mapping

Each press cycles to the next output in a list:

```json
{
	"type": "sequential",
	"outputs": [
		{"mod": 0, "keycode": 30},
		{"mod": 0, "keycode": 31},
		{"mod": 0, "keycode": 32}
	]
}
```

| field | type | description |
|-------|------|-------------|
| `outputs` | array | 1–8 objects, each with `mod` and `keycode`. |

### Gamepad button mapping

Maps a controller button to a real USB HID gamepad control:

```json
{
	"type": "gamepad_button",
	"button": "A"
}
```

| field | type | description |
|-------|------|-------------|
| `button` | string | Gamepad control name: `A`, `B`, `X`, `Y`, `LB`, `RB`, `LT`, `RT`, `View`, `Menu`, `Xbox`, `Share`, `LS`, `RS`, `DUp`, `DDown`, `DLeft`, `DRight`, `P1`, `P2`, `P3`, `P4`. |

### Leader mapping

Designate a key as a leader key. No extra fields — just `{"type": "leader"}`.

Leader sequences are defined at the profile root level (see below).

### Profile switch mapping

Switches the active profile slot and reloads the profile:

```json
{
	"type": "profile_switch",
	"slot": 2
}
```

| field | type | description |
|-------|------|-------------|
| `slot` | int | Target profile slot (0–3). |

Works in direct mappings, layer overrides, and chord actions.

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

Response:

```json
{"rsp":"fw_update_abort","ok":true}
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

### Speaker / buzzer settings

These commands configure the ESP32 BT host piezo/buzzer ("speaker") at runtime. Settings persist on the ESP32 host.

#### Query current settings

```json
{"cmd":"buzzer_get"}
```

Response:

```json
{"rsp":"buzzer_get","ok":true,"enabled":true,"volume":60,"discovery_tick":true,"tone_mask":127}
```

- `enabled`: master enable
- `volume`: 0–100 (0 = mute)
- `discovery_tick`: enable periodic tick while BT discovery is active
- `tone_mask`: per-tone enable bitmask (bit N = tone_id N)

#### Apply settings

```json
{"cmd":"buzzer_set","enabled":true,"volume":60,"discovery_tick":true,"tone_mask":127}
```

Response:

```json
{"rsp":"buzzer_set","ok":true}
```

#### Play a test tone

```json
{"cmd":"buzzer_test","tone_id":1}
```

Response:

```json
{"rsp":"buzzer_test","ok":true}
```

### Set SOCD mode

Configure the Simultaneous Opposing Cardinal Directions cleaning mode on the ESP32 BT host.

```json
{"cmd":"set_socd_mode","mode":"neutral"}
```

- `mode`: `"neutral"` (opposing cancel), `"last_input"` (last pressed wins), `"first_input"` (first pressed wins), or `0`/`1`/`2`

Response:

```json
{"rsp":"set_socd_mode","ok":true}
```

### Set rapid trigger (stick hysteresis)

Configure stick-to-key activation/deactivation thresholds for hysteresis on the ESP32 BT host. This prevents flickering at the deadzone boundary.

```json
{"cmd":"set_rapid_trigger","activation":30,"deactivation":20}
```

- `activation`: threshold for direction to activate (default 30)
- `deactivation`: threshold for direction to deactivate (default 20; must be ≤ activation)

Response:

```json
{"rsp":"set_rapid_trigger","ok":true}
```

### Set humanize

Enable or disable timing humanization (jitter) for macros and turbo repeats.

```json
{"cmd":"set_humanize","enabled":true}
```

Response:

```json
{"rsp":"set_humanize","ok":true,"enabled":true}
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
- Legacy 1-byte key events use `key_id` 0..127 (device_id implicitly 0).
- Multi-device mode uses `key_id = device_id * 128 + base_key_id` and currently ranges 0..639.

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
- `device_id`: `0..4` device slot id (for Joy-Con dual-connect, conventionally `0` = left, `1` = right)
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

## Diagnostics (device -> PC)

### UART bridge diagnostics

Reports the status of the UART bridge between ESP32-S3 and ESP32 BT host.

```json
{"cmd":"uart_diag"}
```

Response:

```json
{"rsp":"uart_diag","port":1,"baud":921600,"rx_gpio":5,"tx_gpio":6,
 "rx_pin_level":1,"buffered_bytes":0,
 "total_rx_bytes":12345,"total_frames":1234,
 "sample_len":16,"sample_hex":"AA 55 06 F7 00 00 00 00 00 F1 AA 55 06 F7 80 00"}
```

- `total_rx_bytes`: cumulative raw bytes received on the bridge UART since boot
- `total_frames`: cumulative valid framed packets decoded since boot
- `rx_pin_level`: current logic level on the RX pin (0 = low, 1 = high/idle)
- `sample_hex`: up to 16 raw bytes from the last UART read (debug context)

### Synthetic key injection (diagnostics / testing only)

Triggers a single press + release of a logical key through the full HID output path.
Useful for verifying the USB HID keyboard output without a physical controller.

```json
{"cmd":"test_key","key_id":1}
```

- `key_id`: logical input key id (0–127, default 1 = W / Forward). See `docs/keymap.md`.

Response:

```json
{"rsp":"test_key","key_id":1,"status":"ok"}
```

The device presses the mapped HID key for ~80 ms then releases it.
