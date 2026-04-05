# Key mapping

This repo is set up for a minimal WASD + modifiers mapping.

## Logical actions (key_id)

- `1` = Forward
- `2` = Back
- `3` = Left
- `4` = Right
- `5` = Jump
- `6` = Sprint
- `7` = Crouch

## Default USB outputs

- Forward  -> `W`
- Back     -> `S`
- Left     -> `A`
- Right    -> `D`
- Jump     -> `Space`
- Sprint   -> `Left Shift`
- Crouch   -> `Left Ctrl`

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

## Conflict detection

The helper app detects when multiple hotspots produce the same output key and highlights them in red. An **auto-fix** button is available to resolve conflicts by keeping the first binding and clearing duplicates.

If you tell me your exact preferred layout (including extra buttons like reload, use, etc.) I’ll update the mapping tables accordingly.
