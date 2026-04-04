#pragma once

#include <stdbool.h>
#include <stdint.h>

void usb_kbd_init(void);

// Update internal key state and send a keyboard report.
void usb_kbd_set_key(uint8_t modifier, uint8_t keycode, bool pressed);
