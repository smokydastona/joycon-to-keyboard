#include "usb_kbd.h"

#include <string.h>

#include "esp_log.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "tinyusb.h"
#include "tusb.h"

// Descriptors defined in tusb_desc.c
extern const tusb_desc_device_t desc_device;
extern const uint8_t desc_configuration[];
extern char const* string_desc_arr[];
extern const int string_desc_arr_count;

static const char* TAG = "usb-kbd";

static uint8_t s_mod = 0;
static uint8_t s_keys[6] = {0};
static SemaphoreHandle_t s_mutex = NULL;

static void set_keycode(uint8_t keycode, bool pressed) {
    if (keycode == 0) return;

    if (pressed) {
        for (int i = 0; i < 6; i++) {
            if (s_keys[i] == keycode) return;
        }
        for (int i = 0; i < 6; i++) {
            if (s_keys[i] == 0) {
                s_keys[i] = keycode;
                return;
            }
        }
    } else {
        for (int i = 0; i < 6; i++) {
            if (s_keys[i] == keycode) s_keys[i] = 0;
        }
    }
}

static void send_report(void) {
    if (!tud_hid_ready()) return;
    tud_hid_keyboard_report(0, s_mod, s_keys);
}

void usb_kbd_init(void) {
    const tinyusb_config_t tusb_cfg = {
        .device_descriptor = &desc_device,
        .string_descriptor = string_desc_arr,
        .string_descriptor_count = string_desc_arr_count,
        .external_phy = false,
        .configuration_descriptor = desc_configuration,
    };

    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    ESP_LOGI(TAG, "TinyUSB keyboard initialized");

    if (!s_mutex) {
        s_mutex = xSemaphoreCreateMutex();
    }

    s_mod = 0;
    memset(s_keys, 0, sizeof(s_keys));
}

void usb_kbd_set_key(uint8_t modifier, uint8_t keycode, bool pressed) {
    if (s_mutex) {
        xSemaphoreTake(s_mutex, portMAX_DELAY);
    }

    if (modifier) {
        if (pressed) {
            s_mod |= modifier;
        } else {
            s_mod &= (uint8_t)~modifier;
        }
    }

    set_keycode(keycode, pressed);
    send_report();

    if (s_mutex) {
        xSemaphoreGive(s_mutex);
    }
}
