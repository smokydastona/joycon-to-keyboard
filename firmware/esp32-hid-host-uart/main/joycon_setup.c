// Joy-Con setup FSM — sends subcommands after BT connect to:
//   1. Request device info (controller type, firmware version)
//   2. Read serial number from SPI flash
//   3. Read controller colors from SPI flash
//   4. Read factory stick calibration from SPI flash
//   5. Read user stick calibration from SPI flash
//   6. Read stick device parameters (deadzone) from SPI flash
//   7. Read factory IMU calibration from SPI flash
//   8. Read user IMU calibration from SPI flash
//   9. Set input report mode to 0x30 (full report with IMU)
//  10. Enable IMU
//  11. Enable vibration (HD Rumble)
//  12. Set player LEDs
//
// Inspired by bluepad32's uni_hid_parser_switch.c (Apache-2.0) and
// dekuNukem/Nintendo_Switch_Reverse_Engineering.
// All techniques are anti-cheat safe: they only affect the ESP32 BT host
// side. The PC still sees a real USB HID keyboard from the ESP32-S3.

#include "joycon_setup.h"

#include <string.h>
#include <math.h>
#include "esp_log.h"
#include "esp_hidh_api.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "uart_framing.h"

static const char *TAG = "joycon-setup";

// Mutex protecting all esp_bt_hid_host_send_data() calls.
// The FSM task (send_subcmd) and external callers (rumble, home LED)
// can race on the BT stack; this serialises them.
static SemaphoreHandle_t s_bt_send_mux;

// --- Subcommand IDs (publicly documented) ---
#define SUBCMD_REQ_DEV_INFO        0x02
#define SUBCMD_SET_REPORT_MODE     0x03
#define SUBCMD_SPI_FLASH_READ      0x10
#define SUBCMD_SET_PLAYER_LEDS     0x30
#define SUBCMD_SET_HOME_LED        0x38
#define SUBCMD_ENABLE_IMU          0x40
#define SUBCMD_SET_IMU_SENS        0x41
#define SUBCMD_ENABLE_VIBRATION    0x48

// Output report types
#define OUTPUT_RUMBLE_AND_SUBCMD   0x01
#define OUTPUT_RUMBLE_ONLY         0x10

// Input report types
#define INPUT_SUBCMD_REPLY  0x21
#define INPUT_IMU_DATA      0x30
#define INPUT_BUTTON_EVENT  0x3F

// SPI flash addresses for stick calibration
#define SPI_FACTORY_STICK_CAL_LEFT   0x603D
#define SPI_FACTORY_STICK_CAL_RIGHT  0x6046
#define SPI_USER_STICK_CAL_LEFT      0x8010
#define SPI_USER_STICK_CAL_RIGHT     0x801D
#define SPI_USER_STICK_CAL_MAGIC_0   0xB2
#define SPI_USER_STICK_CAL_MAGIC_1   0xA1
#define SPI_STICK_CAL_DATA_SIZE      9   // 9 bytes per stick

// SPI flash addresses for serial number
#define SPI_SERIAL_NUMBER       0x6000
#define SPI_SERIAL_NUMBER_SIZE  16   // 15 ASCII chars + padding

// SPI flash addresses for controller colors
#define SPI_BODY_COLOR          0x6050
#define SPI_BODY_COLOR_SIZE     6    // body_rgb(3) + button_rgb(3)

// SPI flash addresses for stick device parameters (deadzone, range)
#define SPI_STICK_PARAMS        0x6086
#define SPI_STICK_PARAMS_SIZE   18   // 18 bytes = two sticks

// SPI flash addresses for IMU calibration
#define SPI_FACTORY_IMU_CAL     0x6020
#define SPI_FACTORY_IMU_CAL_SIZE 24  // 12 Int16LE values
#define SPI_USER_IMU_CAL        0x8026
#define SPI_USER_IMU_CAL_SIZE   26   // 2 magic + 12 Int16LE values

// Setup FSM timeout: if we don't get a reply, advance anyway
#define SETUP_TIMEOUT_MS  1500

// FSM states
typedef enum {
    SETUP_IDLE = 0,
    SETUP_REQ_DEV_INFO,
    SETUP_READ_SERIAL,
    SETUP_READ_COLORS,
    SETUP_READ_FACTORY_STICK_CAL,
    SETUP_READ_USER_STICK_CAL,
    SETUP_READ_STICK_PARAMS,
    SETUP_READ_FACTORY_IMU_CAL,
    SETUP_READ_USER_IMU_CAL,
    SETUP_SET_REPORT_MODE,
    SETUP_ENABLE_IMU,
    SETUP_ENABLE_VIBRATION,
    SETUP_SET_LEDS,
    SETUP_READY,
} setup_state_t;

// Per-device instance data
typedef struct {
    setup_state_t state;
    uint16_t handle;
    uint8_t device_id;
    uint8_t packet_num;

    // Device info
    joycon_controller_type_t controller_type;
    uint8_t fw_version_hi;
    uint8_t fw_version_lo;
    bool has_colors;  // byte[11] of dev_info reply == 0x01

    // Serial number
    char serial[16];  // Up to 15 chars + NUL
    bool serial_valid;

    // Controller colors
    joycon_colors_t colors;

    // Stick calibration
    joycon_stick_cal_t stick_cal;

    // Stick device parameters (deadzone)
    joycon_stick_params_t stick_params;

    // IMU calibration
    joycon_imu_cal_t imu_cal;

    // Battery (0-4, or -1)
    int battery;

    // Timeout tracking
    int64_t last_send_us;
} setup_instance_t;

