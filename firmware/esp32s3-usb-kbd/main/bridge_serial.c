#include "bridge_serial.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nvs.h"
#include "nvs_flash.h"

#include "cJSON.h"

#include "tusb.h"

#include "mbedtls/base64.h"

#include "profile_runtime.h"
#include "uart_proto.h"
#include "fw_ota.h"
#include "config_block.h"

static const char *TAG = "bridge-serial";

// UART control commands to the ESP32 BT host.
// payload: 0xFE, cmd_id, ...
#define CTRL_CMD_SET_TARGET_SUBSTR 0x01
#define CTRL_CMD_START_DISCOVERY   0x02

// OTA control commands relayed to ESP32
#define CTRL_CMD_OTA_BEGIN   0x10
#define CTRL_CMD_OTA_DATA    0x11
#define CTRL_CMD_OTA_END     0x12
#define CTRL_CMD_OTA_ABORT   0x13
#define CTRL_CMD_FW_VERSION  0x14

// Stick / calibration control commands relayed to ESP32
#define CTRL_CMD_SET_STICK_CURVE 0x03
#define CTRL_CMD_CALIBRATION     0x04
#define CTRL_CMD_RUMBLE          0x05
#define CTRL_CMD_HOME_LED        0x06
#define CTRL_CMD_SET_SOCD_MODE   0x07
#define CTRL_CMD_SET_RAPID_TRIGGER 0x08

// OTA response IDs received from ESP32 via UART
#define OTA_RSP_MARKER  0xFB
#define OTA_RSP_BEGIN   0x01
#define OTA_RSP_END     0x03
#define OTA_RSP_VERSION 0x04

// Max raw bytes per UART control frame data (frame payload = 0xFE + cmd_id + data)
#define OTA_UART_CHUNK  218

#define BRIDGE_PROFILE_NS "profiles"
#define BRIDGE_ACTIVE_KEY "active"

#define BRIDGE_MAX_SLOTS 4

// Profiles can include mappings + macros; keep a reasonable cap but larger than 1KB.
#define BRIDGE_MAX_LINE 8192
#define BRIDGE_MAX_PROFILE_JSON 8192

static char s_line[BRIDGE_MAX_LINE];
static size_t s_line_len = 0;

static bool s_host_open = false;

// OTA decode buffer for base64 → raw binary.
#define OTA_DECODE_MAX 4096
static uint8_t s_ota_buf[OTA_DECODE_MAX];

// Pending ESP32 OTA response (set by bridge_serial_handle_ota_rsp from main loop).
static volatile bool s_esp32_ota_rsp_ready = false;
static volatile uint8_t s_esp32_ota_rsp_id = 0;
static volatile uint8_t s_esp32_ota_rsp_status = 0;
static uint8_t s_esp32_ota_rsp_data[64];
static volatile uint8_t s_esp32_ota_rsp_data_len = 0;

static void cdc_write_line(const char *line) {
    if (!tud_cdc_connected()) return;

    tud_cdc_write(line, (uint32_t)strlen(line));
    tud_cdc_write("\n", 1);
    tud_cdc_write_flush();
}

static void cdc_write_json(cJSON *obj) {
    char *out = cJSON_PrintUnformatted(obj);
    if (!out) {
        /* Heap exhausted — send a fixed-string error so the host doesn't hang. */
        cdc_write_line("{\"rsp\":\"error\",\"ok\":false,\"error\":\"out_of_memory\"}");
        return;
    }
    cdc_write_line(out);
    cJSON_free(out);
}

static void respond_error(const char *cmd, const char *err) {
    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) return;
    cJSON_AddStringToObject(rsp, "rsp", cmd ? cmd : "error");
    cJSON_AddBoolToObject(rsp, "ok", false);
    cJSON_AddStringToObject(rsp, "error", err ? err : "unknown");
    cdc_write_json(rsp);
    cJSON_Delete(rsp);
}

static void handle_ping(void) {
    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) return;
    cJSON_AddStringToObject(rsp, "rsp", "pong");
    cdc_write_json(rsp);
    cJSON_Delete(rsp);
}

static bool slot_valid(int slot) {
    return (slot >= 0) && (slot < BRIDGE_MAX_SLOTS);
}

