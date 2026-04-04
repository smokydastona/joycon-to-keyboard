#include "uart_proto.h"

#include "driver/uart.h"

#include "esp_log.h"

static const char* TAG = "uart-proto";

#define SYNC0 0xAA
#define SYNC1 0x55

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

bool uart_proto_poll_event(uint8_t* event_byte) {
    static uint8_t state = 0;
    static uint8_t length = 0;
    static uint8_t payload[8];
    static uint8_t payload_i = 0;

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
