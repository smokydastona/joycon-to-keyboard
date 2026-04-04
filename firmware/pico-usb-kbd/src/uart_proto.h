#pragma once

#include <stdbool.h>
#include <stdint.h>

// Returns true if a complete event was decoded.
// event_byte format:
//   bit 7: pressed
//   bits 6..0: key_id
bool uart_proto_poll_event(uint8_t* event_byte);
