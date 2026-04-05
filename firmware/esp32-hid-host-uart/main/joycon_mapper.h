#pragma once

#include <stdbool.h>
#include <stdint.h>

// Logical keys (key_id) matching docs/keymap.md.
// IDs 1-7: movement + modifiers (original).
// IDs 8-21: face buttons, shoulders, triggers, system, stick clicks.
// IDs 22-25: right stick virtual directions.
enum {
    KEY_ID_FORWARD   = 1,
    KEY_ID_BACK      = 2,
    KEY_ID_LEFT      = 3,
    KEY_ID_RIGHT     = 4,
    KEY_ID_JUMP      = 5,
    KEY_ID_SPRINT    = 6,
    KEY_ID_CROUCH    = 7,

    // Face buttons
    KEY_ID_BTN_A     = 8,
    KEY_ID_BTN_B     = 9,
    KEY_ID_BTN_X     = 10,
    KEY_ID_BTN_Y     = 11,

    // Shoulder / trigger buttons
    KEY_ID_BTN_L     = 12,
    KEY_ID_BTN_R     = 13,
    KEY_ID_BTN_ZL    = 14,
    KEY_ID_BTN_ZR    = 15,

    // System buttons
    KEY_ID_BTN_PLUS  = 16,
    KEY_ID_BTN_MINUS = 17,
    KEY_ID_BTN_HOME  = 18,
    KEY_ID_BTN_CAPTURE = 19,

    // Stick clicks
    KEY_ID_LSTICK_CLICK = 20,
    KEY_ID_RSTICK_CLICK = 21,

    // Right stick virtual WASD
    KEY_ID_RSTICK_UP    = 22,
    KEY_ID_RSTICK_DOWN  = 23,
    KEY_ID_RSTICK_LEFT  = 24,
    KEY_ID_RSTICK_RIGHT = 25,
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
