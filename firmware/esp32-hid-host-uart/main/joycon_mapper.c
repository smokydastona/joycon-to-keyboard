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

static void emit_if_changed_ex(uint8_t device_id, uint8_t key_id, bool now_pressed, bool* prev_pressed) {
    if (now_pressed == *prev_pressed) return;

    if (device_id == 0) {
        bridge_send_key_event(key_id, now_pressed);
    } else {
        bridge_send_key_event_ex(device_id, key_id, now_pressed);
    }
    *prev_pressed = now_pressed;
}

// --- Stick auto-calibration ---
// Tracks min/center/max per axis and maps raw values to a normalized
// -1.0..+1.0 range. Inspired by GamepadPhoenix's StickCal approach.

typedef struct {
    uint16_t min;
    uint16_t center;
    uint16_t max;
    bool initialized;
} axis_cal_t;

typedef struct {
    axis_cal_t lx, ly, rx, ry;
    uint16_t sample_count;
} stick_cal_t;

#define CAL_WARMUP_SAMPLES 8  // first N samples establish center

static stick_cal_t s_cal = {0};

static void cal_update_axis(axis_cal_t* a, uint16_t raw) {
    if (!a->initialized) {
        a->min = raw;
        a->max = raw;
        a->center = raw;
        a->initialized = true;
        return;
    }
    if (raw < a->min) a->min = raw;
    if (raw > a->max) a->max = raw;
}

static void cal_update(stick_cal_t* c, const nintendo_0x30_state_t* st) {
    cal_update_axis(&c->lx, st->lx);
    cal_update_axis(&c->ly, st->ly);
    cal_update_axis(&c->rx, st->rx);
    cal_update_axis(&c->ry, st->ry);

    // During warmup, refine center as the average of first samples.
    if (c->sample_count < CAL_WARMUP_SAMPLES) {
        // Running average: center = center + (raw - center) / (n+1)
        uint16_t n = c->sample_count + 1;
        c->lx.center = (uint16_t)(c->lx.center + ((int)st->lx - (int)c->lx.center) / (int)n);
        c->ly.center = (uint16_t)(c->ly.center + ((int)st->ly - (int)c->ly.center) / (int)n);
        c->rx.center = (uint16_t)(c->rx.center + ((int)st->rx - (int)c->rx.center) / (int)n);
        c->ry.center = (uint16_t)(c->ry.center + ((int)st->ry - (int)c->ry.center) / (int)n);
    }

    if (c->sample_count < 0xFFFF) c->sample_count++;
}

// Returns normalized value in range roughly -4096..+4096 using calibration.
// Positive = above center, negative = below center.
static int cal_normalize(const axis_cal_t* a, uint16_t raw) {
    if (!a->initialized) return 0;

    int val = (int)raw - (int)a->center;

    // Scale based on which side of center we're on.
    int range;
    if (val > 0) {
        range = (int)a->max - (int)a->center;
    } else {
        range = (int)a->center - (int)a->min;
    }

    if (range < 32) return 0; // not enough data yet

    // Normalize to 4096 scale
    return (val * 4096) / range;
}

