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

        // --- Motion / IMU gestures ---
        case 26: // Shake -> T (grenade throw / interact alt)
            *keycode = HID_KEY_T;
            return true;
        case 27: // Tilt Up -> 1 (weapon slot 1)
            *keycode = HID_KEY_1;
            return true;
        case 28: // Tilt Down -> 2 (weapon slot 2)
            *keycode = HID_KEY_2;
            return true;
        case 29: // Tilt Left -> 3 (weapon slot 3)
            *keycode = HID_KEY_3;
            return true;
        case 30: // Tilt Right -> 4 (weapon slot 4)
            *keycode = HID_KEY_4;
            return true;
        case 31: // Flick -> X (special ability)
            *keycode = HID_KEY_X;
            return true;

        // --- Side-rail buttons (SL / SR) ---
        case 32: // SL (left Joy-Con) -> 5 (weapon slot 5)
            *keycode = HID_KEY_5;
            return true;
        case 33: // SR (left Joy-Con) -> 6 (weapon slot 6)
            *keycode = HID_KEY_6;
            return true;
        case 34: // SL (right Joy-Con) -> 7 (weapon slot 7)
            *keycode = HID_KEY_7;
            return true;
        case 35: // SR (right Joy-Con) -> 8 (weapon slot 8)
            *keycode = HID_KEY_8;
            return true;

        default:
            return false;
    }
}
