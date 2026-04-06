#include <stdbool.h>
#include <stdint.h>

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "uart_proto.h"
#include "keymap.h"
#include "usb_kbd.h"
#include "bridge_serial.h"
#include "profile_runtime.h"

static const char* TAG = "s3-kbd";

#define STATUS_MARKER 0xFD
#define KEY_EX_MARKER 0xFC
#define BATTERY_MARKER 0xFA

static const char* status_id_to_state(uint8_t id) {
    switch (id) {
        case 1: return "discovering";
        case 2: return "found";
        case 3: return "connecting";
        case 4: return "connected";
        case 5: return "disconnected";
        default: return "unknown";
    }
}

static const char* bda_to_str(const uint8_t* bda, char* out, size_t out_len) {
    if (!bda || !out || out_len < 18) return NULL;
    snprintf(out, out_len, "%02x:%02x:%02x:%02x:%02x:%02x",
             bda[0], bda[1], bda[2], bda[3], bda[4], bda[5]);
    return out;
}

void app_main(void) {
    usb_kbd_init();
    bridge_serial_init();
    profile_runtime_init();
    uart_proto_init();

    ESP_LOGI(TAG, "Ready: waiting for UART key events");

    while (1) {
        bridge_serial_poll();

        uart_frame_t f;
        while (uart_proto_poll_frame(&f)) {
            if (f.type == UART_FRAME_KEY_EVENT && f.length == 1) {
                uint8_t event = f.payload[0];
                bool pressed = (event & 0x80u) != 0;
                uint8_t key_id = event & 0x7Fu;
                bridge_serial_emit_mapped_key(pressed, key_id);
                profile_runtime_handle_input(pressed, key_id);
                continue;
            }

            if (f.type == UART_FRAME_KEY_EVENT_EX && f.length == 4 && f.payload[0] == KEY_EX_MARKER) {
                uint8_t device_id = f.payload[1];
                bool pressed = (f.payload[2] != 0);
                uint8_t base_key_id = (uint8_t)(f.payload[3] & 0x7Fu);

                // Map into a larger input key_id space.
                // device_id=0 -> 0..127
                // device_id=1 -> 128..255
                uint8_t key_id = base_key_id;
                if (device_id == 1) {
                    key_id = (uint8_t)(128u + base_key_id);
                }

                bridge_serial_emit_mapped_key(pressed, key_id);
                profile_runtime_handle_input(pressed, key_id);
                continue;
            }

            if (f.type == UART_FRAME_STATUS && f.length >= 2 && f.payload[0] == STATUS_MARKER) {
                uint8_t status_id = f.payload[1];
                const char* state = status_id_to_state(status_id);

                const char* name = NULL;
                char bda_str[18];
                const char* bda_out = NULL;

                if (f.length >= 9) {
                    bda_out = bda_to_str(&f.payload[2], bda_str, sizeof(bda_str));

                    uint8_t name_len = f.payload[8];
                    if (name_len > 0 && (uint16_t)(9 + name_len) <= f.length) {
                        static char name_buf[64];
                        uint8_t n = name_len;
                        if (n >= sizeof(name_buf)) n = (uint8_t)(sizeof(name_buf) - 1);
                        memcpy(name_buf, &f.payload[9], n);
                        name_buf[n] = 0;
                        name = name_buf;
                    }
                }

                bridge_serial_emit_bt_status(state, name, bda_out);
                continue;
            }

            if (f.type == UART_FRAME_OTA_RSP) {
                bridge_serial_handle_ota_rsp(f.payload, f.length);
                continue;
            }

            if (f.type == UART_FRAME_BATTERY && f.length >= 3 && f.payload[0] == BATTERY_MARKER) {
                uint8_t device_id = f.payload[1];
                uint8_t level = f.payload[2];
                bridge_serial_emit_battery(device_id, level);
                continue;
            }
        }

        // esp_tinyusb runs tud_task() in its own internal task;
        // yield briefly so the idle task and USB task can run.
        vTaskDelay(1);
    }
}
