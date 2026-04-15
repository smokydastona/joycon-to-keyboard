#include "profile_runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "esp_err.h"
#include "esp_log.h"

#include "esp_timer.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "nvs.h"

#include "cJSON.h"

#include "esp_random.h"

#include "bridge_serial.h"
#include "keymap.h"
#include "usb_gamepad.h"
#include "usb_kbd.h"
#include "usb_mouse.h"
#include "uart_proto.h"

static const char *TAG = "profile";

#define BRIDGE_PROFILE_NS "profiles"
#define BRIDGE_ACTIVE_KEY "active"

#define PROFILE_MAX_SLOTS 4
#define PROFILE_MAX_MACROS 16
#define PROFILE_MAX_STEPS 128
#define PROFILE_MAX_MACRO_ID 24

// Input key-id space is device_id*128 + base_key_id.
// With 5 devices (0..4) and base_key_id 0..127, max is 639.
#define INPUT_KEY_ID_MAX 640

// Anti-cheat humanization: enabled by default, adds timing jitter
// to macro delays and turbo intervals so they don't look robotic.
static bool s_humanize = true;

// Apply ±pct% random jitter to a delay value (min 1 ms result).
static uint32_t humanize_delay(uint32_t base_ms, int pct) {
    if (!s_humanize || base_ms == 0) return base_ms;
    uint32_t rng = esp_random();
    // Map rng to [-pct, +pct] range: offset = base_ms * (rng % (2*pct+1) - pct) / 100
    int spread = (int)(rng % (uint32_t)(2 * pct + 1)) - pct;
    int32_t delta = (int32_t)base_ms * spread / 100;
    int32_t result = (int32_t)base_ms + delta;
    return (result < 1) ? 1 : (uint32_t)result;
}

typedef enum {
    STEP_KEY = 1,
    STEP_DELAY = 2,
    STEP_MOUSE_BUTTON = 3,
    STEP_MACRO_CHAIN = 4,
    STEP_MOUSE_MOVE = 5,
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
        struct {
            uint8_t button;   // MOUSE_BUTTON_LEFT=1, RIGHT=2, etc.
            bool pressed;
        } mouse;
        struct {
            int8_t macro_index;
        } chain;
        struct {
            int8_t dx;
            int8_t dy;
        } mouse_move;
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
    MAP_TURBO = 6,
    MAP_STICKY_MOD = 7,
    MAP_TAP_HOLD = 8,
    MAP_ONESHOT_MOD = 9,
    MAP_AUTO_SHIFT = 10,
    MAP_MOUSE_BUTTON = 11,
    MAP_SEQUENTIAL = 12,
    MAP_LEADER = 13,
    MAP_PROFILE_SWITCH = 14,
    MAP_SNIPER = 15,
    MAP_DPI_CYCLE = 16,
    MAP_GAMEPAD_BUTTON = 17,
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
    // Turbo fields (MAP_TURBO)
    uint8_t turbo_hid_mod;
    uint8_t turbo_hid_keycode;
    uint16_t turbo_delay_ms;   // default 50
    // Sticky modifier fields (MAP_STICKY_MOD)
    uint8_t sticky_hid_mod;
    uint8_t sticky_hid_keycode;
    // Tap-hold fields (MAP_TAP_HOLD)
    uint8_t th_tap_hid_mod;
    uint8_t th_tap_hid_keycode;
    uint8_t th_hold_hid_mod;
    uint8_t th_hold_hid_keycode;
    uint16_t th_hold_ms;       // default 300
    // One-shot modifier fields (MAP_ONESHOT_MOD)
    uint8_t os_hid_mod;
    uint8_t os_hid_keycode;
    // Auto-shift fields (MAP_AUTO_SHIFT)
    uint8_t as_normal_mod;
    uint8_t as_normal_keycode;
    uint8_t as_shifted_mod;
    uint8_t as_shifted_keycode;
    uint16_t as_hold_ms;       // default 200
    // Mouse button fields (MAP_MOUSE_BUTTON)
    uint8_t mouse_button;      // MOUSE_BUTTON_LEFT=1, RIGHT=2, MIDDLE=4
    // Gamepad button fields (MAP_GAMEPAD_BUTTON)
    uint8_t gamepad_button;
    // Sequential fields (MAP_SEQUENTIAL)
    uint8_t seq_count;
    uint8_t seq_mods[8];
    uint8_t seq_keycodes[8];
    // Leader fields (MAP_LEADER) — leader key just sets s_leader_active
    // Profile switch fields (MAP_PROFILE_SWITCH)
    uint8_t profile_slot;  // 0..3
    // Sniper fields (MAP_SNIPER)
    uint16_t sniper_sensitivity;  // override sensitivity while held
} map_entry_t;


static uint8_t parse_gamepad_button_code(cJSON *button_j)
{
    if (cJSON_IsNumber(button_j)) {
        int value = button_j->valueint;
        if (value >= USB_GAMEPAD_OUTPUT_A && value <= USB_GAMEPAD_OUTPUT_DPAD_RIGHT) {
            return (uint8_t)value;
        }
        return 0;
    }

    if (!cJSON_IsString(button_j) || !button_j->valuestring) {
        return 0;
    }

    const char *button = button_j->valuestring;
    if (strcmp(button, "A") == 0) return USB_GAMEPAD_OUTPUT_A;
    if (strcmp(button, "B") == 0) return USB_GAMEPAD_OUTPUT_B;
    if (strcmp(button, "X") == 0) return USB_GAMEPAD_OUTPUT_X;
    if (strcmp(button, "Y") == 0) return USB_GAMEPAD_OUTPUT_Y;
    if (strcmp(button, "LB") == 0) return USB_GAMEPAD_OUTPUT_LB;
    if (strcmp(button, "RB") == 0) return USB_GAMEPAD_OUTPUT_RB;
    if (strcmp(button, "LT") == 0) return USB_GAMEPAD_OUTPUT_LT;
    if (strcmp(button, "RT") == 0) return USB_GAMEPAD_OUTPUT_RT;
    if (strcmp(button, "View") == 0) return USB_GAMEPAD_OUTPUT_VIEW;
    if (strcmp(button, "Menu") == 0) return USB_GAMEPAD_OUTPUT_MENU;
    if (strcmp(button, "LS") == 0) return USB_GAMEPAD_OUTPUT_L3;
    if (strcmp(button, "RS") == 0) return USB_GAMEPAD_OUTPUT_R3;
    if (strcmp(button, "Xbox") == 0) return USB_GAMEPAD_OUTPUT_XBOX;
    if (strcmp(button, "Share") == 0) return USB_GAMEPAD_OUTPUT_SHARE;
    if (strcmp(button, "P1") == 0) return USB_GAMEPAD_OUTPUT_P1;
    if (strcmp(button, "P2") == 0) return USB_GAMEPAD_OUTPUT_P2;
    if (strcmp(button, "P3") == 0) return USB_GAMEPAD_OUTPUT_P3;
    if (strcmp(button, "P4") == 0) return USB_GAMEPAD_OUTPUT_P4;
    if (strcmp(button, "DUp") == 0) return USB_GAMEPAD_OUTPUT_DPAD_UP;
    if (strcmp(button, "DDown") == 0) return USB_GAMEPAD_OUTPUT_DPAD_DOWN;
    if (strcmp(button, "DLeft") == 0) return USB_GAMEPAD_OUTPUT_DPAD_LEFT;
    if (strcmp(button, "DRight") == 0) return USB_GAMEPAD_OUTPUT_DPAD_RIGHT;
    return 0;
}

// --- Layer system ---

#define MAX_LAYERS 4
#define MAX_LAYER_OVERRIDES 32

typedef enum {
    LAYER_HOLD = 0,
    LAYER_TOGGLE = 1,
} layer_mode_t;

typedef struct {
    uint16_t key_id;
    map_entry_t entry;
} layer_override_t;

typedef struct {
    char name[24];
    uint16_t activation_key_id;
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
    uint16_t key_id;
    dt_state_t state;
    esp_timer_handle_t timer;
    // Cached single-tap values for the timeout callback
    uint8_t armed_single_mod;
    uint8_t armed_single_keycode;
} dt_tracker_t;

static dt_tracker_t s_dt_trackers[MAX_DOUBLE_TAP_KEYS];
static size_t s_dt_count = 0;