static setup_instance_t s_inst[2] = {0};

// --- Internal helpers ---

static setup_instance_t *get_inst(uint8_t device_id) {
    if (device_id > 1) device_id = 0;
    return &s_inst[device_id];
}

// Build and send a subcommand request via HID SET_REPORT.
static void send_subcmd(setup_instance_t *inst, uint8_t subcmd_id,
                        const uint8_t *data, uint8_t data_len) {
    // Output report format (publicly documented):
    //   [0] = 0x01 (rumble + subcmd)
    //   [1] = packet_num (0x00-0x0F, incrementing)
    //   [2..5] = rumble left (zeros = no rumble)
    //   [6..9] = rumble right (zeros = no rumble)
    //   [10] = subcmd_id
    //   [11..] = subcmd data
    uint8_t buf[64] = {0};
    buf[0] = OUTPUT_RUMBLE_AND_SUBCMD;
    buf[1] = inst->packet_num;
    inst->packet_num = (inst->packet_num + 1) & 0x0F;
    // bytes 2-9: rumble = 0 (no rumble)
    buf[10] = subcmd_id;
    if (data && data_len > 0) {
        uint8_t copy = (data_len > 53) ? 53 : data_len;
        memcpy(&buf[11], data, copy);
    }

    uint8_t total_len = 11 + (data ? data_len : 0);
    if (total_len < 11) total_len = 11;

    // Use HID host send_data with type OUTPUT.
    xSemaphoreTake(s_bt_send_mux, portMAX_DELAY);
    esp_err_t err = esp_bt_hid_host_send_data(inst->handle,
                                               (uint8_t *)buf, total_len);
    xSemaphoreGive(s_bt_send_mux);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "[%d] send_subcmd 0x%02X failed: %s",
                 inst->device_id, subcmd_id, esp_err_to_name(err));
    } else {
        ESP_LOGI(TAG, "[%d] Sent subcmd 0x%02X (state=%d)",
                 inst->device_id, subcmd_id, inst->state);
    }

    inst->last_send_us = esp_timer_get_time();
}

// Send SPI flash read request.
static void send_spi_read(setup_instance_t *inst, uint32_t addr, uint8_t size) {
    uint8_t data[5];
    data[0] = addr & 0xFF;
    data[1] = (addr >> 8) & 0xFF;
    data[2] = (addr >> 16) & 0xFF;
    data[3] = (addr >> 24) & 0xFF;
    data[4] = size;
    send_subcmd(inst, SUBCMD_SPI_FLASH_READ, data, sizeof(data));
}

// Parse 12-bit packed stick calibration from 9 bytes.
// For left stick: data layout is max_above, center, min_below  (each 3 bytes packed)
// For right stick: data layout is center, min_below, max_above  (each 3 bytes packed)
static void parse_stick_cal(joycon_stick_cal_axis_t *x, joycon_stick_cal_axis_t *y,
                            const uint8_t *data, bool is_left) {
    int32_t cal_x_above, cal_y_above, cal_x_below, cal_y_below;

    if (is_left) {
        // Bytes 0-2: max above center
        cal_x_above = data[0] | ((data[1] & 0x0F) << 8);
        cal_y_above = (data[1] >> 4) | (data[2] << 4);
        // Bytes 3-5: center
        x->center = data[3] | ((data[4] & 0x0F) << 8);
        y->center = (data[4] >> 4) | (data[5] << 4);
        // Bytes 6-8: min below center
        cal_x_below = data[6] | ((data[7] & 0x0F) << 8);
        cal_y_below = (data[7] >> 4) | (data[8] << 4);
    } else {
        // Bytes 0-2: center
        x->center = data[0] | ((data[1] & 0x0F) << 8);
        y->center = (data[1] >> 4) | (data[2] << 4);
        // Bytes 3-5: min below center
        cal_x_below = data[3] | ((data[4] & 0x0F) << 8);
        cal_y_below = (data[4] >> 4) | (data[5] << 4);
        // Bytes 6-8: max above center
        cal_x_above = data[6] | ((data[7] & 0x0F) << 8);
        cal_y_above = (data[7] >> 4) | (data[8] << 4);
    }

    x->max = x->center + cal_x_above;
    x->min = x->center - cal_x_below;
    y->max = y->center + cal_y_above;
    y->min = y->center - cal_y_below;

    // Sanity-check: ensure min < center < max.  If SPI flash contains
    // garbage (0xFFs / corrupt data), fall back to safe defaults.
    if (x->min >= x->center || x->center >= x->max) {
        ESP_LOGW("joycon-setup", "Bad stick cal X (min=%ld center=%ld max=%ld), "
                 "using defaults", (long)x->min, (long)x->center, (long)x->max);
        x->min = 512; x->center = 2048; x->max = 3584;
    }
    if (y->min >= y->center || y->center >= y->max) {
        ESP_LOGW("joycon-setup", "Bad stick cal Y (min=%ld center=%ld max=%ld), "
                 "using defaults", (long)y->min, (long)y->center, (long)y->max);
        y->min = 512; y->center = 2048; y->max = 3584;
    }
}

// --- FSM progression ---

static void fsm_req_dev_info(setup_instance_t *inst) {
    inst->state = SETUP_REQ_DEV_INFO;
    send_subcmd(inst, SUBCMD_REQ_DEV_INFO, NULL, 0);
}

