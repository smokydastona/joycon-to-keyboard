# Key mapping

This repo supports a full Joy-Con button set: movement, face buttons, shoulders/triggers, system buttons, stick clicks, right stick directions, side-rail buttons (SL/SR), and motion gestures.

## Logical actions (key_id)

### Movement (left stick)

| key_id | Action  |
|--------|---------|
| `1`    | Forward |
| `2`    | Back    |
| `3`    | Left    |
| `4`    | Right   |
| `5`    | Jump    |
| `6`    | Sprint  |
| `7`    | Crouch  |

### Face buttons

| key_id | Button |
|--------|--------|
| `8`    | A      |
| `9`    | B      |
| `10`   | X      |
| `11`   | Y      |

### Shoulder / trigger

| key_id | Button |
|--------|--------|
| `12`   | L      |
| `13`   | R      |
| `14`   | ZL     |
| `15`   | ZR     |

### System buttons

| key_id | Button  |
|--------|---------|
| `16`   | Plus    |
| `17`   | Minus   |
| `18`   | Home    |
| `19`   | Capture |

### Stick clicks

| key_id | Button       |
|--------|--------------|
| `20`   | LStick click |
| `21`   | RStick click |

### Right stick directions

| key_id | Direction    |
|--------|--------------|
| `22`   | RStick Up    |
| `23`   | RStick Down  |
| `24`   | RStick Left  |
| `25`   | RStick Right |

### Motion / IMU gestures

| key_id | Gesture     | Description                                      |
|--------|-------------|--------------------------------------------------|
| `26`   | Shake       | Sharp acceleration spike (any axis)              |
| `27`   | Tilt Up     | Sustained forward tilt (accelerometer Y-)        |
| `28`   | Tilt Down   | Sustained backward tilt (accelerometer Y+)       |
| `29`   | Tilt Left   | Sustained left tilt (accelerometer X-)            |
| `30`   | Tilt Right  | Sustained right tilt (accelerometer X+)           |
| `31`   | Flick       | Quick gyroscope twist (high angular velocity)    |

### Side-rail buttons

| key_id | Button | Description                        |
|--------|--------|------------------------------------|
| `32`   | SL(L)  | SL on left Joy-Con (inner rail)    |
| `33`   | SR(L)  | SR on left Joy-Con (inner rail)    |
| `34`   | SL(R)  | SL on right Joy-Con (inner rail)   |
| `35`   | SR(R)  | SR on right Joy-Con (inner rail)   |

## Multi-device extended key_id space

When multiple controllers are connected, each has its own `device_id`.
The UART extended key event (0xFC frame) encodes `device_id` + `base_key_id`.

The ESP32-S3 maps these into a single key space:

| device_id | key_id range | Formula |
|-----------|--------------|---------|
| 0         | 0–127        | `key_id = device_id * 128 + base_key_id` |
| 1         | 128–255      | `key_id = device_id * 128 + base_key_id` |
| 2         | 256–383      | `key_id = device_id * 128 + base_key_id` |
| 3         | 384–511      | `key_id = device_id * 128 + base_key_id` |
| 4         | 512–639      | `key_id = device_id * 128 + base_key_id` |

**Default behavior:** by default, all devices mirror the same base mappings.
In other words, `key_id % 128` uses the same defaults (e.g. key_id 129 maps
like key_id 1). Per-profile overrides can assign distinct bindings per-device
by targeting the full `key_id` value.

## Default USB outputs

