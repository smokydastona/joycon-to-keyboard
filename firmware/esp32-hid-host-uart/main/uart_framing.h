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
