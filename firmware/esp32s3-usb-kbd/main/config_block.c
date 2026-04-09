#include "config_block.h"

#include <string.h>
#include <stdlib.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "tusb.h"
#include "cJSON.h"

#include "profile_runtime.h"
#include "bridge_serial.h"

static const char *TAG = "cfg-block";

/* ── CRC-16 CCITT (xmodem) ────────────────────────────────── */
uint16_t config_block_crc16(const uint8_t *data, size_t len) {
    uint16_t crc = 0x0000;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++) {
            if (crc & 0x8000)
                crc = (uint16_t)((crc << 1) ^ 0x1021);
            else
                crc <<= 1;
        }
    }
    return crc;
}

/* ── Receive state machine ─────────────────────────────────── */
typedef enum {
    RX_IDLE,
    RX_HEADER,   /* reading block_type, slot, len(2) */
    RX_PAYLOAD,
    RX_CRC,
} rx_state_t;

#define CFG_MAX_PAYLOAD 8192

static rx_state_t s_state = RX_IDLE;
static uint8_t s_hdr[4];      /* block_type, slot, len_lo, len_hi */
static size_t s_hdr_pos = 0;
static uint8_t *s_payload = NULL;
static size_t s_payload_len = 0;
static size_t s_payload_pos = 0;
static uint8_t s_crc_buf[2];
static size_t s_crc_pos = 0;

/* Atomic profile push staging area */
static bool s_atomic_active = false;
static int s_atomic_slot = -1;
static cJSON *s_atomic_root = NULL;

static void cdc_write_line(const char *line) {
    if (!tud_cdc_connected()) return;
    tud_cdc_write(line, (uint32_t)strlen(line));
    tud_cdc_write("\n", 1);
    tud_cdc_write_flush();
}

static void respond_block_ok(uint8_t block_type) {
    char buf[80];
    snprintf(buf, sizeof(buf),
             "{\"rsp\":\"config_block\",\"ok\":true,\"type\":%u}", block_type);
    cdc_write_line(buf);
}

static void respond_block_err(const char *err) {
    char buf[128];
    snprintf(buf, sizeof(buf),
             "{\"rsp\":\"config_block\",\"ok\":false,\"error\":\"%s\"}", err);
    cdc_write_line(buf);
}

/* ── Helpers: read little-endian ───────────────────────────── */
static inline uint16_t rd16(const uint8_t *p) {
    return (uint16_t)(p[0] | (p[1] << 8));
}

/* ── Process a complete, CRC-verified block ────────────────── */

