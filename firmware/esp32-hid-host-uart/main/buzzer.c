#include "sdkconfig.h"

#if CONFIG_BIND_BANDIT_BUZZER_ENABLED

#include "buzzer.h"
#include "config.h"

#include <string.h>

#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/timers.h"
#include "nvs.h"

static const char *TAG = "buzzer";

// ---------- persistent runtime config ----------

#define BUZZER_NVS_NS "buzzer"
#define BUZZER_NVS_KEY_ENABLED "en"
#define BUZZER_NVS_KEY_VOLUME "vol"
#define BUZZER_NVS_KEY_TICK "tick"
#define BUZZER_NVS_KEY_MASK "mask"

#define DISCOVERY_TICK_INTERVAL_MS 3000

static buzzer_config_t s_cfg;
static TimerHandle_t s_disc_tick_timer = NULL;
static bool s_disc_tick_requested = false;

static inline uint16_t allowed_tone_mask(void) {
    if (BUZZER_TONE_COUNT >= 16) {
        return 0xFFFFu;
    }
    return (uint16_t)((1u << BUZZER_TONE_COUNT) - 1u);
}

static buzzer_config_t buzzer_cfg_defaults(void) {
    buzzer_config_t d = {
        .enabled = true,
        .volume = (uint8_t)CONFIG_BIND_BANDIT_BUZZER_VOLUME,
#ifdef CONFIG_BIND_BANDIT_BUZZER_DISCOVERY_TICK
        .discovery_tick = (bool)CONFIG_BIND_BANDIT_BUZZER_DISCOVERY_TICK,
#else
        .discovery_tick = false,
#endif
        .tone_mask = allowed_tone_mask(),
    };
    if (d.volume > 100) {
        d.volume = 100;
    }
    return d;
}

static void buzzer_cfg_load_from_nvs(void) {
    s_cfg = buzzer_cfg_defaults();

    nvs_handle_t h;
    esp_err_t err = nvs_open(BUZZER_NVS_NS, NVS_READONLY, &h);
    if (err != ESP_OK) {
        return;
    }

    uint8_t v8;
    uint16_t v16;

    if (nvs_get_u8(h, BUZZER_NVS_KEY_ENABLED, &v8) == ESP_OK) {
        s_cfg.enabled = (v8 != 0);
    }
    if (nvs_get_u8(h, BUZZER_NVS_KEY_VOLUME, &v8) == ESP_OK) {
        s_cfg.volume = (v8 > 100) ? 100 : v8;
    }
    if (nvs_get_u8(h, BUZZER_NVS_KEY_TICK, &v8) == ESP_OK) {
        s_cfg.discovery_tick = (v8 != 0);
    }
    if (nvs_get_u16(h, BUZZER_NVS_KEY_MASK, &v16) == ESP_OK) {
        s_cfg.tone_mask = (uint16_t)(v16 & allowed_tone_mask());
    }

    nvs_close(h);
}

static esp_err_t buzzer_cfg_save_to_nvs(void) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(BUZZER_NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }

    err = nvs_set_u8(h, BUZZER_NVS_KEY_ENABLED, (uint8_t)(s_cfg.enabled ? 1 : 0));
    if (err == ESP_OK) err = nvs_set_u8(h, BUZZER_NVS_KEY_VOLUME, s_cfg.volume);
    if (err == ESP_OK) err = nvs_set_u8(h, BUZZER_NVS_KEY_TICK, (uint8_t)(s_cfg.discovery_tick ? 1 : 0));
    if (err == ESP_OK) err = nvs_set_u16(h, BUZZER_NVS_KEY_MASK, s_cfg.tone_mask);
    if (err == ESP_OK) err = nvs_commit(h);

    nvs_close(h);
    return err;
}

static bool buzzer_tone_allowed(buzzer_tone_t tone) {
    if ((uint8_t)tone >= BUZZER_TONE_COUNT) {
        return false;
    }
    return (s_cfg.tone_mask & (uint16_t)(1u << (uint8_t)tone)) != 0;
}

static void disc_tick_timer_cb(TimerHandle_t xTimer) {
    (void)xTimer;
    buzzer_play(BUZZER_TONE_DISCOVERY_TICK);
}