void joycon_mapper_on_report_ex(uint8_t device_id, const uint8_t* report, uint16_t len) {
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
        // --- Auto-calibration ---
        cal_update(&s_cal, &st);

        // --- Deadzone (scaled from threshold) ---
        const int deadzone = ((int)s_threshold) << 5;  // 32 -> 1024 on 4096 scale

        // --- Left stick → WASD ---
        {
            int dx = cal_normalize(&s_cal.lx, st.lx);
            int dy = cal_normalize(&s_cal.ly, st.ly);

            bool now_right = dx > deadzone;
            bool now_left  = dx < -deadzone;
            bool now_up    = dy < -deadzone;
            bool now_down  = dy > deadzone;

            emit_if_changed_ex(device_id, KEY_ID_FORWARD, now_up, &prev_forward);
            emit_if_changed_ex(device_id, KEY_ID_BACK, now_down, &prev_back);
            emit_if_changed_ex(device_id, KEY_ID_LEFT, now_left, &prev_left);
            emit_if_changed_ex(device_id, KEY_ID_RIGHT, now_right, &prev_right);
        }

        // --- Right stick → virtual directions ---
        {
            static bool prev_rup = false, prev_rdn = false;
            static bool prev_rlt = false, prev_rrt = false;

            int rdx = cal_normalize(&s_cal.rx, st.rx);
            int rdy = cal_normalize(&s_cal.ry, st.ry);

            emit_if_changed_ex(device_id, KEY_ID_RSTICK_UP,    rdy < -deadzone, &prev_rup);
            emit_if_changed_ex(device_id, KEY_ID_RSTICK_DOWN,  rdy >  deadzone, &prev_rdn);
            emit_if_changed_ex(device_id, KEY_ID_RSTICK_LEFT,  rdx < -deadzone, &prev_rlt);
            emit_if_changed_ex(device_id, KEY_ID_RSTICK_RIGHT, rdx >  deadzone, &prev_rrt);
        }

        // --- Face buttons ---
        {
            static bool prev_a = false, prev_b = false;
            static bool prev_x = false, prev_y = false;

            emit_if_changed_ex(device_id, KEY_ID_BTN_A, (st.buttons1 & NIN_BTN1_A) != 0, &prev_a);
            emit_if_changed_ex(device_id, KEY_ID_BTN_B, (st.buttons1 & NIN_BTN1_B) != 0, &prev_b);
            emit_if_changed_ex(device_id, KEY_ID_BTN_X, (st.buttons1 & NIN_BTN1_X) != 0, &prev_x);
            emit_if_changed_ex(device_id, KEY_ID_BTN_Y, (st.buttons1 & NIN_BTN1_Y) != 0, &prev_y);
        }

        // --- Shoulder / trigger buttons ---
        {
            static bool prev_l = false, prev_r = false;
            static bool prev_zl = false, prev_zr = false;

            emit_if_changed_ex(device_id, KEY_ID_BTN_L,  (st.buttons3 & NIN_BTN3_L)  != 0, &prev_l);
            emit_if_changed_ex(device_id, KEY_ID_BTN_R,  (st.buttons1 & NIN_BTN1_R)  != 0, &prev_r);
            emit_if_changed_ex(device_id, KEY_ID_BTN_ZL, (st.buttons3 & NIN_BTN3_ZL) != 0, &prev_zl);
            emit_if_changed_ex(device_id, KEY_ID_BTN_ZR, (st.buttons1 & NIN_BTN1_ZR) != 0, &prev_zr);
        }

        // --- System buttons ---
        {
            static bool prev_plus = false, prev_minus = false;
            static bool prev_home = false, prev_capture = false;

            emit_if_changed_ex(device_id, KEY_ID_BTN_PLUS,    (st.buttons2 & NIN_BTN2_PLUS)    != 0, &prev_plus);
            emit_if_changed_ex(device_id, KEY_ID_BTN_MINUS,   (st.buttons2 & NIN_BTN2_MINUS)   != 0, &prev_minus);
            emit_if_changed_ex(device_id, KEY_ID_BTN_HOME,    (st.buttons2 & NIN_BTN2_HOME)    != 0, &prev_home);
            emit_if_changed_ex(device_id, KEY_ID_BTN_CAPTURE, (st.buttons2 & NIN_BTN2_CAPTURE) != 0, &prev_capture);
        }

        // --- Stick clicks ---
        {
            static bool prev_ls = false, prev_rs = false;

            emit_if_changed_ex(device_id, KEY_ID_LSTICK_CLICK, (st.buttons2 & NIN_BTN2_LSTICK) != 0, &prev_ls);
            emit_if_changed_ex(device_id, KEY_ID_RSTICK_CLICK, (st.buttons2 & NIN_BTN2_RSTICK) != 0, &prev_rs);
        }

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

    emit_if_changed_ex(device_id, KEY_ID_FORWARD, false, &prev_forward);
    emit_if_changed_ex(device_id, KEY_ID_BACK, false, &prev_back);
    emit_if_changed_ex(device_id, KEY_ID_LEFT, false, &prev_left);
    emit_if_changed_ex(device_id, KEY_ID_RIGHT, false, &prev_right);
}

void joycon_mapper_on_report(const uint8_t* report, uint16_t len) {
    joycon_mapper_on_report_ex(0, report, len);
}
