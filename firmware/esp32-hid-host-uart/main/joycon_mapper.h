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

    // Motion / IMU gestures
    KEY_ID_MOTION_SHAKE     = 26,  // Sharp accel spike (any axis)
    KEY_ID_MOTION_TILT_UP   = 27,  // Sustained forward tilt
    KEY_ID_MOTION_TILT_DOWN = 28,  // Sustained backward tilt
    KEY_ID_MOTION_TILT_LEFT = 29,  // Sustained left tilt
    KEY_ID_MOTION_TILT_RIGHT = 30, // Sustained right tilt
    KEY_ID_MOTION_FLICK     = 31,  // Quick gyro flick (twist)
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

// Stick curve types applied to normalized stick values before the threshold test.
typedef enum {
    STICK_CURVE_LINEAR      = 0,
    STICK_CURVE_EXPONENTIAL = 1,  // applies pow(abs(x), exp) * sign(x)
    STICK_CURVE_QUADRATIC   = 2,  // applies x * abs(x)  (smooth ramp-up)
} stick_curve_t;

// Set the stick response curve.
// curve: one of STICK_CURVE_* enum values.
// exp_x100: exponent * 100 (e.g. 150 = 1.5). Only used for EXPONENTIAL.
void joycon_mapper_set_stick_curve(uint8_t curve, uint8_t exp_x100);

// Save current auto-calibration to NVS so it persists across reboots.
void joycon_mapper_save_calibration(void);

// Clear saved calibration from NVS (forces re-calibration on next boot).
void joycon_mapper_clear_calibration(void);

// SOCD (Simultaneous Opposing Cardinal Directions) cleaning modes.
typedef enum {
    SOCD_NEUTRAL     = 0,  // both cancel — safest for anti-cheat
    SOCD_LAST_INPUT  = 1,  // last pressed direction wins
    SOCD_FIRST_INPUT = 2,  // first pressed direction wins (holds)
} socd_mode_t;

void joycon_mapper_set_socd_mode(uint8_t mode);

// Rapid trigger: set separate activation / deactivation thresholds for
// stick-to-key hysteresis.  activation must be >= deactivation.
void joycon_mapper_set_rapid_trigger(uint8_t activation, uint8_t deactivation);

// Reset transient state (SOCD history, stick key states) — call on device
// connect/disconnect to prevent phantom directions from previous sessions.
void joycon_mapper_reset_state(void);