| key_id | Action       | Default output |
|--------|-------------|----------------|
| 1      | Forward     | `W`            |
| 2      | Back        | `S`            |
| 3      | Left        | `A`            |
| 4      | Right       | `D`            |
| 5      | Jump        | `Space`        |
| 6      | Sprint      | `Left Shift`   |
| 7      | Crouch      | `Left Ctrl`    |
| 8      | A           | `E`            |
| 9      | B           | `Q`            |
| 10     | X           | `R`            |
| 11     | Y           | `F`            |
| 12     | L           | `Left Shift`   |
| 13     | R           | `Enter`        |
| 14     | ZL          | `I`            |
| 15     | ZR          | `Left Alt`     |
| 16     | Plus        | `Escape`       |
| 17     | Minus       | `Tab`          |
| 18     | Home        | *(unmapped)*   |
| 19     | Capture     | `Esc`          |
| 20     | LStick click| `Left Ctrl`    |
| 21     | RStick click| `V`            |
| 22     | RStick Up   | `Arrow Up`     |
| 23     | RStick Down | `Arrow Down`   |
| 24     | RStick Left | `Arrow Left`   |
| 25     | RStick Right| `Arrow Right`  |
| 26     | Shake       | *(unmapped by default)* |
| 27     | Tilt Up     | *(unmapped by default)* |
| 28     | Tilt Down   | *(unmapped by default)* |
| 29     | Tilt Left   | *(unmapped by default)* |
| 30     | Tilt Right  | *(unmapped by default)* |
| 31     | Flick       | *(unmapped by default)* |
| 32     | SL(L)       | `5`            |
| 33     | SR(L)       | `6`            |
| 34     | SL(R)       | `7`            |
| 35     | SR(R)       | `8`            |

**D-pad defaults** (profile layer, all slots):

| Button | Default output |
|--------|----------------|
| DUp    | `E`            |
| DLeft  | `F`            |
| DRight | `R`            |
| DDown  | `Space`        |

## Stick auto-calibration

Both sticks use automatic calibration rather than a hardcoded center value.
The firmware tracks min / center / max per axis at runtime:

- The first 8 samples establish the center (running average during warm-up).
- Min and max expand as the stick reaches its physical limits.
- Raw values are normalized to a ±4096 scale, then compared against a configurable deadzone.

Calibration data is automatically saved to NVS (non-volatile storage) on the ESP32
after the warm-up phase completes. On subsequent boots, saved calibration is restored
so the controller is immediately usable without a new warm-up period.

Use the `calibration` helper-app command to manually save or clear calibration data.

## Stick response curves

The profile `stick.curve` field controls how normalized stick values are mapped
to key event thresholds. Available curves:

| Curve         | Behavior                                           |
|---------------|----------------------------------------------------|
| `linear`      | Direct proportional mapping (default)              |
| `exponential` | `pow(abs(x), exp) * sign(x)` — fine center control|
| `quadratic`   | `x * abs(x)` — smooth ramp-up near center         |

The `stick.exp` field sets the exponent for the `exponential` curve (default 1.0).
Higher values increase the dead zone feel and give more precision for small movements.

Example profile stick settings:
```json
{
  "stick": {
    "deadzone": 0.15,
    "shape": "circle",
    "curve": "exponential",
    "exp": 1.5
  }
}
```

When a profile is loaded, stick curve settings are automatically forwarded
to the ESP32 BT host over UART.

## SOCD cleaning modes

When both opposing directions are pressed on a stick simultaneously (e.g. left + right),
the firmware applies SOCD (Simultaneous Opposing Cardinal Directions) cleaning.
Set via profile JSON `stick.socd_mode` or the `set_socd_mode` serial command.

| Mode          | Behavior                                   |
|---------------|--------------------------------------------|
| `neutral`     | Both directions cancel (default; safest)   |
| `last_input`  | Most recently pressed direction wins       |
| `first_input` | First pressed direction holds until released |

## Rapid trigger (stick hysteresis)

To prevent flickering when a stick hovers near the deadzone threshold, the firmware
supports separate activation and deactivation thresholds creating a hysteresis band.
Set via profile JSON `stick.rapid_trigger` or the `set_rapid_trigger` serial command.

| Parameter     | Default | Description                                     |
|---------------|---------|-------------------------------------------------|
| `activation`  | 30      | Threshold to activate direction (stick → key on) |
| `deactivation`| 20      | Threshold to deactivate (key off; must be ≤ activation) |

When a direction is inactive, the stick must exceed the activation threshold to turn on.
Once active, it stays on until the value drops below the deactivation threshold.

## Macro step types

Macro steps are defined in the profile `macros[].steps` array. Each step has a `type` field:

