#pragma once

#include <stdbool.h>
#include <stdint.h>

// Poll for a decoded key event frame.
// event_byte format:
//   bit 7: pressed (1=down)
//   bits 6..0: key_id
bool uart_proto_poll_event(uint8_t* event_byte);

void uart_proto_init(void);