static esp_err_t nvs_set_profile_json(int slot, const char *json) {
    char key[8];
    snprintf(key, sizeof(key), "p%d", slot);

    nvs_handle_t h;
    esp_err_t err = nvs_open(BRIDGE_PROFILE_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;

    err = nvs_set_str(h, key, json);
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}

static esp_err_t nvs_get_profile_json(int slot, char **out_json) {
    *out_json = NULL;

    char key[8];
    snprintf(key, sizeof(key), "p%d", slot);

    nvs_handle_t h;
    esp_err_t err = nvs_open(BRIDGE_PROFILE_NS, NVS_READONLY, &h);
    if (err != ESP_OK) return err;

    size_t len = 0;
    err = nvs_get_str(h, key, NULL, &len);
    if (err != ESP_OK) {
        nvs_close(h);
        return err;
    }

    char *buf = (char *)malloc(len);
    if (!buf) {
        nvs_close(h);
        return ESP_ERR_NO_MEM;
    }

    err = nvs_get_str(h, key, buf, &len);
    nvs_close(h);

    if (err != ESP_OK) {
        free(buf);
        return err;
    }

    *out_json = buf;
    return ESP_OK;
}

static esp_err_t nvs_set_active_slot(int slot) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(BRIDGE_PROFILE_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;

    err = nvs_set_i8(h, BRIDGE_ACTIVE_KEY, (int8_t)slot);
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}

static void handle_write_profile(cJSON *root) {
    cJSON *slot = cJSON_GetObjectItemCaseSensitive(root, "slot");
    cJSON *profile = cJSON_GetObjectItemCaseSensitive(root, "profile");

    if (!cJSON_IsNumber(slot) || !slot_valid(slot->valueint)) {
        respond_error("write_profile", "invalid_slot");
        return;
    }
    if (!profile) {
        respond_error("write_profile", "missing_profile");
        return;
    }

    char *profile_str = cJSON_PrintUnformatted(profile);
    if (!profile_str) {
        respond_error("write_profile", "profile_serialize_failed");
        return;
    }

    size_t profile_len = strlen(profile_str);
    if (profile_len > BRIDGE_MAX_PROFILE_JSON) {
        cJSON_free(profile_str);
        respond_error("write_profile", "profile_too_large");
        return;
    }

    esp_err_t err = nvs_set_profile_json(slot->valueint, profile_str);
    cJSON_free(profile_str);

    if (err != ESP_OK) {
        ESP_LOGW(TAG, "nvs_set_profile_json failed: %s", esp_err_to_name(err));
        respond_error("write_profile", "nvs_write_failed");
        return;
    }

    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) return;
    cJSON_AddStringToObject(rsp, "rsp", "write_profile");
    cJSON_AddBoolToObject(rsp, "ok", true);
    cJSON_AddNumberToObject(rsp, "slot", slot->valueint);
    cdc_write_json(rsp);
    cJSON_Delete(rsp);

    // If user overwrote the active slot, reload runtime mapping/macro tables.
    profile_runtime_reload();
}

static void handle_read_profile(cJSON *root) {
    cJSON *slot = cJSON_GetObjectItemCaseSensitive(root, "slot");
    if (!cJSON_IsNumber(slot) || !slot_valid(slot->valueint)) {
        respond_error("read_profile", "invalid_slot");
        return;
    }

    char *profile_json = NULL;
    esp_err_t err = nvs_get_profile_json(slot->valueint, &profile_json);

    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) {
        free(profile_json);
        return;
    }

    cJSON_AddStringToObject(rsp, "rsp", "read_profile");
    cJSON_AddBoolToObject(rsp, "ok", true);
    cJSON_AddNumberToObject(rsp, "slot", slot->valueint);

    if (err == ESP_OK && profile_json) {
        cJSON *profile_obj = cJSON_Parse(profile_json);
        if (profile_obj) {
            cJSON_AddBoolToObject(rsp, "present", true);
            cJSON_AddItemToObject(rsp, "profile", profile_obj);
        } else {
            cJSON_AddBoolToObject(rsp, "present", true);
            cJSON_AddNullToObject(rsp, "profile");
            cJSON_AddStringToObject(rsp, "profile_raw", profile_json);
        }
    } else {
        cJSON_AddBoolToObject(rsp, "present", false);
        cJSON_AddNullToObject(rsp, "profile");
    }

    cdc_write_json(rsp);
    cJSON_Delete(rsp);
    free(profile_json);
}

static void handle_set_active_profile(cJSON *root) {
    cJSON *slot = cJSON_GetObjectItemCaseSensitive(root, "slot");
    if (!cJSON_IsNumber(slot) || !slot_valid(slot->valueint)) {
        respond_error("set_active_profile", "invalid_slot");
        return;
    }

    esp_err_t err = nvs_set_active_slot(slot->valueint);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "nvs_set_active_slot failed: %s", esp_err_to_name(err));
        respond_error("set_active_profile", "nvs_write_failed");
        return;
    }

    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) return;
    cJSON_AddStringToObject(rsp, "rsp", "set_active_profile");
    cJSON_AddBoolToObject(rsp, "ok", true);
    cJSON_AddNumberToObject(rsp, "slot", slot->valueint);
    cdc_write_json(rsp);
    cJSON_Delete(rsp);

    profile_runtime_reload();
}

static void respond_ok_simple(const char *rsp_name) {
    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) return;
    cJSON_AddStringToObject(rsp, "rsp", rsp_name ? rsp_name : "ok");
    cJSON_AddBoolToObject(rsp, "ok", true);
    cdc_write_json(rsp);
    cJSON_Delete(rsp);
}

static void handle_bt_set_target(cJSON *root) {
    cJSON *name_substr = cJSON_GetObjectItemCaseSensitive(root, "name_substr");
    if (!cJSON_IsString(name_substr) || !name_substr->valuestring) {
        respond_error("bt_set_target", "missing_name_substr");
        return;
    }

    const char *s = name_substr->valuestring;
    size_t n = strlen(s);
    if (n > 48) {
        respond_error("bt_set_target", "name_substr_too_long");
        return;
    }

    if (!uart_proto_send_ctrl(CTRL_CMD_SET_TARGET_SUBSTR, (const uint8_t *)s, (uint8_t)n)) {
        respond_error("bt_set_target", "uart_send_failed");
        return;
    }

    respond_ok_simple("bt_set_target");
}

static void handle_bt_connect(cJSON *root) {
    bool both = false;
    cJSON *both_obj = cJSON_GetObjectItemCaseSensitive(root, "both");
    if (cJSON_IsBool(both_obj)) {
        both = cJSON_IsTrue(both_obj);
    }

    uint8_t flags = both ? 0x01 : 0x00;
    const uint8_t *payload = both ? &flags : NULL;
    uint8_t payload_len = both ? 1 : 0;

    if (!uart_proto_send_ctrl(CTRL_CMD_START_DISCOVERY, payload, payload_len)) {
        respond_error("bt_connect", "uart_send_failed");
        return;
    }
    respond_ok_simple("bt_connect");
}