static void apply_mapping_entry(int slot, const uint8_t *p, size_t len) {
    if (len < 2) { respond_block_err("mapping_too_short"); return; }
    uint8_t key_id = p[0];
    uint8_t mode = p[1];
    /* Build a JSON mapping entry and merge into the staging profile */
    cJSON *entry = cJSON_CreateObject();
    if (!entry) { respond_block_err("oom"); return; }

    const char *type_str = "passthrough";
    switch (mode) {
        case 0:  type_str = "passthrough"; break;
        case 1:  type_str = "disable"; break;
        case 2:  type_str = "remap"; break;
        case 3:  type_str = "macro"; break;
        case 4:  type_str = "remap_hid"; break;
        case 5:  type_str = "double_tap"; break;
        case 6:  type_str = "turbo"; break;
        case 7:  type_str = "sticky"; break;
        case 8:  type_str = "tap_hold"; break;
        case 9:  type_str = "oneshot"; break;
        case 10: type_str = "auto_shift"; break;
        case 11: type_str = "mouse_button"; break;
        case 12: type_str = "sequential"; break;
        case 13: type_str = "leader"; break;
        case 14: type_str = "profile_switch"; break;
        case 15: type_str = "zone"; break;
        case 16: type_str = "activator"; break;
        default: type_str = "passthrough"; break;
    }
    cJSON_AddStringToObject(entry, "type", type_str);

    size_t off = 2;
    switch (mode) {
        case 1: /* disable */ break;
        case 2: /* remap */
            if (off < len) cJSON_AddNumberToObject(entry, "to", p[off]);
            break;
        case 4: /* remap_hid */
            if (off + 1 < len) {
                cJSON_AddNumberToObject(entry, "mod", p[off]);
                cJSON_AddNumberToObject(entry, "keycode", p[off + 1]);
            }
            break;
        case 3: /* macro */
            if (off < len) cJSON_AddNumberToObject(entry, "macro_index", p[off]);
            break;
        case 5: /* double_tap */
            if (off + 5 < len) {
                cJSON *single = cJSON_CreateObject();
                cJSON *dbl = cJSON_CreateObject();
                cJSON_AddNumberToObject(single, "mod", p[off]);
                cJSON_AddNumberToObject(single, "keycode", p[off + 1]);
                cJSON_AddNumberToObject(dbl, "mod", p[off + 2]);
                cJSON_AddNumberToObject(dbl, "keycode", p[off + 3]);
                cJSON_AddItemToObject(entry, "single", single);
                cJSON_AddItemToObject(entry, "double", dbl);
                cJSON_AddNumberToObject(entry, "timeout_ms", rd16(&p[off + 4]));
            }
            break;
        case 6: /* turbo */
            if (off + 3 < len) {
                cJSON_AddNumberToObject(entry, "mod", p[off]);
                cJSON_AddNumberToObject(entry, "keycode", p[off + 1]);
                cJSON_AddNumberToObject(entry, "delay_ms", rd16(&p[off + 2]));
            }
            break;
        case 7: /* sticky */
            if (off + 1 < len) {
                cJSON_AddNumberToObject(entry, "mod", p[off]);
                cJSON_AddNumberToObject(entry, "keycode", p[off + 1]);
            }
            break;
        case 8: /* tap_hold */
            if (off + 5 < len) {
                cJSON *tap = cJSON_CreateObject();
                cJSON *hold = cJSON_CreateObject();
                cJSON_AddStringToObject(tap, "type", "remap_hid");
                cJSON_AddNumberToObject(tap, "mod", p[off]);
                cJSON_AddNumberToObject(tap, "keycode", p[off + 1]);
                cJSON_AddStringToObject(hold, "type", "remap_hid");
                cJSON_AddNumberToObject(hold, "mod", p[off + 2]);
                cJSON_AddNumberToObject(hold, "keycode", p[off + 3]);
                cJSON_AddItemToObject(entry, "tap", tap);
                cJSON_AddItemToObject(entry, "hold", hold);
                cJSON_AddNumberToObject(entry, "hold_ms", rd16(&p[off + 4]));
            }
            break;
        case 9: /* oneshot */
            if (off + 1 < len) {
                cJSON_AddNumberToObject(entry, "mod", p[off]);
                cJSON_AddNumberToObject(entry, "keycode", p[off + 1]);
            }
            break;
        case 10: /* auto_shift */
            if (off + 5 < len) {
                cJSON *normal = cJSON_CreateObject();
                cJSON *shifted = cJSON_CreateObject();
                cJSON_AddNumberToObject(normal, "mod", p[off]);
                cJSON_AddNumberToObject(normal, "keycode", p[off + 1]);
                cJSON_AddNumberToObject(shifted, "mod", p[off + 2]);
                cJSON_AddNumberToObject(shifted, "keycode", p[off + 3]);
                cJSON_AddItemToObject(entry, "normal", normal);
                cJSON_AddItemToObject(entry, "shifted", shifted);
                cJSON_AddNumberToObject(entry, "hold_ms", rd16(&p[off + 4]));
            }
            break;
        case 11: /* mouse_button */
            if (off < len) cJSON_AddNumberToObject(entry, "button", p[off]);
            break;
        case 12: /* sequential */
            if (off < len) {
                uint8_t cnt = p[off++];
                if (cnt > 8) cnt = 8;
                cJSON *outputs = cJSON_CreateArray();
                for (int i = 0; i < cnt && off + 1 < len; i++, off += 2) {
                    cJSON *item = cJSON_CreateObject();
                    cJSON_AddNumberToObject(item, "mod", p[off]);
                    cJSON_AddNumberToObject(item, "keycode", p[off + 1]);
                    cJSON_AddItemToArray(outputs, item);
                }
                cJSON_AddItemToObject(entry, "outputs", outputs);
            }
            break;
        case 13: /* leader */ break;
        case 14: /* profile_switch */
            if (off < len) cJSON_AddNumberToObject(entry, "slot", p[off]);
            break;
        case 15: /* zone */
            if (off < len) cJSON_AddNumberToObject(entry, "zone_index", p[off]);
            break;
        case 16: /* activator */
            if (off < len) cJSON_AddNumberToObject(entry, "activator_index", p[off]);
            break;
        default: break;
    }

    /* Merge into staging profile */
    if (s_atomic_active && s_atomic_root) {
        cJSON *mappings = cJSON_GetObjectItemCaseSensitive(s_atomic_root, "mappings");
        if (!mappings) {
            mappings = cJSON_CreateObject();
            cJSON_AddItemToObject(s_atomic_root, "mappings", mappings);
        }
        char kid_str[8];
        snprintf(kid_str, sizeof(kid_str), "%u", key_id);
        cJSON_DeleteItemFromObjectCaseSensitive(mappings, kid_str);
        cJSON_AddItemToObject(mappings, kid_str, entry);
    } else {
        cJSON_Delete(entry);
    }
    respond_block_ok(CFG_BLOCK_MAPPING);
}