| Type            | Fields                          | Description                                |
|-----------------|---------------------------------|--------------------------------------------|
| `key`           | `key_id` (0–127), `pressed`     | Press or release a keyboard key            |
| `delay`         | `ms` (0–5000)                   | Wait (with humanized jitter)               |
| `mouse_button`  | `button` (1–31), `pressed`      | Press or release a USB HID mouse button    |
| `mouse_move`    | `dx` (-127–127), `dy` (-127–127)| Move the mouse cursor (hardware HID)       |
| `macro_chain`   | `id` (string)                   | Enqueue another macro to run after this one |

### Mouse button values

| Button         | Value |
|----------------|-------|
| Left           | 1     |
| Right          | 2     |
| Middle         | 4     |
| Back / Button4 | 8     |
| Forward / Button5 | 16 |

### Macro chaining example

```json
{
  "macros": [
    {"id": "combo1", "steps": [
      {"type": "key", "key_id": 1, "pressed": true},
      {"type": "delay", "ms": 50},
      {"type": "key", "key_id": 1, "pressed": false},
      {"type": "macro_chain", "id": "combo2"}
    ]},
    {"id": "combo2", "steps": [
      {"type": "mouse_button", "button": 1, "pressed": true},
      {"type": "delay", "ms": 30},
      {"type": "mouse_button", "button": 1, "pressed": false}
    ]}
  ]
}
```

### Mouse movement macro example

```json
{
  "macros": [
    {"id": "flick_shot", "steps": [
      {"type": "mouse_move", "dx": 50, "dy": 0},
      {"type": "delay", "ms": 16},
      {"type": "mouse_button", "button": 1, "pressed": true},
      {"type": "delay", "ms": 30},
      {"type": "mouse_button", "button": 1, "pressed": false},
      {"type": "mouse_move", "dx": -50, "dy": 0}
    ]}
  ]
}
```

## Timing humanization

Macros and turbo repeat use randomized timing jitter to avoid perfectly regular intervals
that anti-cheat software could detect:

- **Macro delays**: ±15% random jitter on each delay step
- **Turbo repeats**: ±10% random jitter on each press/release cycle (one-shot timer re-arm)

Controlled by the profile JSON `"humanize": true` field or the `set_humanize` serial command.
Enabled by default.

## Motion / IMU gesture detection

When the Joy-Con sends 0x30 reports with IMU data (bytes 13-48), the firmware
detects motion gestures and emits them as key events:

- **Shake**: high acceleration magnitude exceeding threshold (any axis).
- **Tilt**: sustained acceleration offset on X or Y axis.
- **Flick**: high gyroscope angular velocity (quick twist).

All gestures use a cooldown timer (250ms default) to prevent rapid re-triggering.
Motion key IDs (26-31) can be remapped like any other key.

This approach adapts to individual controller stick drift and range variations (inspired by the `StickCal` pattern from GamepadPhoenix).

## Sniper button (sensitivity override)

Mapping type `sniper` temporarily overrides mouse sensitivity while held.
Useful for precision aiming in FPS games — like Razer/Logitech DPI-shift.

```json
{"type": "sniper", "sensitivity": 3}
```

When the button is held, sensitivity drops to the configured value (default: 3).
On release, the previous sensitivity is restored. All processing happens on the
ESP32-S3 hardware — anti-cheat safe.

## DPI cycling

Mapping type `dpi_cycle` cycles through a list of sensitivity presets on each press.
Like the DPI button found on every gaming mouse, but executed entirely in hardware.

```json
{"type": "dpi_cycle"}
```

Presets are configured at the profile root:

```json
{"dpi_presets": [5, 10, 20, 30, 50]}
```

Each press advances to the next preset. Wraps around to the first after the last.

## Custom remapping via `remap_hid`

The profile mapping type `remap_hid` bypasses the compiled `keymap.c` table entirely and sends an arbitrary USB HID modifier + keycode.

### Example profile mapping

```json
{
  "mappings": {
    "1": {"type": "remap_hid", "mod": 0, "keycode": 20}
  }
}
```

This maps key_id 1 (Forward) directly to HID keycode 0x14 = `Q`.

### Common HID keycodes

