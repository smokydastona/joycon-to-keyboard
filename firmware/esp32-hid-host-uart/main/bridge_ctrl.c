#include "bridge_ctrl.h"

#include <string.h>

#include "config.h"

#include "driver/uart.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"

#include "bt_hid_host.h"
#include "uart_framing.h"
#include "fw_ota.h"
#include "installer_console.h"
#include "joycon_mapper.h"
#include "joycon_setup.h"
#include "buzzer.h"

static const char *TAG = "bridge-ctrl";

#define SYNC0 0xAA
#define SYNC1 0x55

#define CTRL_MARKER 0xFE

#define CTRL_CMD_SET_TARGET_SUBSTR 0x01
#define CTRL_CMD_START_DISCOVERY   0x02
#define CTRL_CMD_SET_STICK_CURVE   0x03
#define CTRL_CMD_CALIBRATION       0x04
#define CTRL_CMD_RUMBLE            0x05
#define CTRL_CMD_HOME_LED          0x06
#define CTRL_CMD_SET_SOCD_MODE     0x07
#define CTRL_CMD_SET_RAPID_TRIGGER 0x08

// OTA control commands (from ESP32-S3)
#define CTRL_CMD_OTA_BEGIN   0x10
#define CTRL_CMD_OTA_DATA    0x11
#define CTRL_CMD_OTA_END     0x12
#define CTRL_CMD_OTA_ABORT   0x13
#define CTRL_CMD_FW_VERSION  0x14

// Buzzer control commands (runtime, persisted to NVS on ESP32 host)
#define CTRL_CMD_BUZZER_GET  0x20
#define CTRL_CMD_BUZZER_SET  0x21
#define CTRL_CMD_BUZZER_TEST 0x22

// OTA response IDs (sent back to ESP32-S3)
#define OTA_RSP_BEGIN   0x01
#define OTA_RSP_DATA    0x02   /* per-chunk ACK so S3 can throttle */
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
            if (payload_len > 48) {
                ESP_LOGW(TAG, "Target substr too long (%u > 48), truncating", (unsigned)payload_len);
                payload_len = 48;
            }
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
            if (payload_len < 1) {
                ESP_LOGW(TAG, "SET_STICK_CURVE: need ≥1 byte, got %u", (unsigned)payload_len);
                break;
            }
            uint8_t curve = payload[0];
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
        case CTRL_CMD_RUMBLE: {
            // payload[0] = device_id (0=left, 1=right)
            // payload[1..2] = freq_hz (uint16 LE)
            // payload[3] = amp_100 (0-100)
            if (payload_len >= 4) {
                uint8_t dev = payload[0];
                uint16_t freq = (uint16_t)(payload[1] | (payload[2] << 8));
                uint8_t amp = payload[3];
                joycon_setup_send_rumble(dev, freq, amp);
            }
            break;
        }
        case CTRL_CMD_HOME_LED: {
            // payload[0] = device_id
            // payload[1] = brightness (0-15)
            if (payload_len >= 2) {
                joycon_setup_set_home_led(payload[0], payload[1]);
            }
            break;
        }
        case CTRL_CMD_SET_SOCD_MODE: {
            // payload[0] = socd mode (0=neutral, 1=last_input, 2=first_input)
            if (payload_len >= 1) {
                joycon_mapper_set_socd_mode(payload[0]);
            }
            break;
        }
        case CTRL_CMD_SET_RAPID_TRIGGER: {
            // payload[0] = activation threshold, payload[1] = deactivation threshold
            if (payload_len >= 2) {
                joycon_mapper_set_rapid_trigger(payload[0], payload[1]);
            }
            break;
        }
        case CTRL_CMD_BUZZER_GET: {
#if CONFIG_BIND_BANDIT_BUZZER_ENABLED
            buzzer_config_t cfg;
            buzzer_get_config(&cfg);

            uint8_t data[5];
            data[0] = cfg.enabled ? 1 : 0;
            data[1] = cfg.volume;
            data[2] = cfg.discovery_tick ? 1 : 0;
            data[3] = (uint8_t)(cfg.tone_mask & 0xFF);
            data[4] = (uint8_t)((cfg.tone_mask >> 8) & 0xFF);

            bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_GET, 0x00, data, (uint8_t)sizeof(data));