// ---------------------------------------------------------------------------
// Firmware version / OTA update commands
// ---------------------------------------------------------------------------

static bool is_board_esp32(cJSON *root) {
    cJSON *board = cJSON_GetObjectItemCaseSensitive(root, "board");
    return cJSON_IsString(board) && strcmp(board->valuestring, "esp32") == 0;
}

// Wait for an OTA response from ESP32, keeping USB alive.
// Returns true if a response arrived within timeout_ms.
static bool wait_esp32_ota_rsp(uint8_t expected_rsp_id, int timeout_ms) {
    s_esp32_ota_rsp_ready = false;

    TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
    while (xTaskGetTickCount() < deadline) {
        // Do NOT call tud_task() here — tinyusb_driver_install() already runs
        // TinyUSB in its own FreeRTOS task.  Calling tud_task() from a second
        // task concurrently corrupts TinyUSB's CDC TX/RX state machine.

        // Poll UART for frames; the main loop's frame processing is inlined here.
        uart_frame_t f;
        while (uart_proto_poll_frame(&f)) {
            if (f.type == UART_FRAME_OTA_RSP) {
                bridge_serial_handle_ota_rsp(f.payload, f.length);
            }
            // Ignore other frames during OTA relay.
        }

        if (s_esp32_ota_rsp_ready && s_esp32_ota_rsp_id == expected_rsp_id) {
            return true;
        }
        vTaskDelay(1);
    }
    return false;
}

static void handle_fw_version(cJSON *root) {
    if (is_board_esp32(root)) {
        // Relay to ESP32 via UART and wait for response.
        uart_proto_send_ctrl(CTRL_CMD_FW_VERSION, NULL, 0);

        if (!wait_esp32_ota_rsp(OTA_RSP_VERSION, 3000)) {
            respond_error("fw_version", "esp32_timeout");
            return;
        }

        // Build version string from response data.
        char ver[64] = {0};
        uint8_t n = s_esp32_ota_rsp_data_len;
        if (n >= sizeof(ver)) n = (uint8_t)(sizeof(ver) - 1);
        memcpy(ver, s_esp32_ota_rsp_data, n);
        ver[n] = 0;

        cJSON *rsp = cJSON_CreateObject();
        if (!rsp) return;
        cJSON_AddStringToObject(rsp, "rsp", "fw_version");
        cJSON_AddBoolToObject(rsp, "ok", true);
        cJSON_AddStringToObject(rsp, "board", "esp32");
        cJSON_AddStringToObject(rsp, "version", ver);
        cdc_write_json(rsp);
        cJSON_Delete(rsp);
        return;
    }

    // Local (ESP32-S3) version.
    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) return;
    cJSON_AddStringToObject(rsp, "rsp", "fw_version");
    cJSON_AddBoolToObject(rsp, "ok", true);
    cJSON_AddStringToObject(rsp, "board", "esp32s3");
    cJSON_AddStringToObject(rsp, "version", fw_ota_version());
    cdc_write_json(rsp);
    cJSON_Delete(rsp);
}

static void handle_fw_update_begin(cJSON *root) {
    cJSON *size_obj = cJSON_GetObjectItemCaseSensitive(root, "size");
    uint32_t total_size = 0;
    if (cJSON_IsNumber(size_obj)) {
        total_size = (uint32_t)size_obj->valuedouble;
    }

    if (is_board_esp32(root)) {
        // Relay to ESP32.
        uint8_t buf[4];
        buf[0] = (uint8_t)(total_size & 0xFF);
        buf[1] = (uint8_t)((total_size >> 8) & 0xFF);
        buf[2] = (uint8_t)((total_size >> 16) & 0xFF);
        buf[3] = (uint8_t)((total_size >> 24) & 0xFF);
        uart_proto_send_ctrl(CTRL_CMD_OTA_BEGIN, buf, 4);

        if (!wait_esp32_ota_rsp(OTA_RSP_BEGIN, 10000)) {
            respond_error("fw_update_begin", "esp32_timeout");
            return;
        }
        if (s_esp32_ota_rsp_status != 0x00) {
            respond_error("fw_update_begin", "esp32_ota_begin_failed");
            return;
        }
        respond_ok_simple("fw_update_begin");
        return;
    }

    // Local OTA begin.
    esp_err_t err = fw_ota_begin(total_size);
    if (err != ESP_OK) {
        respond_error("fw_update_begin", "ota_begin_failed");
        return;
    }
    respond_ok_simple("fw_update_begin");
}

