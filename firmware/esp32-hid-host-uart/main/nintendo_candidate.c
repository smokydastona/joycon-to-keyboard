#include "nintendo_candidate.h"

#include <string.h>

// Publicly-known (and widely documented) layout for Nintendo-style 0x30 reports
// used by Switch Pro Controller / Joy-Con in certain modes.
//
// We do NOT assume all controllers use this.
// We only parse when the signature matches.

bool nintendo_try_parse_0x30(const uint8_t* report, uint16_t len, nintendo_0x30_state_t* out) {
    if (!report || !out) {
        return false;
    }

    // Typical length is 49 bytes. Allow >= 12 so truncated debug captures
    // can still be interpreted for buttons/sticks.
    if (len < 12) {
        return false;
    }

    if (report[0] != 0x30) {
        return false;
    }

    // Byte positions used by common documentation:
    // [3..5] buttons, [6..8] left stick, [9..11] right stick
    out->report_id = report[0];
    out->buttons1 = report[3];
    out->buttons2 = report[4];
    out->buttons3 = report[5];

    // 12-bit packed values.
    // X: low 8 bits in first byte, high 4 bits in low nibble of second.
    // Y: low 4 bits in high nibble of second, high 8 bits in third.
    out->lx = (uint16_t)report[6] | ((uint16_t)(report[7] & 0x0F) << 8);
    out->ly = ((uint16_t)(report[7] >> 4)) | ((uint16_t)report[8] << 4);

    out->rx = (uint16_t)report[9] | ((uint16_t)(report[10] & 0x0F) << 8);
    out->ry = ((uint16_t)(report[10] >> 4)) | ((uint16_t)report[11] << 4);

    // Parse IMU data if the report is long enough (49 bytes for full 0x30).
    // Bytes 13-48: 3 IMU samples, each 12 bytes (accel xyz + gyro xyz, int16 LE).
    out->has_imu = false;
    if (len >= 49) {
        out->has_imu = true;
        for (int sample = 0; sample < 3; sample++) {
            int base = 13 + sample * 12;
            // Accelerometer: 3 axes as int16 LE
            out->accel[sample][0] = (int16_t)((uint16_t)report[base + 0] | ((uint16_t)report[base + 1] << 8));
            out->accel[sample][1] = (int16_t)((uint16_t)report[base + 2] | ((uint16_t)report[base + 3] << 8));
            out->accel[sample][2] = (int16_t)((uint16_t)report[base + 4] | ((uint16_t)report[base + 5] << 8));
            // Gyroscope: 3 axes as int16 LE
            out->gyro[sample][0] = (int16_t)((uint16_t)report[base + 6] | ((uint16_t)report[base + 7] << 8));
            out->gyro[sample][1] = (int16_t)((uint16_t)report[base + 8] | ((uint16_t)report[base + 9] << 8));
            out->gyro[sample][2] = (int16_t)((uint16_t)report[base + 10] | ((uint16_t)report[base + 11] << 8));
        }
    }

    return true;
}
