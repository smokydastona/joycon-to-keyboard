#pragma once

#include <stdbool.h>
#include <stdint.h>

// Loads the active profile (from NVS) and applies it to incoming key_id events.
// Supports: disable/remap/macro-on-press.

void profile_runtime_init(void);

// Reloads active slot + active profile JSON from NVS.
// Safe to call after write_profile / set_active_profile.
void profile_runtime_reload(void);

// Handle an input key event (from UART): key_id up/down.
void profile_runtime_handle_input(bool pressed, uint8_t key_id);
