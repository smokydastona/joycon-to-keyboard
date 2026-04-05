#pragma once

#include <stdbool.h>
#include <stdint.h>

// Sends a single key event to the USB-keyboard-side device (ESP32-S3).
// key_id: 0..127
// pressed: true=down, false=up
void bridge_send_key_event(uint8_t key_id, bool pressed);

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
