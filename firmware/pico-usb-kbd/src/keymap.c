#include "keymap.h"

#include "tusb.h"

// Default mapping matches docs/keymap.md
// key_id values:
// 1=Forward(W), 2=Back(S), 3=Left(A), 4=Right(D), 5=Jump(Space), 6=Sprint(LShift), 7=Crouch(LCtrl)

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
            *keycode = 0; // modifier-only
            return true;
        case 7:
            *modifier = KEYBOARD_MODIFIER_LEFTCTRL;
            *keycode = 0; // modifier-only
            return true;
        default:
            return false;
    }
}
