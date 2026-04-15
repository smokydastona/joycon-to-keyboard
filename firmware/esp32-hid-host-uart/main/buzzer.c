#include "sdkconfig.h"

#if CONFIG_BIND_BANDIT_BUZZER_ENABLED

#include "buzzer.h"
#include "config.h"

#include "driver/ledc.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/timers.h"

static const char *TAG = "buzzer";

// ---------- note definition ----------

typedef struct {
    uint16_t freq_hz;    // 0 = silence (gap between notes)
    uint16_t duration_ms;
} buzzer_note_t;

// Musical note frequencies (scientific pitch)
#define NOTE_C4  262
#define NOTE_E4  330
#define NOTE_G4  392
#define NOTE_C5  523
#define NOTE_E5  659
#define NOTE_G5  784
#define NOTE_C6  1047
#define NOTE_A4  440

// Each melody is a zero-terminated array of notes.
static const buzzer_note_t melody_startup[] = {
    { NOTE_C5,  80 },
    { 0,        40 },
    { NOTE_E5,  80 },
    { 0,        40 },
    { NOTE_G5, 120 },
    { 0, 0 }
};

static const buzzer_note_t melody_connect[] = {
    { NOTE_C5, 100 },
    { 0,        30 },
    { NOTE_E5, 150 },
    { 0, 0 }
};

static const buzzer_note_t melody_disconnect[] = {
    { NOTE_E5, 150 },
    { 0,        30 },
    { NOTE_C5, 100 },
    { 0, 0 }
};

static const buzzer_note_t melody_discovery_start[] = {
    { NOTE_A4, 80 },
    { 0, 0 }
};

static const buzzer_note_t melody_setup_complete[] = {
    { NOTE_C5, 80 },
    { 0,       30 },
    { NOTE_E5, 80 },
    { 0,       30 },
    { NOTE_G5, 80 },
    { 0, 0 }
};

static const buzzer_note_t melody_error[] = {
    { NOTE_C4, 80 },
    { 0,       60 },
    { NOTE_C4, 80 },
    { 0,       60 },
    { NOTE_C4, 80 },
    { 0, 0 }
};

static const buzzer_note_t melody_discovery_tick[] = {
    { NOTE_A4, 40 },
    { 0, 0 }
};

static const buzzer_note_t *const s_melodies[] = {
    [BUZZER_TONE_STARTUP]        = melody_startup,
    [BUZZER_TONE_CONNECT]        = melody_connect,
    [BUZZER_TONE_DISCONNECT]     = melody_disconnect,
    [BUZZER_TONE_DISCOVERY_START]= melody_discovery_start,
    [BUZZER_TONE_SETUP_COMPLETE] = melody_setup_complete,
    [BUZZER_TONE_ERROR]          = melody_error,
    [BUZZER_TONE_DISCOVERY_TICK]  = melody_discovery_tick,
};

// ---------- playback state ----------

static const buzzer_note_t *s_seq = NULL;  // current melody being played
static uint8_t s_seq_idx = 0;             // current note index in melody
static TimerHandle_t s_timer = NULL;       // FreeRTOS software timer for sequencing

// ---------- low-level LEDC helpers ----------

static void buzzer_ledc_tone(uint16_t freq_hz) {
    if (freq_hz == 0) {
        ledc_set_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL, 0);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL);
        return;
    }
    ledc_set_freq(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_TIMER, freq_hz);
    // Duty cycle from Kconfig volume (1-100).  13-bit resolution → max 8191.
    uint32_t duty = (uint32_t)(8191UL * BUZZER_VOLUME / 100);
    if (duty == 0) duty = 1;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL);
}

static void buzzer_ledc_off(void) {
    ledc_set_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL);
}

// ---------- timer callback (runs in timer daemon task) ----------