static void disc_tick_update_running(void) {
    if (!s_disc_tick_timer) {
        return;
    }

    if (s_cfg.enabled && s_cfg.discovery_tick && s_disc_tick_requested) {
        xTimerStart(s_disc_tick_timer, 0);
    } else {
        xTimerStop(s_disc_tick_timer, 0);
    }
}

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
    [BUZZER_TONE_STARTUP]         = melody_startup,
    [BUZZER_TONE_CONNECT]         = melody_connect,
    [BUZZER_TONE_DISCONNECT]      = melody_disconnect,
    [BUZZER_TONE_DISCOVERY_START] = melody_discovery_start,
    [BUZZER_TONE_SETUP_COMPLETE]  = melody_setup_complete,
    [BUZZER_TONE_ERROR]           = melody_error,
    [BUZZER_TONE_DISCOVERY_TICK]  = melody_discovery_tick,
};

// ---------- playback state ----------

static const buzzer_note_t *s_seq = NULL;  // current melody being played
static uint8_t s_seq_idx = 0;              // current note index in melody
static TimerHandle_t s_timer = NULL;       // FreeRTOS software timer for sequencing

// ---------- low-level LEDC helpers ----------

static void buzzer_ledc_tone(uint16_t freq_hz) {
    if (freq_hz == 0 || !s_cfg.enabled || s_cfg.volume == 0) {
        ledc_set_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL, 0);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_CHANNEL);
        return;
    }

    ledc_set_freq(LEDC_LOW_SPEED_MODE, BUZZER_LEDC_TIMER, freq_hz);

    uint32_t duty = (uint32_t)(8191UL * (uint32_t)s_cfg.volume / 100u);
    if (duty == 0) {
        duty = 1;
    }
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
    buzzer_cfg_load_from_nvs();

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

    // Create periodic discovery tick timer (auto-reload); only starts when requested.
    s_disc_tick_timer = xTimerCreate(
        "bz_tick",
        pdMS_TO_TICKS(DISCOVERY_TICK_INTERVAL_MS),
        pdTRUE,
        NULL,
        disc_tick_timer_cb);
    if (!s_disc_tick_timer) {
        ESP_LOGE(TAG, "Failed to create discovery tick timer");
        return;
    }

    disc_tick_update_running();

    ESP_LOGI(TAG, "Buzzer ready on GPIO%d (LEDC ch%d timer%d) vol=%u enabled=%d mask=0x%04X tick=%d",
             BUZZER_GPIO, BUZZER_LEDC_CHANNEL, BUZZER_LEDC_TIMER,
             (unsigned)s_cfg.volume, (int)s_cfg.enabled, (unsigned)s_cfg.tone_mask, (int)s_cfg.discovery_tick);
}

void buzzer_play(buzzer_tone_t tone) {
    if (!s_cfg.enabled) {
        return;
    }
    if ((unsigned)tone >= sizeof(s_melodies) / sizeof(s_melodies[0])) {
        return;
    }
    if (!buzzer_tone_allowed(tone)) {
        return;
    }

    const buzzer_note_t *melody = s_melodies[tone];
    if (!melody) {
        return;
    }

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

void buzzer_discovery_tick_start(void) {
    s_disc_tick_requested = true;
    disc_tick_update_running();
}

void buzzer_discovery_tick_stop(void) {
    s_disc_tick_requested = false;
    disc_tick_update_running();
}

void buzzer_get_config(buzzer_config_t *out) {
    if (!out) {
        return;
    }
    *out = s_cfg;
}

esp_err_t buzzer_set_config(const buzzer_config_t *cfg, bool persist) {
    if (!cfg) {
        return ESP_ERR_INVALID_ARG;
    }
    if (cfg->volume > 100) {
        return ESP_ERR_INVALID_ARG;
    }

    s_cfg.enabled = cfg->enabled;
    s_cfg.volume = cfg->volume;
    s_cfg.discovery_tick = cfg->discovery_tick;
    s_cfg.tone_mask = (uint16_t)(cfg->tone_mask & allowed_tone_mask());

    // Apply immediately.
    if (!s_cfg.enabled) {
        buzzer_stop();
    }
    disc_tick_update_running();

    if (persist) {
        return buzzer_cfg_save_to_nvs();
    }
    return ESP_OK;
}

#endif // CONFIG_BIND_BANDIT_BUZZER_ENABLED
