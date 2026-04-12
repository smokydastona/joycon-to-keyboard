#include "bt_hid_host.h"

#include <stdbool.h>
#include <string.h>

#include "nvs_flash.h"
#include "nvs.h"

#include "esp_bt.h"
#include "esp_bt_main.h"
#include "esp_bt_device.h"
#include "esp_gap_bt_api.h"

#include "esp_hidh_api.h"

#include "esp_log.h"
#include "esp_timer.h"

#include "freertos/FreeRTOS.h"

#include "joycon_mapper.h"
#include "uart_framing.h"
#include "joycon_setup.h"
#include "config.h"

static const char* TAG = "bt-hidh";

static bool s_connecting = false;
static esp_bd_addr_t s_target_bda = {0};

typedef struct {
    bool connected;
    uint8_t device_id;  // 0..(BRIDGE_MAX_DEVICES-1)
    uint16_t handle;
    esp_bd_addr_t bda;
    char name[64];
} conn_dev_t;

static conn_dev_t s_dev[BRIDGE_MAX_DEVICES] = {0};
static bool s_dual_connect = false;
static uint8_t s_pending_device_id = 0;
static char s_pending_name[64] = {0};

static char s_target_name_override[64] = {0};
static portMUX_TYPE s_name_mux = portMUX_INITIALIZER_UNLOCKED;

// --- Forward declarations (used by reconnect logic below) ---
static bool is_bda_connected(const esp_bd_addr_t bda);
static const char* bda_to_str(const esp_bd_addr_t bda, char* out, size_t out_len);
static void try_connect(const esp_bd_addr_t bda, uint8_t device_id, const char* name);

// --- Auto-reconnect state ---
#if CONFIG_JOYCON_HOST_AUTO_RECONNECT
static esp_timer_handle_t s_reconnect_timer = NULL;
static esp_bd_addr_t s_last_bda = {0};
static char s_last_name[64] = {0};
static uint8_t s_last_device_id = 0;
static bool s_have_last_bda = false;
static int s_reconnect_attempt = 0;
static const int s_reconnect_base_ms = 2000;  // 2s initial backoff

// --- NVS persistence for reconnect across power cycles ---
#define NVS_NS        "bt_host"
#define NVS_KEY_BDA   "last_bda"     // blob, 6 bytes
#define NVS_KEY_NAME  "last_name"    // str
#define NVS_KEY_DEVID "last_devid"   // u8

static void nvs_save_last_device(void) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) != ESP_OK) return;
    nvs_set_blob(h, NVS_KEY_BDA, s_last_bda, sizeof(esp_bd_addr_t));
    nvs_set_str(h, NVS_KEY_NAME, s_last_name);
    nvs_set_u8(h, NVS_KEY_DEVID, s_last_device_id);
    nvs_commit(h);
    nvs_close(h);
    char bda_str[18];
    ESP_LOGI(TAG, "Saved paired device to NVS: %s '%s'",
             bda_to_str(s_last_bda, bda_str, sizeof(bda_str)), s_last_name);
}

static bool nvs_load_last_device(void) {
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) return false;
    size_t bda_len = sizeof(esp_bd_addr_t);
    esp_err_t err = nvs_get_blob(h, NVS_KEY_BDA, s_last_bda, &bda_len);
    if (err != ESP_OK || bda_len != sizeof(esp_bd_addr_t)) {
        nvs_close(h);
        return false;
    }
    size_t name_len = sizeof(s_last_name);
    if (nvs_get_str(h, NVS_KEY_NAME, s_last_name, &name_len) != ESP_OK) {
        s_last_name[0] = 0;
    }
    uint8_t dev_id = 0;
    nvs_get_u8(h, NVS_KEY_DEVID, &dev_id);
    s_last_device_id = dev_id;
    s_have_last_bda = true;
    nvs_close(h);
    return true;
}

