#include "bt_hid_host.h"

#include <stdbool.h>
#include <string.h>

#include "nvs_flash.h"

#include "esp_bt.h"
#include "esp_bt_main.h"
#include "esp_bt_device.h"
#include "esp_gap_bt_api.h"

#include "esp_hidh_api.h"

#include "esp_log.h"

#include "joycon_mapper.h"
#include "uart_framing.h"

static const char* TAG = "bt-hidh";

static bool s_connecting = false;
static esp_bd_addr_t s_target_bda = {0};

static char s_target_name_override[64] = {0};

static bool name_matches_target(const char* name) {
    if (!name) return false;
    const char* needle = (s_target_name_override[0] != 0) ? s_target_name_override : CONFIG_JOYCON_HOST_NAME_SUBSTR;
    if (!needle || needle[0] == 0) {
        return false;
    }
    return (strstr(name, needle) != NULL);
}

static const char* bda_to_str(const esp_bd_addr_t bda, char* out, size_t out_len) {
    if (out_len < 18) return "";
    snprintf(out, out_len, "%02x:%02x:%02x:%02x:%02x:%02x",
             bda[0], bda[1], bda[2], bda[3], bda[4], bda[5]);
    return out;
}

static void try_connect(const esp_bd_addr_t bda) {
    if (s_connecting) return;

    memcpy(s_target_bda, bda, sizeof(esp_bd_addr_t));
    s_connecting = true;

    char bda_str[18];
    ESP_LOGI(TAG, "Connecting to %s", bda_to_str(bda, bda_str, sizeof(bda_str)));
    bridge_send_bt_status(3, bda, NULL);

    esp_err_t err = esp_bt_hid_host_connect((esp_bd_addr_t)bda);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_bt_hid_host_connect failed: %s", esp_err_to_name(err));
        s_connecting = false;
    }
}

static void hidh_cb(esp_hidh_cb_event_t event, esp_hidh_cb_param_t* param) {
    switch (event) {
        case ESP_HIDH_INIT_EVT:
            ESP_LOGI(TAG, "HID host init: status=%d", param->init.status);
            break;
        case ESP_HIDH_OPEN_EVT: {
            char bda_str[18];
            ESP_LOGI(TAG, "HID open: status=%d conn=%d orig=%d handle=%u bda=%s",
                     param->open.status,
                     param->open.conn_status,
                     (int)param->open.is_orig,
                     param->open.handle,
                     bda_to_str(param->open.bd_addr, bda_str, sizeof(bda_str)));

            bridge_send_bt_status(4, param->open.bd_addr, NULL);
            break;
        }
        case ESP_HIDH_CLOSE_EVT:
            ESP_LOGW(TAG, "HID close: status=%d reason=%u conn=%d handle=%u",
                     param->close.status,
                     param->close.reason,
                     param->close.conn_status,
                     param->close.handle);
            s_connecting = false;
            bridge_send_bt_status(5, s_target_bda, NULL);
            break;
        case ESP_HIDH_DATA_IND_EVT:
            if (param->data_ind.status == ESP_HIDH_OK && param->data_ind.data && param->data_ind.len) {
                // Evidence-first workflow: only log when report bytes change.
                // This avoids flooding and makes it easier to identify toggling bits.
                if (CONFIG_JOYCON_HOST_LOG_REPORTS) {
                    static uint8_t last[96];
                    static uint16_t last_len = 0;

                    uint16_t now_len = param->data_ind.len;
                    if (now_len > sizeof(last)) {
                        now_len = sizeof(last);
                    }

                    bool changed = false;
                    if (last_len != now_len) {
                        changed = true;
                    } else if (last_len != 0) {
                        changed = (memcmp(last, param->data_ind.data, now_len) != 0);
                    } else {
                        changed = true;
                    }
                    if (changed) {
                        memcpy(last, param->data_ind.data, now_len);
                        last_len = now_len;

                        ESP_LOGI(TAG, "HID report len=%u", (unsigned)param->data_ind.len);
                        ESP_LOG_BUFFER_HEX_LEVEL(TAG, param->data_ind.data,
                                                 (param->data_ind.len > 64) ? 64 : param->data_ind.len,
                                                 ESP_LOG_INFO);
                    }
                }

                if (CONFIG_JOYCON_HOST_UART_DEBUG_REPORTS) {
                    uint16_t n = param->data_ind.len;
                    if (n > (uint16_t)CONFIG_JOYCON_HOST_UART_DEBUG_MAX_BYTES) {
                        n = (uint16_t)CONFIG_JOYCON_HOST_UART_DEBUG_MAX_BYTES;
                    }
                    bridge_send_debug_hid_report(param->data_ind.data, n);
                }

                joycon_mapper_on_report(param->data_ind.data, param->data_ind.len);
            }
            break;
        default:
            break;
    }
}