static void handle_fw_update_data(cJSON *root) {
    cJSON *data_obj = cJSON_GetObjectItemCaseSensitive(root, "data");
    if (!cJSON_IsString(data_obj) || !data_obj->valuestring) {
        respond_error("fw_update_data", "missing_data");
        return;
    }

    const char *b64 = data_obj->valuestring;
    size_t b64_len = strlen(b64);
    size_t decoded_len = 0;

    int ret = mbedtls_base64_decode(s_ota_buf, sizeof(s_ota_buf), &decoded_len,
                                    (const unsigned char *)b64, b64_len);
    if (ret != 0 || decoded_len == 0) {
        respond_error("fw_update_data", "base64_decode_failed");
        return;
    }

    if (is_board_esp32(root)) {
        // Relay as UART control frames in OTA_UART_CHUNK-sized pieces.
        size_t offset = 0;
        while (offset < decoded_len) {
            size_t chunk = decoded_len - offset;
            if (chunk > OTA_UART_CHUNK) chunk = OTA_UART_CHUNK;
            uart_proto_send_ctrl(CTRL_CMD_OTA_DATA, &s_ota_buf[offset], (uint8_t)chunk);
            offset += chunk;
        }
        respond_ok_simple("fw_update_data");
        return;
    }

    // Local OTA write.
    esp_err_t err = fw_ota_write(s_ota_buf, (uint32_t)decoded_len);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "OTA write failed: %s", esp_err_to_name(err));
        fw_ota_abort();
        respond_error("fw_update_data", "ota_write_failed");
        return;
    }

    cJSON *rsp = cJSON_CreateObject();
    if (!rsp) return;
    cJSON_AddStringToObject(rsp, "rsp", "fw_update_data");
    cJSON_AddBoolToObject(rsp, "ok", true);
    cJSON_AddNumberToObject(rsp, "written", (double)decoded_len);
    cdc_write_json(rsp);
    cJSON_Delete(rsp);
}

static void handle_fw_update_end(cJSON *root) {
    if (is_board_esp32(root)) {
        uart_proto_send_ctrl(CTRL_CMD_OTA_END, NULL, 0);

        if (!wait_esp32_ota_rsp(OTA_RSP_END, 15000)) {
            respond_error("fw_update_end", "esp32_timeout");
            return;
        }
        if (s_esp32_ota_rsp_status != 0x00) {
            respond_error("fw_update_end", "esp32_ota_end_failed");
            return;
        }
        respond_ok_simple("fw_update_end");
        return;
    }

    // Local OTA finalize.
    esp_err_t err = fw_ota_end();
    if (err != ESP_OK) {
        respond_error("fw_update_end", "ota_end_failed");
        return;
    }

    respond_ok_simple("fw_update_end");

    // Reboot after a short delay.
    ESP_LOGI(TAG, "OTA complete – rebooting in 1 s");
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
}

static void handle_fw_update_abort(cJSON *root) {
    if (is_board_esp32(root)) {
        uart_proto_send_ctrl(CTRL_CMD_OTA_ABORT, NULL, 0);
        respond_ok_simple("fw_update_abort");
        return;
    }

    fw_ota_abort();
    respond_ok_simple("fw_update_abort");
}

static void handle_set_stick_curve(cJSON *root) {
    // {"cmd":"set_stick_curve", "curve":"linear"|"exponential"|"quadratic", "exp":1.5}
    cJSON *curve_j = cJSON_GetObjectItemCaseSensitive(root, "curve");
    cJSON *exp_j = cJSON_GetObjectItemCaseSensitive(root, "exp");

    uint8_t curve = 0;  // default linear
    if (cJSON_IsString(curve_j) && curve_j->valuestring) {
        if (strcmp(curve_j->valuestring, "exponential") == 0) curve = 1;
        else if (strcmp(curve_j->valuestring, "quadratic") == 0) curve = 2;
    }

    uint8_t exp_x100 = 100;
    if (cJSON_IsNumber(exp_j)) {
        int v = (int)(exp_j->valuedouble * 100.0);
        if (v < 10) v = 10;
        if (v > 250) v = 250;
        exp_x100 = (uint8_t)v;
    }

    uint8_t payload[2] = {curve, exp_x100};
    if (!uart_proto_send_ctrl(CTRL_CMD_SET_STICK_CURVE, payload, 2)) {
        respond_error("set_stick_curve", "uart_send_failed");
        return;
    }
    respond_ok_simple("set_stick_curve");
}

static void handle_calibration(cJSON *root) {
    // {"cmd":"calibration", "action":"save"|"clear"}
    cJSON *action_j = cJSON_GetObjectItemCaseSensitive(root, "action");
    if (!cJSON_IsString(action_j) || !action_j->valuestring) {
        respond_error("calibration", "missing_action");
        return;
    }

    uint8_t sub = 0;
    if (strcmp(action_j->valuestring, "save") == 0) {
        sub = 0x01;
    } else if (strcmp(action_j->valuestring, "clear") == 0) {
        sub = 0x02;
    } else {
        respond_error("calibration", "invalid_action");
        return;
    }

    if (!uart_proto_send_ctrl(CTRL_CMD_CALIBRATION, &sub, 1)) {
        respond_error("calibration", "uart_send_failed");
        return;
    }
    respond_ok_simple("calibration");
}

static void handle_rumble(cJSON *root) {
    // {"cmd":"rumble", "device_id":0, "freq":160, "amp":50}
    cJSON *dev_j = cJSON_GetObjectItemCaseSensitive(root, "device_id");
    cJSON *freq_j = cJSON_GetObjectItemCaseSensitive(root, "freq");
    cJSON *amp_j = cJSON_GetObjectItemCaseSensitive(root, "amp");

    uint8_t device_id = 0;
    if (cJSON_IsNumber(dev_j)) device_id = (uint8_t)dev_j->valueint;

    uint16_t freq = 160;
    if (cJSON_IsNumber(freq_j)) {
        int f = freq_j->valueint;
        if (f < 41) f = 41;
        if (f > 1253) f = 1253;
        freq = (uint16_t)f;
    }

    uint8_t amp = 50;
    if (cJSON_IsNumber(amp_j)) {
        int a = amp_j->valueint;
        if (a < 0) a = 0;
        if (a > 100) a = 100;
        amp = (uint8_t)a;
    }

    uint8_t payload[4];
    payload[0] = device_id;
    payload[1] = (uint8_t)(freq & 0xFF);
    payload[2] = (uint8_t)((freq >> 8) & 0xFF);
    payload[3] = amp;

    if (!uart_proto_send_ctrl(CTRL_CMD_RUMBLE, payload, 4)) {
        respond_error("rumble", "uart_send_failed");
        return;
    }
    respond_ok_simple("rumble");
}