static void apply_macro_def(int slot, const uint8_t *p, size_t len) {
    /* Binary macro: macro_index:u8, id_len:u8, id[id_len], step_count:u8,
       steps: [type:u8, <type-specific>]... */
    if (len < 3) { respond_block_err("macro_too_short"); return; }
    size_t off = 0;
    /* uint8_t macro_index = p[off++]; */  /* reserved for ordering */
    off++;
    uint8_t id_len = p[off++];
    if (id_len > 23 || off + id_len >= len) { respond_block_err("macro_id_too_long"); return; }
    char id_str[24] = {0};
    memcpy(id_str, &p[off], id_len);
    off += id_len;
    if (off >= len) { respond_block_err("macro_no_steps"); return; }
    uint8_t step_count = p[off++];
    if (step_count > 128) step_count = 128;

    cJSON *macro = cJSON_CreateObject();
    cJSON_AddStringToObject(macro, "id", id_str);
    cJSON *steps = cJSON_CreateArray();

    for (uint8_t i = 0; i < step_count && off < len; i++) {
        uint8_t stype = p[off++];
        cJSON *step = cJSON_CreateObject();
        switch (stype) {
            case 1: /* key */
                if (off + 1 < len) {
                    cJSON_AddStringToObject(step, "type", "key");
                    cJSON_AddNumberToObject(step, "key_id", p[off]);
                    cJSON_AddBoolToObject(step, "pressed", p[off + 1] != 0);
                    off += 2;
                }
                break;
            case 2: /* delay */
                if (off + 1 < len) {
                    cJSON_AddStringToObject(step, "type", "delay");
                    cJSON_AddNumberToObject(step, "ms", rd16(&p[off]));
                    off += 2;
                }
                break;
            case 3: /* mouse_button */
                if (off + 1 < len) {
                    cJSON_AddStringToObject(step, "type", "mouse_button");
                    cJSON_AddNumberToObject(step, "button", p[off]);
                    cJSON_AddBoolToObject(step, "pressed", p[off + 1] != 0);
                    off += 2;
                }
                break;
            case 4: /* macro_chain */
                if (off < len) {
                    uint8_t cid_len = p[off++];
                    if (cid_len <= 23 && off + cid_len <= len) {
                        char cid[24] = {0};
                        memcpy(cid, &p[off], cid_len);
                        cJSON_AddStringToObject(step, "type", "macro_chain");
                        cJSON_AddStringToObject(step, "id", cid);
                        off += cid_len;
                    }
                }
                break;
            default:
                cJSON_Delete(step);
                step = NULL;
                break;
        }
        if (step) cJSON_AddItemToArray(steps, step);
    }

    cJSON_AddItemToObject(macro, "steps", steps);

    if (s_atomic_active && s_atomic_root) {
        cJSON *macros_arr = cJSON_GetObjectItemCaseSensitive(s_atomic_root, "macros");
        if (!macros_arr) {
            macros_arr = cJSON_CreateArray();
            cJSON_AddItemToObject(s_atomic_root, "macros", macros_arr);
        }
        cJSON_AddItemToArray(macros_arr, macro);
    } else {
        cJSON_Delete(macro);
    }
    respond_block_ok(CFG_BLOCK_MACRO);
}