static void reconnect_timer_cb(void *arg) {
    (void)arg;
    if (!s_have_last_bda) return;
    if (is_bda_connected(s_last_bda)) {
        s_reconnect_attempt = 0;
        return;
    }

    char bda_str[18];
    ESP_LOGI(TAG, "Auto-reconnect attempt %d/%d to %s",
             s_reconnect_attempt + 1,
             CONFIG_JOYCON_HOST_AUTO_RECONNECT_MAX_RETRIES,
             bda_to_str(s_last_bda, bda_str, sizeof(bda_str)));
    bridge_send_bt_status(6, s_last_bda, s_last_name);  // status 6 = reconnecting

    try_connect(s_last_bda, s_last_device_id, s_last_name);
}

static void schedule_reconnect(void) {
    if (!s_have_last_bda) return;
    if (s_reconnect_attempt >= CONFIG_JOYCON_HOST_AUTO_RECONNECT_MAX_RETRIES) {
        ESP_LOGW(TAG, "Auto-reconnect exhausted %d retries; restarting discovery",
                 CONFIG_JOYCON_HOST_AUTO_RECONNECT_MAX_RETRIES);
        s_reconnect_attempt = 0;
        s_have_last_bda = false;
        bt_hid_host_start_discovery();
        return;
    }

    // Exponential backoff: 2s, 4s, 8s, ...
    int delay_ms = s_reconnect_base_ms << s_reconnect_attempt;
    s_reconnect_attempt++;
    ESP_LOGI(TAG, "Scheduling reconnect in %d ms (attempt %d)", delay_ms, s_reconnect_attempt);
    esp_timer_start_once(s_reconnect_timer, (uint64_t)delay_ms * 1000);
}
#endif  // CONFIG_JOYCON_HOST_AUTO_RECONNECT

static bool name_matches_target(const char* name) {
    if (!name) return false;
    char local_name[64];
    portENTER_CRITICAL(&s_name_mux);
    memcpy(local_name, s_target_name_override, sizeof(local_name));
    portEXIT_CRITICAL(&s_name_mux);
    const char* needle = (local_name[0] != 0) ? local_name : CONFIG_JOYCON_HOST_NAME_SUBSTR;
    if (!needle || needle[0] == 0) {
        return false;
    }
    return (strstr(name, needle) != NULL);
}

static bool bda_eq(const esp_bd_addr_t a, const esp_bd_addr_t b) {
    return memcmp(a, b, sizeof(esp_bd_addr_t)) == 0;
}

static int connected_count(void) {
    int n = 0;
    for (int i = 0; i < BRIDGE_MAX_DEVICES; i++) {
        if (s_dev[i].connected) n++;
    }
    return n;
}

static int find_free_slot(void) {
    for (int i = 0; i < BRIDGE_MAX_DEVICES; i++) {
        if (!s_dev[i].connected) return i;
    }
    return -1;
}

static bool is_bda_connected(const esp_bd_addr_t bda) {
    for (int i = 0; i < BRIDGE_MAX_DEVICES; i++) {
        if (s_dev[i].connected && bda_eq(s_dev[i].bda, bda)) {
            return true;
        }
    }
    return false;
}

static int detect_device_id_from_name(const char* name) {
    if (!name) return -1;
    if (strstr(name, "(L)") != NULL) return 0;
    if (strstr(name, "(R)") != NULL) return 1;
    return -1;
}

static bool dual_needs_more(void) {
    return s_dual_connect && (!s_dev[0].connected || !s_dev[1].connected);
}

static const char* bda_to_str(const esp_bd_addr_t bda, char* out, size_t out_len) {
    if (out_len < 18) return "";
    snprintf(out, out_len, "%02x:%02x:%02x:%02x:%02x:%02x",
             bda[0], bda[1], bda[2], bda[3], bda[4], bda[5]);
    return out;
}

