#pragma once

#include <stdbool.h>
#include <stdint.h>

// Controller types reported by Joy-Con / Pro Controller device info.
typedef enum {
    JOYCON_TYPE_UNKNOWN = 0,
    JOYCON_TYPE_LEFT    = 1,  // Joy-Con (L)
    JOYCON_TYPE_RIGHT   = 2,  // Joy-Con (R)
    JOYCON_TYPE_PRO     = 3,  // Pro Controller
} joycon_controller_type_t;

// Stick calibration data read from SPI flash.
typedef struct {
    int32_t min;
    int32_t center;
    int32_t max;
} joycon_stick_cal_axis_t;

typedef struct {
    joycon_stick_cal_axis_t lx, ly, rx, ry;
    bool valid;
} joycon_stick_cal_t;

// Called when a BT HID connection opens. Starts the setup FSM for this slot.
// handle: the HID host connection handle (used for sending output reports).
// device_id: 0=left, 1=right.
void joycon_setup_start(uint16_t handle, uint8_t device_id);

// Called when a BT HID connection closes. Tears down the FSM state.
void joycon_setup_stop(uint8_t device_id);

// Feed a 0x21 (subcmd reply) input report into the setup FSM.
// Returns true if the report was consumed by the FSM, false if setup is
// already complete and the report should be processed normally.
bool joycon_setup_on_report(uint8_t device_id, const uint8_t *report, uint16_t len);

// Returns the detected controller type (valid after device info reply).
joycon_controller_type_t joycon_setup_get_type(uint8_t device_id);

// Returns SPI flash stick calibration (valid after calibration reads complete).
const joycon_stick_cal_t *joycon_setup_get_stick_cal(uint8_t device_id);

// Returns battery level 0-4 (or -1 if unknown). Updated with every 0x30 report.
int joycon_setup_get_battery(uint8_t device_id);

// Update battery from a standard 0x30 report's bat_con byte.
void joycon_setup_update_battery(uint8_t device_id, uint8_t bat_con);

// Returns true when setup is complete and the controller is ready for input.
bool joycon_setup_is_ready(uint8_t device_id);
