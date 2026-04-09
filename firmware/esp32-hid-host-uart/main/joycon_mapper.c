#include "joycon_mapper.h"

#include <string.h>
#include <math.h>

#include "esp_log.h"

#include "esp_timer.h"

#include "uart_framing.h"
#include "joycon_setup.h"

#if CONFIG_JOYCON_HOST_TRY_NINTENDO_0X30
#include "nintendo_candidate.h"
#endif

#if CONFIG_JOYCON_HOST_NINTENDO_0X30_EMIT_KEYS
#include "nvs.h"
#include "nvs_flash.h"
#endif

// NOTE:
// Joy-Con report formats vary by mode/handshake.
// This module intentionally starts conservative:
// - It does NOT assume a specific report layout.
// - It provides a placeholder hook so you can quickly wire in a known-good parser.
//
// Next step: once we capture real report bytes for your Joy-Con,
// implement parsing here and emit KEY_ID_* events.

static uint8_t s_act_threshold  = 30;  // activation  (stick → key on)
static uint8_t s_deact_threshold = 20;  // deactivation (key off), hysteresis band

// --- Stick curve state ---
static stick_curve_t s_curve = STICK_CURVE_LINEAR;
static float s_exp = 1.0f;  // exponent for EXPONENTIAL curve

// --- SOCD cleaning mode ---
static socd_mode_t s_socd_mode = SOCD_NEUTRAL;

// History for SOCD last-input-wins: which direction was pressed most recently.
// <0 => negative (left/up), >0 => positive (right/down), 0 => neither.
static int8_t s_socd_lr_last = 0;   // left stick horizontal
static int8_t s_socd_ud_last = 0;   // left stick vertical
static int8_t s_socd_rlr_last = 0;  // right stick horizontal
static int8_t s_socd_rud_last = 0;  // right stick vertical

void joycon_mapper_set_socd_mode(uint8_t mode) {
    if (mode <= SOCD_FIRST_INPUT) {
        s_socd_mode = (socd_mode_t)mode;
    }
    ESP_LOGI("joycon-mapper", "SOCD mode=%d", (int)s_socd_mode);
}

void joycon_mapper_set_stick_threshold(uint8_t threshold) {
    s_act_threshold  = threshold;
    s_deact_threshold = threshold;
}

void joycon_mapper_set_rapid_trigger(uint8_t activation, uint8_t deactivation) {
    if (activation < 1) activation = 1;
    if (deactivation > activation) deactivation = activation;
    s_act_threshold  = activation;
    s_deact_threshold = deactivation;
    ESP_LOGI("joycon-mapper", "Rapid trigger act=%u deact=%u",
             (unsigned)s_act_threshold, (unsigned)s_deact_threshold);
}

void joycon_mapper_reset_state(void) {
    s_socd_lr_last  = 0;
    s_socd_ud_last  = 0;
    s_socd_rlr_last = 0;
    s_socd_rud_last = 0;
    ESP_LOGI("joycon-mapper", "Transient state reset (SOCD history cleared)");
}