static void try_connect(const esp_bd_addr_t bda, uint8_t device_id, const char* name) {
    if (s_connecting) return;

    // Refuse new connects when all slots are full.
    if (find_free_slot() < 0) {
        ESP_LOGW(TAG, "No free device slots (max=%d); ignoring connect", BRIDGE_MAX_DEVICES);
        return;
    }

    uint8_t pending = device_id;
    if (pending >= BRIDGE_MAX_DEVICES || s_dev[pending].connected) {
        int free_slot = find_free_slot();
        pending = (free_slot >= 0) ? (uint8_t)free_slot : 0;
    }
    s_pending_device_id = pending;
    if (name) {
        strncpy(s_pending_name, name, sizeof(s_pending_name) - 1);
        s_pending_name[sizeof(s_pending_name) - 1] = 0;
    } else {
        s_pending_name[0] = 0;
    }

    memcpy(s_target_bda, bda, sizeof(esp_bd_addr_t));
    s_connecting = true;

    char bda_str[18];
    ESP_LOGI(TAG, "Connecting to %s", bda_to_str(bda, bda_str, sizeof(bda_str)));
    bridge_send_bt_status(3, bda, NULL);

    esp_err_t err = esp_bt_hid_host_connect((uint8_t *)bda);
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

            // Handle 0xFF (BTA_HH_INVALID_HANDLE) means the Joy-Con's
            // L2CAP connection completed before BTA_HhOpen was processed
            // by the BTA task queue.  BTA will catch up and fire a second
            // OPEN event with the real handle shortly.  Do NOT disconnect
            // here — the L2CAP link is alive and disconnecting would kill
            // the connection that BTA is about to register.
            if (param->open.handle == 0xFF) {
                ESP_LOGW(TAG, "Premature OPEN (handle=0xFF); waiting for BTA to assign real handle...");
                // Keep s_connecting = true so we don't start new scans.
                break;
            }

            // Non-zero status means the connection attempt failed (e.g.
            // page timeout, auth failure).  Do NOT mark the slot as
            // connected or start the FSM — the device isn't reachable.
            if (param->open.status != 0) {
                ESP_LOGW(TAG, "HID OPEN failed (status=%d); scheduling reconnect",
                         param->open.status);
                s_connecting = false;
#if CONFIG_JOYCON_HOST_AUTO_RECONNECT
                schedule_reconnect();
#else
                bt_hid_host_start_discovery();
#endif
                break;
            }

            bridge_send_bt_status(4, param->open.bd_addr, NULL);

            // Best-effort: stash this connection into the requested slot.
            uint8_t slot = s_pending_device_id;
            if (slot >= BRIDGE_MAX_DEVICES) slot = 0;
            if (s_dev[slot].connected) {
                int free_slot = find_free_slot();
                if (free_slot >= 0) {
                    slot = (uint8_t)free_slot;
                } else {
                    ESP_LOGW(TAG, "No free device slot for incoming connection; dropping");
                    s_connecting = false;
                    break;
                }
            }
            s_dev[slot].connected = true;
            s_dev[slot].device_id = slot;
            s_dev[slot].handle = param->open.handle;
            memcpy(s_dev[slot].bda, param->open.bd_addr, sizeof(esp_bd_addr_t));
            strncpy(s_dev[slot].name, s_pending_name, sizeof(s_dev[slot].name) - 1);
            s_dev[slot].name[sizeof(s_dev[slot].name) - 1] = 0;

            s_connecting = false;

            // NOTE: QoS (minimum poll interval) is deferred until the
            // setup FSM finishes.  Requesting it here races with the
            // Joy-Con's sniff-mode negotiation and can break the data
            // path (ASSERT_WARN in lc_task.c + no further reports).

#if CONFIG_JOYCON_HOST_AUTO_RECONNECT
            // Connected successfully — reset reconnect state.
            s_reconnect_attempt = 0;
            if (s_reconnect_timer) {
                esp_timer_stop(s_reconnect_timer);
            }
            // Save this device to NVS so we reconnect after power cycle.
            memcpy(s_last_bda, param->open.bd_addr, sizeof(esp_bd_addr_t));
            strncpy(s_last_name, s_pending_name, sizeof(s_last_name) - 1);
            s_last_name[sizeof(s_last_name) - 1] = 0;
            s_last_device_id = slot;
            s_have_last_bda = true;
            nvs_save_last_device();
#endif

            // Start the Joy-Con setup FSM (sends subcommands to switch
            // the controller to full 0x30 report mode with IMU, reads
            // SPI flash calibration, sets player LEDs).
            joycon_setup_start(param->open.handle, slot, param->open.bd_addr);

            // Clear SOCD/stick state from any prior session so stale
            // direction history doesn't contaminate the new connection.
            joycon_mapper_reset_state();

            // In dual-connect mode, keep scanning until we have both sides.
            if (dual_needs_more()) {
                (void)bt_hid_host_start_discovery();
            }
            break;
        }
        case ESP_HIDH_CLOSE_EVT:
            ESP_LOGW(TAG, "HID close: status=%d reason=%u conn=%d handle=%u",
                     param->close.status,
                     param->close.reason,
                     param->close.conn_status,
                     param->close.handle);

            // Ignore phantom CLOSE for handle 0xFF — this can arrive if
            // the BTA layer saw a premature L2CAP connection that was
            // never registered.  The real connection (handle != 0xFF) may
            // still be setting up.
            if (param->close.handle == 0xFF) {
                ESP_LOGW(TAG, "Ignoring CLOSE for phantom handle 0xFF");
                break;
            }

            s_connecting = false;

            // Clear any slot matching this handle.
            esp_bd_addr_t closed_bda = {0};
            bool have_bda = false;
            for (int i = 0; i < BRIDGE_MAX_DEVICES; i++) {
                if (!s_dev[i].connected) continue;
                if (s_dev[i].handle == param->close.handle) {
                    memcpy(closed_bda, s_dev[i].bda, sizeof(esp_bd_addr_t));
                    have_bda = true;
#if CONFIG_JOYCON_HOST_AUTO_RECONNECT
                    // Stash info for reconnect before clearing the slot.
                    memcpy(s_last_bda, s_dev[i].bda, sizeof(esp_bd_addr_t));
                    strncpy(s_last_name, s_dev[i].name, sizeof(s_last_name) - 1);
                    s_last_name[sizeof(s_last_name) - 1] = 0;
                    s_last_device_id = s_dev[i].device_id;
                    s_have_last_bda = true;
                    nvs_save_last_device();
#endif
                    joycon_setup_stop(s_dev[i].device_id);
                    memset(&s_dev[i], 0, sizeof(s_dev[i]));
                    break;
                }
            }
            bridge_send_bt_status(5, have_bda ? closed_bda : s_target_bda, NULL);