static void fsm_read_serial(setup_instance_t *inst) {
    inst->state = SETUP_READ_SERIAL;
    send_spi_read(inst, SPI_SERIAL_NUMBER, SPI_SERIAL_NUMBER_SIZE);
}

static void fsm_read_colors(setup_instance_t *inst) {
    inst->state = SETUP_READ_COLORS;
    send_spi_read(inst, SPI_BODY_COLOR, SPI_BODY_COLOR_SIZE);
}

static void fsm_read_factory_stick_cal(setup_instance_t *inst) {
    inst->state = SETUP_READ_FACTORY_STICK_CAL;

    // For Pro Controller, read both left+right in one request (18 bytes).
    // For individual Joy-Con, read only the relevant one (9 bytes).
    uint32_t addr;
    uint8_t size;

    if (inst->controller_type == JOYCON_TYPE_RIGHT) {
        addr = SPI_FACTORY_STICK_CAL_RIGHT;
        size = SPI_STICK_CAL_DATA_SIZE;
    } else {
        addr = SPI_FACTORY_STICK_CAL_LEFT;
        // Pro/Left: read left (9 bytes); for Pro we read both (18 bytes)
        size = (inst->controller_type == JOYCON_TYPE_PRO)
                   ? (SPI_STICK_CAL_DATA_SIZE * 2)
                   : SPI_STICK_CAL_DATA_SIZE;
    }

    send_spi_read(inst, addr, size);
}

static void fsm_read_user_stick_cal(setup_instance_t *inst) {
    inst->state = SETUP_READ_USER_STICK_CAL;

    uint32_t addr;
    uint8_t size;

    if (inst->controller_type == JOYCON_TYPE_RIGHT) {
        addr = SPI_USER_STICK_CAL_RIGHT;
        size = 2 + SPI_STICK_CAL_DATA_SIZE;  // 2 magic + 9 cal
    } else {
        addr = SPI_USER_STICK_CAL_LEFT;
        // For Pro: read both (2 magic + 9 left + 2 magic + 9 right = 22 bytes)
        size = (inst->controller_type == JOYCON_TYPE_PRO)
                   ? (2 + SPI_STICK_CAL_DATA_SIZE + 2 + SPI_STICK_CAL_DATA_SIZE)
                   : (uint8_t)(2 + SPI_STICK_CAL_DATA_SIZE);
    }

    send_spi_read(inst, addr, size);
}

static void fsm_set_report_mode(setup_instance_t *inst) {
    inst->state = SETUP_SET_REPORT_MODE;
    uint8_t mode = 0x30;  // Full report with IMU data
    send_subcmd(inst, SUBCMD_SET_REPORT_MODE, &mode, 1);
}

static void fsm_read_stick_params(setup_instance_t *inst) {
    inst->state = SETUP_READ_STICK_PARAMS;
    send_spi_read(inst, SPI_STICK_PARAMS, SPI_STICK_PARAMS_SIZE);
}

static void fsm_read_factory_imu_cal(setup_instance_t *inst) {
    inst->state = SETUP_READ_FACTORY_IMU_CAL;
    send_spi_read(inst, SPI_FACTORY_IMU_CAL, SPI_FACTORY_IMU_CAL_SIZE);
}

static void fsm_read_user_imu_cal(setup_instance_t *inst) {
    inst->state = SETUP_READ_USER_IMU_CAL;
    send_spi_read(inst, SPI_USER_IMU_CAL, SPI_USER_IMU_CAL_SIZE);
}

static void fsm_enable_imu(setup_instance_t *inst) {
    inst->state = SETUP_ENABLE_IMU;
    uint8_t enable = 0x01;
    send_subcmd(inst, SUBCMD_ENABLE_IMU, &enable, 1);
}

static void fsm_enable_vibration(setup_instance_t *inst) {
    inst->state = SETUP_ENABLE_VIBRATION;
    uint8_t enable = 0x01;
    send_subcmd(inst, SUBCMD_ENABLE_VIBRATION, &enable, 1);
}

static void fsm_set_leds(setup_instance_t *inst) {
    inst->state = SETUP_SET_LEDS;
    // LSB nibble: solid LEDs. Player 1 = 0x01, Player 2 = 0x02, etc.
    uint8_t leds = (inst->device_id == 0) ? 0x01 : 0x02;
    send_subcmd(inst, SUBCMD_SET_PLAYER_LEDS, &leds, 1);
}

