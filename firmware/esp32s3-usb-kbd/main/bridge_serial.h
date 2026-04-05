#pragma once

#include <stdbool.h>
#include <stdint.h>

// USB CDC (serial) protocol for the helper app.
// Transport: TinyUSB CDC-ACM.
// Framing: NDJSON (one JSON object per line).

void bridge_serial_init(void);
void bridge_serial_poll(void);

void bridge_serial_emit_mapped_key(bool pressed, uint8_t key_id);
void bridge_serial_emit_macro_state(const char *id, bool started);

// Emit a BT host status update for the helper app UI.
// state: short string like "discovering", "connecting", "connected", ...
// name/bda_str may be NULL.
void bridge_serial_emit_bt_status(const char *state, const char *name, const char *bda_str);

// Handle an OTA response frame received from the ESP32 BT host via UART.
// payload[0]=0xFB, [1]=rsp_id, [2]=status, [3..]=optional data
void bridge_serial_handle_ota_rsp(const uint8_t *payload, uint8_t length);
