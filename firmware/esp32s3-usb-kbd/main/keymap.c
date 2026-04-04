#include "keymap.h"

#include "tusb.h"

bool keymap_lookup(uint8_t key_id, uint8_t* modifier, uint8_t* keycode) {
    *modifier = 0;
    *keycode = 0;

    switch (key_id) {
        case 1:
            *keycode = HID_KEY_W;
            return true;
        case 2:
            *keycode = HID_KEY_S;
            return true;
        case 3:
            *keycode = HID_KEY_A;
            return true;
        case 4:
            *keycode = HID_KEY_D;
            return true;
        case 5:
            *keycode = HID_KEY_SPACE;
            return true;
        case 6:
            *modifier = KEYBOARD_MODIFIER_LEFTSHIFT;
            *keycode = 0;
            return true;
        case 7:
            *modifier = KEYBOARD_MODIFIER_LEFTCTRL;
            *keycode = 0;
            return true;
        default:
            return false;
    }
}