static void fsm_ready(setup_instance_t *inst) {
    inst->state = SETUP_READY;
    ESP_LOGI(TAG, "[%d] Setup complete! type=%d fw=%d.%d battery=%d serial=%s",
             inst->device_id, inst->controller_type,
             inst->fw_version_hi, inst->fw_version_lo,
             inst->battery, inst->serial_valid ? inst->serial : "(none)");

    if (inst->stick_cal.valid) {
        ESP_LOGI(TAG, "[%d] Stick cal: LX=%d/%d/%d LY=%d/%d/%d RX=%d/%d/%d RY=%d/%d/%d",
                 inst->device_id,
                 (int)inst->stick_cal.lx.min, (int)inst->stick_cal.lx.center, (int)inst->stick_cal.lx.max,
                 (int)inst->stick_cal.ly.min, (int)inst->stick_cal.ly.center, (int)inst->stick_cal.ly.max,
                 (int)inst->stick_cal.rx.min, (int)inst->stick_cal.rx.center, (int)inst->stick_cal.rx.max,
                 (int)inst->stick_cal.ry.min, (int)inst->stick_cal.ry.center, (int)inst->stick_cal.ry.max);
    }

    if (inst->colors.valid) {
        ESP_LOGI(TAG, "[%d] Colors: body=#%02X%02X%02X button=#%02X%02X%02X",
                 inst->device_id,
                 inst->colors.body_r, inst->colors.body_g, inst->colors.body_b,
                 inst->colors.button_r, inst->colors.button_g, inst->colors.button_b);
    }

    if (inst->stick_params.valid) {
        ESP_LOGI(TAG, "[%d] Stick params: deadzone=%u range_ratio=%u",
                 inst->device_id, inst->stick_params.deadzone, inst->stick_params.range_ratio);
    }

    if (inst->imu_cal.valid) {
        ESP_LOGI(TAG, "[%d] IMU cal: acc_orig=[%d,%d,%d] gyro_orig=[%d,%d,%d]",
                 inst->device_id,
                 inst->imu_cal.acc_origin[0], inst->imu_cal.acc_origin[1], inst->imu_cal.acc_origin[2],
                 inst->imu_cal.gyro_origin[0], inst->imu_cal.gyro_origin[1], inst->imu_cal.gyro_origin[2]);
    }

    // Send battery status over UART.
    bridge_send_battery(inst->device_id, (uint8_t)(inst->battery >= 0 ? inst->battery : 0));

    // Send controller info (type, serial, colors, stick params, IMU cal) over UART.
    bridge_send_controller_info(inst->device_id,
                                inst->controller_type,
                                inst->serial_valid ? inst->serial : NULL,
                                inst->colors.valid ? &inst->colors : NULL,
                                inst->stick_params.valid ? &inst->stick_params : NULL,
                                inst->imu_cal.valid ? &inst->imu_cal : NULL);
}

// Advance the FSM to the next state.
static void fsm_next(setup_instance_t *inst) {
    switch (inst->state) {
        case SETUP_IDLE:
            fsm_req_dev_info(inst);
            break;
        case SETUP_REQ_DEV_INFO:
            fsm_read_serial(inst);
            break;
        case SETUP_READ_SERIAL:
            // Only read colors if device info says they're stored
            if (inst->has_colors) {
                fsm_read_colors(inst);
            } else {
                fsm_read_factory_stick_cal(inst);
            }
            break;
        case SETUP_READ_COLORS:
            fsm_read_factory_stick_cal(inst);
            break;
        case SETUP_READ_FACTORY_STICK_CAL:
            fsm_read_user_stick_cal(inst);
            break;
        case SETUP_READ_USER_STICK_CAL:
            fsm_read_stick_params(inst);
            break;
        case SETUP_READ_STICK_PARAMS:
            fsm_read_factory_imu_cal(inst);
            break;
        case SETUP_READ_FACTORY_IMU_CAL:
            fsm_read_user_imu_cal(inst);
            break;
        case SETUP_READ_USER_IMU_CAL:
            fsm_set_report_mode(inst);
            break;
        case SETUP_SET_REPORT_MODE:
            fsm_enable_imu(inst);
            break;
        case SETUP_ENABLE_IMU:
            fsm_enable_vibration(inst);
            break;
        case SETUP_ENABLE_VIBRATION:
            fsm_set_leds(inst);
            break;
        case SETUP_SET_LEDS:
            fsm_ready(inst);
            break;
        case SETUP_READY:
            break;
    }
}

// --- Reply processors ---

static void process_dev_info(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    if (len < 3) {
        ESP_LOGW(TAG, "[%d] Device info too short: %d", inst->device_id, len);
        return;
    }

    inst->fw_version_hi = data[0];
    inst->fw_version_lo = data[1];
    inst->controller_type = (joycon_controller_type_t)data[2];

    // Byte index 4 (0-based) indicates if colors are stored in SPI
    // (dekuNukem docs: reply byte[11] == 0x01 means colors exist;
    //  subcmd reply data starts at byte[14], so data[4] is reply byte[4]
    //  of the subcmd data. Actually the flag is at data offset 4 in the
    //  subcmd data = report byte 18.)
    // For safety, also check data offset 11 which some sources report.
    if (len > 4 && data[4] == 0x01) {
        inst->has_colors = true;
    } else {
        // Conservative: still try to read colors (most controllers have them)
        inst->has_colors = true;
    }

    ESP_LOGI(TAG, "[%d] Device info: type=%d (%s) fw=%d.%d has_colors=%d",
             inst->device_id, inst->controller_type,
             inst->controller_type == JOYCON_TYPE_LEFT ? "JCL" :
             inst->controller_type == JOYCON_TYPE_RIGHT ? "JCR" :
             inst->controller_type == JOYCON_TYPE_PRO ? "Pro" : "???",
             inst->fw_version_hi, inst->fw_version_lo,
             inst->has_colors);
}

