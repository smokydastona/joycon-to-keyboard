#include "uart_framing.h"

#include "config.h"

#include "installer_console.h"

#include "driver/uart.h"
#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include <string.h>

static SemaphoreHandle_t s_uart_tx_mutex = NULL;
static portMUX_TYPE s_uart_tx_mutex_init_lock = portMUX_INITIALIZER_UNLOCKED;

static void bridge_uart_tx_mutex_init_once(void) {
    if (s_uart_tx_mutex) return;
    portENTER_CRITICAL(&s_uart_tx_mutex_init_lock);
    if (!s_uart_tx_mutex) {
        s_uart_tx_mutex = xSemaphoreCreateMutex();
    }
    portEXIT_CRITICAL(&s_uart_tx_mutex_init_lock);
}

static inline uint8_t xor_checksum(uint8_t length, const uint8_t* payload) {
    uint8_t x = length;
    for (uint8_t i = 0; i < length; i++) {
        x ^= payload[i];
    }
    return x;
}

static void bridge_send_frame(const uint8_t* payload, uint8_t length) {
    if (installer_console_passthrough_active()) {
        return;
    }

    bridge_uart_tx_mutex_init_once();
    if (s_uart_tx_mutex) {
        xSemaphoreTake(s_uart_tx_mutex, portMAX_DELAY);
    }

    // Frame format: AA 55 <len> <payload...> <checksum>
    // checksum = XOR of len and payload bytes.
    uint8_t header[3] = {BRIDGE_SYNC0, BRIDGE_SYNC1, length};
    uint8_t checksum = xor_checksum(length, payload);

    uart_write_bytes(BRIDGE_UART_PORT, (const char*)header, sizeof(header));
    uart_write_bytes(BRIDGE_UART_PORT, (const char*)payload, length);
    uart_write_bytes(BRIDGE_UART_PORT, (const char*)&checksum, 1);

    if (s_uart_tx_mutex) {
        xSemaphoreGive(s_uart_tx_mutex);
    }
}

void bridge_send_key_event(uint8_t key_id, bool pressed) {
    uint8_t event = (uint8_t)(key_id & 0x7F);
    if (pressed) {
        event |= 0x80;
    }

    bridge_send_frame(&event, 1);
}

void bridge_send_key_event_ex(uint8_t device_id, uint8_t base_key_id, bool pressed) {
    // Extended payload format (length > 1):
    //   [0] = 0xFC (key event ex marker)
    //   [1] = device_id
    //   [2] = pressed (0/1)
    //   [3] = base_key_id (0..127)
    uint8_t payload[4];
    payload[0] = 0xFC;
    payload[1] = device_id;
    payload[2] = pressed ? 1 : 0;
    payload[3] = (uint8_t)(base_key_id & 0x7F);
    bridge_send_frame(payload, (uint8_t)sizeof(payload));
}

void bridge_send_debug_hid_report(const uint8_t* report, uint16_t report_len) {
    if (!report || report_len == 0) {
        return;
    }

    // Debug payload format (length > 1):
    //   [0] = 0xFF (debug marker)
    //   [1] = N (number of report bytes included)
    //   [2..] = report bytes (truncated)
    // This stays backward-compatible with receivers that only process length==1 frames.
    const uint16_t max_payload = 200; // keep stack use small; Kconfig can further limit on caller side
    uint8_t buf[2 + max_payload];

    uint16_t n = report_len;
    if (n > max_payload) {
        n = max_payload;
    }

    buf[0] = 0xFF;
    buf[1] = (uint8_t)n;
    for (uint16_t i = 0; i < n; i++) {
        buf[2 + i] = report[i];
    }

    uint8_t length = (uint8_t)(2 + n);
    bridge_send_frame(buf, length);
}

void bridge_send_bt_status(uint8_t status_id, const uint8_t* bda6, const char* name) {
    // Status payload format (length > 1):
    //   [0]=0xFD, [1]=status_id, [2..7]=bda, [8]=name_len, [9..]=name
    uint8_t bda_zeros[6] = {0};
    if (!bda6) bda6 = bda_zeros;

    uint8_t name_len = 0;
    const char* nm = name;
    if (nm) {
        size_t n = strlen(nm);
        if (n > 48) n = 48;
        name_len = (uint8_t)n;
    }

    uint8_t payload[1 + 1 + 6 + 1 + 48];
    payload[0] = 0xFD;
    payload[1] = status_id;
    memcpy(&payload[2], bda6, 6);
    payload[8] = name_len;
    if (name_len && nm) {
        memcpy(&payload[9], nm, name_len);
    }

    uint8_t length = (uint8_t)(9 + name_len);
    bridge_send_frame(payload, length);
}

void bridge_send_ota_rsp(uint8_t rsp_id, uint8_t status, const uint8_t* data, uint8_t data_len) {
    // OTA response payload: [0]=0xFB, [1]=rsp_id, [2]=status, [3..]=data
    uint8_t payload[3 + 200];
    payload[0] = 0xFB;
    payload[1] = rsp_id;
    payload[2] = status;

    uint8_t n = data_len;
    if (n > 200) n = 200;
    if (n > 0 && data) {
        memcpy(&payload[3], data, n);
    }

    bridge_send_frame(payload, (uint8_t)(3 + n));
}