#else
            uint8_t err = 0x01; // not_supported
            bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_GET, 0x01, &err, 1);
#endif
            break;
        }
        case CTRL_CMD_BUZZER_SET: {
#if CONFIG_BIND_BANDIT_BUZZER_ENABLED
            // payload: enabled(u8), volume(u8), discovery_tick(u8), tone_mask(u16le)
            if (payload_len < 5) {
                uint8_t err = 0x02; // invalid_arg
                bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_SET, 0x01, &err, 1);
                break;
            }

            buzzer_config_t cfg;
            cfg.enabled = payload[0] != 0;
            cfg.volume = payload[1];
            cfg.discovery_tick = payload[2] != 0;
            cfg.tone_mask = (uint16_t)(payload[3] | ((uint16_t)payload[4] << 8));

            esp_err_t err = buzzer_set_config(&cfg, true);
            if (err != ESP_OK) {
                uint8_t e = (err == ESP_ERR_INVALID_ARG) ? 0x02 : 0x03; // invalid_arg or nvs_error
                bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_SET, 0x01, &e, 1);
            } else {
                bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_SET, 0x00, NULL, 0);
            }
#else
            uint8_t err = 0x01; // not_supported
            bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_SET, 0x01, &err, 1);
#endif
            break;
        }
        case CTRL_CMD_BUZZER_TEST: {
#if CONFIG_BIND_BANDIT_BUZZER_ENABLED
            // payload: tone_id(u8)
            if (payload_len < 1) {
                uint8_t err = 0x02; // invalid_arg
                bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_TEST, 0x01, &err, 1);
                break;
            }
            uint8_t tid = payload[0];
            if (tid >= BUZZER_TONE_COUNT) {
                uint8_t err = 0x02; // invalid_arg
                bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_TEST, 0x01, &err, 1);
                break;
            }

            buzzer_play((buzzer_tone_t)tid);
            bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_TEST, 0x00, NULL, 0);
#else
            uint8_t err = 0x01; // not_supported
            bridge_send_ctrl_rsp(CTRL_CMD_BUZZER_TEST, 0x01, &err, 1);
#endif
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
            if (!fw_ota_in_progress()) {
                bridge_send_ota_rsp(OTA_RSP_DATA, 0x01, NULL, 0);
                break;
            }
            if (payload_len > 0 && payload) {
                esp_err_t err = fw_ota_write(payload, payload_len);
                if (err != ESP_OK) {
                    ESP_LOGE(TAG, "OTA write failed: %s", esp_err_to_name(err));
                    fw_ota_abort();
                    bridge_send_ota_rsp(OTA_RSP_DATA, 0x01, NULL, 0);
                } else {
                    bridge_send_ota_rsp(OTA_RSP_DATA, 0x00, NULL, 0);
                }
            } else {
                bridge_send_ota_rsp(OTA_RSP_DATA, 0x00, NULL, 0);
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

    // UART error counting — alert buzzer on repeated framing errors
    uint32_t uart_err_count = 0;
    int64_t  uart_err_window_start = esp_timer_get_time();
    #define UART_ERR_THRESHOLD    5
    #define UART_ERR_WINDOW_US    (10 * 1000000LL)  // 10 seconds

    while (1) {
        if (installer_console_passthrough_active()) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

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
                    // Count as framing error
                    int64_t now = esp_timer_get_time();
                    if (now - uart_err_window_start > UART_ERR_WINDOW_US) {
                        uart_err_count = 0;
                        uart_err_window_start = now;
                    }
                    uart_err_count++;
                    if (uart_err_count >= UART_ERR_THRESHOLD) {
                        buzzer_play(BUZZER_TONE_ERROR);
                        uart_err_count = 0;
                        uart_err_window_start = now;
                    }
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
                    ESP_LOGD(TAG, "Checksum mismatch: expected 0x%02X got 0x%02X (len=%u)", calc, b, (unsigned)length);
                    int64_t now = esp_timer_get_time();
                    if (now - uart_err_window_start > UART_ERR_WINDOW_US) {
                        uart_err_count = 0;
                        uart_err_window_start = now;
                    }
                    uart_err_count++;
                    if (uart_err_count >= UART_ERR_THRESHOLD) {
                        buzzer_play(BUZZER_TONE_ERROR);
                        uart_err_count = 0;
                        uart_err_window_start = now;
                    }
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
