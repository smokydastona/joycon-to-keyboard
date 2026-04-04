# UART protocol (ESP32 → RP2040)

This is a tiny framing format so the RP2040 can act as the only USB device.

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

`key_id` is mapped to a USB HID keycode + modifier inside the RP2040 firmware.

## Why this design

- Keeps ESP32 code simple: it only needs to emit key_id up/down.
- Keeps RP2040 HID logic deterministic and fast.
