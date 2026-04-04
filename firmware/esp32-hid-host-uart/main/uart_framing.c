#include "uart_framing.h"

#include "config.h"

#include "driver/uart.h"

static inline uint8_t xor_checksum(uint8_t length, const uint8_t* payload) {
    uint8_t x = length;
    for (uint8_t i = 0; i < length; i++) {
        x ^= payload[i];
    }
    return x;
}

void bridge_send_key_event(uint8_t key_id, bool pressed) {
    uint8_t event = (uint8_t)(key_id & 0x7F);
    if (pressed) {
        event |= 0x80;
    }

    uint8_t frame[5];
    frame[0] = BRIDGE_SYNC0;
    frame[1] = BRIDGE_SYNC1;
    frame[2] = 1; // length
    frame[3] = event;
    frame[4] = xor_checksum(frame[2], &frame[3]);

    uart_write_bytes(BRIDGE_UART_PORT, (const char*)frame, sizeof(frame));
}
