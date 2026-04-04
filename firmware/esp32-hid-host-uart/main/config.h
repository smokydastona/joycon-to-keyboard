#pragma once

// UART to RP2040
#define BRIDGE_UART_PORT UART_NUM_2
#define BRIDGE_UART_BAUD 115200

// Common ESP32 dev board pins (adjust as needed)
#define BRIDGE_UART_TX_GPIO 17
#define BRIDGE_UART_RX_GPIO 16

// UART protocol
#define BRIDGE_SYNC0 0xAA
#define BRIDGE_SYNC1 0x55
