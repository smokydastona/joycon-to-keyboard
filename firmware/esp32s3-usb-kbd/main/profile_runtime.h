#pragma once

#include <stdbool.h>
#include <stdint.h>

// Loads the active profile (from NVS) and applies it to incoming key_id events.
// Supports: disable/remap/remap_hid/macro-on-press, with optional layers.

void profile_runtime_init(void);

// Reloads active slot + active profile JSON from NVS.
// Safe to call after write_profile / set_active_profile.
void profile_runtime_reload(void);

// Handle an input key event (from UART): key_id up/down.
void profile_runtime_handle_input(bool pressed, uint8_t key_id);

// Anti-cheat humanization: adds timing jitter to macros/turbo.
void profile_runtime_set_humanize(bool enabled);
bool profile_runtime_get_humanize(void);

// Handle analog stick data from UART.
// device_id: 0=left stick, 0x80=right stick (bit7 marks right).
// x, y: normalized stick values (-4096..+4096).
void profile_runtime_handle_analog(uint8_t device_id, int16_t x, int16_t y);

// Handle raw gyroscope data from UART.
// device_id: 0=left Joy-Con, 1=right Joy-Con.
// gx, gy, gz: averaged raw gyro values (yaw, pitch, roll).
void profile_runtime_handle_gyro(uint8_t device_id, int16_t gx, int16_t gy, int16_t gz);