static void apply_layer_def(int slot, const uint8_t *p, size_t len) {
    /* Binary layer: name_len:u8, name[name_len], key_id:u8, mode:u8,
       override_count:u8, overrides: [key_id:u8, mode:u8, <payload>]... */
    if (len < 4) { respond_block_err("layer_too_short"); return; }
    size_t off = 0;
    uint8_t name_len = p[off++];
    if (name_len > 23 || off + name_len >= len) { respond_block_err("layer_name_long"); return; }
    char name[24] = {0};
    memcpy(name, &p[off], name_len);
    off += name_len;
    if (off + 2 >= len) { respond_block_err("layer_incomplete"); return; }
    uint8_t act_key = p[off++];
    uint8_t mode = p[off++];
    uint8_t ov_count = p[off++];
    if (ov_count > 32) ov_count = 32;

    cJSON *layer = cJSON_CreateObject();
    cJSON_AddStringToObject(layer, "name", name);
    cJSON_AddNumberToObject(layer, "key_id", act_key);
    cJSON_AddStringToObject(layer, "mode", mode == 1 ? "toggle" : "hold");

    cJSON *mappings = cJSON_CreateObject();
    for (uint8_t i = 0; i < ov_count && off + 1 < len; i++) {
        uint8_t ov_key = p[off++];
        uint8_t ov_mode = p[off++];
        cJSON *ov_entry = cJSON_CreateObject();

        const char *ov_type = "passthrough";
        switch (ov_mode) {
            case 1: ov_type = "disable"; break;
            case 2: ov_type = "remap"; break;
            case 4: ov_type = "remap_hid"; break;
            case 3: ov_type = "macro"; break;
            default: break;
        }
        cJSON_AddStringToObject(ov_entry, "type", ov_type);

        switch (ov_mode) {
            case 2: /* remap */
                if (off < len) { cJSON_AddNumberToObject(ov_entry, "to", p[off++]); }
                break;
            case 4: /* remap_hid */
                if (off + 1 < len) {
                    cJSON_AddNumberToObject(ov_entry, "mod", p[off]);
                    cJSON_AddNumberToObject(ov_entry, "keycode", p[off + 1]);
                    off += 2;
                }
                break;
            case 3: /* macro */
                if (off < len) { cJSON_AddNumberToObject(ov_entry, "macro_index", p[off++]); }
                break;
            default: break;
        }

        char kid_str[8];
        snprintf(kid_str, sizeof(kid_str), "%u", ov_key);
        cJSON_AddItemToObject(mappings, kid_str, ov_entry);
    }
    cJSON_AddItemToObject(layer, "mappings", mappings);

    if (s_atomic_active && s_atomic_root) {
        cJSON *layers = cJSON_GetObjectItemCaseSensitive(s_atomic_root, "layers");
        if (!layers) {
            layers = cJSON_CreateArray();
            cJSON_AddItemToObject(s_atomic_root, "layers", layers);
        }
        cJSON_AddItemToArray(layers, layer);
    } else {
        cJSON_Delete(layer);
    }
    respond_block_ok(CFG_BLOCK_LAYER);
}

static void apply_chord_def(int slot, const uint8_t *p, size_t len) {
    /* Binary chord: key_count:u8, keys[key_count], action_mode:u8, <action payload> */
    if (len < 3) { respond_block_err("chord_too_short"); return; }
    size_t off = 0;
    uint8_t key_count = p[off++];
    if (key_count < 2 || key_count > 4) { respond_block_err("chord_key_count"); return; }
    if (off + key_count >= len) { respond_block_err("chord_keys_short"); return; }

    cJSON *chord = cJSON_CreateObject();
    cJSON *keys = cJSON_CreateArray();
    for (uint8_t i = 0; i < key_count; i++) {
        cJSON_AddItemToArray(keys, cJSON_CreateNumber(p[off++]));
    }
    cJSON_AddItemToObject(chord, "keys", keys);

    if (off >= len) { cJSON_Delete(chord); respond_block_err("chord_no_action"); return; }
    uint8_t action_mode = p[off++];

    cJSON *action = cJSON_CreateObject();
    switch (action_mode) {
        case 1: cJSON_AddStringToObject(action, "type", "disable"); break;
        case 4: /* remap_hid */
            cJSON_AddStringToObject(action, "type", "remap_hid");
            if (off + 1 < len) {
                cJSON_AddNumberToObject(action, "mod", p[off]);
                cJSON_AddNumberToObject(action, "keycode", p[off + 1]);
                off += 2;
            }
            break;
        case 2: /* remap */
            cJSON_AddStringToObject(action, "type", "remap");
            if (off < len) cJSON_AddNumberToObject(action, "to", p[off++]);
            break;
        case 3: /* macro */
            cJSON_AddStringToObject(action, "type", "macro");
            if (off < len) {
                uint8_t mid_len = p[off++];
                if (mid_len <= 23 && off + mid_len <= len) {
                    char mid[24] = {0};
                    memcpy(mid, &p[off], mid_len);
                    cJSON_AddStringToObject(action, "id", mid);
                    off += mid_len;
                }
            }
            break;
        default:
            cJSON_AddStringToObject(action, "type", "passthrough");
            break;
    }
    cJSON_AddItemToObject(chord, "action", action);

    if (s_atomic_active && s_atomic_root) {
        cJSON *chords = cJSON_GetObjectItemCaseSensitive(s_atomic_root, "chords");
        if (!chords) {
            chords = cJSON_CreateArray();
            cJSON_AddItemToObject(s_atomic_root, "chords", chords);
        }
        cJSON_AddItemToArray(chords, chord);
    } else {
        cJSON_Delete(chord);
    }
    respond_block_ok(CFG_BLOCK_CHORD);
}