static void buzzer_timer_cb(TimerHandle_t xTimer) {
    (void)xTimer;
    if (!s_seq) {
        buzzer_ledc_off();
        return;
    }

    const buzzer_note_t *note = &s_seq[s_seq_idx];

    // Sentinel: end of melody
    if (note->freq_hz == 0 && note->duration_ms == 0) {
        buzzer_ledc_off();
        s_seq = NULL;
        return;
    }

    buzzer_ledc_tone(note->freq_hz);

    s_seq_idx++;

    // Schedule the next note after this note's duration
    xTimerChangePeriod(s_timer, pdMS_TO_TICKS(note->duration_ms), 0);
}

// ---------- public API ----------

void buzzer_init(void) {
    ledc_timer_config_t timer_cfg = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_13_BIT,
        .timer_num       = BUZZER_LEDC_TIMER,
        .freq_hz         = 1000,  // initial frequency, overwritten per note
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer_cfg));

    ledc_channel_config_t ch_cfg = {
        .gpio_num   = BUZZER_GPIO,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel    = BUZZER_LEDC_CHANNEL,
        .timer_sel  = BUZZER_LEDC_TIMER,
        .duty       = 0,
        .hpoint     = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ch_cfg));

    // Create the one-shot software timer used for note sequencing.
    // Period is placeholder (1 tick) — changed dynamically per note.
    s_timer = xTimerCreate("buzzer", 1, pdFALSE, NULL, buzzer_timer_cb);
    if (!s_timer) {
        ESP_LOGE(TAG, "Failed to create buzzer timer");
        return;
    }

    ESP_LOGI(TAG, "Buzzer ready on GPIO%d (LEDC ch%d timer%d)",
             BUZZER_GPIO, BUZZER_LEDC_CHANNEL, BUZZER_LEDC_TIMER);
}

void buzzer_play(buzzer_tone_t tone) {
    if ((unsigned)tone >= sizeof(s_melodies) / sizeof(s_melodies[0])) return;

    const buzzer_note_t *melody = s_melodies[tone];
    if (!melody) return;

    // Stop any in-progress sequence (latest wins)
    if (s_timer) {
        xTimerStop(s_timer, 0);
    }
    buzzer_ledc_off();

    s_seq = melody;
    s_seq_idx = 0;

    // Kick off the first note immediately via the timer callback.
    // Use 1 tick so it fires as soon as the timer daemon runs.
    if (s_timer) {
        xTimerChangePeriod(s_timer, 1, 0);
    }
}

void buzzer_stop(void) {
    if (s_timer) {
        xTimerStop(s_timer, 0);
    }
    s_seq = NULL;
    buzzer_ledc_off();
}

// ---------- discovery tick (periodic beep while scanning) ----------

#if CONFIG_BIND_BANDIT_BUZZER_DISCOVERY_TICK

#define DISCOVERY_TICK_INTERVAL_MS 3000

static TimerHandle_t s_disc_tick_timer = NULL;

static void disc_tick_timer_cb(TimerHandle_t xTimer) {
    (void)xTimer;
    buzzer_play(BUZZER_TONE_DISCOVERY_TICK);
}

void buzzer_discovery_tick_start(void) {
    if (!s_disc_tick_timer) {
        s_disc_tick_timer = xTimerCreate(
            "bz_tick",
            pdMS_TO_TICKS(DISCOVERY_TICK_INTERVAL_MS),
            pdTRUE,   // auto-reload
            NULL,
            disc_tick_timer_cb);
        if (!s_disc_tick_timer) {
            ESP_LOGE(TAG, "Failed to create discovery tick timer");
            return;
        }
    }
    xTimerStart(s_disc_tick_timer, 0);
}

void buzzer_discovery_tick_stop(void) {
    if (s_disc_tick_timer) {
        xTimerStop(s_disc_tick_timer, 0);
    }
}

#else

void buzzer_discovery_tick_start(void) {}
void buzzer_discovery_tick_stop(void) {}

#endif // CONFIG_BIND_BANDIT_BUZZER_DISCOVERY_TICK

#endif // CONFIG_BIND_BANDIT_BUZZER_ENABLED
