#include "profile_runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_err.h"
#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "nvs.h"

#include "cJSON.h"

#include "bridge_serial.h"
#include "keymap.h"
#include "usb_kbd.h"

static const char *TAG = "profile";

#define BRIDGE_PROFILE_NS "profiles"
#define BRIDGE_ACTIVE_KEY "active"

#define PROFILE_MAX_SLOTS 4
#define PROFILE_MAX_MACROS 16
#define PROFILE_MAX_STEPS 128
#define PROFILE_MAX_MACRO_ID 24

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
} map_mode_t;

typedef struct {
    map_mode_t mode;
    uint8_t remap_to;
    int8_t macro_index;  // -1 when none
} map_entry_t;

static map_entry_t s_map[128];
static macro_t s_macros[PROFILE_MAX_MACROS];
static size_t s_macro_count = 0;

static QueueHandle_t s_macro_q = NULL;

typedef struct {
    int8_t macro_index;
} macro_req_t;

static void free_profile(void) {
    for (size_t i = 0; i < s_macro_count; i++) {
        free(s_macros[i].steps);
        s_macros[i].steps = NULL;
        s_macros[i].step_count = 0;
        s_macros[i].id[0] = 0;
    }
    s_macro_count = 0;

    for (int i = 0; i < 128; i++) {
        s_map[i].mode = MAP_PASSTHROUGH;
        s_map[i].remap_to = (uint8_t)i;
        s_map[i].macro_index = -1;
    }
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
        if (key_id < 0 || key_id > 127) continue;

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
    }
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

    cJSON_Delete(root);

    ESP_LOGI(TAG, "Loaded profile: %u mappings, %u macros", 128u, (unsigned)s_macro_count);
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
    uint8_t mod = 0;
    uint8_t keycode = 0;
    if (!keymap_lookup(key_id, &mod, &keycode)) {
        return;
    }

    usb_kbd_set_key(mod, keycode, pressed);
}

void profile_runtime_handle_input(bool pressed, uint8_t key_id) {
    if (key_id >= 128) return;

    map_entry_t *m = &s_map[key_id];

    switch (m->mode) {
        case MAP_DISABLED:
            return;

        case MAP_REMAP:
            send_key_id(pressed, m->remap_to);
            return;

        case MAP_MACRO:
            if (pressed && s_macro_q && m->macro_index >= 0) {
                macro_req_t req = {.macro_index = m->macro_index};
                (void)xQueueSend(s_macro_q, &req, 0);
            }
            return;

        case MAP_PASSTHROUGH:
        default:
            send_key_id(pressed, key_id);
            return;
    }
}
