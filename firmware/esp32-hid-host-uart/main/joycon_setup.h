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

// Controller body/button colors read from SPI flash.
typedef struct {
    uint8_t body_r, body_g, body_b;
    uint8_t button_r, button_g, button_b;
    bool valid;
} joycon_colors_t;

// Stick device parameters (deadzone/range) read from SPI flash.
typedef struct {
    uint16_t deadzone;
    uint16_t range_ratio;
    bool valid;
} joycon_stick_params_t;

// IMU calibration data read from SPI flash (factory or user).
typedef struct {
    int16_t acc_origin[3];   // Accelerometer XYZ origin
    int16_t acc_sens[3];     // Accelerometer XYZ sensitivity coefficient
    int16_t gyro_origin[3];  // Gyroscope XYZ origin
    int16_t gyro_sens[3];    // Gyroscope XYZ sensitivity coefficient
    bool valid;
} joycon_imu_cal_t;

// Called when a BT HID connection opens. Starts the setup FSM for this slot.
// handle: the HID host connection handle (used for handle-guarding only).
// device_id: 0=left, 1=right.
// bda: 6-byte Bluetooth Device Address (used for esp_bt_hid_host_send_data).
void joycon_setup_start(uint16_t handle, uint8_t device_id, const uint8_t bda[6]);

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

// Returns controller body/button colors (valid after color read).
const joycon_colors_t *joycon_setup_get_colors(uint8_t device_id);

// Returns stick deadzone parameters (valid after param read).
const joycon_stick_params_t *joycon_setup_get_stick_params(uint8_t device_id);

// Returns IMU calibration data (valid after cal reads).
const joycon_imu_cal_t *joycon_setup_get_imu_cal(uint8_t device_id);

// Returns the serial number string (up to 15 chars), or NULL if not read.
const char *joycon_setup_get_serial(uint8_t device_id);

// Returns battery level 0-4 (or -1 if unknown). Updated with every 0x30 report.
int joycon_setup_get_battery(uint8_t device_id);

// Update battery from a standard 0x30 report's bat_con byte.
void joycon_setup_update_battery(uint8_t device_id, uint8_t bat_con);

// Returns true when setup is complete and the controller is ready for input.
bool joycon_setup_is_ready(uint8_t device_id);

// Check all setup instances for FSM timeouts.  Call periodically from the
// main loop (e.g. every ~500 ms) so a lost subcmd reply doesn't stall setup.
void joycon_setup_check_timeouts(void);

// Send an HD Rumble command to the controller.
// freq_hz: frequency in Hz (40-1253), amp_100: amplitude * 100 (0-100).
void joycon_setup_send_rumble(uint8_t device_id, uint16_t freq_hz, uint8_t amp_100);

// Set the Home LED pattern on a Right Joy-Con.
// brightness: 0-15 (0=off, 15=max).
void joycon_setup_set_home_led(uint8_t device_id, uint8_t brightness);