void bridge_send_ctrl_rsp(uint8_t rsp_id, uint8_t status, const uint8_t* data, uint8_t data_len) {
    // CTRL response payload: [0]=0xF5, [1]=rsp_id, [2]=status, [3..]=data
    uint8_t payload[3 + 200];
    payload[0] = 0xF5;
    payload[1] = rsp_id;
    payload[2] = status;

    uint8_t n = data_len;
    if (n > 200) n = 200;
    if (n > 0 && data) {
        memcpy(&payload[3], data, n);
    }

    bridge_send_frame(payload, (uint8_t)(3 + n));
}

void bridge_send_battery(uint8_t device_id, uint8_t level) {
    // Battery payload: [0]=0xFA, [1]=device_id, [2]=level (0-4)
    uint8_t payload[3];
    payload[0] = 0xFA;
    payload[1] = device_id;
    payload[2] = level;
    bridge_send_frame(payload, (uint8_t)sizeof(payload));
}

void bridge_send_controller_info(uint8_t device_id, uint8_t controller_type,
                                 const char *serial,
                                 const joycon_colors_t *colors,
                                 const joycon_stick_params_t *stick_params,
                                 const joycon_imu_cal_t *imu_cal) {
    // Build variable-length payload.
    // Max size: 1+1+1+1+15 + 1+6 + 1+4 + 1+24 = 56 bytes (well under 220)
    uint8_t payload[64];
    uint8_t pos = 0;

    payload[pos++] = 0xF9;  // Controller info marker
    payload[pos++] = device_id;
    payload[pos++] = controller_type;

    // Serial number
    uint8_t serial_len = 0;
    if (serial) {
        const char *s = serial;
        while (*s && serial_len < 15) { serial_len++; s++; }
    }
    payload[pos++] = serial_len;
    if (serial_len > 0) {
        memcpy(&payload[pos], serial, serial_len);
        pos += serial_len;
    }

    // Colors
    if (colors) {
        payload[pos++] = 1;  // has_colors
        payload[pos++] = colors->body_r;
        payload[pos++] = colors->body_g;
        payload[pos++] = colors->body_b;
        payload[pos++] = colors->button_r;
        payload[pos++] = colors->button_g;
        payload[pos++] = colors->button_b;
    } else {
        payload[pos++] = 0;
    }

    // Stick parameters
    if (stick_params) {
        payload[pos++] = 1;  // has_stick_params
        payload[pos++] = (uint8_t)(stick_params->deadzone & 0xFF);
        payload[pos++] = (uint8_t)((stick_params->deadzone >> 8) & 0xFF);
        payload[pos++] = (uint8_t)(stick_params->range_ratio & 0xFF);
        payload[pos++] = (uint8_t)((stick_params->range_ratio >> 8) & 0xFF);
    } else {
        payload[pos++] = 0;
    }

    // IMU calibration
    if (imu_cal) {
        payload[pos++] = 1;  // has_imu_cal
        for (int i = 0; i < 3; i++) {
            payload[pos++] = (uint8_t)(imu_cal->acc_origin[i] & 0xFF);
            payload[pos++] = (uint8_t)((imu_cal->acc_origin[i] >> 8) & 0xFF);
        }
        for (int i = 0; i < 3; i++) {
            payload[pos++] = (uint8_t)(imu_cal->acc_sens[i] & 0xFF);
            payload[pos++] = (uint8_t)((imu_cal->acc_sens[i] >> 8) & 0xFF);
        }
        for (int i = 0; i < 3; i++) {
            payload[pos++] = (uint8_t)(imu_cal->gyro_origin[i] & 0xFF);
            payload[pos++] = (uint8_t)((imu_cal->gyro_origin[i] >> 8) & 0xFF);
        }
        for (int i = 0; i < 3; i++) {
            payload[pos++] = (uint8_t)(imu_cal->gyro_sens[i] & 0xFF);
            payload[pos++] = (uint8_t)((imu_cal->gyro_sens[i] >> 8) & 0xFF);
        }
    } else {
        payload[pos++] = 0;
    }

    if (pos > sizeof(payload)) {
        ESP_LOGE("uart-framing", "controller_info overflow pos=%u", (unsigned)pos);
        return;
    }
    bridge_send_frame(payload, pos);
}

void bridge_send_rssi(uint8_t device_id, int8_t rssi) {
    uint8_t payload[3];
    payload[0] = 0xF8;  // RSSI marker
    payload[1] = device_id;
    payload[2] = (uint8_t)rssi;  // signed, reinterpret on receiver
    bridge_send_frame(payload, (uint8_t)sizeof(payload));
}

void bridge_send_analog(uint8_t device_id, int16_t x, int16_t y) {
    uint8_t payload[6];
    payload[0] = 0xF7;  // Analog marker
    payload[1] = device_id;
    payload[2] = (uint8_t)(x & 0xFF);
    payload[3] = (uint8_t)((x >> 8) & 0xFF);
    payload[4] = (uint8_t)(y & 0xFF);
    payload[5] = (uint8_t)((y >> 8) & 0xFF);
    bridge_send_frame(payload, (uint8_t)sizeof(payload));
}

void bridge_send_gyro(uint8_t device_id, int16_t gx, int16_t gy, int16_t gz) {
    uint8_t payload[8];
    payload[0] = 0xF6;  // Gyro marker
    payload[1] = device_id;
    payload[2] = (uint8_t)(gx & 0xFF);
    payload[3] = (uint8_t)((gx >> 8) & 0xFF);
    payload[4] = (uint8_t)(gy & 0xFF);
    payload[5] = (uint8_t)((gy >> 8) & 0xFF);
    payload[6] = (uint8_t)(gz & 0xFF);
    payload[7] = (uint8_t)((gz >> 8) & 0xFF);
    bridge_send_frame(payload, (uint8_t)sizeof(payload));
}