static void process_factory_stick_cal(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    // Set default calibration (safe fallback)
    inst->stick_cal.lx.min = inst->stick_cal.ly.min = 512;
    inst->stick_cal.rx.min = inst->stick_cal.ry.min = 512;
    inst->stick_cal.lx.center = inst->stick_cal.ly.center = 2048;
    inst->stick_cal.rx.center = inst->stick_cal.ry.center = 2048;
    inst->stick_cal.lx.max = inst->stick_cal.ly.max = 3583;
    inst->stick_cal.rx.max = inst->stick_cal.ry.max = 3583;

    if (inst->controller_type == JOYCON_TYPE_PRO) {
        if (len < SPI_STICK_CAL_DATA_SIZE * 2) {
            ESP_LOGW(TAG, "[%d] Factory cal too short for Pro: %d", inst->device_id, len);
            inst->stick_cal.valid = true;  // Use defaults
            return;
        }
        parse_stick_cal(&inst->stick_cal.lx, &inst->stick_cal.ly, data, true);
        parse_stick_cal(&inst->stick_cal.rx, &inst->stick_cal.ry, &data[9], false);
    } else {
        if (len < SPI_STICK_CAL_DATA_SIZE) {
            ESP_LOGW(TAG, "[%d] Factory cal too short: %d", inst->device_id, len);
            inst->stick_cal.valid = true;
            return;
        }
        bool is_left = (inst->controller_type == JOYCON_TYPE_LEFT);
        if (is_left) {
            parse_stick_cal(&inst->stick_cal.lx, &inst->stick_cal.ly, data, true);
        } else {
            parse_stick_cal(&inst->stick_cal.rx, &inst->stick_cal.ry, data, false);
        }
    }

    inst->stick_cal.valid = true;

    ESP_LOGI(TAG, "[%d] Factory stick cal loaded", inst->device_id);
}

static void process_user_stick_cal(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    // User calibration overrides factory if magic bytes match.
    if (inst->controller_type == JOYCON_TYPE_PRO) {
        if (len < 2 + SPI_STICK_CAL_DATA_SIZE) return;

        // Left stick user cal
        if (data[0] == SPI_USER_STICK_CAL_MAGIC_0 &&
            data[1] == SPI_USER_STICK_CAL_MAGIC_1) {
            parse_stick_cal(&inst->stick_cal.lx, &inst->stick_cal.ly, &data[2], true);
            ESP_LOGI(TAG, "[%d] User left stick cal applied", inst->device_id);
        }

        // Right stick user cal (offset 11 for Pro: 2 bytes magic + 9 bytes left cal)
        if (len >= 11 + 2 + SPI_STICK_CAL_DATA_SIZE) {
            if (data[11] == SPI_USER_STICK_CAL_MAGIC_0 &&
                data[12] == SPI_USER_STICK_CAL_MAGIC_1) {
                parse_stick_cal(&inst->stick_cal.rx, &inst->stick_cal.ry, &data[13], false);
                ESP_LOGI(TAG, "[%d] User right stick cal applied", inst->device_id);
            }
        }
    } else {
        if (len < 2 + SPI_STICK_CAL_DATA_SIZE) return;

        if (data[0] == SPI_USER_STICK_CAL_MAGIC_0 &&
            data[1] == SPI_USER_STICK_CAL_MAGIC_1) {
            bool is_left = (inst->controller_type == JOYCON_TYPE_LEFT);
            if (is_left) {
                parse_stick_cal(&inst->stick_cal.lx, &inst->stick_cal.ly, &data[2], true);
            } else {
                parse_stick_cal(&inst->stick_cal.rx, &inst->stick_cal.ry, &data[2], false);
            }
            ESP_LOGI(TAG, "[%d] User stick cal applied", inst->device_id);
        }
    }
}

static void process_serial_number(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    // Serial number: up to 15 ASCII chars at SPI 0x6000.
    // If first byte >= 0x80, no serial number is stored.
    if (len == 0 || data[0] >= 0x80) {
        inst->serial_valid = false;
        ESP_LOGI(TAG, "[%d] No serial number in SPI", inst->device_id);
        return;
    }

    uint8_t n = (len > 15) ? 15 : len;
    // Copy only printable ASCII bytes
    uint8_t out = 0;
    for (uint8_t i = 0; i < n; i++) {
        if (data[i] >= 0x20 && data[i] < 0x7F) {
            inst->serial[out++] = (char)data[i];
        } else {
            break;  // Stop at non-printable
        }
    }
    inst->serial[out] = '\0';
    inst->serial_valid = (out > 0);
    ESP_LOGI(TAG, "[%d] Serial number: %s", inst->device_id, inst->serial);
}

static void process_colors(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    // Colors: 6 bytes at SPI 0x6050: body_rgb(3) + button_rgb(3)
    if (len < 6) {
        ESP_LOGW(TAG, "[%d] Color data too short: %d", inst->device_id, len);
        inst->colors.valid = false;
        return;
    }

    inst->colors.body_r = data[0];
    inst->colors.body_g = data[1];
    inst->colors.body_b = data[2];
    inst->colors.button_r = data[3];
    inst->colors.button_g = data[4];
    inst->colors.button_b = data[5];
    inst->colors.valid = true;
    ESP_LOGI(TAG, "[%d] Colors: body=#%02X%02X%02X button=#%02X%02X%02X",
             inst->device_id,
             data[0], data[1], data[2], data[3], data[4], data[5]);
}

static void process_stick_params(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    // Stick device parameters at SPI 0x6086, 18 bytes.
    // Byte layout (12-bit packed):
    //   [0..2]: deadzone and range ratio (left)
    //   Simplified: first 2 bytes encode deadzone as 12-bit value.
    if (len < 6) {
        ESP_LOGW(TAG, "[%d] Stick params too short: %d", inst->device_id, len);
        inst->stick_params.valid = false;
        return;
    }

    // Deadzone: bytes [0..1] lower 12 bits
    inst->stick_params.deadzone = data[0] | ((data[1] & 0x0F) << 8);
    // Range ratio: bytes [1..2] upper 12 bits
    inst->stick_params.range_ratio = (data[1] >> 4) | (data[2] << 4);
    inst->stick_params.valid = true;
    ESP_LOGI(TAG, "[%d] Stick params: deadzone=%u range_ratio=%u",
             inst->device_id, inst->stick_params.deadzone, inst->stick_params.range_ratio);
}