static void gap_cb(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t* param) {
    switch (event) {
        case ESP_BT_GAP_DISC_RES_EVT: {
            const esp_bt_gap_dev_prop_t* props = param->disc_res.prop;
            const int prop_count = param->disc_res.num_prop;

            const char* found_name = NULL;
            for (int i = 0; i < prop_count; i++) {
                if (props[i].type == ESP_BT_GAP_DEV_PROP_BDNAME) {
                    found_name = (const char*)props[i].val;
                    break;
                }
                if (props[i].type == ESP_BT_GAP_DEV_PROP_EIR) {
                    uint8_t* eir = (uint8_t*)props[i].val;
                    uint8_t len = 0;
                    uint8_t* name = esp_bt_gap_resolve_eir_data(eir, ESP_BT_EIR_TYPE_CMPL_LOCAL_NAME, &len);
                    if (!name) {
                        name = esp_bt_gap_resolve_eir_data(eir, ESP_BT_EIR_TYPE_SHORT_LOCAL_NAME, &len);
                    }
                    if (name && len > 0) {
                        static char name_buf[64];
                        int copy_len = (len < (sizeof(name_buf) - 1)) ? len : (sizeof(name_buf) - 1);
                        memcpy(name_buf, name, copy_len);
                        name_buf[copy_len] = 0;
                        found_name = name_buf;
                        break;
                    }
                }
            }

            if (found_name && name_matches_target(found_name)) {
                char bda_str[18];
                ESP_LOGI(TAG, "Found %s @ %s", found_name, bda_to_str(param->disc_res.bda, bda_str, sizeof(bda_str)));

                bridge_send_bt_status(2, param->disc_res.bda, found_name);

                // Stop discovery to reduce noise, then connect.
                esp_bt_gap_cancel_discovery();
                try_connect(param->disc_res.bda);
            }
            break;
        }
        case ESP_BT_GAP_DISC_STATE_CHANGED_EVT:
            ESP_LOGI(TAG, "Discovery state changed: %d", param->disc_st_chg.state);
            break;
        case ESP_BT_GAP_AUTH_CMPL_EVT:
            ESP_LOGI(TAG, "Auth complete: success=%d", param->auth_cmpl.stat == ESP_BT_STATUS_SUCCESS);
            break;
        default:
            break;
    }
}

void bt_hid_host_set_target_substr(const char* name_substr, uint8_t len) {
    if (!name_substr || len == 0) {
        s_target_name_override[0] = 0;
        ESP_LOGI(TAG, "Target name substring override cleared; using Kconfig '%s'", CONFIG_JOYCON_HOST_NAME_SUBSTR);
        return;
    }

    if (len >= sizeof(s_target_name_override)) {
        len = (uint8_t)(sizeof(s_target_name_override) - 1);
    }
    memcpy(s_target_name_override, name_substr, len);
    s_target_name_override[len] = 0;
    ESP_LOGI(TAG, "Target name substring override='%s'", s_target_name_override);
}

esp_err_t bt_hid_host_start_discovery(void) {
    const char* needle = (s_target_name_override[0] != 0) ? s_target_name_override : CONFIG_JOYCON_HOST_NAME_SUBSTR;
    ESP_LOGI(TAG, "Starting inquiry scan (match='%s', %ds)...", needle, CONFIG_JOYCON_HOST_DISCOVERY_SECONDS);
    bridge_send_bt_status(1, NULL, needle);

    // Best-effort: ignore cancel errors if not currently discovering.
    (void)esp_bt_gap_cancel_discovery();

    return esp_bt_gap_start_discovery(ESP_BT_INQ_MODE_GENERAL_INQUIRY,
                                     CONFIG_JOYCON_HOST_DISCOVERY_SECONDS, 0);
}

esp_err_t bt_hid_host_start(void) {
    esp_err_t err;

    // NVS is required by the BT stack.
    err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    // Classic BT only to maximize Joy-Con compatibility.
    ESP_ERROR_CHECK(esp_bt_controller_mem_release(ESP_BT_MODE_BLE));

    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bt_controller_init(&bt_cfg));
    ESP_ERROR_CHECK(esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT));

    ESP_ERROR_CHECK(esp_bluedroid_init());
    ESP_ERROR_CHECK(esp_bluedroid_enable());

    ESP_ERROR_CHECK(esp_bt_gap_register_callback(gap_cb));

    ESP_ERROR_CHECK(esp_bt_hid_host_register_callback(hidh_cb));
    ESP_ERROR_CHECK(esp_bt_hid_host_init());

    // Start discovery; Joy-Con should appear as a HID device.
    ESP_ERROR_CHECK(bt_hid_host_start_discovery());

    return ESP_OK;
}
