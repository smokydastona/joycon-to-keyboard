#pragma once

#include "sdkconfig.h"

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef enum {
    BUZZER_TONE_STARTUP,
    BUZZER_TONE_CONNECT,
    BUZZER_TONE_DISCONNECT,
    BUZZER_TONE_DISCOVERY_START,
    BUZZER_TONE_SETUP_COMPLETE,
    BUZZER_TONE_ERROR,
    BUZZER_TONE_DISCOVERY_TICK,
} buzzer_tone_t;

#if CONFIG_BIND_BANDIT_BUZZER_ENABLED

// Tone enable bitmask: bit N corresponds to buzzer_tone_t value N.
// Only the lowest BUZZER_TONE_COUNT bits are used.
#define BUZZER_TONE_COUNT ((uint8_t)(BUZZER_TONE_DISCOVERY_TICK + 1))

typedef struct {
    bool enabled;              // master enable
    uint8_t volume;            // 0..100 (0 = mute)
    bool discovery_tick;       // periodic tick during BT discovery
    uint16_t tone_mask;        // per-tone enable bits
} buzzer_config_t;

void buzzer_init(void);
void buzzer_play(buzzer_tone_t tone);
void buzzer_stop(void);

// Start/stop the periodic discovery-tick beep (runtime-configurable).
void buzzer_discovery_tick_start(void);
void buzzer_discovery_tick_stop(void);

// Runtime configuration (persisted to NVS when requested).
void buzzer_get_config(buzzer_config_t *out);
esp_err_t buzzer_set_config(const buzzer_config_t *cfg, bool persist);

#else

typedef struct {
    bool enabled;
    uint8_t volume;
    bool discovery_tick;
    uint16_t tone_mask;
} buzzer_config_t;

static inline void buzzer_init(void) {}
static inline void buzzer_play(buzzer_tone_t tone) { (void)tone; }
static inline void buzzer_stop(void) {}
static inline void buzzer_discovery_tick_start(void) {}
static inline void buzzer_discovery_tick_stop(void) {}
static inline void buzzer_get_config(buzzer_config_t *out) { if (out) { *out = (buzzer_config_t){0}; } }
static inline esp_err_t buzzer_set_config(const buzzer_config_t *cfg, bool persist) { (void)cfg; (void)persist; return ESP_ERR_NOT_SUPPORTED; }

#endif
