#pragma once

#include <stdbool.h>
#include <stdint.h>

// Minimal, signature-gated parser for a common Nintendo-style input report.
//
// This is intentionally optional and conservative:
// - It only claims success when the report matches a known signature.
// - It does not attempt to do any Joy-Con handshake or mode switching.
// - It is meant to *help* interpret captured bytes, not replace evidence.

// --- Button bitmasks for 0x30 reports ---
// Publicly documented layout used by Switch Pro Controller / Joy-Con.

// buttons1 (report[3]) — Right-side buttons
#define NIN_BTN1_Y           0x01
#define NIN_BTN1_X           0x02
#define NIN_BTN1_B           0x04
#define NIN_BTN1_A           0x08
#define NIN_BTN1_SR_R        0x10
#define NIN_BTN1_SL_R        0x20
#define NIN_BTN1_R           0x40
#define NIN_BTN1_ZR          0x80

// buttons2 (report[4]) — Shared / system buttons
#define NIN_BTN2_MINUS       0x01
#define NIN_BTN2_PLUS        0x02
#define NIN_BTN2_RSTICK      0x04
#define NIN_BTN2_LSTICK      0x08
#define NIN_BTN2_HOME        0x10
#define NIN_BTN2_CAPTURE     0x20

// buttons3 (report[5]) — Left-side buttons / D-pad
#define NIN_BTN3_DPAD_DOWN   0x01
#define NIN_BTN3_DPAD_UP     0x02
#define NIN_BTN3_DPAD_RIGHT  0x04
#define NIN_BTN3_DPAD_LEFT   0x08
#define NIN_BTN3_SR_L        0x10
#define NIN_BTN3_SL_L        0x20
#define NIN_BTN3_L           0x40
#define NIN_BTN3_ZL          0x80

typedef struct {
    uint8_t report_id;
    uint8_t buttons1;
    uint8_t buttons2;
    uint8_t buttons3;
    uint16_t lx;
    uint16_t ly;
    uint16_t rx;
    uint16_t ry;
    // IMU data: 3 samples of 6-axis (accel xyz, gyro xyz), each int16.
    // Only valid when has_imu == true (report length >= 49).
    bool has_imu;
    int16_t accel[3][3];  // [sample][axis: x,y,z]
    int16_t gyro[3][3];   // [sample][axis: x,y,z]
} nintendo_0x30_state_t;

// Try to parse a Nintendo-style 0x30 input report.
//
// Returns true only if the input looks like a 0x30 report and the expected
// byte layout exists.
bool nintendo_try_parse_0x30(const uint8_t* report, uint16_t len, nintendo_0x30_state_t* out);