#if CONFIG_JOYCON_HOST_AUTO_RECONNECT
            schedule_reconnect();
#endif
            break;
        case ESP_HIDH_DATA_EVT:
            ESP_LOGD(TAG, "HID send_data result: status=%d handle=%u reason=%u",
                     param->send_data.status, param->send_data.handle,
                     param->send_data.reason);
            if (param->send_data.status != ESP_HIDH_OK) {
                ESP_LOGE(TAG, "HID send_data FAILED: status=%d handle=%u reason=%u",
                         param->send_data.status, param->send_data.handle,
                         param->send_data.reason);
            }
            break;
        case ESP_HIDH_DATA_IND_EVT:
            if (param->data_ind.status == ESP_HIDH_OK && param->data_ind.data && param->data_ind.len) {
                // Evidence-first workflow: only log when report bytes change.
                // This avoids flooding and makes it easier to identify toggling bits.
                if (CONFIG_JOYCON_HOST_LOG_REPORTS) {
                    // Gate the full hex dump on the 3 button bytes only
                    // (bytes 3-5 of the 0x30 report).  Stick movement
                    // changes bytes 6-8 every frame at 60 Hz; logging the
                    // 5-line hex dump for each stick change floods the
                    // 115200 baud console and triggers the task watchdog.
                    // The mapper already provides a compact one-line log
                    // for stick and button changes.
                    static uint8_t last_btn[3];
                    static bool have_last = false;

                    bool changed = true;
                    if (param->data_ind.len > 5) {
                        const uint8_t *btn = param->data_ind.data + 3;
                        changed = !have_last ||
                                  memcmp(last_btn, btn, 3) != 0;
                        if (changed) {
                            memcpy(last_btn, btn, 3);
                            have_last = true;
                        }
                    }
                    if (changed) {
                        ESP_LOGI(TAG, "HID report len=%u", (unsigned)param->data_ind.len);
                        ESP_LOG_BUFFER_HEX_LEVEL(TAG, param->data_ind.data,
                                                 (param->data_ind.len > 64) ? 64 : param->data_ind.len,
                                                 ESP_LOG_INFO);
                    }
                }

#if CONFIG_JOYCON_HOST_UART_DEBUG_REPORTS
                {
                    uint16_t n = param->data_ind.len;
                    if (n > (uint16_t)CONFIG_JOYCON_HOST_UART_DEBUG_MAX_BYTES) {
                        n = (uint16_t)CONFIG_JOYCON_HOST_UART_DEBUG_MAX_BYTES;
                    }
                    bridge_send_debug_hid_report(param->data_ind.data, n);
                }
#endif

                uint8_t device_id = 0;
                for (int i = 0; i < BRIDGE_MAX_DEVICES; i++) {
                    if (s_dev[i].connected && s_dev[i].handle == param->data_ind.handle) {
                        device_id = s_dev[i].device_id;
                        break;
                    }
                }

                // During setup, route 0x21 (subcmd reply) reports to the
                // setup FSM. It will consume them until setup is complete.
                if (joycon_setup_on_report(device_id, param->data_ind.data,
                                           param->data_ind.len)) {
                    break;  // Consumed by setup FSM
                }

                // Once setup is complete, update battery from 0x30 reports.
                if (param->data_ind.len >= 3 && param->data_ind.data[0] == 0x30) {
                    joycon_setup_update_battery(device_id, param->data_ind.data[2]);
                }

                joycon_mapper_on_report_ex(device_id, param->data_ind.data, param->data_ind.len);
            }
            break;
        default:
            break;
    }
}

