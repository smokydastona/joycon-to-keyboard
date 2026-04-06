#include "bridge_ctrl.h"

#include <string.h>

#include "config.h"

#include "driver/uart.h"
#include "esp_log.h"
#include "esp_system.h"

#include "bt_hid_host.h"
#include "uart_framing.h"
#include "fw_ota.h"
#include "joycon_mapper.h"

static const char *TAG = "bridge-ctrl";

#define SYNC0 0xAA
#define SYNC1 0x55

#define CTRL_MARKER 0xFE

#define CTRL_CMD_SET_TARGET_SUBSTR 0x01
#define CTRL_CMD_START_DISCOVERY   0x02
#define CTRL_CMD_SET_STICK_CURVE   0x03
#define CTRL_CMD_CALIBRATION       0x04

// OTA control commands (from ESP32-S3)
#define CTRL_CMD_OTA_BEGIN   0x10
#define CTRL_CMD_OTA_DATA    0x11
#define CTRL_CMD_OTA_END     0x12
#define CTRL_CMD_OTA_ABORT   0x13
#define CTRL_CMD_FW_VERSION  0x14

// OTA response IDs (sent back to ESP32-S3)
#define OTA_RSP_BEGIN   0x01
#define OTA_RSP_END     0x03
#define OTA_RSP_VERSION 0x04

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
        case CTRL_CMD_SET_STICK_CURVE: {
            // payload[0] = curve type (0=linear, 1=exponential, 2=quadratic)
            // payload[1] = exponent * 100 (only for exponential)
            uint8_t curve = (payload_len >= 1) ? payload[0] : 0;
            uint8_t exp_x100 = (payload_len >= 2) ? payload[1] : 100;
            joycon_mapper_set_stick_curve(curve, exp_x100);
            break;
        }
        case CTRL_CMD_CALIBRATION: {
            // payload[0] = sub-command: 0x01=save, 0x02=clear
            if (payload_len >= 1 && payload[0] == 0x01) {
                joycon_mapper_save_calibration();
            } else if (payload_len >= 1 && payload[0] == 0x02) {
                joycon_mapper_clear_calibration();
            }
            break;
        }
        case CTRL_CMD_FW_VERSION: {
            const char *ver = fw_ota_version();
            uint8_t vlen = (uint8_t)strlen(ver);
            if (vlen > 48) vlen = 48;
            bridge_send_ota_rsp(OTA_RSP_VERSION, 0x00, (const uint8_t *)ver, vlen);
            ESP_LOGI(TAG, "FW version requested → %s", ver);
            break;
        }
        case CTRL_CMD_OTA_BEGIN: {
            uint32_t total_size = 0;
            if (payload_len >= 4) {
                total_size = (uint32_t)payload[0]
                           | ((uint32_t)payload[1] << 8)
                           | ((uint32_t)payload[2] << 16)
                           | ((uint32_t)payload[3] << 24);
            }
            esp_err_t err = fw_ota_begin(total_size);
            bridge_send_ota_rsp(OTA_RSP_BEGIN, (err == ESP_OK) ? 0x00 : 0x01, NULL, 0);
            break;
        }
        case CTRL_CMD_OTA_DATA: {
            if (!fw_ota_in_progress()) break;
            if (payload_len > 0 && payload) {
                esp_err_t err = fw_ota_write(payload, payload_len);
                if (err != ESP_OK) {
                    ESP_LOGE(TAG, "OTA write failed: %s", esp_err_to_name(err));
                    fw_ota_abort();
                }
            }
            break;
        }
        case CTRL_CMD_OTA_END: {
            esp_err_t err = fw_ota_end();
            bridge_send_ota_rsp(OTA_RSP_END, (err == ESP_OK) ? 0x00 : 0x01, NULL, 0);
            if (err == ESP_OK) {
                ESP_LOGI(TAG, "OTA done – rebooting in 1 s");
                vTaskDelay(pdMS_TO_TICKS(1000));
                esp_restart();
            }
            break;
        }
        case CTRL_CMD_OTA_ABORT: {
            fw_ota_abort();
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

    // Control commands can carry OTA data chunks; match UART_PAYLOAD_MAX (220).
    uint8_t payload[220];
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
    xTaskCreate(ctrl_task, "bridge_ctrl", 6144, NULL, 5, NULL);
    ESP_LOGI(TAG, "Control RX task started (UART%d RX GPIO=%d)", (int)BRIDGE_UART_PORT, BRIDGE_UART_RX_GPIO);
}
