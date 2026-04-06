#include "profile_runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_err.h"
#include "esp_log.h"

#include "esp_timer.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "nvs.h"

#include "cJSON.h"

#include "bridge_serial.h"
#include "keymap.h"
#include "usb_kbd.h"
#include "uart_proto.h"

static const char *TAG = "profile";

#define BRIDGE_PROFILE_NS "profiles"
#define BRIDGE_ACTIVE_KEY "active"

#define PROFILE_MAX_SLOTS 4
#define PROFILE_MAX_MACROS 16
#define PROFILE_MAX_STEPS 128
#define PROFILE_MAX_MACRO_ID 24

#define INPUT_KEY_ID_MAX 256

typedef enum {
    STEP_KEY = 1,
    STEP_DELAY = 2,
} step_type_t;

typedef struct {
    step_type_t type;
    union {
        struct {
            uint8_t key_id;
            bool pressed;
        } key;
        struct {
            uint16_t ms;
        } delay;
    } u;
} macro_step_t;

typedef struct {
    char id[PROFILE_MAX_MACRO_ID];
    size_t step_count;
    macro_step_t *steps;
} macro_t;

typedef enum {
    MAP_PASSTHROUGH = 0,
    MAP_DISABLED = 1,
    MAP_REMAP = 2,
    MAP_MACRO = 3,
    MAP_REMAP_HID = 4,
    MAP_DOUBLE_TAP = 5,
} map_mode_t;

typedef struct {
    map_mode_t mode;
    uint8_t remap_to;
    int8_t macro_index;  // -1 when none
    uint8_t hid_mod;     // for MAP_REMAP_HID
    uint8_t hid_keycode; // for MAP_REMAP_HID
    // Double-tap fields (MAP_DOUBLE_TAP)
    uint8_t dt_single_mod;
    uint8_t dt_single_keycode;
    uint8_t dt_double_mod;
    uint8_t dt_double_keycode;
    uint16_t dt_timeout_ms;    // default 300
} map_entry_t;

// --- Layer system ---

#define MAX_LAYERS 4
#define MAX_LAYER_OVERRIDES 32

typedef enum {
    LAYER_HOLD = 0,
    LAYER_TOGGLE = 1,
} layer_mode_t;

typedef struct {
    uint8_t key_id;
    map_entry_t entry;
} layer_override_t;

typedef struct {
    char name[24];
    uint8_t activation_key_id;
    layer_mode_t mode;
    bool active;
    size_t override_count;
    layer_override_t overrides[MAX_LAYER_OVERRIDES];
    // O(1) lookup table: key_id → index into overrides[], or -1 if none.
    int8_t override_index[INPUT_KEY_ID_MAX];
} layer_t;

static map_entry_t s_map[INPUT_KEY_ID_MAX];
static macro_t s_macros[PROFILE_MAX_MACROS];
static size_t s_macro_count = 0;

static layer_t s_layers[MAX_LAYERS];
static size_t s_layer_count = 0;

static QueueHandle_t s_macro_q = NULL;

typedef struct {
    int8_t macro_index;
} macro_req_t;

// --- Double-tap state machine ---

#define MAX_DOUBLE_TAP_KEYS 8

typedef enum {
    DT_IDLE = 0,
    DT_FIRST_DOWN,   // first keydown seen, awaiting keyup
    DT_ARMED,        // first tap complete, timer running
    DT_SECOND_DOWN,  // second keydown (double-tap confirmed)
} dt_state_t;

typedef struct {
    uint8_t key_id;
    dt_state_t state;
    esp_timer_handle_t timer;
    // Cached single-tap values for the timeout callback
    uint8_t armed_single_mod;
    uint8_t armed_single_keycode;
} dt_tracker_t;

static dt_tracker_t s_dt_trackers[MAX_DOUBLE_TAP_KEYS];
static size_t s_dt_count = 0;

static dt_tracker_t *find_dt_tracker(uint8_t key_id) {
    for (size_t i = 0; i < s_dt_count; i++) {
        if (s_dt_trackers[i].key_id == key_id) return &s_dt_trackers[i];
    }
    return NULL;
}

