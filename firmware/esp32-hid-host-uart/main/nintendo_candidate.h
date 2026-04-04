#pragma once

#include <stdbool.h>
#include <stdint.h>

// Minimal, signature-gated parser for a common Nintendo-style input report.
//
// This is intentionally optional and conservative:
// - It only claims success when the report matches a known signature.
// - It does not attempt to do any Joy-Con handshake or mode switching.
// - It is meant to *help* interpret captured bytes, not replace evidence.

typedef struct {
    uint8_t report_id;
    uint8_t buttons1;
    uint8_t buttons2;
    uint8_t buttons3;
    uint16_t lx;
    uint16_t ly;
    uint16_t rx;
    uint16_t ry;
} nintendo_0x30_state_t;

// Try to parse a Nintendo-style 0x30 input report.
//
// Returns true only if the input looks like a 0x30 report and the expected
// byte layout exists.
bool nintendo_try_parse_0x30(const uint8_t* report, uint16_t len, nintendo_0x30_state_t* out);
