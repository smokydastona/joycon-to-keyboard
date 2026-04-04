#include "joycon_mapper.h"

#include <string.h>

#include "uart_framing.h"

// NOTE:
// Joy-Con report formats vary by mode/handshake.
// This module intentionally starts conservative:
// - It does NOT assume a specific report layout.
// - It provides a placeholder hook so you can quickly wire in a known-good parser.
//
// Next step: once we capture real report bytes for your Joy-Con,
// implement parsing here and emit KEY_ID_* events.

static uint8_t s_threshold = 32;

void joycon_mapper_set_stick_threshold(uint8_t threshold) {
    s_threshold = threshold;
}

static void emit_if_changed(uint8_t key_id, bool now_pressed, bool* prev_pressed) {
    if (now_pressed != *prev_pressed) {
        bridge_send_key_event(key_id, now_pressed);
        *prev_pressed = now_pressed;
    }
}

void joycon_mapper_on_report(const uint8_t* report, uint16_t len) {
    (void)s_threshold;

    // Placeholder: treat certain byte patterns as demo-only.
    // This prevents "doing the wrong thing" with guessed Joy-Con layouts.
    //
    // If you run this as-is, it won't generate key presses.

    static bool prev_forward = false;
    static bool prev_back = false;
    static bool prev_left = false;
    static bool prev_right = false;

    if (report == NULL || len == 0) {
        return;
    }

    // TODO: Implement Joy-Con report parsing here.
    //
    // Suggested workflow:
    // 1) Flash ESP32 firmware and capture the first 25 reports from the serial monitor.
    // 2) Press ONE control at a time on the Joy-Con.
    // 3) Identify which bytes/bits toggle.
    // 4) Map those toggles to KEY_ID_* and call emit_if_changed(...).

    emit_if_changed(KEY_ID_FORWARD, false, &prev_forward);
    emit_if_changed(KEY_ID_BACK, false, &prev_back);
    emit_if_changed(KEY_ID_LEFT, false, &prev_left);
    emit_if_changed(KEY_ID_RIGHT, false, &prev_right);
}
