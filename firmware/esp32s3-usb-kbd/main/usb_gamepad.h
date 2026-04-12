#pragma once

#include <stdbool.h>
#include <stdint.h>

// Composite USB HID gamepad (HID instance 2).
// This is a standard HID gamepad so Steam Input can map it to XInput.

void usb_gamepad_init(void);

// key_id uses the expanded multi-device space: key_id = device_id*128 + base_key_id.
void usb_gamepad_handle_key(bool pressed, uint16_t key_id);

// device_id matches UART analog frames:
// - bit 7 clear: left stick for device (0..4)
// - bit 7 set:   right stick for device (0..4)
// x/y are int16 normalized roughly -4096..+4096.
void usb_gamepad_handle_analog(uint8_t device_id, int16_t x, int16_t y);
