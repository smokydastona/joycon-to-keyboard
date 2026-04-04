#include "uart_proto.h"

#include "config.h"

#include "hardware/uart.h"

static inline uint8_t xor_checksum(uint8_t length, const uint8_t* payload) {
    uint8_t x = length;
    for (uint8_t i = 0; i < length; i++) {
        x ^= payload[i];
    }
    return x;
}

bool uart_proto_poll_event(uint8_t* event_byte) {
    // Frame: AA 55 01 <event> <checksum>
    static uint8_t state = 0;
    static uint8_t length = 0;
    static uint8_t payload[8];
    static uint8_t payload_i = 0;

    while (uart_is_readable(KBD_UART_ID)) {
        uint8_t b = (uint8_t)uart_getc(KBD_UART_ID);

        switch (state) {
            case 0: // sync0
                state = (b == KBD_SYNC0) ? 1 : 0;
                break;
            case 1: // sync1
                state = (b == KBD_SYNC1) ? 2 : 0;
                break;
            case 2: // length
                length = b;
                payload_i = 0;
                if (length == 0 || length > sizeof(payload)) {
                    state = 0;
                } else {
                    state = 3;
                }
                break;
            case 3: // payload
                payload[payload_i++] = b;
                if (payload_i >= length) {
                    state = 4;
                }
                break;
            case 4: { // checksum
                uint8_t calc = xor_checksum(length, payload);
                state = 0;
                if (calc != b) {
                    break;
                }
                if (length == 1) {
                    *event_byte = payload[0];
                    return true;
                }
                break;
            }
            default:
                state = 0;
                break;
        }
    }

    return false;
}
