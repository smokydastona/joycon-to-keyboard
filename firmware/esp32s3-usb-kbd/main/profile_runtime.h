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
void profile_runtime_handle_input(bool pressed, uint16_t key_id);

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

// Start gyro calibration: collects N samples at rest and computes bias offsets.
// Returns true if started, false if already in progress.
bool profile_runtime_start_gyro_cal(void);

// Check if calibration is currently running.
bool profile_runtime_gyro_cal_active(void);

// Retrieve current gyro bias offsets (populated after calibration or NVS load).
void profile_runtime_get_gyro_bias(int16_t *bx, int16_t *by, int16_t *bz);

// Set gyro bias offsets manually (e.g. from helper-app or NVS restore).
void profile_runtime_set_gyro_bias(int16_t bx, int16_t by, int16_t bz);

// Send an LED pattern command to the ESP32 host via UART control channel.
// pattern: 0=off, 1=solid, 2=blink, 3=pulse, 4=rainbow
// r,g,b: colour (0-255); speed: blink/pulse speed in ms
void profile_runtime_set_led(uint8_t pattern, uint8_t r, uint8_t g, uint8_t b, uint16_t speed);