static void dt_timeout_cb(void *arg) {
    dt_tracker_t *dt = (dt_tracker_t *)arg;
    if (dt->state != DT_ARMED) return;
    // Timeout expired: fire single-tap press then immediate release.
    usb_kbd_set_key(dt->armed_single_mod, dt->armed_single_keycode, true);
    usb_kbd_set_key(dt->armed_single_mod, dt->armed_single_keycode, false);
    dt->state = DT_IDLE;
}

static void register_dt_tracker(uint8_t key_id) {
    if (find_dt_tracker(key_id)) return;
    if (s_dt_count >= MAX_DOUBLE_TAP_KEYS) {
        ESP_LOGW(TAG, "Max double-tap keys reached (%d)", MAX_DOUBLE_TAP_KEYS);
        return;
    }
    dt_tracker_t *dt = &s_dt_trackers[s_dt_count];
    memset(dt, 0, sizeof(*dt));
    dt->key_id = key_id;
    dt->state = DT_IDLE;
    esp_timer_create_args_t args = {
        .callback = dt_timeout_cb,
        .arg = dt,
        .name = "dt",
    };
    if (esp_timer_create(&args, &dt->timer) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create double-tap timer for key %u", key_id);
        return;
    }
    s_dt_count++;
}

static void free_profile(void) {
    // Clean up double-tap timers.
    for (size_t i = 0; i < s_dt_count; i++) {
        if (s_dt_trackers[i].timer) {
            esp_timer_stop(s_dt_trackers[i].timer);
            esp_timer_delete(s_dt_trackers[i].timer);
        }
    }
    memset(s_dt_trackers, 0, sizeof(s_dt_trackers));
    s_dt_count = 0;

    for (size_t i = 0; i < s_macro_count; i++) {
        free(s_macros[i].steps);
        s_macros[i].steps = NULL;
        s_macros[i].step_count = 0;
        s_macros[i].id[0] = 0;
    }
    s_macro_count = 0;

    for (int i = 0; i < INPUT_KEY_ID_MAX; i++) {
        s_map[i].mode = MAP_PASSTHROUGH;
        // Default behavior:
        // - left input ids (0..127) passthrough to same output id
        // - right input ids (128..255) passthrough mirrors to base id (0..127)
        s_map[i].remap_to = (uint8_t)((i < 128) ? i : (i - 128));
        s_map[i].macro_index = -1;
        s_map[i].hid_mod = 0;
        s_map[i].hid_keycode = 0;
    }

    for (size_t l = 0; l < MAX_LAYERS; l++) {
        memset(&s_layers[l], 0, sizeof(layer_t));
        memset(s_layers[l].override_index, -1, sizeof(s_layers[l].override_index));
    }
    s_layer_count = 0;
}

