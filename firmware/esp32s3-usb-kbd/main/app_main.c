#include <stdbool.h>
#include <stdint.h>

#include "esp_log.h"

#include "uart_proto.h"
#include "keymap.h"
#include "usb_kbd.h"
#include "bridge_serial.h"

static const char* TAG = "s3-kbd";

void app_main(void) {
    usb_kbd_init();
    bridge_serial_init();
    uart_proto_init();

    ESP_LOGI(TAG, "Ready: waiting for UART key events");

    while (1) {
        bridge_serial_poll();

        uint8_t event;
        if (uart_proto_poll_event(&event)) {
            bool pressed = (event & 0x80u) != 0;
            uint8_t key_id = event & 0x7Fu;

            uint8_t mod = 0;
            uint8_t keycode = 0;
            if (!keymap_lookup(key_id, &mod, &keycode)) {
                continue;
            }

            bridge_serial_emit_mapped_key(pressed, key_id);
            usb_kbd_set_key(mod, keycode, pressed);
        }

        // Let TinyUSB run.
        tud_task();
    }
}
