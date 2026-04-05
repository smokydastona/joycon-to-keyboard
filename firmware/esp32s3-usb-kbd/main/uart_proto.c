#include "uart_proto.h"

#include <string.h>

#include "driver/uart.h"

#include "esp_log.h"

static const char* TAG = "uart-proto";

#define SYNC0 0xAA
#define SYNC1 0x55

#define CTRL_MARKER   0xFE
#define DEBUG_MARKER  0xFF
#define STATUS_MARKER 0xFD
#define KEY_EX_MARKER 0xFC
#define OTA_RSP_MARKER 0xFB

// Keep this comfortably under 255 (len is uint8_t) and large enough for
// status frames that include an optional device name.
#define UART_PAYLOAD_MAX 220

static inline uint8_t xor_checksum(uint8_t length, const uint8_t* payload) {
    uint8_t x = length;
    for (uint8_t i = 0; i < length; i++) {
        x ^= payload[i];
    }
    return x;
}

void uart_proto_init(void) {
    const uart_config_t cfg = {
        .baud_rate = CONFIG_BRIDGE_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    uart_port_t port = (uart_port_t)CONFIG_BRIDGE_UART_PORT;

    ESP_ERROR_CHECK(uart_driver_install(port, 2048, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(port, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(port, CONFIG_BRIDGE_UART_TX_GPIO, CONFIG_BRIDGE_UART_RX_GPIO,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));

    ESP_LOGI(TAG, "UART ready: port=%d baud=%d RX_GPIO=%d TX_GPIO=%d",
             CONFIG_BRIDGE_UART_PORT,
             CONFIG_BRIDGE_UART_BAUD,
             CONFIG_BRIDGE_UART_RX_GPIO,
             CONFIG_BRIDGE_UART_TX_GPIO);
}

static void uart_proto_send_frame(const uint8_t* payload, uint8_t length) {
    if (!payload || length == 0) {
        return;
    }

    uart_port_t port = (uart_port_t)CONFIG_BRIDGE_UART_PORT;

    // Frame format: AA 55 <len> <payload...> <checksum>
    uint8_t header[3] = {SYNC0, SYNC1, length};
    uint8_t checksum = xor_checksum(length, payload);

    uart_write_bytes(port, (const char*)header, sizeof(header));
    uart_write_bytes(port, (const char*)payload, length);
    uart_write_bytes(port, (const char*)&checksum, 1);
}

bool uart_proto_send_ctrl(uint8_t cmd_id, const uint8_t* data, uint8_t data_len) {
    // payload = 0xFE, cmd_id, data...
    if (data_len > (uint8_t)(UART_PAYLOAD_MAX - 2)) {
        return false;
    }

    static uint8_t buf[UART_PAYLOAD_MAX];
    buf[0] = CTRL_MARKER;
    buf[1] = cmd_id;
    if (data_len && data) {
        memcpy(&buf[2], data, data_len);
    }
    uart_proto_send_frame(buf, (uint8_t)(2 + data_len));
    return true;
}

bool uart_proto_poll_frame(uart_frame_t* out) {
    static uint8_t state = 0;
    static uint8_t length = 0;
    static uint8_t payload[UART_PAYLOAD_MAX];
    static uint8_t payload_i = 0;

    if (!out) return false;

    uart_port_t port = (uart_port_t)CONFIG_BRIDGE_UART_PORT;

    uint8_t b;
    int got;

    while ((got = uart_read_bytes(port, &b, 1, 0)) == 1) {
        switch (state) {
            case 0:
                state = (b == SYNC0) ? 1 : 0;
                break;
            case 1:
                state = (b == SYNC1) ? 2 : 0;
                break;
            case 2:
                length = b;
                payload_i = 0;
                if (length == 0 || length > sizeof(payload)) {
                    state = 0;
                } else {
                    state = 3;
                }
                break;
            case 3:
                payload[payload_i++] = b;
                if (payload_i >= length) {
                    state = 4;
                }
                break;
            case 4: {
                uint8_t calc = xor_checksum(length, payload);
                state = 0;
                if (calc != b) {
                    break;
                }

                out->length = length;
                out->payload = payload;

                if (length == 1) {
                    out->type = UART_FRAME_KEY_EVENT;
                } else if (length == 4 && payload[0] == KEY_EX_MARKER) {
                    out->type = UART_FRAME_KEY_EVENT_EX;
                } else if (payload[0] == OTA_RSP_MARKER) {
                    out->type = UART_FRAME_OTA_RSP;
                } else if (payload[0] == DEBUG_MARKER) {
                    out->type = UART_FRAME_DEBUG;
                } else if (payload[0] == STATUS_MARKER) {
                    out->type = UART_FRAME_STATUS;
                } else {
                    out->type = UART_FRAME_UNKNOWN;
                }
                return true;
            }
            default:
                state = 0;
                break;
        }
    }

    return false;
}

bool uart_proto_poll_event(uint8_t* event_byte) {
    uart_frame_t f;
    while (uart_proto_poll_frame(&f)) {
        if (f.type == UART_FRAME_KEY_EVENT && f.length == 1) {
            *event_byte = f.payload[0];
            return true;
        }
        // ignore other frame types
    }
    return false;
}