static void handle_home_led(cJSON *root) {
    // {"cmd":"home_led", "device_id":0, "brightness":8}
    cJSON *dev_j = cJSON_GetObjectItemCaseSensitive(root, "device_id");
    cJSON *bright_j = cJSON_GetObjectItemCaseSensitive(root, "brightness");

    uint8_t device_id = 0;
    if (cJSON_IsNumber(dev_j)) device_id = (uint8_t)dev_j->valueint;

    uint8_t brightness = 8;
    if (cJSON_IsNumber(bright_j)) {
        int b = bright_j->valueint;
        if (b < 0) b = 0;
        if (b > 15) b = 15;
        brightness = (uint8_t)b;
    }

    uint8_t payload[2];
    payload[0] = device_id;
    payload[1] = brightness;

    if (!uart_proto_send_ctrl(CTRL_CMD_HOME_LED, payload, 2)) {
        respond_error("home_led", "uart_send_failed");
        return;
    }
    respond_ok_simple("home_led");
}

static void handle_line(const char *line) {
    cJSON *root = cJSON_Parse(line);
    if (!root) {
        respond_error("parse", "invalid_json");
        return;
    }

    cJSON *cmd = cJSON_GetObjectItemCaseSensitive(root, "cmd");
    if (!cJSON_IsString(cmd) || !cmd->valuestring) {
        cJSON_Delete(root);
        respond_error("cmd", "missing_cmd");
        return;
    }

    if (strcmp(cmd->valuestring, "ping") == 0) {
        handle_ping();
    } else if (strcmp(cmd->valuestring, "write_profile") == 0) {
        handle_write_profile(root);
    } else if (strcmp(cmd->valuestring, "read_profile") == 0) {
        handle_read_profile(root);
    } else if (strcmp(cmd->valuestring, "set_active_profile") == 0) {
        handle_set_active_profile(root);
    } else if (strcmp(cmd->valuestring, "bt_set_target") == 0) {
        handle_bt_set_target(root);
    } else if (strcmp(cmd->valuestring, "bt_connect") == 0) {
        handle_bt_connect(root);
    } else if (strcmp(cmd->valuestring, "fw_version") == 0) {
        handle_fw_version(root);
    } else if (strcmp(cmd->valuestring, "fw_update_begin") == 0) {
        handle_fw_update_begin(root);
    } else if (strcmp(cmd->valuestring, "fw_update_data") == 0) {
        handle_fw_update_data(root);
    } else if (strcmp(cmd->valuestring, "fw_update_end") == 0) {
        handle_fw_update_end(root);
    } else if (strcmp(cmd->valuestring, "fw_update_abort") == 0) {
        handle_fw_update_abort(root);
    } else if (strcmp(cmd->valuestring, "set_stick_curve") == 0) {
        handle_set_stick_curve(root);
    } else if (strcmp(cmd->valuestring, "calibration") == 0) {
        handle_calibration(root);
    } else if (strcmp(cmd->valuestring, "rumble") == 0) {
        handle_rumble(root);
    } else if (strcmp(cmd->valuestring, "home_led") == 0) {
        handle_home_led(root);
    } else if (strcmp(cmd->valuestring, "set_socd_mode") == 0) {
        cJSON *mode_j = cJSON_GetObjectItemCaseSensitive(root, "mode");
        uint8_t mode = 0;
        if (cJSON_IsString(mode_j) && mode_j->valuestring) {
            if (strcmp(mode_j->valuestring, "last_input") == 0) mode = 1;
            else if (strcmp(mode_j->valuestring, "first_input") == 0) mode = 2;
        } else if (cJSON_IsNumber(mode_j)) {
            mode = (uint8_t)mode_j->valueint;
        }
        if (mode > 2) mode = 0;
        uart_proto_send_ctrl(CTRL_CMD_SET_SOCD_MODE, &mode, 1);
        respond_ok_simple("set_socd_mode");
    } else if (strcmp(cmd->valuestring, "set_rapid_trigger") == 0) {
        cJSON *act_j = cJSON_GetObjectItemCaseSensitive(root, "activation");
        cJSON *deact_j = cJSON_GetObjectItemCaseSensitive(root, "deactivation");
        uint8_t act = 30, deact = 20;
        if (cJSON_IsNumber(act_j)) act = (uint8_t)act_j->valueint;
        if (cJSON_IsNumber(deact_j)) deact = (uint8_t)deact_j->valueint;
        if (act < 1) act = 1;
        if (deact > act) deact = act;
        uint8_t payload[2] = {act, deact};
        uart_proto_send_ctrl(CTRL_CMD_SET_RAPID_TRIGGER, payload, 2);
        respond_ok_simple("set_rapid_trigger");
    } else if (strcmp(cmd->valuestring, "set_humanize") == 0) {
        cJSON *en = cJSON_GetObjectItemCaseSensitive(root, "enabled");
        if (cJSON_IsBool(en)) {
            profile_runtime_set_humanize(cJSON_IsTrue(en));
        }
        cJSON *rsp = cJSON_CreateObject();
        if (rsp) {
            cJSON_AddStringToObject(rsp, "rsp", "set_humanize");
            cJSON_AddBoolToObject(rsp, "ok", true);
            cJSON_AddBoolToObject(rsp, "enabled", profile_runtime_get_humanize());
            cdc_write_json(rsp);
            cJSON_Delete(rsp);
        }
    } else if (strcmp(cmd->valuestring, "gyro_cal_start") == 0) {
        bool ok = profile_runtime_start_gyro_cal();
        cJSON *rsp = cJSON_CreateObject();
        if (rsp) {
            cJSON_AddStringToObject(rsp, "rsp", "gyro_cal_start");
            cJSON_AddBoolToObject(rsp, "ok", ok);
            if (!ok) cJSON_AddStringToObject(rsp, "error", "already_active");
            cdc_write_json(rsp);
            cJSON_Delete(rsp);
        }
    } else if (strcmp(cmd->valuestring, "gyro_cal_status") == 0) {
        cJSON *rsp = cJSON_CreateObject();
        if (rsp) {
            cJSON_AddStringToObject(rsp, "rsp", "gyro_cal_status");
            cJSON_AddBoolToObject(rsp, "active", profile_runtime_gyro_cal_active());
            int16_t bx, by, bz;
            profile_runtime_get_gyro_bias(&bx, &by, &bz);
            cJSON_AddNumberToObject(rsp, "bias_x", bx);
            cJSON_AddNumberToObject(rsp, "bias_y", by);
            cJSON_AddNumberToObject(rsp, "bias_z", bz);
            cdc_write_json(rsp);
            cJSON_Delete(rsp);
        }
    } else if (strcmp(cmd->valuestring, "gyro_cal_set") == 0) {
        cJSON *bx_j = cJSON_GetObjectItemCaseSensitive(root, "bias_x");
        cJSON *by_j = cJSON_GetObjectItemCaseSensitive(root, "bias_y");
        cJSON *bz_j = cJSON_GetObjectItemCaseSensitive(root, "bias_z");
        int16_t bx = cJSON_IsNumber(bx_j) ? (int16_t)bx_j->valueint : 0;
        int16_t by = cJSON_IsNumber(by_j) ? (int16_t)by_j->valueint : 0;
        int16_t bz = cJSON_IsNumber(bz_j) ? (int16_t)bz_j->valueint : 0;
        profile_runtime_set_gyro_bias(bx, by, bz);
        respond_ok_simple("gyro_cal_set");
    } else if (strcmp(cmd->valuestring, "set_led") == 0) {
        cJSON *pat_j = cJSON_GetObjectItemCaseSensitive(root, "pattern");
        cJSON *r_j = cJSON_GetObjectItemCaseSensitive(root, "r");
        cJSON *g_j = cJSON_GetObjectItemCaseSensitive(root, "g");
        cJSON *b_j = cJSON_GetObjectItemCaseSensitive(root, "b");
        cJSON *spd_j = cJSON_GetObjectItemCaseSensitive(root, "speed");
        uint8_t pat = cJSON_IsNumber(pat_j) ? (uint8_t)pat_j->valueint : 0;
        uint8_t r = cJSON_IsNumber(r_j) ? (uint8_t)r_j->valueint : 0;
        uint8_t g = cJSON_IsNumber(g_j) ? (uint8_t)g_j->valueint : 0;
        uint8_t b = cJSON_IsNumber(b_j) ? (uint8_t)b_j->valueint : 0;
        uint16_t speed = cJSON_IsNumber(spd_j) ? (uint16_t)spd_j->valueint : 500;
        profile_runtime_set_led(pat, r, g, b, speed);
        respond_ok_simple("set_led");
    } else if (strcmp(cmd->valuestring, "test_key") == 0) {
        // Synthetic key press for HID path verification.
        // Usage: {"cmd":"test_key","key_id":1}  (key_id 1 = W / Forward)
        cJSON *kid_j = cJSON_GetObjectItemCaseSensitive(root, "key_id");
        uint8_t test_kid = (kid_j && cJSON_IsNumber(kid_j)) ? (uint8_t)kid_j->valueint : 1u;
        profile_runtime_handle_input(true, test_kid);
        vTaskDelay(pdMS_TO_TICKS(80));
        profile_runtime_handle_input(false, test_kid);
        cJSON *rsp = cJSON_CreateObject();
        if (rsp) {
            cJSON_AddStringToObject(rsp, "rsp", "test_key");
            cJSON_AddNumberToObject(rsp, "key_id", test_kid);
            cJSON_AddStringToObject(rsp, "status", "ok");
            cdc_write_json(rsp);
            cJSON_Delete(rsp);
        }
    } else if (strcmp(cmd->valuestring, "uart_diag") == 0) {
        uart_diag_t diag;
        uart_proto_get_diag(&diag);
        cJSON *rsp = cJSON_CreateObject();
        if (rsp) {
            cJSON_AddStringToObject(rsp, "rsp", "uart_diag");
            cJSON_AddNumberToObject(rsp, "port", diag.port);
            cJSON_AddNumberToObject(rsp, "baud", diag.baud);
            cJSON_AddNumberToObject(rsp, "rx_gpio", diag.rx_gpio);
            cJSON_AddNumberToObject(rsp, "tx_gpio", diag.tx_gpio);
            cJSON_AddNumberToObject(rsp, "rx_pin_level", diag.rx_pin_level);
            cJSON_AddNumberToObject(rsp, "buffered_bytes", (double)diag.buffered_bytes);
            cJSON_AddNumberToObject(rsp, "total_rx_bytes", (double)diag.total_rx_bytes);
            cJSON_AddNumberToObject(rsp, "total_frames", (double)diag.total_frames);
            cJSON_AddNumberToObject(rsp, "sample_len", diag.sample_len);
            if (diag.sample_len > 0) {
                char hex[sizeof(diag.sample) * 3 + 1];
                hex[0] = '\0';
                for (int i = 0; i < diag.sample_len; i++) {
                    char tmp[4];
                    snprintf(tmp, sizeof(tmp), "%s%02X",
                             (i > 0) ? " " : "", diag.sample[i]);
                    strcat(hex, tmp);
                }
                cJSON_AddStringToObject(rsp, "sample_hex", hex);
            }
            cdc_write_json(rsp);
            cJSON_Delete(rsp);
        }
    } else {
        respond_error(cmd->valuestring, "unknown_cmd");
    }

    cJSON_Delete(root);
}

