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
	UART_FRAME_BATTERY = 6,   // payload[0]==0xFA, battery level from ESP32
	UART_FRAME_CONTROLLER_INFO = 7, // payload[0]==0xF9, controller info from ESP32
	UART_FRAME_RSSI = 8,          // payload[0]==0xF8, BT RSSI from ESP32
	UART_FRAME_ANALOG = 9,        // payload[0]==0xF7, analog stick data from ESP32
	UART_FRAME_GYRO = 10,         // payload[0]==0xF6, raw gyro data from ESP32
	UART_FRAME_UNKNOWN = 255,
} uart_frame_type_t;

typedef struct {
	uart_frame_type_t type;
	uint8_t length;
	const uint8_t* payload; // points to internal storage valid until next poll
} uart_frame_t;

// Poll for any decoded UART frame (key/debug/status).
bool uart_proto_poll_frame(uart_frame_t* out);

// Send a control command frame from the ESP32-S3 to the ESP32 BT host.
// Payload format: [0]=0xFE (ctrl marker), [1]=cmd_id, [2..]=cmd payload.
bool uart_proto_send_ctrl(uint8_t cmd_id, const uint8_t* data, uint8_t data_len);

void uart_proto_init(void);

// Block until UART data arrives or timeout_ticks expires.
// Returns true if UART data woke the task, false on timeout.
// Use instead of vTaskDelay() in the main loop for immediate wake-up.
bool uart_proto_wait(uint32_t timeout_ticks);
