#include "bridge_ctrl.h"

#include <string.h>

#include "config.h"

#include "driver/uart.h"
#include "esp_log.h"

#include "bt_hid_host.h"

static const char *TAG = "bridge-ctrl";

#define SYNC0 0xAA
#define SYNC1 0x55

#define CTRL_MARKER 0xFE

#define CTRL_CMD_SET_TARGET_SUBSTR 0x01
#define CTRL_CMD_START_DISCOVERY   0x02

static inline uint8_t xor_checksum(uint8_t length, const uint8_t *payload) {
    uint8_t x = length;
    for (uint8_t i = 0; i < length; i++) {
        x ^= payload[i];
    }
    return x;
}

static void handle_ctrl_cmd(uint8_t cmd_id, const uint8_t *payload, uint8_t payload_len) {
    switch (cmd_id) {
        case CTRL_CMD_SET_TARGET_SUBSTR: {
            // payload bytes are ASCII substring (not null-terminated)
            bt_hid_host_set_target_substr((const char *)payload, payload_len);
            ESP_LOGI(TAG, "Target name substring override set (len=%u)", (unsigned)payload_len);
            break;
        }
        case CTRL_CMD_START_DISCOVERY: {
            bool dual = (payload_len >= 1) && ((payload[0] & 0x01u) != 0);
            esp_err_t err = bt_hid_host_start_discovery_ex(dual);
            ESP_LOGI(TAG, "Start discovery requested (dual=%d): %s", (int)dual, esp_err_to_name(err));
            break;
        }
        default:
            ESP_LOGW(TAG, "Unknown ctrl cmd_id=0x%02X len=%u", cmd_id, (unsigned)payload_len);
            break;
    }
}

static void ctrl_task(void *arg) {
    (void)arg;

    uint8_t state = 0;
    uint8_t length = 0;

    // Control commands are tiny; keep the buffer small but big enough for a name substring.
    uint8_t payload[80];
    uint8_t payload_i = 0;

    while (1) {
        uint8_t b;
        int got = uart_read_bytes(BRIDGE_UART_PORT, &b, 1, pdMS_TO_TICKS(20));
        if (got != 1) {
            continue;
        }

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

                if (length >= 2 && payload[0] == CTRL_MARKER) {
                    uint8_t cmd_id = payload[1];
                    const uint8_t *cmd_payload = (length > 2) ? &payload[2] : NULL;
                    uint8_t cmd_len = (length > 2) ? (uint8_t)(length - 2) : 0;
                    handle_ctrl_cmd(cmd_id, cmd_payload, cmd_len);
                }
                break;
            }
            default:
                state = 0;
                break;
        }
    }
}

void bridge_ctrl_init(void) {
    xTaskCreate(ctrl_task, "bridge_ctrl", 4096, NULL, 5, NULL);
    ESP_LOGI(TAG, "Control RX task started (UART%d RX GPIO=%d)", (int)BRIDGE_UART_PORT, BRIDGE_UART_RX_GPIO);
}