static esp_timer_handle_t s_rssi_timer = NULL;

// Timer-based discovery restart — avoids blocking the BTC task with vTaskDelay.
static esp_timer_handle_t s_disc_restart_timer = NULL;
static void disc_restart_cb(void *arg) {
    (void)arg;
    // Re-check conditions in case a connection arrived during the delay.
    int desired = s_dual_connect ? 2 : BRIDGE_MAX_DEVICES;
    if (connected_count() < desired && !s_connecting) {
        bt_hid_host_start_discovery();
    }
}

static void rssi_poll_cb(void *arg) {
    (void)arg;
    for (int i = 0; i < BRIDGE_MAX_DEVICES; i++) {
        if (s_dev[i].connected) {
            esp_bt_gap_read_rssi_delta(s_dev[i].bda);
        }
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

                if (is_bda_connected(param->disc_res.bda)) {
                    break;
                }

                uint8_t device_id = 0;
                if (s_dual_connect) {
                    int detected = detect_device_id_from_name(found_name);
                    if (detected >= 0) {
                        device_id = (uint8_t)detected;
                    } else {
                        // Fallback: fill the first empty slot.
                        device_id = s_dev[0].connected ? 1 : 0;
                    }

                    if (device_id < 2 && s_dev[device_id].connected) {
                        break;
                    }
                } else {
                    int free_slot = find_free_slot();
                    if (free_slot < 0) {
                        ESP_LOGI(TAG, "All %d device slots full; stopping discovery", BRIDGE_MAX_DEVICES);
                        esp_bt_gap_cancel_discovery();
                        break;
                    }
                    device_id = (uint8_t)free_slot;
                }

                bridge_send_bt_status(2, param->disc_res.bda, found_name);

                // Stop discovery to reduce noise, then connect.
                esp_bt_gap_cancel_discovery();
                try_connect(param->disc_res.bda, device_id, found_name);
            }
            break;
        }
        case ESP_BT_GAP_DISC_STATE_CHANGED_EVT:
            ESP_LOGI(TAG, "Discovery state changed: %d", param->disc_st_chg.state);
            if (param->disc_st_chg.state == 1) {
                // Scan started — cancel any pending restart timer so it
                // doesn't fire mid-scan and cancel the running inquiry.
                esp_timer_stop(s_disc_restart_timer);
            } else if (param->disc_st_chg.state == 0 &&
                       connected_count() < (s_dual_connect ? 2 : BRIDGE_MAX_DEVICES) &&
                       !s_connecting &&
                       !esp_timer_is_active(s_disc_restart_timer)) {
                // Scan ended naturally (not cancelled by a pending restart).
                ESP_LOGI(TAG, "Discovery ended; restarting in 2 s");
                esp_timer_start_once(s_disc_restart_timer, 2000000);  // 2 s
            }
            break;
        case ESP_BT_GAP_AUTH_CMPL_EVT:
            ESP_LOGI(TAG, "Auth complete: success=%d", param->auth_cmpl.stat == ESP_BT_STATUS_SUCCESS);
            break;
        case ESP_BT_GAP_MODE_CHG_EVT: {
            const char *mode_str = "???";
            switch (param->mode_chg.mode) {
                case ESP_BT_PM_MD_ACTIVE: mode_str = "active"; break;
                case ESP_BT_PM_MD_HOLD:   mode_str = "hold";   break;
                case ESP_BT_PM_MD_SNIFF:  mode_str = "sniff";  break;
                case ESP_BT_PM_MD_PARK:   mode_str = "park";   break;
                default: break;
            }
            char bda_str2[18];
            ESP_LOGI(TAG, "BT power-mode change: %s -> %s",
                     bda_to_str(param->mode_chg.bda, bda_str2, sizeof(bda_str2)),
                     mode_str);
            break;
        }
        case ESP_BT_GAP_READ_RSSI_DELTA_EVT: {
            if (param->read_rssi_delta.stat == ESP_BT_STATUS_SUCCESS) {
                int8_t rssi = param->read_rssi_delta.rssi_delta;
                // Find device_id by BDA
                uint8_t dev_id = 0;
                for (int i = 0; i < BRIDGE_MAX_DEVICES; i++) {
                    if (s_dev[i].connected && bda_eq(s_dev[i].bda, param->read_rssi_delta.bda)) {
                        dev_id = s_dev[i].device_id;
                        break;
                    }
                }
                bridge_send_rssi(dev_id, rssi);
            }
            break;
        }
        default:
            break;
    }
}

