#pragma once

#include <stdbool.h>
#include <stdint.h>

// key_id (0..127) -> (modifier, keycode)
// Returns false if unmapped.
bool keymap_lookup(uint8_t key_id, uint8_t* modifier, uint8_t* keycode);