static void apply_stick_config(int slot, const uint8_t *p, size_t len) {
    /* Binary stick config: see header for format */
    if (len < 14) { respond_block_err("stick_too_short"); return; }

    cJSON *stick = cJSON_CreateObject();

    const char *modes[] = {"keys", "mouse", "scroll"};
    uint8_t rm = p[0];
    if (rm > 2) rm = 0;
    cJSON_AddStringToObject(s_atomic_root ? s_atomic_root : stick,
                            "right_stick_mode", modes[rm]);
    cJSON_AddNumberToObject(s_atomic_root ? s_atomic_root : stick,
                            "mouse_sensitivity", rd16(&p[1]));

    cJSON *sprint = cJSON_CreateObject();
    cJSON_AddBoolToObject(sprint, "enabled", p[3] != 0);
    cJSON_AddNumberToObject(sprint, "threshold", p[4]);
    cJSON *sprint_key = cJSON_CreateObject();
    cJSON_AddNumberToObject(sprint_key, "mod", p[5]);
    cJSON_AddNumberToObject(sprint_key, "keycode", p[6]);
    cJSON_AddItemToObject(sprint, "key", sprint_key);

    const char *curves[] = {"linear", "exponential", "quadratic"};
    uint8_t ct = p[7];
    if (ct > 2) ct = 0;

    cJSON_AddItemToObject(stick, "curve", cJSON_CreateString(curves[ct]));
    cJSON_AddNumberToObject(stick, "exp", (double)p[8] / 100.0);

    const char *socd_modes[] = {"neutral", "last_input", "first_input"};
    uint8_t sm = p[9];
    if (sm > 2) sm = 0;
    cJSON_AddStringToObject(stick, "socd_mode", socd_modes[sm]);

    cJSON *rt = cJSON_CreateObject();
    cJSON_AddNumberToObject(rt, "activation", p[10]);
    cJSON_AddNumberToObject(rt, "deactivation", p[11]);
    cJSON_AddItemToObject(stick, "rapid_trigger", rt);

    cJSON_AddNumberToObject(stick, "deadzone_inner", rd16(&p[12]));
    if (len >= 16) {
        cJSON_AddNumberToObject(stick, "deadzone_outer", rd16(&p[14]));
    }

    if (s_atomic_active && s_atomic_root) {
        cJSON_DeleteItemFromObjectCaseSensitive(s_atomic_root, "stick");
        cJSON_AddItemToObject(s_atomic_root, "stick", stick);
        cJSON_DeleteItemFromObjectCaseSensitive(s_atomic_root, "sprint_zone");
        cJSON_AddItemToObject(s_atomic_root, "sprint_zone", sprint);
    } else {
        cJSON_Delete(stick);
        cJSON_Delete(sprint);
    }
    respond_block_ok(CFG_BLOCK_STICK);
}

