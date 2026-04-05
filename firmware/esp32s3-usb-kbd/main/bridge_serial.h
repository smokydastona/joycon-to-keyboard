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
