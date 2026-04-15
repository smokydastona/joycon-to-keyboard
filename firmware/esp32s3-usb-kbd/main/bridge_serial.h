#pragma once

#include <stdbool.h>
#include <stdint.h>

// USB CDC (serial) protocol for the helper app.
// Transport: TinyUSB CDC-ACM.
// Framing: NDJSON (one JSON object per line).

void bridge_serial_init(void);
void bridge_serial_poll(void);

void bridge_serial_emit_mapped_key(bool pressed, uint16_t key_id);
void bridge_serial_emit_macro_state(const char *id, bool started);

// Emit a layer activation/deactivation event for the helper app UI.
void bridge_serial_emit_layer_state(const char *name, bool active);

// Emit a BT host status update for the helper app UI.
// state: short string like "discovering", "connecting", "connected", ...
// name/bda_str may be NULL.
void bridge_serial_emit_bt_status(const char *state, const char *name, const char *bda_str);

// Handle an OTA response frame received from the ESP32 BT host via UART.
// payload[0]=0xFB, [1]=rsp_id, [2]=status, [3..]=optional data
void bridge_serial_handle_ota_rsp(const uint8_t *payload, uint8_t length);

// Handle a control response frame received from the ESP32 BT host via UART.
// payload[0]=0xF5, [1]=rsp_id, [2]=status, [3..]=optional data
void bridge_serial_handle_ctrl_rsp(const uint8_t *payload, uint8_t length);

// Emit a battery level event for the helper app UI.
// device_id: 0=left, 1=right. level: 0=empty, 1-3=mid, 4=full.
void bridge_serial_emit_battery(uint8_t device_id, uint8_t level);

// Emit a controller info event (serial, colors, stick params, IMU cal).
// payload/length: raw UART frame payload starting with 0xF9 marker.
void bridge_serial_emit_controller_info(const uint8_t *payload, uint8_t length);

// Emit a BT RSSI (signal strength) event as NDJSON.
void bridge_serial_emit_rssi(uint8_t device_id, int8_t rssi);
