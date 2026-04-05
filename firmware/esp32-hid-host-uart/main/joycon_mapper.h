#pragma once

#include <stdbool.h>
#include <stdint.h>

// Minimal logical keys (key_id) matching docs/keymap.md
enum {
    KEY_ID_FORWARD = 1,
    KEY_ID_BACK = 2,
    KEY_ID_LEFT = 3,
    KEY_ID_RIGHT = 4,
    KEY_ID_JUMP = 5,
    KEY_ID_SPRINT = 6,
    KEY_ID_CROUCH = 7,
};

// Feed raw HID report bytes into the mapper.
// This will emit key events over UART.
void joycon_mapper_on_report(const uint8_t* report, uint16_t len);

// Like joycon_mapper_on_report(), but tags emitted key events with a device_id.
// device_id=0 (left) uses the legacy 1-byte key event frames.
// device_id=1 (right) uses the extended key event frames.
void joycon_mapper_on_report_ex(uint8_t device_id, const uint8_t* report, uint16_t len);

// Allows overriding deadzone/thresholds later.
void joycon_mapper_set_stick_threshold(uint8_t threshold);