static void apply_zone_def(int slot, const uint8_t *p, size_t len) {
    /* Zone definition: see header comments */
    if (len < 12) { respond_block_err("zone_too_short"); return; }
    size_t off = 0;
    uint8_t zone_index = p[off++];
    uint8_t input_source = p[off++];
    uint8_t shape = p[off++];
    uint16_t inner_radius = rd16(&p[off]); off += 2;
    uint16_t outer_radius = rd16(&p[off]); off += 2;
    uint16_t angle_start = rd16(&p[off]); off += 2;
    uint16_t angle_end = rd16(&p[off]); off += 2;

    cJSON *zone = cJSON_CreateObject();
    cJSON_AddNumberToObject(zone, "index", zone_index);

    const char *sources[] = {"lstick", "rstick", "ltrigger", "rtrigger"};
    if (input_source > 3) input_source = 0;
    cJSON_AddStringToObject(zone, "input", sources[input_source]);

    const char *shapes[] = {"radial", "sector", "box"};
    if (shape > 2) shape = 0;
    cJSON_AddStringToObject(zone, "shape", shapes[shape]);

    cJSON_AddNumberToObject(zone, "inner_radius", inner_radius);
    cJSON_AddNumberToObject(zone, "outer_radius", outer_radius);
    cJSON_AddNumberToObject(zone, "angle_start", (double)angle_start / 10.0);
    cJSON_AddNumberToObject(zone, "angle_end", (double)angle_end / 10.0);

    /* Parse action payload if present */
    if (off < len) {
        uint8_t action_mode = p[off++];
        cJSON *action = cJSON_CreateObject();
        switch (action_mode) {
            case 4: /* remap_hid */
                cJSON_AddStringToObject(action, "type", "remap_hid");
                if (off + 1 < len) {
                    cJSON_AddNumberToObject(action, "mod", p[off]);
                    cJSON_AddNumberToObject(action, "keycode", p[off + 1]);
                    off += 2;
                }
                break;
            case 11: /* mouse_button */
                cJSON_AddStringToObject(action, "type", "mouse_button");
                if (off < len) cJSON_AddNumberToObject(action, "button", p[off++]);
                break;
            default:
                cJSON_AddStringToObject(action, "type", "passthrough");
                break;
        }
        cJSON_AddItemToObject(zone, "action", action);
    }

    if (s_atomic_active && s_atomic_root) {
        cJSON *zones = cJSON_GetObjectItemCaseSensitive(s_atomic_root, "zones");
        if (!zones) {
            zones = cJSON_CreateArray();
            cJSON_AddItemToObject(s_atomic_root, "zones", zones);
        }
        cJSON_AddItemToArray(zones, zone);
    } else {
        cJSON_Delete(zone);
    }
    respond_block_ok(CFG_BLOCK_ZONE);
}

static void apply_activator_def(int slot, const uint8_t *p, size_t len) {
    if (len < 5) { respond_block_err("activator_too_short"); return; }
    size_t off = 0;
    uint8_t act_index = p[off++];
    uint8_t act_type = p[off++];
    uint8_t key_id = p[off++];
    uint16_t param1 = rd16(&p[off]); off += 2;

    cJSON *activator = cJSON_CreateObject();
    cJSON_AddNumberToObject(activator, "index", act_index);

    const char *types[] = {"press", "release", "double_press", "long_press",
                           "chord", "turbo_hold"};
    if (act_type > 5) act_type = 0;
    cJSON_AddStringToObject(activator, "type", types[act_type]);
    cJSON_AddNumberToObject(activator, "key_id", key_id);
    cJSON_AddNumberToObject(activator, "param", param1);

    /* Parse action payload if present */
    if (off < len) {
        uint8_t action_mode = p[off++];
        cJSON *action = cJSON_CreateObject();
        switch (action_mode) {
            case 4: /* remap_hid */
                cJSON_AddStringToObject(action, "type", "remap_hid");
                if (off + 1 < len) {
                    cJSON_AddNumberToObject(action, "mod", p[off]);
                    cJSON_AddNumberToObject(action, "keycode", p[off + 1]);
                    off += 2;
                }
                break;
            case 3: /* macro */
                cJSON_AddStringToObject(action, "type", "macro");
                if (off < len) {
                    uint8_t mid_len = p[off++];
                    if (mid_len <= 23 && off + mid_len <= len) {
                        char mid[24] = {0};
                        memcpy(mid, &p[off], mid_len);
                        cJSON_AddStringToObject(action, "id", mid);
                        off += mid_len;
                    }
                }
                break;
            default:
                cJSON_AddStringToObject(action, "type", "passthrough");
                break;
        }
        cJSON_AddItemToObject(activator, "action", action);
    }

    if (s_atomic_active && s_atomic_root) {
        cJSON *activators = cJSON_GetObjectItemCaseSensitive(s_atomic_root, "activators");
        if (!activators) {
            activators = cJSON_CreateArray();
            cJSON_AddItemToObject(s_atomic_root, "activators", activators);
        }
        cJSON_AddItemToArray(activators, activator);
    } else {
        cJSON_Delete(activator);
    }
    respond_block_ok(CFG_BLOCK_ACTIVATOR);
}

