#include "bridge_serial.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_err.h"
#include "esp_log.h"

#include "nvs.h"
#include "nvs_flash.h"

#include "cJSON.h"

#include "tusb.h"

#include "profile_runtime.h"
#include "uart_proto.h"

static const char *TAG = "bridge-serial";

// UART control commands to the ESP32 BT host.
// payload: 0xFE, cmd_id, ...
#define CTRL_CMD_SET_TARGET_SUBSTR 0x01
#define CTRL_CMD_START_DISCOVERY   0x02

#define BRIDGE_PROFILE_NS "profiles"
#define BRIDGE_ACTIVE_KEY "active"

#define BRIDGE_MAX_SLOTS 4

// Profiles can include mappings + macros; keep a reasonable cap but larger than 1KB.
#define BRIDGE_MAX_LINE 8192
#define BRIDGE_MAX_PROFILE_JSON 8192

static char s_line[BRIDGE_MAX_LINE];
static size_t s_line_len = 0;

static bool s_host_open = false;

static void cdc_write_line(const char *line) {
    if (!tud_cdc_connected()) return;

    tud_cdc_write(line, (uint32_t)strlen(line));
    tud_cdc_write("\n", 1);
    tud_cdc_write_flush();
}

static void cdc_write_json(cJSON *obj) {
    char *out = cJSON_PrintUnformatted(obj);
    if (!out) return;
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

    ESP_LOGI(TAG, "Serial protocol ready (NDJSON over CDC)");
}

void bridge_serial_poll(void) {
    if (!tud_cdc_connected()) return;

    while (tud_cdc_available()) {
        uint8_t ch;
        if (tud_cdc_read(&ch, 1) != 1) break;

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