static void process_factory_imu_cal(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    // 24 bytes = 12 Int16LE values: acc_orig(3), acc_sens(3), gyro_orig(3), gyro_sens(3)
    if (len < 24) {
        ESP_LOGW(TAG, "[%d] Factory IMU cal too short: %d", inst->device_id, len);
        return;
    }

    for (int i = 0; i < 3; i++) {
        inst->imu_cal.acc_origin[i] = (int16_t)(data[i * 2] | (data[i * 2 + 1] << 8));
        inst->imu_cal.acc_sens[i]   = (int16_t)(data[6 + i * 2] | (data[6 + i * 2 + 1] << 8));
        inst->imu_cal.gyro_origin[i] = (int16_t)(data[12 + i * 2] | (data[12 + i * 2 + 1] << 8));
        inst->imu_cal.gyro_sens[i]   = (int16_t)(data[18 + i * 2] | (data[18 + i * 2 + 1] << 8));
    }
    inst->imu_cal.valid = true;
    ESP_LOGI(TAG, "[%d] Factory IMU cal loaded", inst->device_id);
}

static void process_user_imu_cal(setup_instance_t *inst, const uint8_t *data, uint8_t len) {
    // 2 magic bytes + 24 bytes of cal data
    if (len < 2) return;

    if (data[0] != SPI_USER_STICK_CAL_MAGIC_0 ||
        data[1] != SPI_USER_STICK_CAL_MAGIC_1) {
        ESP_LOGI(TAG, "[%d] No user IMU cal (magic mismatch)", inst->device_id);
        return;
    }

    if (len < 26) {
        ESP_LOGW(TAG, "[%d] User IMU cal too short: %d", inst->device_id, len);
        return;
    }

    const uint8_t *d = &data[2];
    for (int i = 0; i < 3; i++) {
        inst->imu_cal.acc_origin[i] = (int16_t)(d[i * 2] | (d[i * 2 + 1] << 8));
        inst->imu_cal.acc_sens[i]   = (int16_t)(d[6 + i * 2] | (d[6 + i * 2 + 1] << 8));
        inst->imu_cal.gyro_origin[i] = (int16_t)(d[12 + i * 2] | (d[12 + i * 2 + 1] << 8));
        inst->imu_cal.gyro_sens[i]   = (int16_t)(d[18 + i * 2] | (d[18 + i * 2 + 1] << 8));
    }
    inst->imu_cal.valid = true;
    ESP_LOGI(TAG, "[%d] User IMU cal applied", inst->device_id);
}

static void process_spi_read(setup_instance_t *inst, const uint8_t *subcmd_data, uint8_t len) {
    // subcmd_data format:  [0..3]=address LE, [4]=data_size, [5..]=data
    if (len < 5) return;

    uint8_t data_size = subcmd_data[4];
    const uint8_t *cal_data = &subcmd_data[5];
    uint8_t avail = (len > 5) ? (uint8_t)(len - 5) : 0;
    if (avail < data_size) data_size = avail;

    switch (inst->state) {
        case SETUP_READ_SERIAL:
            process_serial_number(inst, cal_data, data_size);
            break;
        case SETUP_READ_COLORS:
            process_colors(inst, cal_data, data_size);
            break;
        case SETUP_READ_FACTORY_STICK_CAL:
            process_factory_stick_cal(inst, cal_data, data_size);
            break;
        case SETUP_READ_USER_STICK_CAL:
            process_user_stick_cal(inst, cal_data, data_size);
            break;
        case SETUP_READ_STICK_PARAMS:
            process_stick_params(inst, cal_data, data_size);
            break;
        case SETUP_READ_FACTORY_IMU_CAL:
            process_factory_imu_cal(inst, cal_data, data_size);
            break;
        case SETUP_READ_USER_IMU_CAL:
            process_user_imu_cal(inst, cal_data, data_size);
            break;
        default:
            ESP_LOGW(TAG, "[%d] Unexpected SPI read in state %d", inst->device_id, inst->state);
            break;
    }
}

// --- Public API ---

void joycon_setup_start(uint16_t handle, uint8_t device_id) {
    // One-time mutex creation (idempotent — safe if called for both slots).
    if (!s_bt_send_mux) {
        s_bt_send_mux = xSemaphoreCreateMutex();
    }

    setup_instance_t *inst = get_inst(device_id);
    memset(inst, 0, sizeof(*inst));
    inst->handle = handle;
    inst->device_id = device_id;
    inst->battery = -1;
    inst->controller_type = JOYCON_TYPE_PRO;  // Default until we learn otherwise

    ESP_LOGI(TAG, "[%d] Starting setup FSM (handle=%u)", device_id, handle);
    fsm_next(inst);  // IDLE -> REQ_DEV_INFO
}

void joycon_setup_stop(uint8_t device_id) {
    setup_instance_t *inst = get_inst(device_id);
    ESP_LOGI(TAG, "[%d] Setup stopped", device_id);
    inst->state = SETUP_IDLE;
}

