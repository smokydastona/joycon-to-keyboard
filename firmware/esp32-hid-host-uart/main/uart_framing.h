#pragma once

#include <stdbool.h>
#include <stdint.h>

// Sends a single key event to RP2040.
// key_id: 0..127
// pressed: true=down, false=up
void bridge_send_key_event(uint8_t key_id, bool pressed);
