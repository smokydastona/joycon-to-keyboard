#pragma once

#include <stdbool.h>
#include <stdint.h>

// Starts a small UART RX task that listens for framed control commands
// from the ESP32-S3 helper-app bridge.
//
// Control frame payload format (len > 1):
//   [0] = 0xFE (ctrl marker)
//   [1] = cmd_id
//   [2..] = cmd payload
void bridge_ctrl_init(void);
