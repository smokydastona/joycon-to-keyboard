#pragma once

#include <stdbool.h>
#include <stdint.h>

// Initialize the USB mouse subsystem (creates mutex). Call once at startup.
void usb_mouse_init(void);

// Move the USB HID mouse cursor by (dx, dy) pixels.
// Values are clamped to int8_t range (-127..127).
void usb_mouse_move(int16_t dx, int16_t dy);

// Scroll the mouse wheel by delta (positive = up, negative = down).
void usb_mouse_scroll(int8_t vertical, int8_t horizontal);

// Press or release a mouse button.
// button: MOUSE_BUTTON_LEFT (1), MOUSE_BUTTON_RIGHT (2),
//         MOUSE_BUTTON_MIDDLE (4), MOUSE_BUTTON_BACKWARD (8),
//         MOUSE_BUTTON_FORWARD (16).
void usb_mouse_button(uint8_t button, bool pressed);