static esp_err_t nvs_get_active_slot(int *out_slot) {
    *out_slot = 0;

    nvs_handle_t h;
    esp_err_t err = nvs_open(BRIDGE_PROFILE_NS, NVS_READONLY, &h);
    if (err != ESP_OK) return err;

    int8_t slot = 0;
    err = nvs_get_i8(h, BRIDGE_ACTIVE_KEY, &slot);
    nvs_close(h);

    if (err == ESP_OK) {
        *out_slot = slot;
    }
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

static int8_t find_macro_index(const char *id) {
    for (size_t i = 0; i < s_macro_count; i++) {
        if (strncmp(s_macros[i].id, id, PROFILE_MAX_MACRO_ID) == 0) {
            return (int8_t)i;
        }
    }
    return -1;
}

static bool parse_macro_step(cJSON *step_obj, macro_step_t *out_step) {
    memset(out_step, 0, sizeof(*out_step));

    cJSON *type = cJSON_GetObjectItemCaseSensitive(step_obj, "type");
    if (!cJSON_IsString(type) || !type->valuestring) return false;

    if (strcmp(type->valuestring, "delay") == 0) {
        cJSON *ms = cJSON_GetObjectItemCaseSensitive(step_obj, "ms");
        if (!cJSON_IsNumber(ms) || ms->valueint < 0 || ms->valueint > 5000) return false;
        out_step->type = STEP_DELAY;
        out_step->u.delay.ms = (uint16_t)ms->valueint;
        return true;
    }

    if (strcmp(type->valuestring, "key") == 0) {
        cJSON *key_id = cJSON_GetObjectItemCaseSensitive(step_obj, "key_id");
        cJSON *pressed = cJSON_GetObjectItemCaseSensitive(step_obj, "pressed");
        if (!cJSON_IsNumber(key_id) || key_id->valueint < 0 || key_id->valueint > 127) return false;
        if (!cJSON_IsBool(pressed)) return false;

        out_step->type = STEP_KEY;
        out_step->u.key.key_id = (uint8_t)key_id->valueint;
        out_step->u.key.pressed = cJSON_IsTrue(pressed);
        return true;
    }

    return false;
}

static void parse_macros(cJSON *root) {
    cJSON *macros = cJSON_GetObjectItemCaseSensitive(root, "macros");
    if (!cJSON_IsArray(macros)) return;

    size_t macro_count = 0;

    cJSON *macro_obj;
    cJSON_ArrayForEach(macro_obj, macros) {
        if (!cJSON_IsObject(macro_obj)) continue;
        if (macro_count >= PROFILE_MAX_MACROS) break;

        cJSON *id = cJSON_GetObjectItemCaseSensitive(macro_obj, "id");
        cJSON *steps = cJSON_GetObjectItemCaseSensitive(macro_obj, "steps");
        if (!cJSON_IsString(id) || !id->valuestring) continue;
        if (!cJSON_IsArray(steps)) continue;

        macro_t *m = &s_macros[macro_count];
        memset(m, 0, sizeof(*m));
        strncpy(m->id, id->valuestring, sizeof(m->id) - 1);

        size_t steps_n = (size_t)cJSON_GetArraySize(steps);
        if (steps_n > PROFILE_MAX_STEPS) steps_n = PROFILE_MAX_STEPS;
        if (steps_n == 0) continue;

        m->steps = (macro_step_t *)calloc(steps_n, sizeof(macro_step_t));
        if (!m->steps) {
            ESP_LOGW(TAG, "OOM allocating macro steps");
            break;
        }

        size_t out_n = 0;
        cJSON *step_obj;
        cJSON_ArrayForEach(step_obj, steps) {
            if (out_n >= steps_n) break;
            if (!cJSON_IsObject(step_obj)) continue;

            macro_step_t st;
            if (!parse_macro_step(step_obj, &st)) continue;

            m->steps[out_n++] = st;
        }

        m->step_count = out_n;
        if (m->step_count == 0) {
            free(m->steps);
            m->steps = NULL;
            continue;
        }

        macro_count++;
    }

    s_macro_count = macro_count;
}

static void parse_mappings(cJSON *root) {
    cJSON *mappings = cJSON_GetObjectItemCaseSensitive(root, "mappings");
    if (!cJSON_IsObject(mappings)) return;

    cJSON *entry = NULL;
    cJSON_ArrayForEach(entry, mappings) {
        if (!entry || !entry->string) continue;

        int key_id = atoi(entry->string);
        if (key_id < 0 || key_id >= INPUT_KEY_ID_MAX) continue;

        if (!cJSON_IsObject(entry)) continue;

        cJSON *type = cJSON_GetObjectItemCaseSensitive(entry, "type");
        if (!cJSON_IsString(type) || !type->valuestring) continue;

        if (strcmp(type->valuestring, "disable") == 0) {
            s_map[key_id].mode = MAP_DISABLED;
            continue;
        }

        if (strcmp(type->valuestring, "remap") == 0) {
            cJSON *to = cJSON_GetObjectItemCaseSensitive(entry, "to");
            if (cJSON_IsNumber(to) && to->valueint >= 0 && to->valueint <= 127) {
                s_map[key_id].mode = MAP_REMAP;
                s_map[key_id].remap_to = (uint8_t)to->valueint;
            }
            continue;
        }

        if (strcmp(type->valuestring, "macro") == 0) {
            cJSON *id = cJSON_GetObjectItemCaseSensitive(entry, "id");
            if (cJSON_IsString(id) && id->valuestring) {
                int8_t idx = find_macro_index(id->valuestring);
                if (idx >= 0) {
                    s_map[key_id].mode = MAP_MACRO;
                    s_map[key_id].macro_index = idx;
                }
            }
            continue;
        }

        if (strcmp(type->valuestring, "remap_hid") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            if (cJSON_IsNumber(mod_j) && cJSON_IsNumber(kc_j)) {
                s_map[key_id].mode = MAP_REMAP_HID;
                s_map[key_id].hid_mod = (uint8_t)mod_j->valueint;
                s_map[key_id].hid_keycode = (uint8_t)kc_j->valueint;
            }
            continue;
        }

        if (strcmp(type->valuestring, "double_tap") == 0) {
            cJSON *single = cJSON_GetObjectItemCaseSensitive(entry, "single");
            cJSON *dbl = cJSON_GetObjectItemCaseSensitive(entry, "double");
            cJSON *timeout = cJSON_GetObjectItemCaseSensitive(entry, "timeout_ms");
            if (!cJSON_IsObject(single) || !cJSON_IsObject(dbl)) continue;
            cJSON *s_mod = cJSON_GetObjectItemCaseSensitive(single, "mod");
            cJSON *s_kc = cJSON_GetObjectItemCaseSensitive(single, "keycode");
            cJSON *d_mod = cJSON_GetObjectItemCaseSensitive(dbl, "mod");
            cJSON *d_kc = cJSON_GetObjectItemCaseSensitive(dbl, "keycode");
            if (!cJSON_IsNumber(s_mod) || !cJSON_IsNumber(s_kc)) continue;
            if (!cJSON_IsNumber(d_mod) || !cJSON_IsNumber(d_kc)) continue;
            s_map[key_id].mode = MAP_DOUBLE_TAP;
            s_map[key_id].dt_single_mod = (uint8_t)s_mod->valueint;
            s_map[key_id].dt_single_keycode = (uint8_t)s_kc->valueint;
            s_map[key_id].dt_double_mod = (uint8_t)d_mod->valueint;
            s_map[key_id].dt_double_keycode = (uint8_t)d_kc->valueint;
            s_map[key_id].dt_timeout_ms = 300;
            if (cJSON_IsNumber(timeout) && timeout->valueint >= 100 && timeout->valueint <= 1000) {
                s_map[key_id].dt_timeout_ms = (uint16_t)timeout->valueint;
            }
            register_dt_tracker((uint8_t)key_id);
            continue;
        }
    }
}

static void parse_layer_mappings(cJSON *mappings_obj, layer_t *layer) {
    if (!cJSON_IsObject(mappings_obj)) return;

    cJSON *entry = NULL;
    cJSON_ArrayForEach(entry, mappings_obj) {
        if (!entry || !entry->string) continue;
        if (layer->override_count >= MAX_LAYER_OVERRIDES) break;

        int key_id = atoi(entry->string);
        if (key_id < 0 || key_id >= INPUT_KEY_ID_MAX) continue;
        if (!cJSON_IsObject(entry)) continue;

        cJSON *type = cJSON_GetObjectItemCaseSensitive(entry, "type");
        if (!cJSON_IsString(type) || !type->valuestring) continue;

        layer_override_t *ov = &layer->overrides[layer->override_count];
        ov->key_id = (uint8_t)key_id;
        memset(&ov->entry, 0, sizeof(ov->entry));
        ov->entry.mode = MAP_PASSTHROUGH;
        ov->entry.macro_index = -1;

        if (strcmp(type->valuestring, "disable") == 0) {
            ov->entry.mode = MAP_DISABLED;
        } else if (strcmp(type->valuestring, "remap") == 0) {
            cJSON *to = cJSON_GetObjectItemCaseSensitive(entry, "to");
            if (!cJSON_IsNumber(to) || to->valueint < 0 || to->valueint > 127) continue;
            ov->entry.mode = MAP_REMAP;
            ov->entry.remap_to = (uint8_t)to->valueint;
        } else if (strcmp(type->valuestring, "remap_hid") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            ov->entry.mode = MAP_REMAP_HID;
            ov->entry.hid_mod = (uint8_t)mod_j->valueint;
            ov->entry.hid_keycode = (uint8_t)kc_j->valueint;
        } else if (strcmp(type->valuestring, "macro") == 0) {
            cJSON *id = cJSON_GetObjectItemCaseSensitive(entry, "id");
            if (!cJSON_IsString(id) || !id->valuestring) continue;
            int8_t idx = find_macro_index(id->valuestring);
            if (idx < 0) continue;
            ov->entry.mode = MAP_MACRO;
            ov->entry.macro_index = idx;
        } else if (strcmp(type->valuestring, "double_tap") == 0) {
            cJSON *single = cJSON_GetObjectItemCaseSensitive(entry, "single");
            cJSON *dbl = cJSON_GetObjectItemCaseSensitive(entry, "double");
            cJSON *timeout = cJSON_GetObjectItemCaseSensitive(entry, "timeout_ms");
            if (!cJSON_IsObject(single) || !cJSON_IsObject(dbl)) continue;
            cJSON *s_mod = cJSON_GetObjectItemCaseSensitive(single, "mod");
            cJSON *s_kc = cJSON_GetObjectItemCaseSensitive(single, "keycode");
            cJSON *d_mod = cJSON_GetObjectItemCaseSensitive(dbl, "mod");
            cJSON *d_kc = cJSON_GetObjectItemCaseSensitive(dbl, "keycode");
            if (!cJSON_IsNumber(s_mod) || !cJSON_IsNumber(s_kc)) continue;
            if (!cJSON_IsNumber(d_mod) || !cJSON_IsNumber(d_kc)) continue;
            ov->entry.mode = MAP_DOUBLE_TAP;
            ov->entry.dt_single_mod = (uint8_t)s_mod->valueint;
            ov->entry.dt_single_keycode = (uint8_t)s_kc->valueint;
            ov->entry.dt_double_mod = (uint8_t)d_mod->valueint;
            ov->entry.dt_double_keycode = (uint8_t)d_kc->valueint;
            ov->entry.dt_timeout_ms = 300;
            if (cJSON_IsNumber(timeout) && timeout->valueint >= 100 && timeout->valueint <= 1000) {
                ov->entry.dt_timeout_ms = (uint16_t)timeout->valueint;
            }
            register_dt_tracker((uint8_t)key_id);
        } else {
            continue;
        }

        layer->override_count++;
    }
}

static void parse_layers(cJSON *root) {
    cJSON *layers = cJSON_GetObjectItemCaseSensitive(root, "layers");
    if (!cJSON_IsArray(layers)) return;

    size_t count = 0;
    cJSON *layer_obj;
    cJSON_ArrayForEach(layer_obj, layers) {
        if (!cJSON_IsObject(layer_obj)) continue;
        if (count >= MAX_LAYERS) break;

        cJSON *name = cJSON_GetObjectItemCaseSensitive(layer_obj, "name");
        cJSON *key_id_j = cJSON_GetObjectItemCaseSensitive(layer_obj, "key_id");
        cJSON *mode_j = cJSON_GetObjectItemCaseSensitive(layer_obj, "mode");
        cJSON *mappings = cJSON_GetObjectItemCaseSensitive(layer_obj, "mappings");

        if (!cJSON_IsNumber(key_id_j)) continue;

        layer_t *l = &s_layers[count];
        memset(l, 0, sizeof(*l));
        // Initialize override_index to -1 (no override).
        memset(l->override_index, -1, sizeof(l->override_index));

        if (cJSON_IsString(name) && name->valuestring) {
            strncpy(l->name, name->valuestring, sizeof(l->name) - 1);
        } else {
            snprintf(l->name, sizeof(l->name), "layer%u", (unsigned)count);
        }

        l->activation_key_id = (uint8_t)key_id_j->valueint;
        l->mode = LAYER_HOLD;
        if (cJSON_IsString(mode_j) && mode_j->valuestring &&
            strcmp(mode_j->valuestring, "toggle") == 0) {
            l->mode = LAYER_TOGGLE;
        }
        l->active = false;

        parse_layer_mappings(mappings, l);

        // Build O(1) override_index from parsed overrides.
        for (size_t i = 0; i < l->override_count; i++) {
            l->override_index[l->overrides[i].key_id] = (int8_t)i;
        }

        ESP_LOGI(TAG, "Layer '%s': activation=key_id %u, mode=%s, %u overrides",
                 l->name, l->activation_key_id,
                 l->mode == LAYER_TOGGLE ? "toggle" : "hold",
                 (unsigned)l->override_count);
        count++;
    }

    s_layer_count = count;
}

static void load_profile_json(const char *json) {
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        ESP_LOGW(TAG, "Profile JSON parse failed; using passthrough");
        return;
    }

    // Optional version field; unknown versions are tolerated.
    cJSON *ver = cJSON_GetObjectItemCaseSensitive(root, "ver");
    if (cJSON_IsNumber(ver)) {
        ESP_LOGI(TAG, "Profile ver=%d", ver->valueint);
    }

    parse_macros(root);
    parse_mappings(root);
    parse_layers(root);

    // --- Forward stick settings to ESP32 BT host ---
    cJSON *stick = cJSON_GetObjectItemCaseSensitive(root, "stick");
    if (cJSON_IsObject(stick)) {
        cJSON *curve_j = cJSON_GetObjectItemCaseSensitive(stick, "curve");
        cJSON *exp_j = cJSON_GetObjectItemCaseSensitive(stick, "exp");

        uint8_t curve = 0;  // linear
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
        uart_proto_send_ctrl(0x03, payload, 2);
        ESP_LOGI(TAG, "Forwarded stick curve=%u exp_x100=%u to ESP32", curve, exp_x100);
    }

    cJSON_Delete(root);

    ESP_LOGI(TAG, "Loaded profile: %u mappings, %u macros, %u layers",
             (unsigned)INPUT_KEY_ID_MAX, (unsigned)s_macro_count,
             (unsigned)s_layer_count);
}