void bt_hid_host_set_target_substr(const char* name_substr, uint8_t len) {
    if (!name_substr || len == 0) {
        portENTER_CRITICAL(&s_name_mux);
        s_target_name_override[0] = 0;
        portEXIT_CRITICAL(&s_name_mux);
        ESP_LOGI(TAG, "Target name substring override cleared; using Kconfig '%s'", CONFIG_JOYCON_HOST_NAME_SUBSTR);
        return;
    }

    if (len >= sizeof(s_target_name_override)) {
        len = (uint8_t)(sizeof(s_target_name_override) - 1);
    }
    portENTER_CRITICAL(&s_name_mux);
    memcpy(s_target_name_override, name_substr, len);
    s_target_name_override[len] = 0;
    portEXIT_CRITICAL(&s_name_mux);
    ESP_LOGI(TAG, "Target name substring override='%s'", s_target_name_override);
}

esp_err_t bt_hid_host_start_discovery(void) {
    char local_name[64];
    portENTER_CRITICAL(&s_name_mux);
    memcpy(local_name, s_target_name_override, sizeof(local_name));
    portEXIT_CRITICAL(&s_name_mux);
    const char* needle = (local_name[0] != 0) ? local_name : CONFIG_JOYCON_HOST_NAME_SUBSTR;
    ESP_LOGI(TAG, "Starting inquiry scan (match='%s', %ds)...", needle, CONFIG_JOYCON_HOST_DISCOVERY_SECONDS);
    bridge_send_bt_status(1, NULL, needle);

    // Best-effort: ignore cancel errors if not currently discovering.
    (void)esp_bt_gap_cancel_discovery();

    return esp_bt_gap_start_discovery(ESP_BT_INQ_MODE_GENERAL_INQUIRY,
                                     CONFIG_JOYCON_HOST_DISCOVERY_SECONDS, 0);
}