static void apply_gyro_config(int slot, const uint8_t *p, size_t len) {
    if (len < 11) { respond_block_err("gyro_too_short"); return; }
    /* Binary format (matches serial_client.py _send_gyro_block):
     *   [0]    enabled:u8
     *   [1-2]  sensitivity_x:u16-LE
     *   [3-4]  sensitivity_y:u16-LE
     *   [5-6]  deadzone:u16-LE
     *   [7]    accel_type:u8
     *   [8-9]  accel_param:u16-LE
     *   [10]   invert_x:u8
     *   [11]   invert_y:u8  (optional)
     */
    cJSON *gyro = cJSON_CreateObject();
    cJSON_AddBoolToObject(gyro, "enabled", p[0] != 0);
    cJSON_AddNumberToObject(gyro, "sensitivity_x", rd16(&p[1]));
    cJSON_AddNumberToObject(gyro, "sensitivity_y", rd16(&p[3]));
    cJSON_AddNumberToObject(gyro, "deadzone", rd16(&p[5]));
    cJSON_AddNumberToObject(gyro, "accel_type", p[7]);
    cJSON_AddNumberToObject(gyro, "accel_param", rd16(&p[8]));
    cJSON_AddBoolToObject(gyro, "invert_x", p[10] != 0);
    if (len > 11) cJSON_AddBoolToObject(gyro, "invert_y", p[11] != 0);

    if (s_atomic_active && s_atomic_root) {
        cJSON_DeleteItemFromObjectCaseSensitive(s_atomic_root, "gyro");
        cJSON_AddItemToObject(s_atomic_root, "gyro", gyro);
    } else {
        cJSON_Delete(gyro);
    }
    respond_block_ok(CFG_BLOCK_GYRO);
}

static void apply_profile_begin(int slot) {
    if (s_atomic_active) {
        /* Abort any in-progress push */
        cJSON_Delete(s_atomic_root);
        s_atomic_root = NULL;
    }
    s_atomic_active = true;
    s_atomic_slot = slot;
    s_atomic_root = cJSON_CreateObject();
    cJSON_AddNumberToObject(s_atomic_root, "ver", 2);
    ESP_LOGI(TAG, "Atomic profile push started for slot %d", slot);
    respond_block_ok(CFG_BLOCK_PROFILE_BEGIN);
}

static void apply_profile_end(int slot) {
    if (!s_atomic_active || !s_atomic_root) {
        respond_block_err("no_active_push");
        return;
    }

    /* Serialize and write to NVS */
    char *json = cJSON_PrintUnformatted(s_atomic_root);
    cJSON_Delete(s_atomic_root);
    s_atomic_root = NULL;
    s_atomic_active = false;

    if (!json) {
        respond_block_err("serialize_failed");
        return;
    }

    /* Write to NVS via bridge_serial's existing NVS interface */
    nvs_handle_t h;
    char key[8];
    snprintf(key, sizeof(key), "p%d", s_atomic_slot);
    esp_err_t err = nvs_open("profiles", NVS_READWRITE, &h);
    if (err != ESP_OK) {
        free(json);
        respond_block_err("nvs_open_failed");
        return;
    }
    err = nvs_set_str(h, key, json);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    free(json);

    if (err != ESP_OK) {
        respond_block_err("nvs_write_failed");
        return;
    }

    ESP_LOGI(TAG, "Atomic profile committed to slot %d", s_atomic_slot);
    respond_block_ok(CFG_BLOCK_PROFILE_END);

    /* Reload if this was the active slot */
    profile_runtime_reload();
}

static void apply_profile_abort(void) {
    cJSON_Delete(s_atomic_root);
    s_atomic_root = NULL;
    s_atomic_active = false;
    ESP_LOGI(TAG, "Atomic profile push aborted");
    respond_block_ok(CFG_BLOCK_PROFILE_ABORT);
}

static void process_block(uint8_t block_type, uint8_t slot, const uint8_t *payload, size_t len) {
    switch (block_type) {
        case CFG_BLOCK_PROFILE_BEGIN:
            apply_profile_begin(slot);
            break;
        case CFG_BLOCK_PROFILE_END:
            apply_profile_end(slot);
            break;
        case CFG_BLOCK_PROFILE_ABORT:
            apply_profile_abort();
            break;
        case CFG_BLOCK_MAPPING:
            apply_mapping_entry(slot, payload, len);
            break;
        case CFG_BLOCK_MACRO:
            apply_macro_def(slot, payload, len);
            break;
        case CFG_BLOCK_LAYER:
            apply_layer_def(slot, payload, len);
            break;
        case CFG_BLOCK_CHORD:
            apply_chord_def(slot, payload, len);
            break;
        case CFG_BLOCK_STICK:
            apply_stick_config(slot, payload, len);
            break;
        case CFG_BLOCK_ZONE:
            apply_zone_def(slot, payload, len);
            break;
        case CFG_BLOCK_ACTIVATOR:
            apply_activator_def(slot, payload, len);
            break;
        case CFG_BLOCK_GYRO:
            apply_gyro_config(slot, payload, len);
            break;
        case CFG_BLOCK_BULK_JSON:
            /* Fallback: treat payload as raw JSON profile string */
            if (len > 0 && slot >= 0 && slot < 4) {
                char *json_str = (char *)malloc(len + 1);
                if (json_str) {
                    memcpy(json_str, payload, len);
                    json_str[len] = '\0';

                    nvs_handle_t h;
                    char key[8];
                    snprintf(key, sizeof(key), "p%d", slot);
                    esp_err_t err = nvs_open("profiles", NVS_READWRITE, &h);
                    if (err == ESP_OK) {
                        err = nvs_set_str(h, key, json_str);
                        if (err == ESP_OK) nvs_commit(h);
                        nvs_close(h);
                    }
                    free(json_str);

                    if (err == ESP_OK) {
                        respond_block_ok(CFG_BLOCK_BULK_JSON);
                        profile_runtime_reload();
                    } else {
                        respond_block_err("nvs_write_failed");
                    }
                } else {
                    respond_block_err("oom");
                }
            } else {
                respond_block_err("invalid_bulk");
            }
            break;
        default:
            respond_block_err("unknown_block_type");
            break;
    }
}

