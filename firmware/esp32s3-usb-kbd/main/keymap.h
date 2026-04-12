#pragma once

#include <stdbool.h>
#include <stdint.h>

// key_id (0..255) -> (modifier, keycode)
// Left controller uses 1..35, right controller uses 129..163 (128 + base).
// Returns false if unmapped.
bool keymap_lookup(uint16_t key_id, uint8_t* modifier, uint8_t* keycode);