static void macro_task(void *arg) {
    (void)arg;

    bool held[128] = {0};

    while (1) {
        macro_req_t req;
        if (xQueueReceive(s_macro_q, &req, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        if (req.macro_index < 0 || (size_t)req.macro_index >= s_macro_count) {
            continue;
        }

        macro_t *m = &s_macros[req.macro_index];
        ESP_LOGI(TAG, "Macro start: %s", m->id);
        bridge_serial_emit_macro_state(m->id, true);

        memset(held, 0, sizeof(held));

        // Hard safety limits: total duration and step count.
        uint32_t total_ms = 0;
        size_t steps = m->step_count;
        if (steps > PROFILE_MAX_STEPS) steps = PROFILE_MAX_STEPS;

        for (size_t i = 0; i < steps; i++) {
            macro_step_t *st = &m->steps[i];

            if (st->type == STEP_DELAY) {
                total_ms += st->u.delay.ms;
                if (total_ms > 4000) break;
                vTaskDelay(pdMS_TO_TICKS(st->u.delay.ms));
                continue;
            }

            if (st->type == STEP_KEY) {
                uint8_t out_key_id = st->u.key.key_id;

                uint8_t mod = 0;
                uint8_t keycode = 0;
                if (keymap_lookup(out_key_id, &mod, &keycode)) {
                    usb_kbd_set_key(mod, keycode, st->u.key.pressed);
                    held[out_key_id] = st->u.key.pressed;
                }

                // Small yield to keep USB responsive.
                vTaskDelay(pdMS_TO_TICKS(1));
                continue;
            }
        }

        // Safety: ensure any macro-held keys are released.
        for (int key_id = 0; key_id < 128; key_id++) {
            if (!held[key_id]) continue;

            uint8_t mod = 0;
            uint8_t keycode = 0;
            if (keymap_lookup((uint8_t)key_id, &mod, &keycode)) {
                usb_kbd_set_key(mod, keycode, false);
            }
        }

        bridge_serial_emit_macro_state(m->id, false);
        ESP_LOGI(TAG, "Macro end: %s", m->id);
    }
}

void profile_runtime_init(void) {
    free_profile();

    s_macro_q = xQueueCreate(4, sizeof(macro_req_t));
    if (!s_macro_q) {
        ESP_LOGE(TAG, "Failed to create macro queue");
        return;
    }

    xTaskCreate(macro_task, "macro", 4096, NULL, 5, NULL);

    profile_runtime_reload();
}

void profile_runtime_reload(void) {
    free_profile();

    int slot = 0;
    esp_err_t err = nvs_get_active_slot(&slot);
    if (err != ESP_OK) {
        ESP_LOGI(TAG, "No active slot set; using passthrough");
        return;
    }

    if (slot < 0 || slot >= PROFILE_MAX_SLOTS) {
        ESP_LOGW(TAG, "Active slot out of range (%d); using passthrough", slot);
        return;
    }

    char *json = NULL;
    err = nvs_get_profile_json(slot, &json);
    if (err != ESP_OK || !json) {
        ESP_LOGI(TAG, "No profile in slot %d; using passthrough", slot);
        free(json);
        return;
    }

    ESP_LOGI(TAG, "Loading profile from slot %d", slot);
    load_profile_json(json);

    free(json);
}

static void send_key_id(bool pressed, uint8_t key_id) {
    if (key_id >= 128) return;

    uint8_t mod = 0;
    uint8_t keycode = 0;
    if (!keymap_lookup(key_id, &mod, &keycode)) {
        return;
    }

    usb_kbd_set_key(mod, keycode, pressed);
}

static map_entry_t *find_layer_override(uint8_t key_id) {
    // Check layers in reverse priority (last active layer wins).
    // O(1) lookup per layer via the override_index table.
    for (int l = (int)s_layer_count - 1; l >= 0; l--) {
        if (!s_layers[l].active) continue;
        int8_t idx = s_layers[l].override_index[key_id];
        if (idx >= 0) {
            return &s_layers[l].overrides[idx].entry;
        }
    }
    return NULL;
}

static void dispatch_mapping(map_entry_t *m, bool pressed, uint8_t key_id) {
    switch (m->mode) {
        case MAP_DISABLED:
            return;

        case MAP_REMAP:
            send_key_id(pressed, m->remap_to);
            return;

        case MAP_REMAP_HID:
            usb_kbd_set_key(m->hid_mod, m->hid_keycode, pressed);
            return;

        case MAP_MACRO:
            if (pressed && s_macro_q && m->macro_index >= 0) {
                macro_req_t req = {.macro_index = m->macro_index};
                (void)xQueueSend(s_macro_q, &req, 0);
            }
            return;

        case MAP_DOUBLE_TAP: {
            dt_tracker_t *dt = find_dt_tracker(key_id);
            if (!dt) {
                // Fallback: fire single action directly.
                usb_kbd_set_key(m->dt_single_mod, m->dt_single_keycode, pressed);
                return;
            }
            switch (dt->state) {
                case DT_IDLE:
                    if (pressed) dt->state = DT_FIRST_DOWN;
                    break;
                case DT_FIRST_DOWN:
                    if (!pressed) {
                        dt->state = DT_ARMED;
                        dt->armed_single_mod = m->dt_single_mod;
                        dt->armed_single_keycode = m->dt_single_keycode;
                        esp_timer_start_once(dt->timer,
                                             (uint64_t)m->dt_timeout_ms * 1000);
                    }
                    break;
                case DT_ARMED:
                    if (pressed) {
                        esp_timer_stop(dt->timer);
                        dt->state = DT_SECOND_DOWN;
                        usb_kbd_set_key(m->dt_double_mod,
                                        m->dt_double_keycode, true);
                    }
                    break;
                case DT_SECOND_DOWN:
                    if (!pressed) {
                        usb_kbd_set_key(m->dt_double_mod,
                                        m->dt_double_keycode, false);
                        dt->state = DT_IDLE;
                    }
                    break;
            }
            return;
        }

        case MAP_PASSTHROUGH:
        default:
            send_key_id(pressed, m->remap_to);
            return;
    }
}

void profile_runtime_handle_input(bool pressed, uint8_t key_id) {
    // Check if this key_id activates a layer.
    for (size_t l = 0; l < s_layer_count; l++) {
        if (s_layers[l].activation_key_id == key_id) {
            if (s_layers[l].mode == LAYER_HOLD) {
                s_layers[l].active = pressed;
            } else if (s_layers[l].mode == LAYER_TOGGLE && pressed) {
                s_layers[l].active = !s_layers[l].active;
            }
            bridge_serial_emit_layer_state(s_layers[l].name, s_layers[l].active);
            return;  // Consumed by layer activation.
        }
    }

    // Look for a layer override, then fall back to the base mapping.
    map_entry_t *override = find_layer_override(key_id);
    map_entry_t *m = override ? override : &s_map[key_id];

    dispatch_mapping(m, pressed, key_id);
}
