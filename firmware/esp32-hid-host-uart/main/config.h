#pragma once

// UART to USB keyboard device (ESP32-S3)
#define BRIDGE_UART_PORT UART_NUM_2
#define BRIDGE_UART_BAUD 921600

// Hard limit for concurrently connected Bluetooth HID devices.
// Device IDs range 0..(BRIDGE_MAX_DEVICES-1).
#define BRIDGE_MAX_DEVICES 5

// Common ESP32 dev board pins (adjust as needed)
#define BRIDGE_UART_TX_GPIO 17
#define BRIDGE_UART_RX_GPIO 16

// Host-side first-install bridge to the Nano ESP32-S3 ROM bootloader.
// GPIO21 drives Nano B1 / GPIO0, GPIO22 drives Nano RESET.
#define INSTALLER_S3_BOOT_GPIO  CONFIG_BIND_BANDIT_INSTALLER_S3_BOOT_GPIO
#define INSTALLER_S3_RESET_GPIO CONFIG_BIND_BANDIT_INSTALLER_S3_RESET_GPIO

// Piezo buzzer (passive, LEDC PWM)
#define BUZZER_GPIO          CONFIG_BIND_BANDIT_BUZZER_GPIO
#define BUZZER_LEDC_CHANNEL  LEDC_CHANNEL_0
#define BUZZER_LEDC_TIMER    LEDC_TIMER_0

// UART protocol
#define BRIDGE_SYNC0 0xAA
#define BRIDGE_SYNC1 0x55