void bridge_serial_init(void) {
    // NVS is used for profile slot persistence.
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    config_block_init();

    ESP_LOGI(TAG, "Serial protocol ready (NDJSON + binary config over CDC)");
}

void bridge_serial_poll(void) {
    if (!tud_cdc_connected()) return;

    while (tud_cdc_available()) {
        /* --- Binary config mode: feed all available bytes until idle --- */
        if (config_block_receiving()) {
            uint8_t buf[64];
            uint32_t avail = tud_cdc_available();
            if (avail > sizeof(buf)) avail = sizeof(buf);
            uint32_t rd = tud_cdc_read(buf, avail);
            if (rd) config_block_feed(buf, rd);
            continue;
        }

        uint8_t ch;
        if (tud_cdc_read(&ch, 1) != 1) break;

        /* Detect the binary config marker at the start of a new "line". */
        if (s_line_len == 0 && ch == CONFIG_BLOCK_MARKER) {
            /* Feed the marker byte to kick the state machine out of IDLE. */
            config_block_feed(&ch, 1);
            continue;
        }

        if (ch == '\r') continue;

        if (ch == '\n') {
            if (s_line_len > 0) {
                s_line[s_line_len] = 0;
                handle_line(s_line);
                s_line_len = 0;
            }
            continue;
        }

        if (s_line_len + 1 >= sizeof(s_line)) {
            // Overlong line; drop it.
            s_line_len = 0;
            respond_error("parse", "line_too_long");
            continue;
        }

        s_line[s_line_len++] = (char)ch;
    }
}

