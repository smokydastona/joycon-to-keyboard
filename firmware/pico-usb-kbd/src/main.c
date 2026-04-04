#include <stdbool.h>
#include <string.h>

#include "pico/stdlib.h"
#include "hardware/uart.h"

#include "tusb.h"

#include "config.h"
#include "uart_proto.h"
#include "keymap.h"

static uint8_t current_mod = 0;
static uint8_t current_keys[6] = {0};

static void clear_keys(void) {
    current_mod = 0;
    memset(current_keys, 0, sizeof(current_keys));
}

static void set_key_state(uint8_t keycode, bool pressed) {
    if (keycode == 0) {
        return;
    }

    if (pressed) {
        for (int i = 0; i < 6; i++) {
            if (current_keys[i] == keycode) {
                return;
            }
        }
        for (int i = 0; i < 6; i++) {
            if (current_keys[i] == 0) {
                current_keys[i] = keycode;
                return;
            }
        }
    } else {
        for (int i = 0; i < 6; i++) {
            if (current_keys[i] == keycode) {
                current_keys[i] = 0;
            }
        }
    }
}

static void send_report(void) {
    if (!tud_hid_ready()) {
        return;
    }
    tud_hid_keyboard_report(0, current_mod, current_keys);
}

int main(void) {
    // UART init
    uart_init(KBD_UART_ID, KBD_UART_BAUD);
    gpio_set_function(KBD_UART_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(KBD_UART_RX_PIN, GPIO_FUNC_UART);
    uart_set_format(KBD_UART_ID, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(KBD_UART_ID, true);

    // USB init
    tusb_init();

    clear_keys();

    while (true) {
        tud_task();

        uint8_t event;
        bool changed = false;

        while (uart_proto_poll_event(&event)) {
            bool pressed = (event & 0x80u) != 0;
            uint8_t key_id = event & 0x7Fu;

            uint8_t mod = 0;
            uint8_t keycode = 0;
            if (!keymap_lookup(key_id, &mod, &keycode)) {
                continue;
            }

            if (mod != 0) {
                if (pressed) {
                    if ((current_mod & mod) == 0) {
                        current_mod |= mod;
                        changed = true;
                    }
                } else {
                    if ((current_mod & mod) != 0) {
                        current_mod &= (uint8_t)~mod;
                        changed = true;
                    }
                }
            }

            if (keycode != 0) {
                uint8_t before[6];
                memcpy(before, current_keys, sizeof(before));
                set_key_state(keycode, pressed);
                if (memcmp(before, current_keys, sizeof(before)) != 0) {
                    changed = true;
                }
            }
        }

        if (changed) {
            send_report();
        }
    }

    return 0;
}
