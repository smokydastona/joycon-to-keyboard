#pragma once

#include "sdkconfig.h"

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

void buzzer_init(void);
void buzzer_play(buzzer_tone_t tone);
void buzzer_stop(void);

/** Start / stop the periodic discovery-tick beep (Kconfig gated). */
void buzzer_discovery_tick_start(void);
void buzzer_discovery_tick_stop(void);

#else

static inline void buzzer_init(void) {}
static inline void buzzer_play(buzzer_tone_t tone) { (void)tone; }
static inline void buzzer_stop(void) {}
static inline void buzzer_discovery_tick_start(void) {}
static inline void buzzer_discovery_tick_stop(void) {}

#endif