void bridge_serial_emit_mapped_key(bool pressed, uint8_t key_id) {
    if (!tud_cdc_connected() || !s_host_open) return;

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;

    cJSON_AddStringToObject(evt, "evt", "mapped_key");
    cJSON_AddBoolToObject(evt, "pressed", pressed);
    cJSON_AddNumberToObject(evt, "key_id", key_id);

    cdc_write_json(evt);
    cJSON_Delete(evt);
}

void bridge_serial_emit_macro_state(const char *id, bool started) {
    if (!tud_cdc_connected() || !s_host_open) return;
    if (!id) return;

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;

    cJSON_AddStringToObject(evt, "evt", "macro");
    cJSON_AddStringToObject(evt, "id", id);
    cJSON_AddStringToObject(evt, "state", started ? "start" : "end");

    cdc_write_json(evt);
    cJSON_Delete(evt);
}

void bridge_serial_emit_layer_state(const char *name, bool active) {
    if (!tud_cdc_connected() || !s_host_open) return;
    if (!name) return;

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;

    cJSON_AddStringToObject(evt, "evt", "layer");
    cJSON_AddStringToObject(evt, "name", name);
    cJSON_AddBoolToObject(evt, "active", active);

    cdc_write_json(evt);
    cJSON_Delete(evt);
}

void bridge_serial_emit_bt_status(const char *state, const char *name, const char *bda_str) {
    if (!tud_cdc_connected() || !s_host_open) return;
    if (!state) return;

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;

    cJSON_AddStringToObject(evt, "evt", "bt_status");
    cJSON_AddStringToObject(evt, "state", state);
    if (name) {
        cJSON_AddStringToObject(evt, "name", name);
    }
    if (bda_str) {
        cJSON_AddStringToObject(evt, "bda", bda_str);
    }

    cdc_write_json(evt);
    cJSON_Delete(evt);
}

void bridge_serial_handle_ota_rsp(const uint8_t *payload, uint8_t length) {
    // payload: [0]=0xFB, [1]=rsp_id, [2]=status, [3..]=data
    if (length < 3) return;

    s_esp32_ota_rsp_id = payload[1];
    s_esp32_ota_rsp_status = payload[2];

    uint8_t dlen = (length > 3) ? (uint8_t)(length - 3) : 0;
    if (dlen > sizeof(s_esp32_ota_rsp_data)) dlen = sizeof(s_esp32_ota_rsp_data);
    if (dlen > 0) {
        memcpy(s_esp32_ota_rsp_data, &payload[3], dlen);
    }
    s_esp32_ota_rsp_data_len = dlen;
    s_esp32_ota_rsp_ready = true;
}