bool joycon_setup_on_report(uint8_t device_id, const uint8_t *report, uint16_t len) {
    setup_instance_t *inst = get_inst(device_id);

    if (inst->state == SETUP_IDLE || inst->state == SETUP_READY) {
        return false;  // Not our concern
    }

    // We handle 0x21 (subcmd reply) reports during setup.
    if (len < 2 || report[0] != INPUT_SUBCMD_REPLY) {
        return false;
    }

    // 0x21 report layout:
    //   [0] = 0x21
    //   [1] = timer
    //   [2] = bat_con (battery + connection info)
    //   [3..5] = buttons
    //   [6..8] = left stick
    //   [9..11] = right stick
    //   [12] = ack
    //   [13] = subcmd_id
    //   [14..] = subcmd data
    if (len < 14) {
        ESP_LOGW(TAG, "[%d] 0x21 report too short: %d", device_id, len);
        return true;  // Consumed, but can't parse
    }

    // Parse battery from bat_con
    uint8_t bat_con = report[2];
    int battery = bat_con >> 5;
    if (battery > 4) battery = 4;
    inst->battery = battery;

    uint8_t ack = report[12];
    uint8_t subcmd_id = report[13];

    if ((ack & 0x80) == 0) {
        ESP_LOGW(TAG, "[%d] Subcmd 0x%02X NACK (ack=0x%02X)",
                 device_id, subcmd_id, ack);
        // Still advance the FSM — some controllers NACK certain commands
        // but the overall flow should continue.
    }

    const uint8_t *subcmd_data = (len > 14) ? &report[14] : NULL;
    uint8_t subcmd_len = (len > 14) ? (uint8_t)(len - 14) : 0;

    switch (subcmd_id) {
        case SUBCMD_REQ_DEV_INFO:
            if (inst->state == SETUP_REQ_DEV_INFO) {
                process_dev_info(inst, subcmd_data, subcmd_len);
            }
            break;

        case SUBCMD_SPI_FLASH_READ:
            if (inst->state == SETUP_READ_SERIAL ||
                inst->state == SETUP_READ_COLORS ||
                inst->state == SETUP_READ_FACTORY_STICK_CAL ||
                inst->state == SETUP_READ_USER_STICK_CAL ||
                inst->state == SETUP_READ_STICK_PARAMS ||
                inst->state == SETUP_READ_FACTORY_IMU_CAL ||
                inst->state == SETUP_READ_USER_IMU_CAL) {
                process_spi_read(inst, subcmd_data, subcmd_len);
            }
            break;

        case SUBCMD_SET_REPORT_MODE:
        case SUBCMD_ENABLE_IMU:
        case SUBCMD_ENABLE_VIBRATION:
        case SUBCMD_SET_PLAYER_LEDS:
        case SUBCMD_SET_HOME_LED:
        case SUBCMD_SET_IMU_SENS:
            // Simple ACK — just advance
            break;

        default:
            ESP_LOGD(TAG, "[%d] Unexpected subcmd reply 0x%02X in state %d",
                     device_id, subcmd_id, inst->state);
            return true;
    }

    // Advance to next FSM state
    fsm_next(inst);
    return true;
}

joycon_controller_type_t joycon_setup_get_type(uint8_t device_id) {
    return get_inst(device_id)->controller_type;
}

const joycon_stick_cal_t *joycon_setup_get_stick_cal(uint8_t device_id) {
    setup_instance_t *inst = get_inst(device_id);
    return inst->stick_cal.valid ? &inst->stick_cal : NULL;
}

const joycon_colors_t *joycon_setup_get_colors(uint8_t device_id) {
    setup_instance_t *inst = get_inst(device_id);
    return inst->colors.valid ? &inst->colors : NULL;
}

const joycon_stick_params_t *joycon_setup_get_stick_params(uint8_t device_id) {
    setup_instance_t *inst = get_inst(device_id);
    return inst->stick_params.valid ? &inst->stick_params : NULL;
}

const joycon_imu_cal_t *joycon_setup_get_imu_cal(uint8_t device_id) {
    setup_instance_t *inst = get_inst(device_id);
    return inst->imu_cal.valid ? &inst->imu_cal : NULL;
}

const char *joycon_setup_get_serial(uint8_t device_id) {
    setup_instance_t *inst = get_inst(device_id);
    return inst->serial_valid ? inst->serial : NULL;
}

int joycon_setup_get_battery(uint8_t device_id) {
    return get_inst(device_id)->battery;
}

void joycon_setup_update_battery(uint8_t device_id, uint8_t bat_con) {
    setup_instance_t *inst = get_inst(device_id);
    int battery = bat_con >> 5;
    if (battery > 4) battery = 4;

    if (battery != inst->battery) {
        inst->battery = battery;
        bridge_send_battery(inst->device_id, (uint8_t)battery);
        ESP_LOGD(TAG, "[%d] Battery updated: %d", device_id, battery);
    }
}

bool joycon_setup_is_ready(uint8_t device_id) {
    return get_inst(device_id)->state == SETUP_READY;
}

void joycon_setup_check_timeouts(void) {
    int64_t now = esp_timer_get_time();
    for (int i = 0; i < 2; i++) {
        setup_instance_t *inst = &s_inst[i];
        if (inst->state <= SETUP_IDLE || inst->state >= SETUP_READY)
            continue;
        if (inst->last_send_us == 0)
            continue;
        int64_t elapsed_ms = (now - inst->last_send_us) / 1000;
        if (elapsed_ms >= SETUP_TIMEOUT_MS) {
            ESP_LOGW(TAG, "[%d] FSM timeout in state %d after %lld ms, advancing",
                     inst->device_id, inst->state, (long long)elapsed_ms);
            fsm_next(inst);
        }
    }
}

