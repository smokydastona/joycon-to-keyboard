#pragma once

// UART configuration (ESP32 -> RP2040)
#define KBD_UART_ID uart0
#define KBD_UART_BAUD 115200

// Default Pico pinout: GPIO0=TX, GPIO1=RX
#define KBD_UART_TX_PIN 0
#define KBD_UART_RX_PIN 1

// UART protocol sync bytes
#define KBD_SYNC0 0xAA
#define KBD_SYNC1 0x55