void bridge_serial_emit_battery(uint8_t device_id, uint8_t level) {
    if (!tud_cdc_connected() || !s_host_open) return;

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;

    cJSON_AddStringToObject(evt, "evt", "battery");
    cJSON_AddNumberToObject(evt, "device_id", device_id);
    cJSON_AddNumberToObject(evt, "level", level);

    cdc_write_json(evt);
    cJSON_Delete(evt);
}

void bridge_serial_emit_controller_info(const uint8_t *payload, uint8_t length) {
    if (!tud_cdc_connected() || !s_host_open) return;
    // payload[0]=0xF9, [1]=device_id, [2]=ctrl_type, [3]=serial_len, [4..]=serial, ...
    if (length < 4) return;

    uint8_t pos = 1;
    uint8_t device_id = payload[pos++];
    uint8_t ctrl_type = payload[pos++];
    uint8_t serial_len = payload[pos++];

    char serial[16] = {0};
    if (serial_len > 0 && serial_len <= 15 && pos + serial_len <= length) {
        memcpy(serial, &payload[pos], serial_len);
        serial[serial_len] = '\0';
        pos += serial_len;
    }

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;
    cJSON_AddStringToObject(evt, "evt", "controller_info");
    cJSON_AddNumberToObject(evt, "device_id", device_id);

    const char *type_str = "unknown";
    if (ctrl_type == 1) type_str = "joycon_l";
    else if (ctrl_type == 2) type_str = "joycon_r";
    else if (ctrl_type == 3) type_str = "pro";
    cJSON_AddStringToObject(evt, "type", type_str);

    if (serial_len > 0) {
        cJSON_AddStringToObject(evt, "serial", serial);
    }

    // Colors
    if (pos < length) {
        uint8_t has_colors = payload[pos++];
        if (has_colors && pos + 6 <= length) {
            char body_hex[8], btn_hex[8];
            snprintf(body_hex, sizeof(body_hex), "#%02X%02X%02X",
                     payload[pos], payload[pos + 1], payload[pos + 2]);
            snprintf(btn_hex, sizeof(btn_hex), "#%02X%02X%02X",
                     payload[pos + 3], payload[pos + 4], payload[pos + 5]);
            cJSON_AddStringToObject(evt, "body_color", body_hex);
            cJSON_AddStringToObject(evt, "button_color", btn_hex);
            pos += 6;
        }
    }

    // Stick params
    if (pos < length) {
        uint8_t has_params = payload[pos++];
        if (has_params && pos + 4 <= length) {
            uint16_t deadzone = (uint16_t)(payload[pos] | (payload[pos + 1] << 8));
            uint16_t range_ratio = (uint16_t)(payload[pos + 2] | (payload[pos + 3] << 8));
            cJSON_AddNumberToObject(evt, "stick_deadzone", deadzone);
            cJSON_AddNumberToObject(evt, "stick_range_ratio", range_ratio);
            pos += 4;
        }
    }

    // IMU cal
    if (pos < length) {
        uint8_t has_imu = payload[pos++];
        if (has_imu && pos + 24 <= length) {
            cJSON *imu = cJSON_CreateObject();
            if (imu) {
                cJSON *acc_o = cJSON_CreateArray();
                cJSON *acc_s = cJSON_CreateArray();
                cJSON *gyro_o = cJSON_CreateArray();
                cJSON *gyro_s = cJSON_CreateArray();
                for (int i = 0; i < 3; i++) {
                    int16_t v = (int16_t)(payload[pos] | (payload[pos + 1] << 8));
                    cJSON_AddItemToArray(acc_o, cJSON_CreateNumber(v));
                    pos += 2;
                }
                for (int i = 0; i < 3; i++) {
                    int16_t v = (int16_t)(payload[pos] | (payload[pos + 1] << 8));
                    cJSON_AddItemToArray(acc_s, cJSON_CreateNumber(v));
                    pos += 2;
                }
                for (int i = 0; i < 3; i++) {
                    int16_t v = (int16_t)(payload[pos] | (payload[pos + 1] << 8));
                    cJSON_AddItemToArray(gyro_o, cJSON_CreateNumber(v));
                    pos += 2;
                }
                for (int i = 0; i < 3; i++) {
                    int16_t v = (int16_t)(payload[pos] | (payload[pos + 1] << 8));
                    cJSON_AddItemToArray(gyro_s, cJSON_CreateNumber(v));
                    pos += 2;
                }
                cJSON_AddItemToObject(imu, "acc_origin", acc_o);
                cJSON_AddItemToObject(imu, "acc_sens", acc_s);
                cJSON_AddItemToObject(imu, "gyro_origin", gyro_o);
                cJSON_AddItemToObject(imu, "gyro_sens", gyro_s);
                cJSON_AddItemToObject(evt, "imu_cal", imu);
            }
        }
    }

    cdc_write_json(evt);
    cJSON_Delete(evt);
}

void bridge_serial_emit_rssi(uint8_t device_id, int8_t rssi) {
    if (!tud_cdc_connected() || !s_host_open) return;

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;

    cJSON_AddStringToObject(evt, "evt", "rssi");
    cJSON_AddNumberToObject(evt, "device_id", device_id);
    cJSON_AddNumberToObject(evt, "rssi", rssi);

    cdc_write_json(evt);
    cJSON_Delete(evt);
}

// Optional callback fired when the host opens/closes the serial port.
void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts) {
    (void)itf;
    (void)rts;

    s_host_open = dtr;

    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;
    cJSON_AddStringToObject(evt, "evt", "cdc");
    cJSON_AddBoolToObject(evt, "open", s_host_open);
    cdc_write_json(evt);
    cJSON_Delete(evt);
}
