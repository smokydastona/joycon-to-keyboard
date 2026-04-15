#pragma once

#include <stdbool.h>
#include <stdint.h>

// Composite USB HID gamepad (HID instance 1, report ID 2).
// This is a standard HID gamepad so Steam Input can map it to XInput.

typedef enum {
	USB_GAMEPAD_OUTPUT_A = 1,
	USB_GAMEPAD_OUTPUT_B,
	USB_GAMEPAD_OUTPUT_X,
	USB_GAMEPAD_OUTPUT_Y,
	USB_GAMEPAD_OUTPUT_LB,
	USB_GAMEPAD_OUTPUT_RB,
	USB_GAMEPAD_OUTPUT_LT,
	USB_GAMEPAD_OUTPUT_RT,
	USB_GAMEPAD_OUTPUT_VIEW,
	USB_GAMEPAD_OUTPUT_MENU,
	USB_GAMEPAD_OUTPUT_L3,
	USB_GAMEPAD_OUTPUT_R3,
	USB_GAMEPAD_OUTPUT_XBOX,
	USB_GAMEPAD_OUTPUT_SHARE,
	USB_GAMEPAD_OUTPUT_P1,
	USB_GAMEPAD_OUTPUT_P2,
	USB_GAMEPAD_OUTPUT_P3,
	USB_GAMEPAD_OUTPUT_P4,
	USB_GAMEPAD_OUTPUT_DPAD_UP,
	USB_GAMEPAD_OUTPUT_DPAD_DOWN,
	USB_GAMEPAD_OUTPUT_DPAD_LEFT,
	USB_GAMEPAD_OUTPUT_DPAD_RIGHT,
} bind_bandit_gamepad_output_t;

void usb_gamepad_init(void);

// When disabled, the USB gamepad interface still enumerates, but the firmware
// stops sending gamepad reports.
void usb_gamepad_set_enabled(bool enabled);
bool usb_gamepad_get_enabled(void);

// key_id uses the expanded multi-device space: key_id = device_id*128 + base_key_id.
void usb_gamepad_handle_key(bool pressed, uint16_t key_id);

// Drive a virtual gamepad control from the profile runtime.
void usb_gamepad_set_virtual_button(uint8_t output, bool pressed);

// device_id matches UART analog frames:
// - bit 7 clear: left stick for device (0..4)
// - bit 7 set:   right stick for device (0..4)
// x/y are int16 normalized roughly -4096..+4096.
void usb_gamepad_handle_analog(uint8_t device_id, int16_t x, int16_t y);