void joycon_setup_send_rumble(uint8_t device_id, uint16_t freq_hz, uint8_t amp_100) {
    setup_instance_t *inst = get_inst(device_id);
    if (inst->state != SETUP_READY) return;

    // Clamp inputs
    if (freq_hz < 41) freq_hz = 41;
    if (freq_hz > 1253) freq_hz = 1253;
    if (amp_100 > 100) amp_100 = 100;

    // Encode frequency: encoded = round(log2(freq/10.0) * 32.0)
    double encoded_freq = round(log2((double)freq_hz / 10.0) * 32.0);
    uint8_t enc_f = (uint8_t)encoded_freq;

    // HF byte: (encoded - 0x60) * 4, clamp to [0x00, 0x01FC], stored as uint8_t pair
    int hf_val = ((int)enc_f - 0x60) * 4;
    if (hf_val < 0) hf_val = 0;
    if (hf_val > 0x01FC) hf_val = 0x01FC;

    // LF byte: encoded - 0x40, clamp to [0x01, 0x7F]
    int lf_val = (int)enc_f - 0x40;
    if (lf_val < 1) lf_val = 1;
    if (lf_val > 0x7F) lf_val = 0x7F;

    // Encode amplitude (0.0 to 1.0)
    // amp_100 = 0 → no rumble, amp_100 = 100 → max safe amplitude (~1.0)
    double amp = (double)amp_100 / 100.0;

    uint8_t hf_amp = 0;
    uint8_t lf_amp = 0x40;  // base offset

    if (amp > 0.0) {
        // Safety capped at ~1.0 to protect the linear resonant actuator
        if (amp > 1.0) amp = 1.0;

        double encoded_amp;
        if (amp >= 0.23) {
            encoded_amp = round(log2(amp * 8.7) * 32.0);
        } else if (amp >= 0.12) {
            encoded_amp = round(log2(amp * 17.0) * 16.0);
        } else {
            encoded_amp = round(log2(amp * 34.0) * 8.0);
        }
        if (encoded_amp < 0) encoded_amp = 0;
        if (encoded_amp > 0xC8) encoded_amp = 0xC8;  // Safety limit

        uint8_t enc_a = (uint8_t)encoded_amp;
        hf_amp = (uint8_t)(enc_a * 2);
        lf_amp = (uint8_t)(enc_a / 2 + 64);
    }

    // Build 4-byte rumble data per actuator:
    //   [0] = hf_lo (low byte of HF)
    //   [1] = hf_amp + hf_hi (high nibble of HF in low nibble)
    //   [2] = lf + lf_amp_hi (LF in low 7 bits + high bit of LF_amp)
    //   [3] = lf_amp_lo
    uint8_t rumble[4];
    rumble[0] = (uint8_t)(hf_val & 0xFF);
    rumble[1] = (uint8_t)(hf_amp + ((hf_val >> 8) & 0x01));
    rumble[2] = (uint8_t)((lf_val & 0x7F) | ((lf_amp & 0x80) ? 0x80 : 0x00));
    rumble[3] = (uint8_t)(lf_amp & 0x7F);

    // Output report: 0x10 = rumble-only
    uint8_t buf[10] = {0};
    buf[0] = OUTPUT_RUMBLE_ONLY;
    buf[1] = inst->packet_num;
    inst->packet_num = (inst->packet_num + 1) & 0x0F;
    // Left actuator (bytes 2-5)
    memcpy(&buf[2], rumble, 4);
    // Right actuator (bytes 6-9) — same data
    memcpy(&buf[6], rumble, 4);

    xSemaphoreTake(s_bt_send_mux, portMAX_DELAY);
    esp_err_t err = esp_bt_hid_host_send_data(inst->handle, buf, sizeof(buf));
    xSemaphoreGive(s_bt_send_mux);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "[%d] Rumble send failed: %s", inst->device_id, esp_err_to_name(err));
    }
}

void joycon_setup_set_home_led(uint8_t device_id, uint8_t brightness) {
    setup_instance_t *inst = get_inst(device_id);
    if (inst->state != SETUP_READY) return;

    // Home LED is only on Right Joy-Con (and Pro Controller)
    if (inst->controller_type == JOYCON_TYPE_LEFT) {
        ESP_LOGW(TAG, "[%d] Left Joy-Con has no Home LED", device_id);
        return;
    }

    if (brightness > 0x0F) brightness = 0x0F;

    // Subcmd 0x38: 25 bytes argument for HOME LED control
    // Simplified: steady brightness, no animation
    // Byte 0: number of mini cycles (0 = infinite) + start intensity
    // Byte 1: number of full cycles + LED intensity
    // ... we just set a simple steady-on pattern
    uint8_t data[25] = {0};
    if (brightness > 0) {
        // Mini-cycle mode: 1 cycle, full intensity, no fade
        data[0] = 0x01;  // 1 mini cycle
        data[1] = brightness;  // LED start intensity (0x0-0xF)
        data[2] = 0x00;  // No fade
        data[3] = (brightness << 4) | 0x00;  // Phase 0: full brightness
    }
    // else: all zeros = LED off

    send_subcmd(inst, SUBCMD_SET_HOME_LED, data, sizeof(data));
}