esp_err_t bt_hid_host_start_discovery_ex(bool dual_connect) {
    s_dual_connect = dual_connect;
    return bt_hid_host_start_discovery();
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

    // Enable page scan so the controller can reconnect to us without
    // going into pairing mode.  Without this the default scan mode is
    // non-connectable and the Joy-Con's page request goes unanswered.
    esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_NON_DISCOVERABLE);

    // Start periodic RSSI polling (every 5 seconds).
    esp_timer_create_args_t rssi_args = {
        .callback = rssi_poll_cb,
        .arg = NULL,
        .name = "rssi_poll",
    };
    ESP_ERROR_CHECK(esp_timer_create(&rssi_args, &s_rssi_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(s_rssi_timer, 5000000));  // 5s

    // Discovery restart timer (one-shot, used from GAP callback).
    esp_timer_create_args_t disc_args = {
        .callback = disc_restart_cb,
        .arg = NULL,
        .name = "disc_restart",
    };
    ESP_ERROR_CHECK(esp_timer_create(&disc_args, &s_disc_restart_timer));

#if CONFIG_JOYCON_HOST_AUTO_RECONNECT
    esp_timer_create_args_t reconn_args = {
        .callback = reconnect_timer_cb,
        .arg = NULL,
        .name = "bt_reconn",
    };
    ESP_ERROR_CHECK(esp_timer_create(&reconn_args, &s_reconnect_timer));
    ESP_LOGI(TAG, "Auto-reconnect enabled (max %d retries)", CONFIG_JOYCON_HOST_AUTO_RECONNECT_MAX_RETRIES);

    // If a device was paired before the last power cycle, try to reconnect
    // to it directly.  The Joy-Con will also page us (page scan is enabled
    // above), so the connection may arrive before our first retry fires.
    if (nvs_load_last_device()) {
        char bda_str[18];
        ESP_LOGI(TAG, "Loaded saved device from NVS: %s '%s'; reconnecting...",
                 bda_to_str(s_last_bda, bda_str, sizeof(bda_str)), s_last_name);
        // Pre-populate pending fields so an incoming connection from the
        // Joy-Con fills the correct device slot.
        s_pending_device_id = s_last_device_id;
        strncpy(s_pending_name, s_last_name, sizeof(s_pending_name) - 1);
        s_pending_name[sizeof(s_pending_name) - 1] = 0;
        schedule_reconnect();  // attempts in 2s, 4s, 8s then falls to discovery
    } else {
        // No saved device — start inquiry so user can pair for the first time.
        ESP_ERROR_CHECK(bt_hid_host_start_discovery());
    }
#else
    // Auto-reconnect disabled; always start discovery.
    ESP_ERROR_CHECK(bt_hid_host_start_discovery());
#endif

    return ESP_OK;
}
