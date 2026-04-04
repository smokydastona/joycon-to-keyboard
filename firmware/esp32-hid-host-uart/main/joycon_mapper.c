#include "joycon_mapper.h"

#include <string.h>

#include "esp_log.h"

#include "uart_framing.h"

#if CONFIG_JOYCON_HOST_TRY_NINTENDO_0X30
#include "nintendo_candidate.h"
#endif

// NOTE:
// Joy-Con report formats vary by mode/handshake.
// This module intentionally starts conservative:
// - It does NOT assume a specific report layout.
// - It provides a placeholder hook so you can quickly wire in a known-good parser.
//
// Next step: once we capture real report bytes for your Joy-Con,
// implement parsing here and emit KEY_ID_* events.

static uint8_t s_threshold = 32;

static const char* TAG = "joycon-mapper";

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

#if CONFIG_JOYCON_HOST_TRY_NINTENDO_0X30
    // Optional: try interpret a common Nintendo-style report signature.
    // This is a *hint* layer for evidence-based development.
    nintendo_0x30_state_t st;
    if (nintendo_try_parse_0x30(report, len, &st)) {
        static nintendo_0x30_state_t last;
        static bool have_last = false;

        if (!have_last || memcmp(&last, &st, sizeof(st)) != 0) {
            ESP_LOGI(TAG, "nintendo 0x30: btn=%02X %02X %02X  LX=%u LY=%u  RX=%u RY=%u",
                     st.buttons1, st.buttons2, st.buttons3,
                     (unsigned)st.lx, (unsigned)st.ly, (unsigned)st.rx, (unsigned)st.ry);
            last = st;
            have_last = true;
        }

#if CONFIG_JOYCON_HOST_NINTENDO_0X30_EMIT_KEYS
        // Advanced mode: use left stick as WASD.
        // Keep disabled until you verify the parsed fields match real inputs.
        const int center = 2048;
        const int deadzone = ((int)s_threshold) << 3;  // simple scaling: 32 -> 256

        const int dx = (int)st.lx - center;
        const int dy = (int)st.ly - center;

        const bool now_right = dx > deadzone;
        const bool now_left = dx < -deadzone;
        const bool now_up = dy < -deadzone;
        const bool now_down = dy > deadzone;

        emit_if_changed(KEY_ID_FORWARD, now_up, &prev_forward);
        emit_if_changed(KEY_ID_BACK, now_down, &prev_back);
        emit_if_changed(KEY_ID_LEFT, now_left, &prev_left);
        emit_if_changed(KEY_ID_RIGHT, now_right, &prev_right);

        return;
#endif

        // If we successfully parsed, but key emission is disabled, stop here.
        // (We don't want to also run placeholder logic below.)
        return;
    }
#endif

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