void joycon_mapper_set_stick_curve(uint8_t curve, uint8_t exp_x100) {
    if (curve <= STICK_CURVE_QUADRATIC) {
        s_curve = (stick_curve_t)curve;
    }
    if (exp_x100 > 0) {
        s_exp = (float)exp_x100 / 100.0f;
    }
    ESP_LOGI("joycon-mapper", "Stick curve=%d exp=%.2f", (int)s_curve, (double)s_exp);
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

// SOCD clean an axis pair (neg = left/up, pos = right/down).
// Updates *last_dir history for last-input-wins mode.
static void socd_clean(bool *neg, bool *pos, int8_t *last_dir) {
    if (!*neg && !*pos) {
        *last_dir = 0;
        return;
    }
    // Track last direction pressed for SOCD_LAST_INPUT.
    if (*neg && !*pos) *last_dir = -1;
    if (*pos && !*neg) *last_dir = 1;

    if (*neg && *pos) {
        switch (s_socd_mode) {
            case SOCD_NEUTRAL:
                *neg = false;
                *pos = false;
                break;
            case SOCD_LAST_INPUT:
                if (*last_dir < 0) { *pos = false; }
                else if (*last_dir > 0) { *neg = false; }
                else { *neg = false; *pos = false; }  // tie → neutral
                break;
            case SOCD_FIRST_INPUT:
                if (*last_dir < 0) { *pos = false; }
                else if (*last_dir > 0) { *neg = false; }
                else { *neg = false; *pos = false; }
                break;
        }
    }
}

#if CONFIG_JOYCON_HOST_NINTENDO_0X30_EMIT_KEYS

// Apply selected curve to a normalized stick value (-4096..+4096).
// Returns a value in the same range with the curve applied.
static int apply_stick_curve(int val) {
    if (s_curve == STICK_CURVE_LINEAR || val == 0) {
        return val;
    }

    float sign = (val > 0) ? 1.0f : -1.0f;
    float abs_val = (float)(val > 0 ? val : -val);
    float norm = abs_val / 4096.0f;  // 0..1

    float result;
    switch (s_curve) {
        case STICK_CURVE_EXPONENTIAL:
            result = powf(norm, s_exp);
            break;
        case STICK_CURVE_QUADRATIC:
            result = norm * norm;
            break;
        default:
            result = norm;
            break;
    }

    return (int)(sign * result * 4096.0f);
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
static portMUX_TYPE s_cal_mux = portMUX_INITIALIZER_UNLOCKED;

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

// --- Calibration persistence (NVS) ---
#define CAL_NVS_NS "stick_cal"
#define CAL_NVS_KEY "cal_data"

// Packed struct for NVS persistence.
typedef struct {
    uint16_t lx_min, lx_center, lx_max;
    uint16_t ly_min, ly_center, ly_max;
    uint16_t rx_min, rx_center, rx_max;
    uint16_t ry_min, ry_center, ry_max;
} cal_nvs_data_t;

static void cal_save_axis(cal_nvs_data_t *d, const axis_cal_t *a,
                          uint16_t *out_min, uint16_t *out_center, uint16_t *out_max) {
    *out_min = a->min;
    *out_center = a->center;
    *out_max = a->max;
}

static void cal_restore_axis(axis_cal_t *a, uint16_t mn, uint16_t center, uint16_t mx) {
    a->min = mn;
    a->center = center;
    a->max = mx;
    a->initialized = true;
}

void joycon_mapper_save_calibration(void) {
    cal_nvs_data_t d;
    portENTER_CRITICAL(&s_cal_mux);
    cal_save_axis(&d, &s_cal.lx, &d.lx_min, &d.lx_center, &d.lx_max);
    cal_save_axis(&d, &s_cal.ly, &d.ly_min, &d.ly_center, &d.ly_max);
    cal_save_axis(&d, &s_cal.rx, &d.rx_min, &d.rx_center, &d.rx_max);
    cal_save_axis(&d, &s_cal.ry, &d.ry_min, &d.ry_center, &d.ry_max);
    portEXIT_CRITICAL(&s_cal_mux);

    nvs_handle_t h;
    esp_err_t err = nvs_open(CAL_NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        ESP_LOGW("joycon-mapper", "NVS open failed for cal save: %s", esp_err_to_name(err));
        return;
    }
    err = nvs_set_blob(h, CAL_NVS_KEY, &d, sizeof(d));
    if (err == ESP_OK) {
        nvs_commit(h);
        ESP_LOGI("joycon-mapper", "Calibration saved to NVS");
    }
    nvs_close(h);
}

void joycon_mapper_clear_calibration(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(CAL_NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return;
    nvs_erase_key(h, CAL_NVS_KEY);
    nvs_commit(h);
    nvs_close(h);

    portENTER_CRITICAL(&s_cal_mux);
    memset(&s_cal, 0, sizeof(s_cal));
    portEXIT_CRITICAL(&s_cal_mux);
    ESP_LOGI("joycon-mapper", "Calibration cleared");
}

static void cal_restore_from_nvs(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(CAL_NVS_NS, NVS_READONLY, &h);
    if (err != ESP_OK) return;

    cal_nvs_data_t d;
    size_t len = sizeof(d);
    err = nvs_get_blob(h, CAL_NVS_KEY, &d, &len);
    nvs_close(h);

    if (err != ESP_OK || len != sizeof(d)) return;

    cal_restore_axis(&s_cal.lx, d.lx_min, d.lx_center, d.lx_max);
    cal_restore_axis(&s_cal.ly, d.ly_min, d.ly_center, d.ly_max);
    cal_restore_axis(&s_cal.rx, d.rx_min, d.rx_center, d.rx_max);
    cal_restore_axis(&s_cal.ry, d.ry_min, d.ry_center, d.ry_max);
    s_cal.sample_count = CAL_WARMUP_SAMPLES; // skip warmup
    ESP_LOGI("joycon-mapper", "Calibration restored from NVS");
}

static bool s_cal_restored = false;

// --- Motion / IMU gesture detection ---
#define MOTION_SHAKE_THRESHOLD   12000  // accel magnitude for shake
#define MOTION_TILT_THRESHOLD    3000   // accel tilt per-axis
#define MOTION_FLICK_THRESHOLD   10000  // gyro magnitude for flick
#define MOTION_COOLDOWN_MS       250    // minimum ms between gesture triggers

typedef struct {
    int64_t last_shake_ms;
    int64_t last_tilt_up_ms;
    int64_t last_tilt_down_ms;
    int64_t last_tilt_left_ms;
    int64_t last_tilt_right_ms;
    int64_t last_flick_ms;
    bool shake_pressed;
    bool tilt_up_pressed;
    bool tilt_down_pressed;
    bool tilt_left_pressed;
    bool tilt_right_pressed;
    bool flick_pressed;
} motion_state_t;

static motion_state_t s_motion = {0};

static int64_t get_time_ms(void) {
    return (int64_t)(esp_timer_get_time() / 1000);
}
#else /* !CONFIG_JOYCON_HOST_NINTENDO_0X30_EMIT_KEYS */

/* Stubs so bridge_ctrl.c links even when the feature is disabled. */
void joycon_mapper_save_calibration(void)  { /* no-op */ }
void joycon_mapper_clear_calibration(void) { /* no-op */ }

#endif /* CONFIG_JOYCON_HOST_NINTENDO_0X30_EMIT_KEYS */

void joycon_mapper_on_report_ex(uint8_t device_id, const uint8_t* report, uint16_t len) {
    (void)s_act_threshold;
    (void)s_deact_threshold;

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
            ESP_LOGI("joycon-mapper", "nintendo 0x30: btn=%02X %02X %02X  LX=%u LY=%u  RX=%u RY=%u",
                     st.buttons1, st.buttons2, st.buttons3,
                     (unsigned)st.lx, (unsigned)st.ly, (unsigned)st.rx, (unsigned)st.ry);
            last = st;
            have_last = true;
        }

#if CONFIG_JOYCON_HOST_NINTENDO_0X30_EMIT_KEYS
        // --- Restore calibration from NVS on first report ---
        if (!s_cal_restored) {
            // Wait until setup FSM is done reading SPI cal data.
            if (!joycon_setup_is_ready(device_id)) {
                // Auto-cal handles the first few reports; once FSM is
                // ready we'll apply SPI cal on the next report.
            } else {
                // Prefer SPI flash calibration from setup FSM (read from Joy-Con
                // hardware) over our runtime auto-calibration or NVS data.
                const joycon_stick_cal_t *spi_cal = joycon_setup_get_stick_cal(device_id);
                if (spi_cal && spi_cal->valid) {
                    // Apply SPI flash calibration to our auto-cal structure.
                    s_cal.lx.min = (uint16_t)spi_cal->lx.min;
                    s_cal.lx.center = (uint16_t)spi_cal->lx.center;
                    s_cal.lx.max = (uint16_t)spi_cal->lx.max;
                    s_cal.lx.initialized = true;

                    s_cal.ly.min = (uint16_t)spi_cal->ly.min;
                    s_cal.ly.center = (uint16_t)spi_cal->ly.center;
                    s_cal.ly.max = (uint16_t)spi_cal->ly.max;
                    s_cal.ly.initialized = true;

                    s_cal.rx.min = (uint16_t)spi_cal->rx.min;
                    s_cal.rx.center = (uint16_t)spi_cal->rx.center;
                    s_cal.rx.max = (uint16_t)spi_cal->rx.max;
                    s_cal.rx.initialized = true;

                    s_cal.ry.min = (uint16_t)spi_cal->ry.min;
                    s_cal.ry.center = (uint16_t)spi_cal->ry.center;
                    s_cal.ry.max = (uint16_t)spi_cal->ry.max;
                    s_cal.ry.initialized = true;

                    s_cal.sample_count = CAL_WARMUP_SAMPLES;  // skip warmup
                    ESP_LOGI("joycon-mapper", "Using SPI flash calibration from setup FSM");
                } else {
                    cal_restore_from_nvs();
                }
                s_cal_restored = true;
            }
        }

        // --- Auto-calibration (mutex-protected — also accessed from bridge_ctrl) ---
        portENTER_CRITICAL(&s_cal_mux);
        cal_update(&s_cal, &st);
        portEXIT_CRITICAL(&s_cal_mux);

        // --- Auto-save calibration after warmup completes ---
        if (s_cal.sample_count == CAL_WARMUP_SAMPLES + 1) {
            joycon_mapper_save_calibration();
        }

        // --- Deadzone with hysteresis (rapid trigger) ---
        const int act_dz   = ((int)s_act_threshold) << 5;   // activation deadzone
        const int deact_dz = ((int)s_deact_threshold) << 5;  // deactivation deadzone

        // --- Left stick -> WASD (with curve + SOCD cleaning) ---
        {
            portENTER_CRITICAL(&s_cal_mux);
            int dx = apply_stick_curve(cal_normalize(&s_cal.lx, st.lx));
            int dy = apply_stick_curve(cal_normalize(&s_cal.ly, st.ly));
            portEXIT_CRITICAL(&s_cal_mux);

            // Send left stick analog data for sprint zone detection.
            bridge_send_analog(device_id, (int16_t)dx, (int16_t)dy);

            // Hysteresis: use lower threshold to keep active, higher to activate
            bool now_right = prev_right ? (dx > deact_dz)  : (dx > act_dz);
            bool now_left  = prev_left  ? (dx < -deact_dz) : (dx < -act_dz);
            bool now_up    = prev_forward ? (dy < -deact_dz) : (dy < -act_dz);
            bool now_down  = prev_back    ? (dy > deact_dz)  : (dy > act_dz);

            // SOCD cleaning using the selected mode.
            socd_clean(&now_left, &now_right, &s_socd_lr_last);
            socd_clean(&now_up,   &now_down,  &s_socd_ud_last);

            emit_if_changed_ex(device_id, KEY_ID_FORWARD, now_up, &prev_forward);
            emit_if_changed_ex(device_id, KEY_ID_BACK, now_down, &prev_back);
            emit_if_changed_ex(device_id, KEY_ID_LEFT, now_left, &prev_left);
            emit_if_changed_ex(device_id, KEY_ID_RIGHT, now_right, &prev_right);
        }

        // --- Right stick -> virtual directions (with curve + SOCD cleaning) ---
        {
            static bool prev_rup = false, prev_rdn = false;
            static bool prev_rlt = false, prev_rrt = false;

            portENTER_CRITICAL(&s_cal_mux);
            int rdx = apply_stick_curve(cal_normalize(&s_cal.rx, st.rx));
            int rdy = apply_stick_curve(cal_normalize(&s_cal.ry, st.ry));
            portEXIT_CRITICAL(&s_cal_mux);

            // Send right stick analog data for mouse/scroll modes.
            bridge_send_analog((uint8_t)(device_id | 0x80), (int16_t)rdx, (int16_t)rdy);

            bool now_rup = prev_rup ? (rdy < -deact_dz) : (rdy < -act_dz);
            bool now_rdn = prev_rdn ? (rdy >  deact_dz) : (rdy >  act_dz);
            bool now_rlt = prev_rlt ? (rdx < -deact_dz) : (rdx < -act_dz);
            bool now_rrt = prev_rrt ? (rdx >  deact_dz) : (rdx >  act_dz);

            // SOCD cleaning for right stick directions.
            socd_clean(&now_rlt, &now_rrt, &s_socd_rlr_last);
            socd_clean(&now_rup, &now_rdn, &s_socd_rud_last);

            emit_if_changed_ex(device_id, KEY_ID_RSTICK_UP,    now_rup, &prev_rup);
            emit_if_changed_ex(device_id, KEY_ID_RSTICK_DOWN,  now_rdn, &prev_rdn);
            emit_if_changed_ex(device_id, KEY_ID_RSTICK_LEFT,  now_rlt, &prev_rlt);
            emit_if_changed_ex(device_id, KEY_ID_RSTICK_RIGHT, now_rrt, &prev_rrt);
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

        // --- Side-rail buttons (SL / SR) ---
        {
            static bool prev_sl_l = false, prev_sr_l = false;
            static bool prev_sl_r = false, prev_sr_r = false;

            emit_if_changed_ex(device_id, KEY_ID_BTN_SL_L, (st.buttons3 & NIN_BTN3_SL_L) != 0, &prev_sl_l);
            emit_if_changed_ex(device_id, KEY_ID_BTN_SR_L, (st.buttons3 & NIN_BTN3_SR_L) != 0, &prev_sr_l);
            emit_if_changed_ex(device_id, KEY_ID_BTN_SL_R, (st.buttons1 & NIN_BTN1_SL_R) != 0, &prev_sl_r);
            emit_if_changed_ex(device_id, KEY_ID_BTN_SR_R, (st.buttons1 & NIN_BTN1_SR_R) != 0, &prev_sr_r);
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

        // --- Motion / IMU gesture detection ---
        if (st.has_imu) {
            int64_t now = get_time_ms();

            // Average acceleration across the 3 IMU samples
            int32_t ax = 0, ay = 0, az = 0;
            int32_t gx = 0, gy = 0, gz = 0;
            for (int i = 0; i < 3; i++) {
                ax += st.accel[i][0];
                ay += st.accel[i][1];
                az += st.accel[i][2];
                gx += st.gyro[i][0];
                gy += st.gyro[i][1];
                gz += st.gyro[i][2];
            }
            ax /= 3; ay /= 3; az /= 3;
            gx /= 3; gy /= 3; gz /= 3;

            // Shake: high acceleration magnitude (subtract gravity ~4096 on one axis)
            int32_t accel_mag = (int32_t)(sqrtf((float)(ax*ax + ay*ay + az*az)));
            bool shake_now = (accel_mag > MOTION_SHAKE_THRESHOLD);
            if (shake_now && !s_motion.shake_pressed &&
                (now - s_motion.last_shake_ms) > MOTION_COOLDOWN_MS) {
                s_motion.shake_pressed = true;
                s_motion.last_shake_ms = now;
                emit_if_changed_ex(device_id, KEY_ID_MOTION_SHAKE, true, &s_motion.shake_pressed);
            } else if (!shake_now && s_motion.shake_pressed &&
                       (now - s_motion.last_shake_ms) > MOTION_COOLDOWN_MS) {
                s_motion.shake_pressed = false;
                emit_if_changed_ex(device_id, KEY_ID_MOTION_SHAKE, false, &s_motion.shake_pressed);
            }

            // Tilt: sustained acceleration on a single axis beyond threshold
            bool tilt_up    = (ay < -MOTION_TILT_THRESHOLD);
            bool tilt_down  = (ay >  MOTION_TILT_THRESHOLD);
            bool tilt_left  = (ax < -MOTION_TILT_THRESHOLD);
            bool tilt_right = (ax >  MOTION_TILT_THRESHOLD);

            emit_if_changed_ex(device_id, KEY_ID_MOTION_TILT_UP,    tilt_up,    &s_motion.tilt_up_pressed);
            emit_if_changed_ex(device_id, KEY_ID_MOTION_TILT_DOWN,  tilt_down,  &s_motion.tilt_down_pressed);
            emit_if_changed_ex(device_id, KEY_ID_MOTION_TILT_LEFT,  tilt_left,  &s_motion.tilt_left_pressed);
            emit_if_changed_ex(device_id, KEY_ID_MOTION_TILT_RIGHT, tilt_right, &s_motion.tilt_right_pressed);

            // Flick: high gyro magnitude (quick twist)
            int32_t gyro_mag = (int32_t)(sqrtf((float)(gx*gx + gy*gy + gz*gz)));
            bool flick_now = (gyro_mag > MOTION_FLICK_THRESHOLD);
            if (flick_now && !s_motion.flick_pressed &&
                (now - s_motion.last_flick_ms) > MOTION_COOLDOWN_MS) {
                s_motion.flick_pressed = true;
                s_motion.last_flick_ms = now;
                emit_if_changed_ex(device_id, KEY_ID_MOTION_FLICK, true, &s_motion.flick_pressed);
            } else if (!flick_now && s_motion.flick_pressed &&
                       (now - s_motion.last_flick_ms) > MOTION_COOLDOWN_MS) {
                s_motion.flick_pressed = false;
                emit_if_changed_ex(device_id, KEY_ID_MOTION_FLICK, false, &s_motion.flick_pressed);
            }

            // Forward averaged raw gyro data to the USB side for gyro-to-mouse.
            bridge_send_gyro(device_id, (int16_t)gx, (int16_t)gy, (int16_t)gz);
        }

        return;
#endif

        // If we successfully parsed, but key emission is disabled, stop here.
        // (We don't want to also run placeholder logic below.)
        return;
    }
#endif

    // Fallback: if extended parsing above was compiled out or didn't match,
    // release all buttons so nothing sticks.

    emit_if_changed_ex(device_id, KEY_ID_FORWARD, false, &prev_forward);
    emit_if_changed_ex(device_id, KEY_ID_BACK, false, &prev_back);
    emit_if_changed_ex(device_id, KEY_ID_LEFT, false, &prev_left);
    emit_if_changed_ex(device_id, KEY_ID_RIGHT, false, &prev_right);
}

void joycon_mapper_on_report(const uint8_t* report, uint16_t len) {
    joycon_mapper_on_report_ex(0, report, len);
}