/* ── Feed raw CDC bytes ────────────────────────────────────── */

void config_block_init(void) {
    s_state = RX_IDLE;
    s_hdr_pos = 0;
    s_payload_pos = 0;
    s_crc_pos = 0;
    s_atomic_active = false;
    s_atomic_slot = -1;
    if (s_atomic_root) {
        cJSON_Delete(s_atomic_root);
        s_atomic_root = NULL;
    }
    if (!s_payload) {
        s_payload = (uint8_t *)malloc(CFG_MAX_PAYLOAD);
        if (!s_payload) {
            ESP_LOGE(TAG, "Config block payload buffer alloc failed");
        }
    }
}

bool config_block_receiving(void) {
    return s_state != RX_IDLE;
}

size_t config_block_feed(const uint8_t *data, size_t len) {
    size_t consumed = 0;

    while (consumed < len) {
        uint8_t byte = data[consumed];

        switch (s_state) {
            case RX_IDLE:
                if (byte == CONFIG_BLOCK_MARKER) {
                    s_state = RX_HEADER;
                    s_hdr_pos = 0;
                    consumed++;
                } else {
                    return consumed; /* Not binary data - return to NDJSON */
                }
                break;

            case RX_HEADER:
                s_hdr[s_hdr_pos++] = byte;
                consumed++;
                if (s_hdr_pos >= 4) {
                    s_payload_len = rd16(&s_hdr[2]);
                    if (s_payload_len > CFG_MAX_PAYLOAD || !s_payload) {
                        ESP_LOGW(TAG, "Config block too large: %u", (unsigned)s_payload_len);
                        respond_block_err("payload_too_large");
                        s_state = RX_IDLE;
                    } else if (s_payload_len == 0) {
                        s_state = RX_CRC;
                        s_crc_pos = 0;
                        s_payload_pos = 0;
                    } else {
                        s_state = RX_PAYLOAD;
                        s_payload_pos = 0;
                    }
                }
                break;

            case RX_PAYLOAD:
                s_payload[s_payload_pos++] = byte;
                consumed++;
                if (s_payload_pos >= s_payload_len) {
                    s_state = RX_CRC;
                    s_crc_pos = 0;
                }
                break;

            case RX_CRC:
                s_crc_buf[s_crc_pos++] = byte;
                consumed++;
                if (s_crc_pos >= 2) {
                    /* Verify CRC */
                    uint16_t rx_crc = rd16(s_crc_buf);

                    /* CRC covers: block_type + slot + len(2) + payload */
                    size_t crc_len = 4 + s_payload_len;
                    uint8_t *crc_data = (uint8_t *)malloc(crc_len);
                    if (crc_data) {
                        memcpy(crc_data, s_hdr, 4);
                        if (s_payload_len > 0) {
                            memcpy(crc_data + 4, s_payload, s_payload_len);
                        }
                        uint16_t calc_crc = config_block_crc16(crc_data, crc_len);
                        free(crc_data);

                        if (calc_crc == rx_crc) {
                            process_block(s_hdr[0], s_hdr[1],
                                          s_payload, s_payload_len);
                        } else {
                            ESP_LOGW(TAG, "CRC mismatch: got 0x%04X expected 0x%04X",
                                     rx_crc, calc_crc);
                            respond_block_err("crc_mismatch");
                        }
                    } else {
                        respond_block_err("oom");
                    }

                    s_state = RX_IDLE;
                }
                break;
        }
    }
    return consumed;
}
