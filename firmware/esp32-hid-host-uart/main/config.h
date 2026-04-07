#pragma once

// UART to USB keyboard device (ESP32-S3)
#define BRIDGE_UART_PORT UART_NUM_2
#define BRIDGE_UART_BAUD 921600

// Common ESP32 dev board pins (adjust as needed)
#define BRIDGE_UART_TX_GPIO 17
#define BRIDGE_UART_RX_GPIO 16

// UART protocol
#define BRIDGE_SYNC0 0xAA
#define BRIDGE_SYNC1 0x55
