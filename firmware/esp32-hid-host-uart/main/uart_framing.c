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

static void bridge_send_frame(const uint8_t* payload, uint8_t length) {
    // Frame format: AA 55 <len> <payload...> <checksum>
    // checksum = XOR of len and payload bytes.
    uint8_t header[3] = {BRIDGE_SYNC0, BRIDGE_SYNC1, length};
    uint8_t checksum = xor_checksum(length, payload);

    uart_write_bytes(BRIDGE_UART_PORT, (const char*)header, sizeof(header));
    uart_write_bytes(BRIDGE_UART_PORT, (const char*)payload, length);
    uart_write_bytes(BRIDGE_UART_PORT, (const char*)&checksum, 1);
}

void bridge_send_key_event(uint8_t key_id, bool pressed) {
    uint8_t event = (uint8_t)(key_id & 0x7F);
    if (pressed) {
        event |= 0x80;
    }

    bridge_send_frame(&event, 1);
}

void bridge_send_debug_hid_report(const uint8_t* report, uint16_t report_len) {
    if (!report || report_len == 0) {
        return;
    }

    // Debug payload format (length > 1):
    //   [0] = 0xFF (debug marker)
    //   [1] = N (number of report bytes included)
    //   [2..] = report bytes (truncated)
    // This stays backward-compatible with receivers that only process length==1 frames.
    const uint16_t max_payload = 200; // keep stack use small; Kconfig can further limit on caller side
    uint8_t buf[2 + max_payload];

    uint16_t n = report_len;
    if (n > max_payload) {
        n = max_payload;
    }

    buf[0] = 0xFF;
    buf[1] = (uint8_t)n;
    for (uint16_t i = 0; i < n; i++) {
        buf[2 + i] = report[i];
    }

    uint8_t length = (uint8_t)(2 + n);
    bridge_send_frame(buf, length);
}
