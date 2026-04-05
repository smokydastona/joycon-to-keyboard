#include "keymap.h"

#include "tusb.h"

bool keymap_lookup(uint8_t key_id, uint8_t* modifier, uint8_t* keycode) {
    *modifier = 0;
    *keycode = 0;

    switch (key_id) {
        // --- Movement (left stick) ---
        case 1:  // Forward
            *keycode = HID_KEY_W;
            return true;
        case 2:  // Back
            *keycode = HID_KEY_S;
            return true;
        case 3:  // Left
            *keycode = HID_KEY_A;
            return true;
        case 4:  // Right
            *keycode = HID_KEY_D;
            return true;
        case 5:  // Jump
            *keycode = HID_KEY_SPACE;
            return true;
        case 6:  // Sprint
            *modifier = KEYBOARD_MODIFIER_LEFTSHIFT;
            *keycode = 0;
            return true;
        case 7:  // Crouch
            *modifier = KEYBOARD_MODIFIER_LEFTCTRL;
            *keycode = 0;
            return true;

        // --- Face buttons ---
        case 8:  // A -> E (Use / Interact)
            *keycode = HID_KEY_E;
            return true;
        case 9:  // B -> Q (Ability / Alt action)
            *keycode = HID_KEY_Q;
            return true;
        case 10: // X -> R (Reload)
            *keycode = HID_KEY_R;
            return true;
        case 11: // Y -> F (Melee / Alt)
            *keycode = HID_KEY_F;
            return true;

        // --- Shoulder / trigger ---
        case 12: // L -> Tab (Scoreboard / Map)
            *keycode = HID_KEY_TAB;
            return true;
        case 13: // R -> Enter
            *keycode = HID_KEY_ENTER;
            return true;
        case 14: // ZL -> Right mouse (mapped as Right Alt for now)
            *modifier = KEYBOARD_MODIFIER_RIGHTALT;
            *keycode = 0;
            return true;
        case 15: // ZR -> Left mouse (mapped as Left Alt for now)
            *modifier = KEYBOARD_MODIFIER_LEFTALT;
            *keycode = 0;
            return true;

        // --- System buttons ---
        case 16: // Plus -> Escape
            *keycode = HID_KEY_ESCAPE;
            return true;
        case 17: // Minus -> Grave (backtick / console)
            *keycode = HID_KEY_GRAVE;
            return true;
        case 18: // Home -> (unmapped by default)
            return false;
        case 19: // Capture -> G (grenade / utility)
            *keycode = HID_KEY_G;
            return true;

        // --- Stick clicks ---
        case 20: // LStick click -> Left Shift (Sprint toggle)
            *modifier = KEYBOARD_MODIFIER_LEFTSHIFT;
            *keycode = 0;
            return true;
        case 21: // RStick click -> V (melee alt)
            *keycode = HID_KEY_V;
            return true;

        // --- Right stick virtual directions ---
        case 22: // RStick Up -> Arrow Up
            *keycode = HID_KEY_ARROW_UP;
            return true;
        case 23: // RStick Down -> Arrow Down
            *keycode = HID_KEY_ARROW_DOWN;
            return true;
        case 24: // RStick Left -> Arrow Left
            *keycode = HID_KEY_ARROW_LEFT;
            return true;
        case 25: // RStick Right -> Arrow Right
            *keycode = HID_KEY_ARROW_RIGHT;
            return true;

        default:
            return false;
    }
}
