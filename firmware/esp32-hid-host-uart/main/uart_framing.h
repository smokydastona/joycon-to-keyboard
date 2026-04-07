#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "joycon_setup.h"  // For joycon_colors_t, joycon_stick_params_t, joycon_imu_cal_t

// Sends a single key event to the USB-keyboard-side device (ESP32-S3).
// key_id: 0..127
// pressed: true=down, false=up
void bridge_send_key_event(uint8_t key_id, bool pressed);

// Extended key event (for multi-device sources).
// device_id: 0=left/primary, 1=right/secondary
// base_key_id: 0..127 (7-bit). The receiver may expand this into a larger
// input key_id space (e.g. right side = 128..255).
void bridge_send_key_event_ex(uint8_t device_id, uint8_t base_key_id, bool pressed);

// Sends a debug frame (length > 1) containing raw HID report bytes.
// This is for offline capture and evidence-based mapper development.
// The ESP32-S3 receiver ignores frames where length != 1.
void bridge_send_debug_hid_report(const uint8_t* report, uint16_t report_len);

// Sends a status frame (length > 1) describing the BT host state.
// Payload format:
//   [0] = 0xFD (status marker)
//   [1] = status_id
//   [2..7] = device BDA (6 bytes, or 00..00 if unknown)
//   [8] = name_len
//   [9..] = UTF-8 bytes of device name (truncated)
// Status IDs (current):
//   1 discovering, 2 found, 3 connecting, 4 connected, 5 disconnected
void bridge_send_bt_status(uint8_t status_id, const uint8_t* bda6, const char* name);

// Sends an OTA response frame back to the ESP32-S3.
// Payload format:
//   [0] = 0xFB (OTA response marker)
//   [1] = rsp_id
//   [2] = status (0x00 = ok, 0x01 = error)
//   [3..] = optional data
// rsp_ids: 0x01=begin, 0x02=data_ack (unused), 0x03=end, 0x04=version
void bridge_send_ota_rsp(uint8_t rsp_id, uint8_t status, const uint8_t* data, uint8_t data_len);

// Sends a battery level frame to the ESP32-S3.
// Payload format:
//   [0] = 0xFA (battery marker)
//   [1] = device_id (0=left, 1=right)
//   [2] = battery level (0=empty, 1-3=charging, 4=full)
void bridge_send_battery(uint8_t device_id, uint8_t level);

// Sends a controller info frame to the ESP32-S3.
// Contains: controller type, serial number, body/button colors,
//   stick deadzone parameters, IMU calibration data.
// Payload format:
//   [0] = 0xF9 (controller info marker)
//   [1] = device_id (0=left, 1=right)
//   [2] = controller_type (1=JCL, 2=JCR, 3=Pro)
//   [3] = serial_len (0 if no serial)
//   [4..4+serial_len-1] = serial ASCII (max 15)
//   next 1 byte: has_colors (0/1)
//   if has_colors: 6 bytes (body_rgb + button_rgb)
//   next 1 byte: has_stick_params (0/1)
//   if has_stick_params: 4 bytes (deadzone u16le, range_ratio u16le)
//   next 1 byte: has_imu_cal (0/1)
//   if has_imu_cal: 24 bytes (12 Int16LE values)
void bridge_send_controller_info(uint8_t device_id, uint8_t controller_type,
                                 const char *serial,
                                 const joycon_colors_t *colors,
                                 const joycon_stick_params_t *stick_params,
                                 const joycon_imu_cal_t *imu_cal);

// Sends a BT RSSI (signal strength) frame to the ESP32-S3.
// Payload format:
//   [0] = 0xF8 (RSSI marker)
//   [1] = device_id (0=left, 1=right)
//   [2] = rssi (int8_t, dBm, signed)
void bridge_send_rssi(uint8_t device_id, int8_t rssi);

// Sends analog stick data to the ESP32-S3 for mouse/scroll processing.
// Payload format:
//   [0] = 0xF7 (analog marker)
//   [1] = device_id (0=left, 1=right)
//   [2..3] = x (int16_t LE, normalized -4096..+4096)
//   [4..5] = y (int16_t LE, normalized -4096..+4096)
void bridge_send_analog(uint8_t device_id, int16_t x, int16_t y);