| Key | Keycode (hex) | Key | Keycode (hex) |
|-----|---------------|-----|---------------|
| A   | 0x04          | 1   | 0x1E          |
| B   | 0x05          | 2   | 0x1F          |
| W   | 0x1A          | Space | 0x2C        |
| Z   | 0x1D          | Enter | 0x28        |

Full table: USB HID Usage Tables, section 10 (Keyboard/Keypad Page).

### Modifier bitmask

| Bit  | Modifier    |
|------|-------------|
| 0x01 | Left Ctrl   |
| 0x02 | Left Shift  |
| 0x04 | Left Alt    |
| 0x08 | Left GUI    |
| 0x10 | Right Ctrl  |
| 0x20 | Right Shift |
| 0x40 | Right Alt   |
| 0x80 | Right GUI   |

### Press-to-bind (helper app)

The helper app's Controller tab supports **unified click-to-bind**: click a hotspot on the controller diagram and the app immediately enters the appropriate mode:

- If the hotspot has no learned `key_id`, it enters **learn mode** — press the controller button to associate it.
- If the hotspot has a `key_id`, it enters **bind mode** — press any keyboard key to remap it via `remap_hid`.

Right-click a hotspot for additional options: Learn, Bind, Reset to passthrough, Clear binding, or Disable.

Active hotspots use a **pulse animation** to indicate the currently pressed controller button in real time.

### Tap-hold mapping

A single button can produce different actions depending on press duration:

```json
{"type": "tap_hold", "tap": {"type": "passthrough"}, "hold": {"type": "remap_hid", "mod": 2, "keycode": 0}, "hold_ms": 300}
```

The `hold_ms` threshold (default 300 ms) separates a quick tap from a long hold.

### Chording

Multiple buttons pressed simultaneously can trigger a combined action:

```json
{"chords": [{"keys": [1, 2], "action": {"type": "remap_hid", "mod": 0, "keycode": 40}}]}
```

Chords are evaluated before individual key mappings. See `helper-app/protocol.md` for the full schema.

## Layers

Profiles can define up to 4 overlay layers. Each layer is activated by holding (or toggling) a controller button, and overrides specific key mappings while active. See `helper-app/protocol.md` for the full layer schema.

## Auto-shift

Quick tap sends one keycode; holding past a threshold sends the shifted variant:

```json
{"type": "auto_shift", "normal": {"mod": 0, "keycode": 4}, "shifted": {"mod": 2, "keycode": 4}, "hold_ms": 200}
```

## Mouse button mapping

Maps a controller button to a real USB HID mouse button:

```json
{"type": "mouse_button", "button": 1}
```

Button values: `1` = left, `2` = right, `4` = middle.

## Sequential / cycle button

Each press sends the next output in a list, wrapping around:

```json
{"type": "sequential", "outputs": [{"mod": 0, "keycode": 30}, {"mod": 0, "keycode": 31}]}
```

## Leader key sequences

Designate a key as a leader key. After pressing it, subsequent key presses within 1 second are buffered and matched against configured sequences. Define sequences in the profile root:

```json
{
  "leader_sequences": [
    {"keys": [8, 9], "action": {"mod": 0, "keycode": 40}}
  ]
}
```

## Profile switching

Switch the active profile slot on-the-fly from the controller:

```json
{"type": "profile_switch", "slot": 2}
```

Works as a standalone mapping or as a chord action. Slots: 0–3.

## Right stick modes

Set `right_stick_mode` in the profile root to control right stick behavior:

- `"keys"` — virtual direction keys (default)
- `"mouse"` — mouse cursor movement (scaled by `mouse_sensitivity`, 1–50)
- `"scroll"` — scroll wheel

## Sprint zone

Automatically press a sprint key when the left stick exceeds a deflection threshold:

```json
{
  "sprint_zone": {
    "enabled": true,
    "threshold": 90,
    "key": {"mod": 0, "keycode": 0xE1}
  }
}
```

## Conflict detection

The helper app detects when multiple hotspots produce the same output key and highlights them in red. An **auto-fix** button is available to resolve conflicts by keeping the first binding and clearing duplicates.

If you tell me your exact preferred layout (including extra buttons like reload, use, etc.) I’ll update the mapping tables accordingly.