static dt_tracker_t *find_dt_tracker(uint16_t key_id) {
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

static void register_dt_tracker(uint16_t key_id) {
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

// --- Turbo (rapid-fire) system ---

#define MAX_TURBO_KEYS 8

typedef struct {
    uint16_t key_id;
    bool active;
    bool key_pressed;  // toggle state
    uint8_t hid_mod;
    uint8_t hid_keycode;
    uint16_t delay_ms;  // base interval for humanized re-arm
    esp_timer_handle_t timer;
} turbo_tracker_t;

static turbo_tracker_t s_turbo_trackers[MAX_TURBO_KEYS];
static size_t s_turbo_count = 0;

static turbo_tracker_t *find_turbo_tracker(uint16_t key_id) {
    for (size_t i = 0; i < s_turbo_count; i++) {
        if (s_turbo_trackers[i].key_id == key_id) return &s_turbo_trackers[i];
    }
    return NULL;
}

static void turbo_timer_cb(void *arg) {
    turbo_tracker_t *tt = (turbo_tracker_t *)arg;
    if (!tt->active) return;
    tt->key_pressed = !tt->key_pressed;
    usb_kbd_set_key(tt->hid_mod, tt->hid_keycode, tt->key_pressed);
    // Re-arm as one-shot with ±10% humanized jitter so turbo doesn't
    // look like a perfectly periodic bot to anti-cheat.
    uint32_t next = humanize_delay(tt->delay_ms, 10);
    esp_timer_start_once(tt->timer, (uint64_t)next * 1000);
}

static void register_turbo_tracker(uint16_t key_id) {
    if (find_turbo_tracker(key_id)) return;
    if (s_turbo_count >= MAX_TURBO_KEYS) {
        ESP_LOGW(TAG, "Max turbo keys reached (%d)", MAX_TURBO_KEYS);
        return;
    }
    turbo_tracker_t *tt = &s_turbo_trackers[s_turbo_count];
    memset(tt, 0, sizeof(*tt));
    tt->key_id = key_id;
    esp_timer_create_args_t args = {
        .callback = turbo_timer_cb,
        .arg = tt,
        .name = "turbo",
    };
    if (esp_timer_create(&args, &tt->timer) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create turbo timer for key %u", key_id);
        return;
    }
    s_turbo_count++;
}

// --- Sticky modifier state ---

static bool s_sticky_state[INPUT_KEY_ID_MAX];

// --- Tap-hold state machine ---

#define MAX_TAP_HOLD_KEYS 8

typedef enum {
    TH_IDLE = 0,
    TH_PRESSED,   // key pressed, waiting for hold threshold
    TH_HOLDING,   // hold threshold exceeded, hold action active
} th_state_t;

typedef struct {
    uint16_t key_id;
    th_state_t state;
    esp_timer_handle_t timer;
    uint8_t tap_hid_mod;
    uint8_t tap_hid_keycode;
    uint8_t hold_hid_mod;
    uint8_t hold_hid_keycode;
} th_tracker_t;

static th_tracker_t s_th_trackers[MAX_TAP_HOLD_KEYS];
static size_t s_th_count = 0;

static th_tracker_t *find_th_tracker(uint16_t key_id) {
    for (size_t i = 0; i < s_th_count; i++) {
        if (s_th_trackers[i].key_id == key_id) return &s_th_trackers[i];
    }
    return NULL;
}

static void th_timeout_cb(void *arg) {
    th_tracker_t *th = (th_tracker_t *)arg;
    if (th->state != TH_PRESSED) return;
    // Hold threshold reached: fire hold action.
    th->state = TH_HOLDING;
    usb_kbd_set_key(th->hold_hid_mod, th->hold_hid_keycode, true);
}

static void register_th_tracker(uint16_t key_id) {
    if (find_th_tracker(key_id)) return;
    if (s_th_count >= MAX_TAP_HOLD_KEYS) {
        ESP_LOGW(TAG, "Max tap-hold keys reached (%d)", MAX_TAP_HOLD_KEYS);
        return;
    }
    th_tracker_t *th = &s_th_trackers[s_th_count];
    memset(th, 0, sizeof(*th));
    th->key_id = key_id;
    th->state = TH_IDLE;
    esp_timer_create_args_t args = {
        .callback = th_timeout_cb,
        .arg = th,
        .name = "th",
    };
    if (esp_timer_create(&args, &th->timer) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create tap-hold timer for key %u", key_id);
        return;
    }
    s_th_count++;
}

// --- One-shot modifier system ---
// Press the one-shot key → modifier is armed.
// Press any other key → modifier applied for that key press, then auto-released.
// 3-second timeout: if no other key is pressed, modifier is disarmed.

typedef enum {
    OS_IDLE = 0,
    OS_ARMED = 1,
} os_state_t;

#define MAX_ONESHOT_KEYS 8

typedef struct {
    uint16_t key_id;
    os_state_t state;
    uint8_t hid_mod;
    uint8_t hid_keycode;
    esp_timer_handle_t timer;
} os_tracker_t;

static os_tracker_t s_os_trackers[MAX_ONESHOT_KEYS];
static size_t s_os_count = 0;

static os_tracker_t *find_os_tracker(uint16_t key_id) {
    for (size_t i = 0; i < s_os_count; i++) {
        if (s_os_trackers[i].key_id == key_id) return &s_os_trackers[i];
    }
    return NULL;
}

static void os_timeout_cb(void *arg) {
    os_tracker_t *os = (os_tracker_t *)arg;
    if (os->state == OS_ARMED) {
        // Timeout: disarm without firing.
        os->state = OS_IDLE;
        usb_kbd_set_key(os->hid_mod, os->hid_keycode, false);
    }
}

static void register_os_tracker(uint16_t key_id) {
    if (find_os_tracker(key_id)) return;
    if (s_os_count >= MAX_ONESHOT_KEYS) {
        ESP_LOGW(TAG, "Max one-shot keys reached (%d)", MAX_ONESHOT_KEYS);
        return;
    }
    os_tracker_t *os = &s_os_trackers[s_os_count];
    memset(os, 0, sizeof(*os));
    os->key_id = key_id;
    os->state = OS_IDLE;
    esp_timer_create_args_t args = {
        .callback = os_timeout_cb,
        .arg = os,
        .name = "os",
    };
    if (esp_timer_create(&args, &os->timer) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create one-shot timer for key %u", key_id);
        return;
    }
    s_os_count++;
}

// Consume armed one-shot modifiers: press the modifier, let the caller
// handle the actual key, then schedule release on key-up.
static bool s_oneshot_pending_release = false;
static uint8_t s_oneshot_release_mod = 0;
static uint8_t s_oneshot_release_kc = 0;

static void oneshot_apply_if_armed(void) {
    for (size_t i = 0; i < s_os_count; i++) {
        if (s_os_trackers[i].state == OS_ARMED) {
            esp_timer_stop(s_os_trackers[i].timer);
            // Modifier is already pressed from arm; we just need to
            // record that it should be released after the next key-up.
            s_oneshot_pending_release = true;
            s_oneshot_release_mod = s_os_trackers[i].hid_mod;
            s_oneshot_release_kc = s_os_trackers[i].hid_keycode;
            s_os_trackers[i].state = OS_IDLE;
        }
    }
}

static void oneshot_release_if_pending(void) {
    if (s_oneshot_pending_release) {
        usb_kbd_set_key(s_oneshot_release_mod, s_oneshot_release_kc, false);
        s_oneshot_pending_release = false;
    }
}

// --- Auto-shift state machine ---
// Quick tap = normal keycode, hold > threshold = Shift+keycode
// Reuses the tap-hold timer pattern.

#define MAX_AUTO_SHIFT_KEYS 8

typedef enum {
    AS_IDLE = 0,
    AS_PRESSED,   // key pressed, waiting for hold threshold
    AS_HOLDING,   // hold threshold exceeded, shifted action active
} as_state_t;

typedef struct {
    uint16_t key_id;
    as_state_t state;
    esp_timer_handle_t timer;
    uint8_t normal_mod;
    uint8_t normal_keycode;
    uint8_t shifted_mod;
    uint8_t shifted_keycode;
} as_tracker_t;

static as_tracker_t s_as_trackers[MAX_AUTO_SHIFT_KEYS];
static size_t s_as_count = 0;

static as_tracker_t *find_as_tracker(uint16_t key_id) {
    for (size_t i = 0; i < s_as_count; i++) {
        if (s_as_trackers[i].key_id == key_id) return &s_as_trackers[i];
    }
    return NULL;
}

static void as_timeout_cb(void *arg) {
    as_tracker_t *as = (as_tracker_t *)arg;
    if (as->state != AS_PRESSED) return;
    // Hold threshold reached: fire shifted action.
    as->state = AS_HOLDING;
    usb_kbd_set_key(as->shifted_mod, as->shifted_keycode, true);
}

static void register_as_tracker(uint16_t key_id) {
    if (find_as_tracker(key_id)) return;
    if (s_as_count >= MAX_AUTO_SHIFT_KEYS) {
        ESP_LOGW(TAG, "Max auto-shift keys reached (%d)", MAX_AUTO_SHIFT_KEYS);
        return;
    }
    as_tracker_t *as = &s_as_trackers[s_as_count];
    memset(as, 0, sizeof(*as));
    as->key_id = key_id;
    as->state = AS_IDLE;
    esp_timer_create_args_t args = {
        .callback = as_timeout_cb,
        .arg = as,
        .name = "as",
    };
    if (esp_timer_create(&args, &as->timer) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create auto-shift timer for key %u", key_id);
        return;
    }
    s_as_count++;
}

// --- Sequential/cycle button ---
// Each press sends the next item in a list, wrapping around.

static uint8_t s_seq_index[INPUT_KEY_ID_MAX];

// --- Leader key sequences ---
// Designate a key as leader; after pressing, buffer subsequent keys
// within timeout and match against configured sequences.

#define MAX_LEADER_SEQS 8
#define MAX_LEADER_SEQ_LEN 4
#define LEADER_TIMEOUT_MS 1000

typedef struct {
    uint16_t keys[MAX_LEADER_SEQ_LEN];
    uint8_t key_count;
    uint8_t action_mod;
    uint8_t action_keycode;
} leader_seq_t;

static leader_seq_t s_leader_seqs[MAX_LEADER_SEQS];
static size_t s_leader_seq_count = 0;

static bool s_leader_active = false;
static uint16_t s_leader_buf[MAX_LEADER_SEQ_LEN];
static size_t s_leader_buf_len = 0;
static esp_timer_handle_t s_leader_timer = NULL;

static void leader_timeout_cb(void *arg) {
    (void)arg;
    if (!s_leader_active) return;

    // Try to match the buffered sequence.
    for (size_t i = 0; i < s_leader_seq_count; i++) {
        leader_seq_t *ls = &s_leader_seqs[i];
        if (ls->key_count != s_leader_buf_len) continue;
        bool match = true;
        for (size_t j = 0; j < ls->key_count; j++) {
            if (ls->keys[j] != s_leader_buf[j]) { match = false; break; }
        }
        if (match) {
            usb_kbd_set_key(ls->action_mod, ls->action_keycode, true);
            usb_kbd_set_key(ls->action_mod, ls->action_keycode, false);
            break;
        }
    }

    s_leader_active = false;
    s_leader_buf_len = 0;
}

// --- Right stick mode ---
typedef enum {
    STICK_MODE_KEYS = 0,     // default: stick → WASD key events
    STICK_MODE_MOUSE = 1,    // stick → mouse cursor movement
    STICK_MODE_SCROLL = 2,   // stick → scroll wheel
} stick_mode_t;

static stick_mode_t s_right_stick_mode = STICK_MODE_KEYS;
static uint16_t s_mouse_sensitivity = 10;  // sensitivity multiplier (1-50)

// --- DPI presets (cycled by MAP_DPI_CYCLE) ---
#define DPI_PRESET_MAX 5
static uint16_t s_dpi_presets[DPI_PRESET_MAX] = {5, 10, 20, 30, 50};
static uint8_t  s_dpi_preset_count = 5;
static uint8_t  s_dpi_preset_index = 1;  // default → preset[1] = 10

// --- Sniper mode (temporary sensitivity override while held) ---
static bool     s_sniper_active = false;
static uint16_t s_sniper_sensitivity = 3;  // default: very slow for precision
static uint16_t s_base_sensitivity = 10;   // saved before sniper activates

// --- Sprint zone (left stick magnitude → sprint key) ---
static bool s_sprint_zone_enabled = false;
static uint8_t s_sprint_zone_threshold = 90;  // % of max deflection
static uint8_t s_sprint_key_mod = 0;
static uint8_t s_sprint_key_keycode = 0;
static bool s_sprint_active = false;

// --- Gyro-to-mouse configuration ---
typedef enum {
    GYRO_ACCEL_NONE   = 0,   // linear: raw × sensitivity
    GYRO_ACCEL_POWER  = 1,   // pow(magnitude, param) scaling
    GYRO_ACCEL_SMOOTH = 2,   // smooth ramp with threshold
} gyro_accel_t;

static bool     s_gyro_enabled     = false;
static uint16_t s_gyro_sens_x      = 100;   // sensitivity × 100 (100 = 1.0×)
static uint16_t s_gyro_sens_y      = 100;
static uint16_t s_gyro_deadzone    = 50;     // raw gyro units below which input is ignored
static gyro_accel_t s_gyro_accel   = GYRO_ACCEL_NONE;
static uint16_t s_gyro_accel_param = 150;    // ×100 for POWER (150 = 1.5 exponent)
static bool     s_gyro_invert_x    = false;
static bool     s_gyro_invert_y    = false;

// --- Flick stick system ---
// When enabled on right stick: a fast stick deflection triggers a 180°
// camera "flick" to the stick angle, then gyro yaw controls aiming while
// stick is held.  On release the stick resets.
static bool     s_flick_stick_enabled = false;
static uint16_t s_flick_stick_threshold = 3000;  // magnitude threshold to enter flick (0..4096)
static uint16_t s_flick_snap_degrees   = 0;      // if >0, snap flick to nearest N degrees (e.g. 45)
// runtime state
static bool     s_flick_active     = false;       // stick currently in deflected "flick" state
static float    s_flick_last_angle = 0.0f;        // last raw stick angle while flicking (radians)

// --- Configurable acceleration curves for stick-to-mouse ---
typedef enum {
    STICK_ACCEL_LINEAR = 0,   // no curve, raw proportional
    STICK_ACCEL_POWER  = 1,   // power curve (like gyro)
    STICK_ACCEL_SCURVE = 2,   // S-curve: slow→fast→slow
} stick_accel_t;

static stick_accel_t s_stick_accel       = STICK_ACCEL_LINEAR;
static uint16_t      s_stick_accel_param = 200;   // ×100 exponent for power; midpoint for S-curve

// --- Gyro calibration (bias offsets subtracted from raw data) ---
static int16_t  s_gyro_bias_x  = 0;
static int16_t  s_gyro_bias_y  = 0;
static int16_t  s_gyro_bias_z  = 0;

// Calibration wizard state: when active, samples are accumulated
// and averaged to compute bias.
#define GYRO_CAL_SAMPLES 128
static bool     s_cal_active    = false;
static int      s_cal_count     = 0;
static int32_t  s_cal_sum_x     = 0;
static int32_t  s_cal_sum_y     = 0;
static int32_t  s_cal_sum_z     = 0;

// --- Zone system (stick regions → key outputs) ---
#define MAX_ZONES 16

typedef enum {
    ZONE_SHAPE_CIRCLE = 0,
    ZONE_SHAPE_RING   = 1,
    ZONE_SHAPE_WEDGE  = 2,
    ZONE_SHAPE_RECT   = 3,
} zone_shape_t;

typedef struct {
    zone_shape_t shape;
    int16_t  cx, cy;           // center (normalized -4096..+4096 or 0 for stick center)
    uint16_t param1, param2;   // shape-specific: circle=radius; ring=inner,outer; rect=w,h
    uint16_t param3, param4;   // reserved / wedge angles
    int16_t  angle_start;      // for wedge: start angle in degrees
    int16_t  angle_end;        // for wedge: end angle in degrees
    uint8_t  output_key;       // HID keycode to press when active
    bool     active;           // runtime: currently inside zone?
} zone_t;

static zone_t s_zones[MAX_ZONES];
static size_t s_zone_count = 0;

// --- Activator system (trigger → action) ---
#define MAX_ACTIVATORS 16

typedef enum {
    ACT_PRESS        = 0,
    ACT_RELEASE      = 1,
    ACT_DOUBLE_PRESS = 2,
    ACT_LONG_PRESS   = 3,
    ACT_CHORD_TRIGGER = 4,
} activator_trigger_t;

typedef struct {
    activator_trigger_t trigger;
    uint16_t source_key;       // input key_id that triggers this
    uint8_t  output_key;       // HID keycode to emit
    uint16_t threshold_ms;     // for long_press / double_press timing window
    uint16_t flags;            // reserved (used as secondary key_id for ACT_CHORD_TRIGGER)
    // Runtime state
    int64_t  last_press_ms;
    int64_t  last_release_ms;
    uint8_t  press_count;
    bool     waiting_double;   // waiting to see if another press arrives
    bool     long_fired;       // long_press already emitted
    bool     output_active;    // output currently pressed?
} activator_t;

static activator_t s_activators[MAX_ACTIVATORS];
static size_t s_activator_count = 0;

// --- On-controller profile switching ---
static int s_active_slot = 0;

// --- Chord (combo) system ---

#define MAX_CHORDS 8
#define MAX_CHORD_KEYS 4

typedef struct {
    uint16_t keys[MAX_CHORD_KEYS];
    uint8_t key_count;
    map_entry_t action;
    bool active;  // Is this chord currently firing?
} chord_t;

static chord_t s_chords[MAX_CHORDS];
static size_t s_chord_count = 0;
static bool s_key_pressed[INPUT_KEY_ID_MAX];
static bool s_chord_suppressed[INPUT_KEY_ID_MAX];

static void free_profile(void) {
    // Drain any pending macro requests first — prevents use-after-free
    // when the macro task executes a stale request after steps are freed.
    if (s_macro_q) {
        xQueueReset(s_macro_q);
    }

    // Clean up double-tap timers.
    for (size_t i = 0; i < s_dt_count; i++) {
        if (s_dt_trackers[i].timer) {
            esp_timer_stop(s_dt_trackers[i].timer);
            esp_timer_delete(s_dt_trackers[i].timer);
        }
    }
    memset(s_dt_trackers, 0, sizeof(s_dt_trackers));
    s_dt_count = 0;

    // Clean up turbo timers.
    for (size_t i = 0; i < s_turbo_count; i++) {
        if (s_turbo_trackers[i].timer) {
            esp_timer_stop(s_turbo_trackers[i].timer);
            esp_timer_delete(s_turbo_trackers[i].timer);
        }
    }
    memset(s_turbo_trackers, 0, sizeof(s_turbo_trackers));
    s_turbo_count = 0;

    // Clean up tap-hold timers.
    for (size_t i = 0; i < s_th_count; i++) {
        if (s_th_trackers[i].timer) {
            esp_timer_stop(s_th_trackers[i].timer);
            esp_timer_delete(s_th_trackers[i].timer);
        }
    }
    memset(s_th_trackers, 0, sizeof(s_th_trackers));
    s_th_count = 0;

    // Clean up one-shot timers.
    for (size_t i = 0; i < s_os_count; i++) {
        if (s_os_trackers[i].timer) {
            esp_timer_stop(s_os_trackers[i].timer);
            // Release any armed one-shot modifier.
            if (s_os_trackers[i].state == OS_ARMED) {
                usb_kbd_set_key(s_os_trackers[i].hid_mod,
                                s_os_trackers[i].hid_keycode, false);
            }
            esp_timer_delete(s_os_trackers[i].timer);
        }
    }
    memset(s_os_trackers, 0, sizeof(s_os_trackers));
    s_os_count = 0;
    s_oneshot_pending_release = false;

    // Release any currently-held sticky modifiers before clearing state,
    // otherwise the USB HID report retains phantom key presses.
    for (int i = 0; i < INPUT_KEY_ID_MAX; i++) {
        if (s_sticky_state[i] && s_map[i].mode == MAP_STICKY_MOD) {
            usb_kbd_set_key(s_map[i].sticky_hid_mod,
                            s_map[i].sticky_hid_keycode, false);
        }
    }

    // Reset sticky, chord, and key-pressed state.
    memset(s_sticky_state, 0, sizeof(s_sticky_state));
    memset(s_chords, 0, sizeof(s_chords));
    s_chord_count = 0;
    memset(s_key_pressed, 0, sizeof(s_key_pressed));
    memset(s_chord_suppressed, 0, sizeof(s_chord_suppressed));

    // Clean up auto-shift timers.
    for (size_t i = 0; i < s_as_count; i++) {
        if (s_as_trackers[i].timer) {
            esp_timer_stop(s_as_trackers[i].timer);
            esp_timer_delete(s_as_trackers[i].timer);
        }
    }
    memset(s_as_trackers, 0, sizeof(s_as_trackers));
    s_as_count = 0;

    // Reset sequential state.
    memset(s_seq_index, 0, sizeof(s_seq_index));

    // Reset leader state.
    s_leader_active = false;
    s_leader_buf_len = 0;
    memset(s_leader_seqs, 0, sizeof(s_leader_seqs));
    s_leader_seq_count = 0;
    if (s_leader_timer) {
        esp_timer_stop(s_leader_timer);
    }

    // Reset stick mode and sprint zone.
    s_right_stick_mode = STICK_MODE_KEYS;
    s_mouse_sensitivity = 10;
    s_sniper_active = false;
    s_sniper_sensitivity = 3;
    s_base_sensitivity = 10;
    s_dpi_preset_count = 5;
    s_dpi_preset_index = 1;
    s_dpi_presets[0] = 5; s_dpi_presets[1] = 10; s_dpi_presets[2] = 20;
    s_dpi_presets[3] = 30; s_dpi_presets[4] = 50;
    s_sprint_zone_enabled = false;
    s_sprint_zone_threshold = 90;
    s_sprint_key_mod = 0;
    s_sprint_key_keycode = 0;
    if (s_sprint_active) {
        usb_kbd_set_key(s_sprint_key_mod, s_sprint_key_keycode, false);
        s_sprint_active = false;
    }

    // Reset gyro-to-mouse config.
    s_gyro_enabled = false;
    s_gyro_sens_x = 100;
    s_gyro_sens_y = 100;
    s_gyro_deadzone = 50;
    s_gyro_accel = GYRO_ACCEL_NONE;
    s_gyro_accel_param = 150;
    s_gyro_invert_x = false;
    s_gyro_invert_y = false;

    // Reset flick stick.
    s_flick_stick_enabled = false;
    s_flick_stick_threshold = 3000;
    s_flick_snap_degrees = 0;
    s_flick_active = false;
    s_flick_last_angle = 0.0f;

    // Reset stick acceleration curve.
    s_stick_accel = STICK_ACCEL_LINEAR;
    s_stick_accel_param = 200;

    // Reset zones — release any active zone keys first.
    for (size_t i = 0; i < s_zone_count; i++) {
        if (s_zones[i].active && s_zones[i].output_key != 0) {
            usb_kbd_set_key(0, s_zones[i].output_key, false);
        }
    }
    memset(s_zones, 0, sizeof(s_zones));
    s_zone_count = 0;

    // Reset activators — release any active outputs first.
    for (size_t i = 0; i < s_activator_count; i++) {
        if (s_activators[i].output_active && s_activators[i].output_key != 0) {
            usb_kbd_set_key(0, s_activators[i].output_key, false);
        }
    }
    memset(s_activators, 0, sizeof(s_activators));
    s_activator_count = 0;

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
        // - input ids map to output base id (0..127) via modulo
        //   (supports device_id*128 + base_key_id)
        s_map[i].remap_to = (uint8_t)(i % 128);
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

    if (strcmp(type->valuestring, "mouse_button") == 0) {
        cJSON *btn = cJSON_GetObjectItemCaseSensitive(step_obj, "button");
        cJSON *pressed = cJSON_GetObjectItemCaseSensitive(step_obj, "pressed");
        if (!cJSON_IsNumber(btn) || btn->valueint < 1 || btn->valueint > 31) return false;
        if (!cJSON_IsBool(pressed)) return false;

        out_step->type = STEP_MOUSE_BUTTON;
        out_step->u.mouse.button = (uint8_t)btn->valueint;
        out_step->u.mouse.pressed = cJSON_IsTrue(pressed);
        return true;
    }

    if (strcmp(type->valuestring, "mouse_move") == 0) {
        cJSON *dx_j = cJSON_GetObjectItemCaseSensitive(step_obj, "dx");
        cJSON *dy_j = cJSON_GetObjectItemCaseSensitive(step_obj, "dy");
        if (!cJSON_IsNumber(dx_j) || !cJSON_IsNumber(dy_j)) return false;
        int dxv = dx_j->valueint;
        int dyv = dy_j->valueint;
        if (dxv < -127 || dxv > 127 || dyv < -127 || dyv > 127) return false;

        out_step->type = STEP_MOUSE_MOVE;
        out_step->u.mouse_move.dx = (int8_t)dxv;
        out_step->u.mouse_move.dy = (int8_t)dyv;
        return true;
    }

    if (strcmp(type->valuestring, "macro_chain") == 0) {
        cJSON *id = cJSON_GetObjectItemCaseSensitive(step_obj, "id");
        if (!cJSON_IsString(id) || !id->valuestring) return false;
        // Resolve macro id to index (deferred — filled in after macros are parsed).
        // Store id temporarily in type-punned key_id; resolved in a second pass.
        out_step->type = STEP_MACRO_CHAIN;
        out_step->u.chain.macro_index = -1;
        // Store the id string length + content in the key_id field temporarily.
        // We'll resolve this after all macros are loaded — see parse_macros().
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

    // Second pass: resolve STEP_MACRO_CHAIN references now that all macros
    // are indexed. Walk the JSON again paired with parsed macros.
    size_t mi = 0;
    cJSON_ArrayForEach(macro_obj, macros) {
        if (!cJSON_IsObject(macro_obj)) continue;
        if (mi >= s_macro_count) break;

        cJSON *steps = cJSON_GetObjectItemCaseSensitive(macro_obj, "steps");
        if (!cJSON_IsArray(steps)) { mi++; continue; }

        size_t si = 0;
        cJSON *step_obj;
        cJSON_ArrayForEach(step_obj, steps) {
            if (si >= s_macros[mi].step_count) break;
            if (s_macros[mi].steps[si].type == STEP_MACRO_CHAIN) {
                cJSON *type = cJSON_GetObjectItemCaseSensitive(step_obj, "type");
                if (cJSON_IsString(type) && type->valuestring &&
                    strcmp(type->valuestring, "macro_chain") == 0) {
                    cJSON *chain_id = cJSON_GetObjectItemCaseSensitive(step_obj, "id");
                    if (cJSON_IsString(chain_id) && chain_id->valuestring) {
                        int8_t idx = find_macro_index(chain_id->valuestring);
                        s_macros[mi].steps[si].u.chain.macro_index = idx;
                        if (idx < 0) {
                            ESP_LOGW(TAG, "Macro chain target '%s' not found",
                                     chain_id->valuestring);
                        }
                    }
                }
            }
            si++;
        }
        mi++;
    }
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
            register_dt_tracker((uint16_t)key_id);
            continue;
        }

        if (strcmp(type->valuestring, "turbo") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            cJSON *delay_j = cJSON_GetObjectItemCaseSensitive(entry, "delay_ms");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            s_map[key_id].mode = MAP_TURBO;
            s_map[key_id].turbo_hid_mod = (uint8_t)mod_j->valueint;
            s_map[key_id].turbo_hid_keycode = (uint8_t)kc_j->valueint;
            s_map[key_id].turbo_delay_ms = 50;
            if (cJSON_IsNumber(delay_j) && delay_j->valueint >= 10 && delay_j->valueint <= 500) {
                s_map[key_id].turbo_delay_ms = (uint16_t)delay_j->valueint;
            }
            register_turbo_tracker((uint16_t)key_id);
            continue;
        }

        if (strcmp(type->valuestring, "sticky") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            s_map[key_id].mode = MAP_STICKY_MOD;
            s_map[key_id].sticky_hid_mod = (uint8_t)mod_j->valueint;
            s_map[key_id].sticky_hid_keycode = (uint8_t)kc_j->valueint;
            continue;
        }

        if (strcmp(type->valuestring, "tap_hold") == 0) {
            cJSON *tap_j = cJSON_GetObjectItemCaseSensitive(entry, "tap");
            cJSON *hold_j = cJSON_GetObjectItemCaseSensitive(entry, "hold");
            cJSON *hold_ms_j = cJSON_GetObjectItemCaseSensitive(entry, "hold_ms");
            if (!cJSON_IsObject(tap_j) || !cJSON_IsObject(hold_j)) continue;

            // Resolve tap action to HID mod+keycode.
            uint8_t tap_mod = 0, tap_kc = 0;
            cJSON *tap_type = cJSON_GetObjectItemCaseSensitive(tap_j, "type");
            if (cJSON_IsString(tap_type) && tap_type->valuestring) {
                if (strcmp(tap_type->valuestring, "remap_hid") == 0) {
                    cJSON *m = cJSON_GetObjectItemCaseSensitive(tap_j, "mod");
                    cJSON *k = cJSON_GetObjectItemCaseSensitive(tap_j, "keycode");
                    if (cJSON_IsNumber(m)) tap_mod = (uint8_t)m->valueint;
                    if (cJSON_IsNumber(k)) tap_kc = (uint8_t)k->valueint;
                } else if (strcmp(tap_type->valuestring, "passthrough") == 0) {
                    uint8_t base = (uint8_t)(key_id % 128);
                    keymap_lookup(base, &tap_mod, &tap_kc);
                } else if (strcmp(tap_type->valuestring, "remap") == 0) {
                    cJSON *to = cJSON_GetObjectItemCaseSensitive(tap_j, "to");
                    if (cJSON_IsNumber(to) && to->valueint >= 0 && to->valueint <= 127) {
                        keymap_lookup((uint8_t)to->valueint, &tap_mod, &tap_kc);
                    }
                }
            }

            // Resolve hold action to HID mod+keycode.
            uint8_t hold_mod = 0, hold_kc = 0;
            cJSON *hold_type = cJSON_GetObjectItemCaseSensitive(hold_j, "type");
            if (cJSON_IsString(hold_type) && hold_type->valuestring) {
                if (strcmp(hold_type->valuestring, "remap_hid") == 0) {
                    cJSON *m = cJSON_GetObjectItemCaseSensitive(hold_j, "mod");
                    cJSON *k = cJSON_GetObjectItemCaseSensitive(hold_j, "keycode");
                    if (cJSON_IsNumber(m)) hold_mod = (uint8_t)m->valueint;
                    if (cJSON_IsNumber(k)) hold_kc = (uint8_t)k->valueint;
                } else if (strcmp(hold_type->valuestring, "passthrough") == 0) {
                    uint8_t base = (uint8_t)(key_id % 128);
                    keymap_lookup(base, &hold_mod, &hold_kc);
                } else if (strcmp(hold_type->valuestring, "remap") == 0) {
                    cJSON *to = cJSON_GetObjectItemCaseSensitive(hold_j, "to");
                    if (cJSON_IsNumber(to) && to->valueint >= 0 && to->valueint <= 127) {
                        keymap_lookup((uint8_t)to->valueint, &hold_mod, &hold_kc);
                    }
                }
            }

            s_map[key_id].mode = MAP_TAP_HOLD;
            s_map[key_id].th_tap_hid_mod = tap_mod;
            s_map[key_id].th_tap_hid_keycode = tap_kc;
            s_map[key_id].th_hold_hid_mod = hold_mod;
            s_map[key_id].th_hold_hid_keycode = hold_kc;
            s_map[key_id].th_hold_ms = 300;
            if (cJSON_IsNumber(hold_ms_j) && hold_ms_j->valueint >= 50 && hold_ms_j->valueint <= 2000) {
                s_map[key_id].th_hold_ms = (uint16_t)hold_ms_j->valueint;
            }
            register_th_tracker((uint16_t)key_id);
            continue;
        }

        if (strcmp(type->valuestring, "oneshot") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            s_map[key_id].mode = MAP_ONESHOT_MOD;
            s_map[key_id].os_hid_mod = (uint8_t)mod_j->valueint;
            s_map[key_id].os_hid_keycode = (uint8_t)kc_j->valueint;
            register_os_tracker((uint16_t)key_id);
            continue;
        }

        if (strcmp(type->valuestring, "auto_shift") == 0) {
            cJSON *normal_j = cJSON_GetObjectItemCaseSensitive(entry, "normal");
            cJSON *shifted_j = cJSON_GetObjectItemCaseSensitive(entry, "shifted");
            cJSON *hold_ms_j = cJSON_GetObjectItemCaseSensitive(entry, "hold_ms");
            if (!cJSON_IsObject(normal_j) || !cJSON_IsObject(shifted_j)) continue;
            cJSON *nm = cJSON_GetObjectItemCaseSensitive(normal_j, "mod");
            cJSON *nk = cJSON_GetObjectItemCaseSensitive(normal_j, "keycode");
            cJSON *sm = cJSON_GetObjectItemCaseSensitive(shifted_j, "mod");
            cJSON *sk = cJSON_GetObjectItemCaseSensitive(shifted_j, "keycode");
            if (!cJSON_IsNumber(nm) || !cJSON_IsNumber(nk)) continue;
            if (!cJSON_IsNumber(sm) || !cJSON_IsNumber(sk)) continue;
            s_map[key_id].mode = MAP_AUTO_SHIFT;
            s_map[key_id].as_normal_mod = (uint8_t)nm->valueint;
            s_map[key_id].as_normal_keycode = (uint8_t)nk->valueint;
            s_map[key_id].as_shifted_mod = (uint8_t)sm->valueint;
            s_map[key_id].as_shifted_keycode = (uint8_t)sk->valueint;
            s_map[key_id].as_hold_ms = 200;
            if (cJSON_IsNumber(hold_ms_j) && hold_ms_j->valueint >= 50 && hold_ms_j->valueint <= 1000) {
                s_map[key_id].as_hold_ms = (uint16_t)hold_ms_j->valueint;
            }
            register_as_tracker((uint16_t)key_id);
            continue;
        }

        if (strcmp(type->valuestring, "mouse_button") == 0) {
            cJSON *btn_j = cJSON_GetObjectItemCaseSensitive(entry, "button");
            if (!cJSON_IsNumber(btn_j)) continue;
            s_map[key_id].mode = MAP_MOUSE_BUTTON;
            s_map[key_id].mouse_button = (uint8_t)btn_j->valueint;
            continue;
        }

        if (strcmp(type->valuestring, "gamepad_button") == 0) {
            cJSON *btn_j = cJSON_GetObjectItemCaseSensitive(entry, "button");
            uint8_t output = parse_gamepad_button_code(btn_j);
            if (output == 0) continue;
            s_map[key_id].mode = MAP_GAMEPAD_BUTTON;
            s_map[key_id].gamepad_button = output;
            continue;
        }

        if (strcmp(type->valuestring, "sequential") == 0) {
            cJSON *outputs = cJSON_GetObjectItemCaseSensitive(entry, "outputs");
            if (!cJSON_IsArray(outputs)) continue;
            int cnt = cJSON_GetArraySize(outputs);
            if (cnt < 1 || cnt > 8) continue;
            s_map[key_id].mode = MAP_SEQUENTIAL;
            s_map[key_id].seq_count = (uint8_t)cnt;
            int idx = 0;
            cJSON *item;
            cJSON_ArrayForEach(item, outputs) {
                if (idx >= 8) break;
                if (!cJSON_IsObject(item)) { idx++; continue; }
                cJSON *m_j = cJSON_GetObjectItemCaseSensitive(item, "mod");
                cJSON *k_j = cJSON_GetObjectItemCaseSensitive(item, "keycode");
                s_map[key_id].seq_mods[idx] = cJSON_IsNumber(m_j) ? (uint8_t)m_j->valueint : 0;
                s_map[key_id].seq_keycodes[idx] = cJSON_IsNumber(k_j) ? (uint8_t)k_j->valueint : 0;
                idx++;
            }
            continue;
        }

        if (strcmp(type->valuestring, "leader") == 0) {
            s_map[key_id].mode = MAP_LEADER;
            continue;
        }

        if (strcmp(type->valuestring, "profile_switch") == 0) {
            cJSON *slot_j = cJSON_GetObjectItemCaseSensitive(entry, "slot");
            if (!cJSON_IsNumber(slot_j) || slot_j->valueint < 0 || slot_j->valueint >= PROFILE_MAX_SLOTS) continue;
            s_map[key_id].mode = MAP_PROFILE_SWITCH;
            s_map[key_id].profile_slot = (uint8_t)slot_j->valueint;
            continue;
        }

        if (strcmp(type->valuestring, "sniper") == 0) {
            cJSON *sens_j = cJSON_GetObjectItemCaseSensitive(entry, "sensitivity");
            s_map[key_id].mode = MAP_SNIPER;
            s_map[key_id].sniper_sensitivity = 3;  // default
            if (cJSON_IsNumber(sens_j) && sens_j->valueint >= 1 && sens_j->valueint <= 50) {
                s_map[key_id].sniper_sensitivity = (uint16_t)sens_j->valueint;
            }
            continue;
        }

        if (strcmp(type->valuestring, "dpi_cycle") == 0) {
            s_map[key_id].mode = MAP_DPI_CYCLE;
            continue;
        }

        ESP_LOGW(TAG, "Unknown mapping type '%s' for key %d", type->valuestring, key_id);
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
        ov->key_id = (uint16_t)key_id;
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
            register_dt_tracker((uint16_t)key_id);
        } else if (strcmp(type->valuestring, "turbo") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            cJSON *delay_j = cJSON_GetObjectItemCaseSensitive(entry, "delay_ms");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            ov->entry.mode = MAP_TURBO;
            ov->entry.turbo_hid_mod = (uint8_t)mod_j->valueint;
            ov->entry.turbo_hid_keycode = (uint8_t)kc_j->valueint;
            ov->entry.turbo_delay_ms = 50;
            if (cJSON_IsNumber(delay_j) && delay_j->valueint >= 10 && delay_j->valueint <= 500) {
                ov->entry.turbo_delay_ms = (uint16_t)delay_j->valueint;
            }
            register_turbo_tracker((uint16_t)key_id);
        } else if (strcmp(type->valuestring, "sticky") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            ov->entry.mode = MAP_STICKY_MOD;
            ov->entry.sticky_hid_mod = (uint8_t)mod_j->valueint;
            ov->entry.sticky_hid_keycode = (uint8_t)kc_j->valueint;
        } else if (strcmp(type->valuestring, "tap_hold") == 0) {
            cJSON *tap_j = cJSON_GetObjectItemCaseSensitive(entry, "tap");
            cJSON *hold_j = cJSON_GetObjectItemCaseSensitive(entry, "hold");
            cJSON *hold_ms_j = cJSON_GetObjectItemCaseSensitive(entry, "hold_ms");
            if (!cJSON_IsObject(tap_j) || !cJSON_IsObject(hold_j)) continue;
            uint8_t tap_mod = 0, tap_kc = 0;
            cJSON *tap_type = cJSON_GetObjectItemCaseSensitive(tap_j, "type");
            if (cJSON_IsString(tap_type) && tap_type->valuestring) {
                if (strcmp(tap_type->valuestring, "remap_hid") == 0) {
                    cJSON *m = cJSON_GetObjectItemCaseSensitive(tap_j, "mod");
                    cJSON *k = cJSON_GetObjectItemCaseSensitive(tap_j, "keycode");
                    if (cJSON_IsNumber(m)) tap_mod = (uint8_t)m->valueint;
                    if (cJSON_IsNumber(k)) tap_kc = (uint8_t)k->valueint;
                } else if (strcmp(tap_type->valuestring, "passthrough") == 0) {
                    uint8_t base = (uint8_t)(key_id % 128);
                    keymap_lookup(base, &tap_mod, &tap_kc);
                } else if (strcmp(tap_type->valuestring, "remap") == 0) {
                    cJSON *to = cJSON_GetObjectItemCaseSensitive(tap_j, "to");
                    if (cJSON_IsNumber(to) && to->valueint >= 0 && to->valueint <= 127)
                        keymap_lookup((uint8_t)to->valueint, &tap_mod, &tap_kc);
                }
            }
            uint8_t hold_mod = 0, hold_kc = 0;
            cJSON *hold_type = cJSON_GetObjectItemCaseSensitive(hold_j, "type");
            if (cJSON_IsString(hold_type) && hold_type->valuestring) {
                if (strcmp(hold_type->valuestring, "remap_hid") == 0) {
                    cJSON *m = cJSON_GetObjectItemCaseSensitive(hold_j, "mod");
                    cJSON *k = cJSON_GetObjectItemCaseSensitive(hold_j, "keycode");
                    if (cJSON_IsNumber(m)) hold_mod = (uint8_t)m->valueint;
                    if (cJSON_IsNumber(k)) hold_kc = (uint8_t)k->valueint;
                } else if (strcmp(hold_type->valuestring, "passthrough") == 0) {
                    uint8_t base = (uint8_t)(key_id % 128);
                    keymap_lookup(base, &hold_mod, &hold_kc);
                } else if (strcmp(hold_type->valuestring, "remap") == 0) {
                    cJSON *to = cJSON_GetObjectItemCaseSensitive(hold_j, "to");
                    if (cJSON_IsNumber(to) && to->valueint >= 0 && to->valueint <= 127)
                        keymap_lookup((uint8_t)to->valueint, &hold_mod, &hold_kc);
                }
            }
            ov->entry.mode = MAP_TAP_HOLD;
            ov->entry.th_tap_hid_mod = tap_mod;
            ov->entry.th_tap_hid_keycode = tap_kc;
            ov->entry.th_hold_hid_mod = hold_mod;
            ov->entry.th_hold_hid_keycode = hold_kc;
            ov->entry.th_hold_ms = 300;
            if (cJSON_IsNumber(hold_ms_j) && hold_ms_j->valueint >= 50 && hold_ms_j->valueint <= 2000) {
                ov->entry.th_hold_ms = (uint16_t)hold_ms_j->valueint;
            }
            register_th_tracker((uint16_t)key_id);
        } else if (strcmp(type->valuestring, "oneshot") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(entry, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(entry, "keycode");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            ov->entry.mode = MAP_ONESHOT_MOD;
            ov->entry.os_hid_mod = (uint8_t)mod_j->valueint;
            ov->entry.os_hid_keycode = (uint8_t)kc_j->valueint;
            register_os_tracker((uint16_t)key_id);
        } else if (strcmp(type->valuestring, "profile_switch") == 0) {
            cJSON *slot_j = cJSON_GetObjectItemCaseSensitive(entry, "slot");
            if (!cJSON_IsNumber(slot_j) || slot_j->valueint < 0 || slot_j->valueint >= 4) continue;
            ov->entry.mode = MAP_PROFILE_SWITCH;
            ov->entry.profile_slot = (uint8_t)slot_j->valueint;
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
        if (key_id_j->valueint < 0 || key_id_j->valueint >= INPUT_KEY_ID_MAX) continue;

        layer_t *l = &s_layers[count];
        memset(l, 0, sizeof(*l));
        // Initialize override_index to -1 (no override).
        memset(l->override_index, -1, sizeof(l->override_index));

        if (cJSON_IsString(name) && name->valuestring) {
            strncpy(l->name, name->valuestring, sizeof(l->name) - 1);
        } else {
            snprintf(l->name, sizeof(l->name), "layer%u", (unsigned)count);
        }

        l->activation_key_id = (uint16_t)key_id_j->valueint;
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

static void parse_chords(cJSON *root) {
    cJSON *chords = cJSON_GetObjectItemCaseSensitive(root, "chords");
    if (!cJSON_IsArray(chords)) return;

    size_t count = 0;
    cJSON *chord_obj;
    cJSON_ArrayForEach(chord_obj, chords) {
        if (!cJSON_IsObject(chord_obj)) continue;
        if (count >= MAX_CHORDS) break;

        cJSON *keys = cJSON_GetObjectItemCaseSensitive(chord_obj, "keys");
        cJSON *action = cJSON_GetObjectItemCaseSensitive(chord_obj, "action");
        if (!cJSON_IsArray(keys) || !cJSON_IsObject(action)) continue;

        chord_t *c = &s_chords[count];
        memset(c, 0, sizeof(*c));

        int kc = 0;
        cJSON *k;
        cJSON_ArrayForEach(k, keys) {
            if (kc >= MAX_CHORD_KEYS) break;
            if (!cJSON_IsNumber(k)) continue;
            if (k->valueint < 0 || k->valueint >= INPUT_KEY_ID_MAX) continue;
            c->keys[kc++] = (uint16_t)k->valueint;
        }
        if (kc < 2) continue;  // Need at least 2 keys for a chord.
        c->key_count = (uint8_t)kc;

        // Parse chord action (support common mapping types).
        cJSON *type = cJSON_GetObjectItemCaseSensitive(action, "type");
        if (!cJSON_IsString(type) || !type->valuestring) continue;

        c->action.mode = MAP_PASSTHROUGH;
        c->action.macro_index = -1;

        if (strcmp(type->valuestring, "remap_hid") == 0) {
            cJSON *mod_j = cJSON_GetObjectItemCaseSensitive(action, "mod");
            cJSON *kc_j = cJSON_GetObjectItemCaseSensitive(action, "keycode");
            if (!cJSON_IsNumber(mod_j) || !cJSON_IsNumber(kc_j)) continue;
            c->action.mode = MAP_REMAP_HID;
            c->action.hid_mod = (uint8_t)mod_j->valueint;
            c->action.hid_keycode = (uint8_t)kc_j->valueint;
        } else if (strcmp(type->valuestring, "remap") == 0) {
            cJSON *to = cJSON_GetObjectItemCaseSensitive(action, "to");
            if (!cJSON_IsNumber(to) || to->valueint < 0 || to->valueint > 127) continue;
            c->action.mode = MAP_REMAP;
            c->action.remap_to = (uint8_t)to->valueint;
        } else if (strcmp(type->valuestring, "macro") == 0) {
            cJSON *id = cJSON_GetObjectItemCaseSensitive(action, "id");
            if (!cJSON_IsString(id) || !id->valuestring) continue;
            int8_t idx = find_macro_index(id->valuestring);
            if (idx < 0) continue;
            c->action.mode = MAP_MACRO;
            c->action.macro_index = idx;
        } else if (strcmp(type->valuestring, "disable") == 0) {
            c->action.mode = MAP_DISABLED;
        } else if (strcmp(type->valuestring, "profile_switch") == 0) {
            cJSON *slot_j = cJSON_GetObjectItemCaseSensitive(action, "slot");
            if (!cJSON_IsNumber(slot_j) || slot_j->valueint < 0 || slot_j->valueint >= PROFILE_MAX_SLOTS) continue;
            c->action.mode = MAP_PROFILE_SWITCH;
            c->action.profile_slot = (uint8_t)slot_j->valueint;
        } else {
            continue;
        }

        c->active = false;
        ESP_LOGI(TAG, "Chord %u: %u keys, action=%d", (unsigned)count,
                 (unsigned)c->key_count, c->action.mode);
        count++;
    }

    s_chord_count = count;
}

static void load_profile_json(const char *json) {
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        ESP_LOGW(TAG, "Profile JSON parse failed; using passthrough");
        return;
    }

    if (!cJSON_IsObject(root)) {
        ESP_LOGW(TAG, "Profile root is not a JSON object; ignoring");
        cJSON_Delete(root);
        return;
    }

    // Minimal schema check: warn (but continue) if no recognised top-level keys
    // are present.  This helps catch completely garbage profiles early.
    static const char *known_keys[] = {
        "ver", "mappings", "macros", "layers", "chords",
        "leader_sequences", "right_stick_mode", "mouse_sensitivity",
        "sprint_zone", "humanize", "stick", "gyro", "zones", "activators",
        "flick_stick", "stick_accel", NULL
    };
    bool has_any = false;
    for (const char **k = known_keys; *k; k++) {
        if (cJSON_HasObjectItem(root, *k)) { has_any = true; break; }
    }
    if (!has_any) {
        ESP_LOGW(TAG, "Profile has no recognised keys — applying as empty");
    }

    // Optional version field; unknown versions are tolerated.
    cJSON *ver = cJSON_GetObjectItemCaseSensitive(root, "ver");
    if (cJSON_IsNumber(ver)) {
        ESP_LOGI(TAG, "Profile ver=%d", ver->valueint);
    }

    parse_macros(root);
    parse_mappings(root);
    parse_layers(root);
    parse_chords(root);

    // --- Parse leader sequences ---
    cJSON *leader_j = cJSON_GetObjectItemCaseSensitive(root, "leader_sequences");
    if (cJSON_IsArray(leader_j)) {
        size_t lcount = 0;
        cJSON *ls_obj;
        cJSON_ArrayForEach(ls_obj, leader_j) {
            if (!cJSON_IsObject(ls_obj)) continue;
            if (lcount >= MAX_LEADER_SEQS) break;

            cJSON *keys_j = cJSON_GetObjectItemCaseSensitive(ls_obj, "keys");
            cJSON *action_j = cJSON_GetObjectItemCaseSensitive(ls_obj, "action");
            if (!cJSON_IsArray(keys_j) || !cJSON_IsObject(action_j)) continue;

            leader_seq_t *ls = &s_leader_seqs[lcount];
            memset(ls, 0, sizeof(*ls));

            int kc = 0;
            cJSON *k;
            cJSON_ArrayForEach(k, keys_j) {
                if (kc >= MAX_LEADER_SEQ_LEN) break;
                if (!cJSON_IsNumber(k)) continue;
                if (k->valueint < 0 || k->valueint >= INPUT_KEY_ID_MAX) continue;
                ls->keys[kc++] = (uint16_t)k->valueint;
            }
            if (kc < 1) continue;
            ls->key_count = (uint8_t)kc;

            cJSON *am = cJSON_GetObjectItemCaseSensitive(action_j, "mod");
            cJSON *ak = cJSON_GetObjectItemCaseSensitive(action_j, "keycode");
            if (cJSON_IsNumber(am)) ls->action_mod = (uint8_t)am->valueint;
            if (cJSON_IsNumber(ak)) ls->action_keycode = (uint8_t)ak->valueint;

            lcount++;
        }
        s_leader_seq_count = lcount;
        ESP_LOGI(TAG, "Loaded %u leader sequences", (unsigned)lcount);
    }

    // --- Parse right stick mode ---
    cJSON *rstick_j = cJSON_GetObjectItemCaseSensitive(root, "right_stick_mode");
    if (cJSON_IsString(rstick_j) && rstick_j->valuestring) {
        if (strcmp(rstick_j->valuestring, "mouse") == 0) {
            s_right_stick_mode = STICK_MODE_MOUSE;
        } else if (strcmp(rstick_j->valuestring, "scroll") == 0) {
            s_right_stick_mode = STICK_MODE_SCROLL;
        } else {
            s_right_stick_mode = STICK_MODE_KEYS;
        }
        ESP_LOGI(TAG, "Right stick mode: %s", rstick_j->valuestring);
    }

    // --- Parse mouse sensitivity ---
    cJSON *sens_j = cJSON_GetObjectItemCaseSensitive(root, "mouse_sensitivity");
    if (cJSON_IsNumber(sens_j)) {
        int v = sens_j->valueint;
        if (v < 1) v = 1;
        if (v > 50) v = 50;
        s_mouse_sensitivity = (uint16_t)v;
        s_base_sensitivity = s_mouse_sensitivity;
    }

    // --- Parse DPI presets ---
    cJSON *dpi_j = cJSON_GetObjectItemCaseSensitive(root, "dpi_presets");
    if (cJSON_IsArray(dpi_j)) {
        int cnt = cJSON_GetArraySize(dpi_j);
        if (cnt > DPI_PRESET_MAX) cnt = DPI_PRESET_MAX;
        int valid = 0;
        cJSON *item;
        cJSON_ArrayForEach(item, dpi_j) {
            if (valid >= cnt) break;
            if (!cJSON_IsNumber(item)) continue;
            int v = item->valueint;
            if (v < 1) v = 1;
            if (v > 50) v = 50;
            s_dpi_presets[valid++] = (uint16_t)v;
        }
        if (valid > 0) {
            s_dpi_preset_count = (uint8_t)valid;
            // Find index of current sensitivity in presets.
            s_dpi_preset_index = 0;
            for (int i = 0; i < valid; i++) {
                if (s_dpi_presets[i] == s_mouse_sensitivity) {
                    s_dpi_preset_index = (uint8_t)i;
                    break;
                }
            }
            ESP_LOGI(TAG, "DPI presets: %u entries, active index %u", valid, s_dpi_preset_index);
        }
    }

    // --- Parse sprint zone ---
    cJSON *sprint_j = cJSON_GetObjectItemCaseSensitive(root, "sprint_zone");
    if (cJSON_IsObject(sprint_j)) {
        cJSON *enabled_j = cJSON_GetObjectItemCaseSensitive(sprint_j, "enabled");
        cJSON *threshold_j = cJSON_GetObjectItemCaseSensitive(sprint_j, "threshold");
        cJSON *key_j = cJSON_GetObjectItemCaseSensitive(sprint_j, "key");

        s_sprint_zone_enabled = cJSON_IsTrue(enabled_j);
        if (cJSON_IsNumber(threshold_j) && threshold_j->valueint >= 10 && threshold_j->valueint <= 100) {
            s_sprint_zone_threshold = (uint8_t)threshold_j->valueint;
        }
        if (cJSON_IsObject(key_j)) {
            cJSON *km = cJSON_GetObjectItemCaseSensitive(key_j, "mod");
            cJSON *kk = cJSON_GetObjectItemCaseSensitive(key_j, "keycode");
            if (cJSON_IsNumber(km)) s_sprint_key_mod = (uint8_t)km->valueint;
            if (cJSON_IsNumber(kk)) s_sprint_key_keycode = (uint8_t)kk->valueint;
        }
        ESP_LOGI(TAG, "Sprint zone: enabled=%d threshold=%u%%",
                 s_sprint_zone_enabled, (unsigned)s_sprint_zone_threshold);
    }

    // Optional humanize flag (default true).
    cJSON *humanize_j = cJSON_GetObjectItemCaseSensitive(root, "humanize");
    if (cJSON_IsBool(humanize_j)) {
        s_humanize = cJSON_IsTrue(humanize_j);
    } else {
        s_humanize = true;  // default on
    }

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

        // Forward SOCD mode if present in stick settings.
        cJSON *socd_j = cJSON_GetObjectItemCaseSensitive(stick, "socd_mode");
        if (cJSON_IsString(socd_j) && socd_j->valuestring) {
            uint8_t socd = 0;
            if (strcmp(socd_j->valuestring, "last_input") == 0) socd = 1;
            else if (strcmp(socd_j->valuestring, "first_input") == 0) socd = 2;
            uart_proto_send_ctrl(0x07, &socd, 1);
            ESP_LOGI(TAG, "Forwarded SOCD mode=%u to ESP32", socd);
        }

        // Forward rapid trigger thresholds if present.
        cJSON *rt_j = cJSON_GetObjectItemCaseSensitive(stick, "rapid_trigger");
        if (cJSON_IsObject(rt_j)) {
            cJSON *act_j = cJSON_GetObjectItemCaseSensitive(rt_j, "activation");
            cJSON *deact_j = cJSON_GetObjectItemCaseSensitive(rt_j, "deactivation");
            uint8_t act = 30, deact = 20;
            if (cJSON_IsNumber(act_j)) act = (uint8_t)act_j->valueint;
            if (cJSON_IsNumber(deact_j)) deact = (uint8_t)deact_j->valueint;
            if (act < 1) act = 1;
            if (deact > act) deact = act;
            uint8_t rt_payload[2] = {act, deact};
            uart_proto_send_ctrl(0x08, rt_payload, 2);
            ESP_LOGI(TAG, "Forwarded rapid trigger act=%u deact=%u to ESP32", act, deact);
        }
    }

    // --- Gyro-to-mouse configuration ---
    cJSON *gyro = cJSON_GetObjectItemCaseSensitive(root, "gyro");
    if (cJSON_IsObject(gyro)) {
        cJSON *en = cJSON_GetObjectItemCaseSensitive(gyro, "enabled");
        if (cJSON_IsBool(en)) {
            s_gyro_enabled = cJSON_IsTrue(en);
        }
        cJSON *sx_j = cJSON_GetObjectItemCaseSensitive(gyro, "sensitivity_x");
        if (cJSON_IsNumber(sx_j)) {
            s_gyro_sens_x = (uint16_t)sx_j->valueint;
        }
        cJSON *sy_j = cJSON_GetObjectItemCaseSensitive(gyro, "sensitivity_y");
        if (cJSON_IsNumber(sy_j)) {
            s_gyro_sens_y = (uint16_t)sy_j->valueint;
        }
        cJSON *dz_j = cJSON_GetObjectItemCaseSensitive(gyro, "deadzone");
        if (cJSON_IsNumber(dz_j)) {
            s_gyro_deadzone = (uint16_t)dz_j->valueint;
        }
        cJSON *at_j = cJSON_GetObjectItemCaseSensitive(gyro, "accel_type");
        if (cJSON_IsNumber(at_j)) {
            int v = at_j->valueint;
            if (v >= 0 && v <= 2) s_gyro_accel = (gyro_accel_t)v;
        }
        cJSON *ap_j = cJSON_GetObjectItemCaseSensitive(gyro, "accel_param");
        if (cJSON_IsNumber(ap_j)) {
            s_gyro_accel_param = (uint16_t)ap_j->valueint;
        }
        cJSON *ix_j = cJSON_GetObjectItemCaseSensitive(gyro, "invert_x");
        if (cJSON_IsBool(ix_j)) {
            s_gyro_invert_x = cJSON_IsTrue(ix_j);
        }
        cJSON *iy_j = cJSON_GetObjectItemCaseSensitive(gyro, "invert_y");
        if (cJSON_IsBool(iy_j)) {
            s_gyro_invert_y = cJSON_IsTrue(iy_j);
        }
        ESP_LOGI(TAG, "Gyro: en=%d sens=%u/%u dz=%u accel=%d param=%u inv=%d/%d",
                 s_gyro_enabled, s_gyro_sens_x, s_gyro_sens_y, s_gyro_deadzone,
                 s_gyro_accel, s_gyro_accel_param, s_gyro_invert_x, s_gyro_invert_y);
    }

    // --- Flick stick configuration ---
    cJSON *flick = cJSON_GetObjectItemCaseSensitive(root, "flick_stick");
    if (cJSON_IsObject(flick)) {
        cJSON *fen = cJSON_GetObjectItemCaseSensitive(flick, "enabled");
        if (cJSON_IsBool(fen)) {
            s_flick_stick_enabled = cJSON_IsTrue(fen);
        }
        cJSON *fth = cJSON_GetObjectItemCaseSensitive(flick, "threshold");
        if (cJSON_IsNumber(fth)) {
            s_flick_stick_threshold = (uint16_t)fth->valueint;
        }
        cJSON *fsnap = cJSON_GetObjectItemCaseSensitive(flick, "snap_degrees");
        if (cJSON_IsNumber(fsnap)) {
            s_flick_snap_degrees = (uint16_t)fsnap->valueint;
        }
        ESP_LOGI(TAG, "Flick stick: en=%d threshold=%u snap=%u",
                 s_flick_stick_enabled, s_flick_stick_threshold, s_flick_snap_degrees);
    }

    // --- Stick acceleration curve ---
    cJSON *saccel = cJSON_GetObjectItemCaseSensitive(root, "stick_accel");
    if (cJSON_IsObject(saccel)) {
        cJSON *st_j = cJSON_GetObjectItemCaseSensitive(saccel, "type");
        if (cJSON_IsNumber(st_j)) {
            int v = st_j->valueint;
            if (v >= 0 && v <= 2) s_stick_accel = (stick_accel_t)v;
        }
        cJSON *sp_j = cJSON_GetObjectItemCaseSensitive(saccel, "param");
        if (cJSON_IsNumber(sp_j)) {
            s_stick_accel_param = (uint16_t)sp_j->valueint;
        }
        ESP_LOGI(TAG, "Stick accel: type=%d param=%u", s_stick_accel, s_stick_accel_param);
    }

    // --- Parse zones ---
    cJSON *zones_arr = cJSON_GetObjectItemCaseSensitive(root, "zones");
    if (cJSON_IsArray(zones_arr)) {
        int zcount = cJSON_GetArraySize(zones_arr);
        if (zcount > MAX_ZONES) zcount = MAX_ZONES;
        for (int i = 0; i < zcount; i++) {
            cJSON *zj = cJSON_GetArrayItem(zones_arr, i);
            if (!cJSON_IsObject(zj)) continue;

            zone_t *z = &s_zones[s_zone_count];
            memset(z, 0, sizeof(*z));

            cJSON *shape_j = cJSON_GetObjectItemCaseSensitive(zj, "shape");
            if (cJSON_IsString(shape_j) && shape_j->valuestring) {
                if (strcmp(shape_j->valuestring, "ring") == 0) z->shape = ZONE_SHAPE_RING;
                else if (strcmp(shape_j->valuestring, "wedge") == 0) z->shape = ZONE_SHAPE_WEDGE;
                else if (strcmp(shape_j->valuestring, "rect") == 0) z->shape = ZONE_SHAPE_RECT;
                else z->shape = ZONE_SHAPE_CIRCLE;
            } else if (cJSON_IsNumber(shape_j)) {
                z->shape = (zone_shape_t)shape_j->valueint;
            }

            cJSON *cx_j = cJSON_GetObjectItemCaseSensitive(zj, "cx");
            if (cJSON_IsNumber(cx_j)) z->cx = (int16_t)cx_j->valueint;
            cJSON *cy_j = cJSON_GetObjectItemCaseSensitive(zj, "cy");
            if (cJSON_IsNumber(cy_j)) z->cy = (int16_t)cy_j->valueint;
            cJSON *p1 = cJSON_GetObjectItemCaseSensitive(zj, "param1");
            if (cJSON_IsNumber(p1)) z->param1 = (uint16_t)p1->valueint;
            cJSON *p2 = cJSON_GetObjectItemCaseSensitive(zj, "param2");
            if (cJSON_IsNumber(p2)) z->param2 = (uint16_t)p2->valueint;
            cJSON *p3 = cJSON_GetObjectItemCaseSensitive(zj, "param3");
            if (cJSON_IsNumber(p3)) z->param3 = (uint16_t)p3->valueint;
            cJSON *p4 = cJSON_GetObjectItemCaseSensitive(zj, "param4");
            if (cJSON_IsNumber(p4)) z->param4 = (uint16_t)p4->valueint;
            cJSON *as_j = cJSON_GetObjectItemCaseSensitive(zj, "angle_start");
            if (cJSON_IsNumber(as_j)) z->angle_start = (int16_t)as_j->valueint;
            cJSON *ae_j = cJSON_GetObjectItemCaseSensitive(zj, "angle_end");
            if (cJSON_IsNumber(ae_j)) z->angle_end = (int16_t)ae_j->valueint;
            cJSON *ok_j = cJSON_GetObjectItemCaseSensitive(zj, "output_key");
            if (cJSON_IsNumber(ok_j)) z->output_key = (uint8_t)ok_j->valueint;

            // Also accept "radius" shorthand for circle zones
            cJSON *r_j = cJSON_GetObjectItemCaseSensitive(zj, "radius");
            if (cJSON_IsNumber(r_j) && z->shape == ZONE_SHAPE_CIRCLE) {
                z->param1 = (uint16_t)r_j->valueint;
            }

            s_zone_count++;
        }
        ESP_LOGI(TAG, "Loaded %u zones", (unsigned)s_zone_count);
    }

    // --- Parse activators ---
    cJSON *acts_arr = cJSON_GetObjectItemCaseSensitive(root, "activators");
    if (cJSON_IsArray(acts_arr)) {
        int acount = cJSON_GetArraySize(acts_arr);
        if (acount > MAX_ACTIVATORS) acount = MAX_ACTIVATORS;
        for (int i = 0; i < acount; i++) {
            cJSON *aj = cJSON_GetArrayItem(acts_arr, i);
            if (!cJSON_IsObject(aj)) continue;

            activator_t *a = &s_activators[s_activator_count];
            memset(a, 0, sizeof(*a));

            cJSON *trig_j = cJSON_GetObjectItemCaseSensitive(aj, "trigger");
            if (cJSON_IsString(trig_j) && trig_j->valuestring) {
                if (strcmp(trig_j->valuestring, "release") == 0) a->trigger = ACT_RELEASE;
                else if (strcmp(trig_j->valuestring, "double_press") == 0) a->trigger = ACT_DOUBLE_PRESS;
                else if (strcmp(trig_j->valuestring, "long_press") == 0) a->trigger = ACT_LONG_PRESS;
                else if (strcmp(trig_j->valuestring, "chord") == 0) a->trigger = ACT_CHORD_TRIGGER;
                else a->trigger = ACT_PRESS;
            } else if (cJSON_IsNumber(trig_j)) {
                a->trigger = (activator_trigger_t)trig_j->valueint;
            }

            cJSON *sk_j = cJSON_GetObjectItemCaseSensitive(aj, "source_key");
            if (cJSON_IsNumber(sk_j) && sk_j->valueint >= 0 && sk_j->valueint < INPUT_KEY_ID_MAX) {
                a->source_key = (uint16_t)sk_j->valueint;
            }
            cJSON *ok_j = cJSON_GetObjectItemCaseSensitive(aj, "output_key");
            if (cJSON_IsNumber(ok_j)) a->output_key = (uint8_t)ok_j->valueint;
            cJSON *tm_j = cJSON_GetObjectItemCaseSensitive(aj, "threshold_ms");
            if (cJSON_IsNumber(tm_j)) a->threshold_ms = (uint16_t)tm_j->valueint;
            cJSON *fl_j = cJSON_GetObjectItemCaseSensitive(aj, "flags");
            if (cJSON_IsNumber(fl_j) && fl_j->valueint >= 0) a->flags = (uint16_t)fl_j->valueint;

            if (a->threshold_ms == 0) {
                // Defaults
                if (a->trigger == ACT_DOUBLE_PRESS) a->threshold_ms = 300;
                else if (a->trigger == ACT_LONG_PRESS) a->threshold_ms = 500;
            }

            s_activator_count++;
        }
        ESP_LOGI(TAG, "Loaded %u activators", (unsigned)s_activator_count);
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
        const uint32_t macro_total_cap = 5000;
        size_t steps = m->step_count;
        if (steps > PROFILE_MAX_STEPS) steps = PROFILE_MAX_STEPS;

        for (size_t i = 0; i < steps; i++) {
            macro_step_t *st = &m->steps[i];

            if (st->type == STEP_DELAY) {
                uint32_t remaining = (total_ms < macro_total_cap) ? (macro_total_cap - total_ms) : 0;
                uint32_t base = (st->u.delay.ms > remaining) ? remaining : st->u.delay.ms;
                uint32_t actual = humanize_delay(base, 15);
                if (actual > remaining) actual = remaining;
                total_ms += actual;
                if (actual == 0) break;
                vTaskDelay(pdMS_TO_TICKS(actual));
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

            if (st->type == STEP_MOUSE_BUTTON) {
                usb_mouse_button(st->u.mouse.button, st->u.mouse.pressed);
                vTaskDelay(pdMS_TO_TICKS(1));
                continue;
            }

            if (st->type == STEP_MACRO_CHAIN) {
                int8_t chain_idx = st->u.chain.macro_index;
                if (chain_idx >= 0 && (size_t)chain_idx < s_macro_count) {
                    // Enqueue the chained macro and continue.
                    macro_req_t chain_req = {.macro_index = chain_idx};
                    if (xQueueSend(s_macro_q, &chain_req, 0) != pdTRUE) {
                        ESP_LOGW(TAG, "Macro chain queue full, dropped chain to %d", chain_idx);
                    }
                }
                continue;
            }

            if (st->type == STEP_MOUSE_MOVE) {
                usb_mouse_move(st->u.mouse_move.dx, st->u.mouse_move.dy);
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

    s_macro_q = xQueueCreate(8, sizeof(macro_req_t));
    if (!s_macro_q) {
        ESP_LOGE(TAG, "Failed to create macro queue");
        return;
    }

    // Create leader key timeout timer (persistent, reused across profiles).
    if (!s_leader_timer) {
        esp_timer_create_args_t args = {
            .callback = leader_timeout_cb,
            .arg = NULL,
            .name = "leader",
        };
        esp_timer_create(&args, &s_leader_timer);
    }

    xTaskCreate(macro_task, "macro", 4096, NULL, 5, NULL);

    // Restore gyro calibration bias from NVS (if previously calibrated).
    {
        nvs_handle_t h;
        if (nvs_open("gyro_cal", NVS_READONLY, &h) == ESP_OK) {
            int16_t bx = 0, by = 0, bz = 0;
            nvs_get_i16(h, "bx", &bx);
            nvs_get_i16(h, "by", &by);
            nvs_get_i16(h, "bz", &bz);
            nvs_close(h);
            s_gyro_bias_x = bx;
            s_gyro_bias_y = by;
            s_gyro_bias_z = bz;
            ESP_LOGI(TAG, "Restored gyro bias from NVS: (%d,%d,%d)", bx, by, bz);
        }
    }

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

    s_active_slot = slot;

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

static void send_key_id(bool pressed, uint16_t key_id) {
    uint8_t mod = 0;
    uint8_t keycode = 0;
    if (!keymap_lookup(key_id, &mod, &keycode)) {
        return;
    }

    usb_kbd_set_key(mod, keycode, pressed);
}

static map_entry_t *find_layer_override(uint16_t key_id) {
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

static void dispatch_mapping(map_entry_t *m, bool pressed, uint16_t key_id) {
    // One-shot modifier integration: when a non-oneshot key is pressed,
    // consume any armed one-shot modifier. On release, release it.
    if (m->mode != MAP_ONESHOT_MOD && s_os_count > 0) {
        if (pressed) {
            oneshot_apply_if_armed();
        } else {
            oneshot_release_if_pending();
        }
    }

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
                if (xQueueSend(s_macro_q, &req, 0) != pdTRUE) {
                    ESP_LOGW(TAG, "Macro queue full, dropped macro %d", m->macro_index);
                }
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

        case MAP_TURBO: {
            turbo_tracker_t *tt = find_turbo_tracker(key_id);
            if (!tt) {
                // Fallback: simple press/release.
                usb_kbd_set_key(m->turbo_hid_mod, m->turbo_hid_keycode, pressed);
                return;
            }
            if (pressed) {
                tt->active = true;
                tt->key_pressed = true;
                tt->hid_mod = m->turbo_hid_mod;
                tt->hid_keycode = m->turbo_hid_keycode;
                tt->delay_ms = m->turbo_delay_ms;
                usb_kbd_set_key(tt->hid_mod, tt->hid_keycode, true);
                uint32_t first = humanize_delay(m->turbo_delay_ms, 10);
                esp_timer_start_once(tt->timer,
                                     (uint64_t)first * 1000);
            } else {
                tt->active = false;
                esp_timer_stop(tt->timer);
                if (tt->key_pressed) {
                    usb_kbd_set_key(tt->hid_mod, tt->hid_keycode, false);
                    tt->key_pressed = false;
                }
            }
            return;
        }

        case MAP_STICKY_MOD:
            if (pressed) {
                s_sticky_state[key_id] = !s_sticky_state[key_id];
                usb_kbd_set_key(m->sticky_hid_mod, m->sticky_hid_keycode,
                                s_sticky_state[key_id]);
            }
            // Release events are ignored for sticky keys.
            return;

        case MAP_TAP_HOLD: {
            th_tracker_t *th = find_th_tracker(key_id);
            if (!th) {
                // Fallback: fire tap action directly.
                usb_kbd_set_key(m->th_tap_hid_mod, m->th_tap_hid_keycode, pressed);
                return;
            }
            switch (th->state) {
                case TH_IDLE:
                    if (pressed) {
                        th->state = TH_PRESSED;
                        th->tap_hid_mod = m->th_tap_hid_mod;
                        th->tap_hid_keycode = m->th_tap_hid_keycode;
                        th->hold_hid_mod = m->th_hold_hid_mod;
                        th->hold_hid_keycode = m->th_hold_hid_keycode;
                        esp_timer_start_once(th->timer,
                                             (uint64_t)m->th_hold_ms * 1000);
                    }
                    break;
                case TH_PRESSED:
                    if (!pressed) {
                        // Released before hold threshold: fire tap.
                        esp_timer_stop(th->timer);
                        usb_kbd_set_key(th->tap_hid_mod, th->tap_hid_keycode, true);
                        usb_kbd_set_key(th->tap_hid_mod, th->tap_hid_keycode, false);
                        th->state = TH_IDLE;
                    }
                    break;
                case TH_HOLDING:
                    if (!pressed) {
                        // Release hold action.
                        usb_kbd_set_key(th->hold_hid_mod, th->hold_hid_keycode, false);
                        th->state = TH_IDLE;
                    }
                    break;
            }
            return;
        }

        case MAP_ONESHOT_MOD: {
            os_tracker_t *os = find_os_tracker(key_id);
            if (!os) return;
            if (pressed) {
                if (os->state == OS_IDLE) {
                    os->state = OS_ARMED;
                    os->hid_mod = m->os_hid_mod;
                    os->hid_keycode = m->os_hid_keycode;
                    usb_kbd_set_key(os->hid_mod, os->hid_keycode, true);
                    // 3-second timeout to auto-disarm.
                    esp_timer_start_once(os->timer, 3000000);
                }
            }
            // Release of the oneshot key itself is ignored; the modifier
            // stays armed until consumed by another key or timeout.
            return;
        }

        case MAP_AUTO_SHIFT: {
            as_tracker_t *as = find_as_tracker(key_id);
            if (!as) {
                // Fallback: fire normal action directly.
                usb_kbd_set_key(m->as_normal_mod, m->as_normal_keycode, pressed);
                return;
            }
            switch (as->state) {
                case AS_IDLE:
                    if (pressed) {
                        as->state = AS_PRESSED;
                        as->normal_mod = m->as_normal_mod;
                        as->normal_keycode = m->as_normal_keycode;
                        as->shifted_mod = m->as_shifted_mod;
                        as->shifted_keycode = m->as_shifted_keycode;
                        esp_timer_start_once(as->timer,
                                             (uint64_t)m->as_hold_ms * 1000);
                    }
                    break;
                case AS_PRESSED:
                    if (!pressed) {
                        // Released before hold threshold: fire normal tap.
                        esp_timer_stop(as->timer);
                        usb_kbd_set_key(as->normal_mod, as->normal_keycode, true);
                        usb_kbd_set_key(as->normal_mod, as->normal_keycode, false);
                        as->state = AS_IDLE;
                    }
                    break;
                case AS_HOLDING:
                    if (!pressed) {
                        // Release shifted action.
                        usb_kbd_set_key(as->shifted_mod, as->shifted_keycode, false);
                        as->state = AS_IDLE;
                    }
                    break;
            }
            return;
        }

        case MAP_MOUSE_BUTTON:
            usb_mouse_button(m->mouse_button, pressed);
            return;

        case MAP_GAMEPAD_BUTTON:
            usb_gamepad_set_virtual_button(m->gamepad_button, pressed);
            return;

        case MAP_SEQUENTIAL:
            if (pressed && m->seq_count > 0) {
                uint8_t idx = s_seq_index[key_id];
                usb_kbd_set_key(m->seq_mods[idx], m->seq_keycodes[idx], true);
                usb_kbd_set_key(m->seq_mods[idx], m->seq_keycodes[idx], false);
                s_seq_index[key_id] = (uint8_t)((idx + 1) % m->seq_count);
            }
            return;

        case MAP_LEADER:
            if (pressed) {
                s_leader_active = true;
                s_leader_buf_len = 0;
                if (s_leader_timer) {
                    esp_timer_stop(s_leader_timer);
                    esp_timer_start_once(s_leader_timer,
                                         (uint64_t)LEADER_TIMEOUT_MS * 1000);
                }
            }
            return;

        case MAP_PROFILE_SWITCH:
            if (pressed) {
                int slot = (int)m->profile_slot;
                if (slot >= 0 && slot < PROFILE_MAX_SLOTS) {
                    ESP_LOGI(TAG, "Profile switch → slot %d", slot);
                    esp_err_t err = nvs_set_active_slot(slot);
                    if (err == ESP_OK) {
                        s_active_slot = slot;
                        profile_runtime_reload();
                    } else {
                        ESP_LOGW(TAG, "Profile switch NVS write failed: %s",
                                 esp_err_to_name(err));
                    }
                }
            }
            return;

        case MAP_SNIPER:
            if (pressed) {
                s_sniper_active = true;
                s_base_sensitivity = s_mouse_sensitivity;
                s_mouse_sensitivity = m->sniper_sensitivity;
                ESP_LOGI(TAG, "Sniper ON (sens %u → %u)", s_base_sensitivity, s_mouse_sensitivity);
            } else {
                s_sniper_active = false;
                s_mouse_sensitivity = s_base_sensitivity;
                ESP_LOGI(TAG, "Sniper OFF (sens → %u)", s_mouse_sensitivity);
            }
            return;

        case MAP_DPI_CYCLE:
            if (pressed && s_dpi_preset_count > 0) {
                s_dpi_preset_index = (uint8_t)((s_dpi_preset_index + 1) % s_dpi_preset_count);
                s_mouse_sensitivity = s_dpi_presets[s_dpi_preset_index];
                s_base_sensitivity = s_mouse_sensitivity;
                ESP_LOGI(TAG, "DPI cycle → preset %u (sens %u)", s_dpi_preset_index, s_mouse_sensitivity);
            }
            return;

        case MAP_PASSTHROUGH:
        default:
            send_key_id(pressed, m->remap_to);
            return;
    }
}

void profile_runtime_handle_input(bool pressed, uint16_t key_id) {
    if (key_id >= INPUT_KEY_ID_MAX) {
        return;
    }

    // Update global pressed state for chord detection.
    s_key_pressed[key_id] = pressed;

    // --- Leader key buffer interception ---
    // When leader mode is active, buffer key presses and reset the timeout.
    if (s_leader_active && pressed) {
        // Don't buffer the leader key itself again.
        map_entry_t *km = &s_map[key_id];
        if (km->mode != MAP_LEADER) {
            if (s_leader_buf_len < MAX_LEADER_SEQ_LEN) {
                s_leader_buf[s_leader_buf_len++] = key_id;
            }
            // Reset timeout for each key press.
            if (s_leader_timer) {
                esp_timer_stop(s_leader_timer);
                esp_timer_start_once(s_leader_timer,
                                     (uint64_t)LEADER_TIMEOUT_MS * 1000);
            }
            // Check for immediate match (if sequence matches exactly).
            for (size_t i = 0; i < s_leader_seq_count; i++) {
                leader_seq_t *ls = &s_leader_seqs[i];
                if (ls->key_count != s_leader_buf_len) continue;
                bool match = true;
                for (size_t j = 0; j < ls->key_count; j++) {
                    if (ls->keys[j] != s_leader_buf[j]) { match = false; break; }
                }
                if (match) {
                    if (s_leader_timer) esp_timer_stop(s_leader_timer);
                    usb_kbd_set_key(ls->action_mod, ls->action_keycode, true);
                    usb_kbd_set_key(ls->action_mod, ls->action_keycode, false);
                    s_leader_active = false;
                    s_leader_buf_len = 0;
                    return;
                }
            }
            return;  // Consumed by leader buffer.
        }
    }

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

    // --- Chord evaluation (before individual mappings) ---
    if (s_chord_count > 0) {
        for (size_t ci = 0; ci < s_chord_count; ci++) {
            chord_t *c = &s_chords[ci];
            bool is_member = false;
            for (uint8_t ki = 0; ki < c->key_count; ki++) {
                if (c->keys[ki] == key_id) { is_member = true; break; }
            }
            if (!is_member) continue;

            // Check if all chord keys are now pressed.
            bool all_pressed = true;
            for (uint8_t ki = 0; ki < c->key_count; ki++) {
                if (!s_key_pressed[c->keys[ki]]) { all_pressed = false; break; }
            }

            if (all_pressed && !c->active) {
                // Chord just completed. Undo individual actions for keys
                // that were already pressed.
                for (uint8_t ki = 0; ki < c->key_count; ki++) {
                    uint16_t ck = c->keys[ki];
                    if (ck == key_id) continue;  // This key's mapping hasn't fired yet.
                    if (s_chord_suppressed[ck]) continue;
                    map_entry_t *cm = find_layer_override(ck);
                    if (!cm) cm = &s_map[ck];
                    switch (cm->mode) {
                        case MAP_PASSTHROUGH:
                        case MAP_REMAP:
                            send_key_id(false, cm->remap_to);
                            break;
                        case MAP_REMAP_HID:
                            usb_kbd_set_key(cm->hid_mod, cm->hid_keycode, false);
                            break;
                        case MAP_TURBO: {
                            turbo_tracker_t *tt = find_turbo_tracker(ck);
                            if (tt && tt->active) {
                                tt->active = false;
                                esp_timer_stop(tt->timer);
                                if (tt->key_pressed) {
                                    usb_kbd_set_key(tt->hid_mod, tt->hid_keycode, false);
                                    tt->key_pressed = false;
                                }
                            }
                            break;
                        }
                        case MAP_STICKY_MOD:
                            if (s_sticky_state[ck]) {
                                s_sticky_state[ck] = false;
                                usb_kbd_set_key(cm->sticky_hid_mod, cm->sticky_hid_keycode, false);
                            }
                            break;
                        case MAP_TAP_HOLD: {
                            th_tracker_t *th = find_th_tracker(ck);
                            if (th) {
                                if (th->state == TH_PRESSED) {
                                    esp_timer_stop(th->timer);
                                } else if (th->state == TH_HOLDING) {
                                    usb_kbd_set_key(th->hold_hid_mod, th->hold_hid_keycode, false);
                                }
                                th->state = TH_IDLE;
                            }
                            break;
                        }
                        case MAP_DOUBLE_TAP: {
                            dt_tracker_t *dt = find_dt_tracker(ck);
                            if (dt) {
                                if (dt->state == DT_ARMED)
                                    esp_timer_stop(dt->timer);
                                dt->state = DT_IDLE;
                            }
                            break;
                        }
                        default:
                            break;
                    }
                }
                // Suppress all chord keys & fire chord action.
                for (uint8_t ki = 0; ki < c->key_count; ki++) {
                    s_chord_suppressed[c->keys[ki]] = true;
                }
                c->active = true;
                dispatch_mapping(&c->action, true, key_id);
                return;
            }

            if (!all_pressed && c->active) {
                // A chord key was released: deactivate chord.
                c->active = false;
                dispatch_mapping(&c->action, false, key_id);
                // Unsuppress keys no longer part of any active chord.
                for (uint8_t ki = 0; ki < c->key_count; ki++) {
                    uint16_t ck = c->keys[ki];
                    bool still_suppressed = false;
                    for (size_t cj = 0; cj < s_chord_count; cj++) {
                        if (!s_chords[cj].active) continue;
                        for (uint8_t kj = 0; kj < s_chords[cj].key_count; kj++) {
                            if (s_chords[cj].keys[kj] == ck) {
                                still_suppressed = true;
                                break;
                            }
                        }
                        if (still_suppressed) break;
                    }
                    if (!still_suppressed) s_chord_suppressed[ck] = false;
                }
                return;
            }
        }

        // If this key is currently suppressed by an active chord, eat the event.
        if (s_chord_suppressed[key_id]) return;
    }

    // --- Activator evaluation ---
    if (s_activator_count > 0) {
        int64_t now = (int64_t)(esp_timer_get_time() / 1000);  // ms
        for (size_t i = 0; i < s_activator_count; i++) {
            activator_t *a = &s_activators[i];
            if (a->source_key != key_id) continue;

            switch (a->trigger) {
                case ACT_PRESS:
                    if (pressed) {
                        a->output_active = true;
                        usb_kbd_set_key(0, a->output_key, true);
                    } else {
                        if (a->output_active) {
                            a->output_active = false;
                            usb_kbd_set_key(0, a->output_key, false);
                        }
                    }
                    break;

                case ACT_RELEASE:
                    if (!pressed) {
                        // Momentary tap on release
                        usb_kbd_set_key(0, a->output_key, true);
                        usb_kbd_set_key(0, a->output_key, false);
                    }
                    break;

                case ACT_DOUBLE_PRESS:
                    if (pressed) {
                        if (a->waiting_double &&
                            (now - a->last_press_ms) <= (int64_t)a->threshold_ms) {
                            // Double press detected!
                            a->waiting_double = false;
                            a->output_active = true;
                            usb_kbd_set_key(0, a->output_key, true);
                        } else {
                            a->waiting_double = true;
                            a->last_press_ms = now;
                        }
                    } else {
                        if (a->output_active) {
                            a->output_active = false;
                            usb_kbd_set_key(0, a->output_key, false);
                        }
                    }
                    break;

                case ACT_LONG_PRESS:
                    if (pressed) {
                        a->last_press_ms = now;
                        a->long_fired = false;
                    } else {
                        if (a->long_fired && a->output_active) {
                            a->output_active = false;
                            usb_kbd_set_key(0, a->output_key, false);
                        }
                        a->long_fired = false;
                    }
                    break;

                case ACT_CHORD_TRIGGER:
                    // Chord activators: fire when source_key is pressed
                    // AND another key (stored in flags as key_id) is also pressed.
                    if (pressed && a->flags < INPUT_KEY_ID_MAX && s_key_pressed[a->flags]) {
                        a->output_active = true;
                        usb_kbd_set_key(0, a->output_key, true);
                    } else if (!pressed && a->output_active) {
                        a->output_active = false;
                        usb_kbd_set_key(0, a->output_key, false);
                    }
                    break;
            }
        }

        // Long-press check: evaluate held keys against activators.
        // (Called on every input event — checks elapsed time since press.)
        for (size_t i = 0; i < s_activator_count; i++) {
            activator_t *a = &s_activators[i];
            if (a->trigger != ACT_LONG_PRESS) continue;
            if (a->long_fired) continue;
            if (a->source_key >= INPUT_KEY_ID_MAX) continue;
            if (!s_key_pressed[a->source_key]) continue;
            if (a->last_press_ms > 0 &&
                (now - a->last_press_ms) >= (int64_t)a->threshold_ms) {
                a->long_fired = true;
                a->output_active = true;
                usb_kbd_set_key(0, a->output_key, true);
            }
        }
    }

    // Look for a layer override, then fall back to the base mapping.
    map_entry_t *override = find_layer_override(key_id);
    map_entry_t *m = override ? override : &s_map[key_id];

    dispatch_mapping(m, pressed, key_id);
}

void profile_runtime_set_humanize(bool enabled) {
    s_humanize = enabled;
}

bool profile_runtime_get_humanize(void) {
    return s_humanize;
}

void profile_runtime_handle_analog(uint8_t device_id, int16_t x, int16_t y) {
    // device_id encoding from joycon_mapper:
    //   0x00 = left stick
    //   0x80 = right stick (bit 7 set)
    bool is_right = (device_id & 0x80) != 0;

    if (is_right) {
        // --- Right stick: mouse / scroll / keys ---
        switch (s_right_stick_mode) {
            case STICK_MODE_MOUSE: {
                int32_t mag_sq = (int32_t)x * x + (int32_t)y * y;
                int32_t ft = (int32_t)s_flick_stick_threshold;

                if (s_flick_stick_enabled) {
                    // Flick-stick mode: on initial deflection past threshold,
                    // output a large horizontal mouse delta corresponding to
                    // the stick angle (180° flick).  While held, track angle
                    // changes and convert them to horizontal mouse movement
                    // (for camera turning).  On release, reset.
                    if (mag_sq >= ft * ft) {
                        float angle = atan2f((float)y, (float)x);  // radians

                        // Optional snap to nearest N degrees
                        if (s_flick_snap_degrees > 0) {
                            float snap_rad = (float)s_flick_snap_degrees * 3.14159265f / 180.0f;
                            angle = snap_rad * (float)(int)(angle / snap_rad + (angle >= 0 ? 0.5f : -0.5f));
                        }

                        if (!s_flick_active) {
                            // Initial flick: convert stick angle to a camera turn.
                            // Full rightward stick → 0°, upward → +90°, etc.
                            // Map angle to mouse pixels.  A full 180° (π rad)
                            // maps to ~800 px (typical 360° turn at 400 dpi × 10 sens).
                            float flick_px = angle * 800.0f / 3.14159265f;
                            int16_t dx = (int16_t)flick_px;
                            if (dx != 0) usb_mouse_move(dx, 0);

                            s_flick_active = true;
                            s_flick_last_angle = angle;
                        } else {
                            // Sustained hold: track angle delta for smooth turning.
                            float delta = angle - s_flick_last_angle;
                            // Normalize to (-π, π]
                            if (delta > 3.14159265f) delta -= 2.0f * 3.14159265f;
                            else if (delta < -3.14159265f) delta += 2.0f * 3.14159265f;

                            float turn_px = delta * 800.0f / 3.14159265f;
                            int16_t dx = (int16_t)turn_px;
                            if (dx != 0) usb_mouse_move(dx, 0);

                            s_flick_last_angle = angle;
                        }
                    } else {
                        s_flick_active = false;
                    }
                    break;
                }

                // Normal stick-to-mouse with configurable acceleration curve.
                float fx = (float)x;
                float fy = (float)y;
                // Deadzone
                if (fx > -200.0f && fx < 200.0f) fx = 0.0f;
                if (fy > -200.0f && fy < 200.0f) fy = 0.0f;
                if (fx == 0.0f && fy == 0.0f) break;

                // Normalize to 0..1 range
                float nx = fx / 4096.0f;
                float ny = fy / 4096.0f;

                // Apply acceleration curve
                switch (s_stick_accel) {
                    case STICK_ACCEL_POWER: {
                        float mag = sqrtf(nx * nx + ny * ny);
                        if (mag > 0.001f) {
                            float exp_f = (float)s_stick_accel_param / 100.0f;
                            float scale = powf(mag, exp_f - 1.0f);
                            nx *= scale;
                            ny *= scale;
                        }
                        break;
                    }
                    case STICK_ACCEL_SCURVE: {
                        // S-curve: smoothstep-like. Midpoint param controls
                        // transition sharpness.
                        float mag = sqrtf(nx * nx + ny * ny);
                        if (mag > 0.001f) {
                            float clamped = mag;
                            if (clamped > 1.0f) clamped = 1.0f;
                            // Hermite smoothstep: 3t² - 2t³
                            float t = clamped;
                            float smooth = t * t * (3.0f - 2.0f * t);
                            float scale = smooth / mag;
                            nx *= scale;
                            ny *= scale;
                        }
                        break;
                    }
                    default:
                        break;
                }

                int16_t dx = (int16_t)(nx * (float)s_mouse_sensitivity);
                int16_t dy = (int16_t)(ny * (float)s_mouse_sensitivity);
                if (dx != 0 || dy != 0) {
                    usb_mouse_move(dx, dy);
                }
                break;
            }
            case STICK_MODE_SCROLL: {
                // Scroll mode: Y axis → vertical scroll, X axis → horizontal.
                int8_t vs = 0, hs = 0;
                if (y > 1000) vs = -1;
                else if (y < -1000) vs = 1;
                if (x > 1000) hs = 1;
                else if (x < -1000) hs = -1;
                if (vs != 0 || hs != 0) {
                    usb_mouse_scroll(vs, hs);
                }
                break;
            }
            case STICK_MODE_KEYS:
            default:
                // Keys mode: stick-to-key is handled by joycon_mapper
                // on the ESP32 host side (existing behavior).
                break;
        }
    } else {
        // --- Left stick: sprint zone detection ---
        if (s_sprint_zone_enabled) {
            // Calculate stick magnitude (0..4096 range).
            int32_t mag_sq = (int32_t)x * x + (int32_t)y * y;
            int32_t threshold = (int32_t)s_sprint_zone_threshold * 4096 / 100;
            int32_t thresh_sq = threshold * threshold;

            bool should_sprint = (mag_sq > thresh_sq);
            if (should_sprint && !s_sprint_active) {
                s_sprint_active = true;
                usb_kbd_set_key(s_sprint_key_mod, s_sprint_key_keycode, true);
            } else if (!should_sprint && s_sprint_active) {
                s_sprint_active = false;
                usb_kbd_set_key(s_sprint_key_mod, s_sprint_key_keycode, false);
            }
        }
    }

    // --- Evaluate zones (both sticks) ---
    if (s_zone_count > 0) {
        for (size_t i = 0; i < s_zone_count; i++) {
            zone_t *z = &s_zones[i];
            // Offset from zone center
            int32_t dx = (int32_t)x - (int32_t)z->cx;
            int32_t dy = (int32_t)y - (int32_t)z->cy;
            bool inside = false;

            switch (z->shape) {
                case ZONE_SHAPE_CIRCLE: {
                    int32_t dist_sq = dx * dx + dy * dy;
                    int32_t r = (int32_t)z->param1;
                    inside = (dist_sq <= r * r);
                    break;
                }
                case ZONE_SHAPE_RING: {
                    int32_t dist_sq = dx * dx + dy * dy;
                    int32_t inner = (int32_t)z->param1;
                    int32_t outer = (int32_t)z->param2;
                    inside = (dist_sq >= inner * inner && dist_sq <= outer * outer);
                    break;
                }
                case ZONE_SHAPE_WEDGE: {
                    // Wedge: check angle and distance
                    int32_t dist_sq = dx * dx + dy * dy;
                    int32_t outer = (int32_t)z->param1;
                    if (outer > 0 && dist_sq <= outer * outer) {
                        // Compute angle in degrees (-180..+180)
                        float angle = atan2f((float)dy, (float)dx) * 180.0f / 3.14159265f;
                        float start = (float)z->angle_start;
                        float end = (float)z->angle_end;
                        // Normalize: handle wrapping
                        if (start <= end) {
                            inside = (angle >= start && angle <= end);
                        } else {
                            inside = (angle >= start || angle <= end);
                        }
                    }
                    break;
                }
                case ZONE_SHAPE_RECT: {
                    int32_t hw = (int32_t)z->param1 / 2;
                    int32_t hh = (int32_t)z->param2 / 2;
                    inside = (dx >= -hw && dx <= hw && dy >= -hh && dy <= hh);
                    break;
                }
            }

            if (inside && !z->active) {
                z->active = true;
                if (z->output_key != 0) {
                    usb_kbd_set_key(0, z->output_key, true);
                }
            } else if (!inside && z->active) {
                z->active = false;
                if (z->output_key != 0) {
                    usb_kbd_set_key(0, z->output_key, false);
                }
            }
        }
    }
}

void profile_runtime_handle_gyro(uint8_t device_id, int16_t gx, int16_t gy, int16_t gz) {
    (void)device_id;  // Currently same config for both Joy-Cons

    // If calibration is active, accumulate samples.
    if (s_cal_active) {
        s_cal_sum_x += gx;
        s_cal_sum_y += gy;
        s_cal_sum_z += gz;
        s_cal_count++;
        if (s_cal_count >= GYRO_CAL_SAMPLES) {
            s_gyro_bias_x = (int16_t)(s_cal_sum_x / GYRO_CAL_SAMPLES);
            s_gyro_bias_y = (int16_t)(s_cal_sum_y / GYRO_CAL_SAMPLES);
            s_gyro_bias_z = (int16_t)(s_cal_sum_z / GYRO_CAL_SAMPLES);
            s_cal_active = false;
            ESP_LOGI(TAG, "Gyro calibration done: bias=(%d,%d,%d)",
                     s_gyro_bias_x, s_gyro_bias_y, s_gyro_bias_z);

            // Persist to NVS
            nvs_handle_t h;
            if (nvs_open("gyro_cal", NVS_READWRITE, &h) == ESP_OK) {
                nvs_set_i16(h, "bx", s_gyro_bias_x);
                nvs_set_i16(h, "by", s_gyro_bias_y);
                nvs_set_i16(h, "bz", s_gyro_bias_z);
                nvs_commit(h);
                nvs_close(h);
            }
        }
        return;  // Don't process gyro input during calibration
    }

    // Apply calibration bias
    gx -= s_gyro_bias_x;
    gy -= s_gyro_bias_y;
    gz -= s_gyro_bias_z;

    if (!s_gyro_enabled) return;

    // Apply deadzone: zero out axes below threshold
    float fx = (float)gx;
    float fy = (float)gy;
    float dz = (float)s_gyro_deadzone;

    if (fabsf(fx) < dz) fx = 0.0f;
    if (fabsf(fy) < dz) fy = 0.0f;

    if (fx == 0.0f && fy == 0.0f) return;

    // Apply sensitivity (÷100 so 100 = 1.0× multiplier)
    float sx = fx * (float)s_gyro_sens_x / 100.0f;
    float sy = fy * (float)s_gyro_sens_y / 100.0f;

    // Apply acceleration curve
    switch (s_gyro_accel) {
        case GYRO_ACCEL_POWER: {
            float mag = sqrtf(sx * sx + sy * sy);
            if (mag > 0.01f) {
                float exp_f = (float)s_gyro_accel_param / 100.0f;
                float scale = powf(mag, exp_f - 1.0f);
                sx *= scale;
                sy *= scale;
            }
            break;
        }
        case GYRO_ACCEL_SMOOTH: {
            float mag = sqrtf(sx * sx + sy * sy);
            float threshold = (float)s_gyro_accel_param;
            if (mag > threshold && threshold > 0.01f) {
                float excess = mag - threshold;
                float scale = 1.0f + (excess / threshold);
                sx *= scale;
                sy *= scale;
            }
            break;
        }
        default:
            break;
    }

    // Apply inversion
    if (s_gyro_invert_x) sx = -sx;
    if (s_gyro_invert_y) sy = -sy;

    // Scale to mouse pixel deltas.
    int16_t dx = (int16_t)(sx * 0.02f);
    int16_t dy = (int16_t)(sy * 0.02f);

    if (dx != 0 || dy != 0) {
        usb_mouse_move(dx, dy);
    }
}

// -----------------------------------------------------------------
// Gyro calibration API
// -----------------------------------------------------------------

bool profile_runtime_start_gyro_cal(void) {
    if (s_cal_active) return false;
    s_cal_active = true;
    s_cal_count = 0;
    s_cal_sum_x = 0;
    s_cal_sum_y = 0;
    s_cal_sum_z = 0;
    ESP_LOGI(TAG, "Gyro calibration started (%d samples)", GYRO_CAL_SAMPLES);
    return true;
}

bool profile_runtime_gyro_cal_active(void) {
    return s_cal_active;
}

void profile_runtime_get_gyro_bias(int16_t *bx, int16_t *by, int16_t *bz) {
    if (bx) *bx = s_gyro_bias_x;
    if (by) *by = s_gyro_bias_y;
    if (bz) *bz = s_gyro_bias_z;
}

void profile_runtime_set_gyro_bias(int16_t bx, int16_t by, int16_t bz) {
    s_gyro_bias_x = bx;
    s_gyro_bias_y = by;
    s_gyro_bias_z = bz;
    ESP_LOGI(TAG, "Gyro bias set to (%d,%d,%d)", bx, by, bz);
}

// -----------------------------------------------------------------
// LED pattern control — sends command to ESP32 host via UART ctrl
// -----------------------------------------------------------------

void profile_runtime_set_led(uint8_t pattern, uint8_t r, uint8_t g, uint8_t b, uint16_t speed) {
    // UART control command 0x0A: LED pattern
    // payload: [pattern, r, g, b, speed_lo, speed_hi]
    uint8_t payload[6] = {
        pattern, r, g, b,
        (uint8_t)(speed & 0xFF),
        (uint8_t)((speed >> 8) & 0xFF)
    };
    uart_proto_send_ctrl(0x0A, payload, 6);
    ESP_LOGI(TAG, "LED pattern=%u rgb=(%u,%u,%u) speed=%u", pattern, r, g, b, speed);
}
