#include "usb_mouse.h"

#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "tusb.h"

static const char *TAG = "usb-mouse";

static SemaphoreHandle_t s_mutex = NULL;
static uint8_t s_buttons = 0;

// --- Report deduplication (reduce USB bus noise) ---
static uint8_t s_last_buttons = 0;
static int8_t s_last_dx = 0;
static int8_t s_last_dy = 0;
static int8_t s_last_vscroll = 0;
static int8_t s_last_hscroll = 0;

// --- Anti-cheat rate guard ---
static int64_t s_last_report_us = 0;
#define MIN_REPORT_INTERVAL_US 1000  // 1 ms guard (match keyboard)

// Pending movement/scroll accumulated between reports.
static int16_t s_pending_dx = 0;
static int16_t s_pending_dy = 0;
static int8_t s_pending_vscroll = 0;
static int8_t s_pending_hscroll = 0;

static int8_t clamp8(int16_t v) {
    if (v > 127) return 127;
    if (v < -127) return -127;
    return (int8_t)v;
}

static void send_report(void) {
    if (!tud_hid_n_ready(1)) return;

    int8_t dx = clamp8(s_pending_dx);
    int8_t dy = clamp8(s_pending_dy);
    int8_t vs = s_pending_vscroll;
    int8_t hs = s_pending_hscroll;

    // Deduplication: skip if report is identical to last AND no movement.
    if (s_buttons == s_last_buttons && dx == 0 && dy == 0 && vs == 0 && hs == 0) {
        return;
    }

    // Anti-cheat rate guard.
    int64_t now = esp_timer_get_time();
    if ((now - s_last_report_us) < MIN_REPORT_INTERVAL_US) {
        return;
    }

    tud_hid_n_mouse_report(1, 0, s_buttons, dx, dy, vs, hs);

    // Subtract what we sent from pending accumulators.
    s_pending_dx -= dx;
    s_pending_dy -= dy;
    s_pending_vscroll = 0;
    s_pending_hscroll = 0;

    s_last_buttons = s_buttons;
    s_last_dx = dx;
    s_last_dy = dy;
    s_last_vscroll = vs;
    s_last_hscroll = hs;
    s_last_report_us = now;
}

void usb_mouse_init(void) {
    if (!s_mutex) {
        s_mutex = xSemaphoreCreateMutex();
    }
    s_buttons = 0;
    s_pending_dx = 0;
    s_pending_dy = 0;
    s_pending_vscroll = 0;
    s_pending_hscroll = 0;
    ESP_LOGI(TAG, "USB mouse subsystem initialized");
}

void usb_mouse_move(int16_t dx, int16_t dy) {
    if (!s_mutex) return;

    xSemaphoreTake(s_mutex, portMAX_DELAY);

    s_pending_dx += dx;
    s_pending_dy += dy;

    // Clamp accumulated values to avoid overflow.
    if (s_pending_dx > 127) s_pending_dx = 127;
    if (s_pending_dx < -127) s_pending_dx = -127;
    if (s_pending_dy > 127) s_pending_dy = 127;
    if (s_pending_dy < -127) s_pending_dy = -127;

    send_report();

    xSemaphoreGive(s_mutex);
}

void usb_mouse_scroll(int8_t vertical, int8_t horizontal) {
    if (!s_mutex) return;

    xSemaphoreTake(s_mutex, portMAX_DELAY);

    s_pending_vscroll += vertical;
    s_pending_hscroll += horizontal;

    // Clamp to int8_t range to avoid overflow.
    if (s_pending_vscroll > 127) s_pending_vscroll = 127;
    if (s_pending_vscroll < -127) s_pending_vscroll = -127;
    if (s_pending_hscroll > 127) s_pending_hscroll = 127;
    if (s_pending_hscroll < -127) s_pending_hscroll = -127;

    send_report();

    xSemaphoreGive(s_mutex);
}

void usb_mouse_button(uint8_t button, bool pressed) {
    if (!s_mutex) return;

    xSemaphoreTake(s_mutex, portMAX_DELAY);

    if (pressed) {
        s_buttons |= button;
    } else {
        s_buttons &= (uint8_t)~button;
    }

    send_report();

    xSemaphoreGive(s_mutex);
}
