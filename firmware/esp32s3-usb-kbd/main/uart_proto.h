#pragma once

#include <stdbool.h>
#include <stdint.h>

// UART framing is shared with the ESP32 BT host side:
//   AA 55 <len> <payload...> <checksum>
// checksum = XOR of len and payload bytes.

typedef enum {
	UART_FRAME_KEY_EVENT = 1, // len==1, payload[0]=event
	UART_FRAME_KEY_EVENT_EX = 4, // len==4, payload[0]==0xFC
	UART_FRAME_DEBUG = 2,     // payload[0]==0xFF
	UART_FRAME_STATUS = 3,    // payload[0]==0xFD
	UART_FRAME_OTA_RSP = 5,  // payload[0]==0xFB, OTA response from ESP32
	UART_FRAME_UNKNOWN = 255,
} uart_frame_type_t;

typedef struct {
	uart_frame_type_t type;
	uint8_t length;
	const uint8_t* payload; // points to internal storage valid until next poll
} uart_frame_t;

// Poll for any decoded UART frame (key/debug/status).
bool uart_proto_poll_frame(uart_frame_t* out);

// Poll for a decoded key event frame.
// event_byte format:
//   bit 7: pressed (1=down)
//   bits 6..0: key_id
bool uart_proto_poll_event(uint8_t* event_byte);

// Send a control command frame from the ESP32-S3 to the ESP32 BT host.
// Payload format: [0]=0xFE (ctrl marker), [1]=cmd_id, [2..]=cmd payload.
bool uart_proto_send_ctrl(uint8_t cmd_id, const uint8_t* data, uint8_t data_len);

void uart_proto_init(void);
