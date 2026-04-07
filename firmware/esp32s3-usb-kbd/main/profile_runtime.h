#pragma once

#include <stdbool.h>
#include <stdint.h>

// Loads the active profile (from NVS) and applies it to incoming key_id events.
// Supports: disable/remap/remap_hid/macro-on-press, with optional layers.

void profile_runtime_init(void);

// Reloads active slot + active profile JSON from NVS.
// Safe to call after write_profile / set_active_profile.
void profile_runtime_reload(void);

// Handle an input key event (from UART): key_id up/down.
void profile_runtime_handle_input(bool pressed, uint8_t key_id);

// Anti-cheat humanization: adds timing jitter to macros/turbo.
void profile_runtime_set_humanize(bool enabled);
bool profile_runtime_get_humanize(void);
