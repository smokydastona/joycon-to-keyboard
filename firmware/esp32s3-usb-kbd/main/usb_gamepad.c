#include "usb_gamepad.h"

#include <string.h>

#include "tusb.h"

// HID instance index for the gamepad interface in this firmware.
// 0 = keyboard, 1 = mouse, 2 = gamepad
#define GAMEPAD_HID_INSTANCE 2

// Key IDs (base ids) as defined by this project.
// Keep in sync with docs/keymap.md and any key_id packing rules.
#define KEY_ID_FORWARD 1
#define KEY_ID_BACK 2
#define KEY_ID_LEFT 3
#define KEY_ID_RIGHT 4
#define KEY_ID_JOYCON_L 20
#define KEY_ID_JOYCON_ZL 21
#define KEY_ID_JOYCON_R 22
#define KEY_ID_JOYCON_ZR 23
#define KEY_ID_ESC 52
#define KEY_ID_SPACE 54
#define KEY_ID_SHIFT 55
#define KEY_ID_CTRL 56

#define DEVICE_SLOT_COUNT 5

typedef struct __attribute__((packed))
{
    uint16_t buttons;
    uint8_t hat; // low nibble hat (0..7), 8 = neutral; high nibble padding
    int16_t x;
    int16_t y;
    int16_t rx;
    int16_t ry;
} hid_gamepad_report_t;

static struct
{
    // Digital state used for hat and buttons.
    bool up;
    bool down;
    bool left;
    bool right;

    bool a;
    bool b;
    bool x;
    bool y;

    bool lb;
    bool rb;

    bool back;
    bool start;

    bool l3;
    bool r3;

    // Analog state.
    int16_t lx;
    int16_t ly;
    int16_t rx;
    int16_t ry;

    // Per-slot stick sources. Right stick prefers slot 0 then slot 1.
    int16_t slot_lx[DEVICE_SLOT_COUNT];
    int16_t slot_ly[DEVICE_SLOT_COUNT];
    int16_t slot_rx[DEVICE_SLOT_COUNT];
    int16_t slot_ry[DEVICE_SLOT_COUNT];
} g_gamepad;

static bool g_gamepad_enabled = true;

static int16_t scale_axis_i16(int16_t v)
{
    // Incoming is approximately [-4096, +4096]. Scale to [-32767, +32767].
    int32_t scaled = (int32_t)v * 8;
    if (scaled > 32767)
        scaled = 32767;
    if (scaled < -32767)
        scaled = -32767;
    return (int16_t)scaled;
}

static uint8_t hat_from_dpad(bool up, bool down, bool left, bool right)
{
    // HID hat: 0=Up,1=UpRight,2=Right,3=DownRight,4=Down,5=DownLeft,6=Left,7=UpLeft,8=Neutral
    if (up && right)
        return 1;
    if (right && down)
        return 3;
    if (down && left)
        return 5;
    if (left && up)
        return 7;

    if (up)
        return 0;
    if (right)
        return 2;
    if (down)
        return 4;
    if (left)
        return 6;

    return 8;
}

static void build_report(hid_gamepad_report_t *r)
{
    memset(r, 0, sizeof(*r));

    // Buttons (16).
    // 0: A, 1: B, 2: X, 3: Y, 4: LB, 5: RB, 6: Back, 7: Start, 8: L3, 9: R3
    if (g_gamepad.a)
        r->buttons |= (1u << 0);
    if (g_gamepad.b)
        r->buttons |= (1u << 1);
    if (g_gamepad.x)
        r->buttons |= (1u << 2);
    if (g_gamepad.y)
        r->buttons |= (1u << 3);
    if (g_gamepad.lb)
        r->buttons |= (1u << 4);
    if (g_gamepad.rb)
        r->buttons |= (1u << 5);
    if (g_gamepad.back)
        r->buttons |= (1u << 6);
    if (g_gamepad.start)
        r->buttons |= (1u << 7);
    if (g_gamepad.l3)
        r->buttons |= (1u << 8);
    if (g_gamepad.r3)
        r->buttons |= (1u << 9);

    r->hat = hat_from_dpad(g_gamepad.up, g_gamepad.down, g_gamepad.left, g_gamepad.right);

    r->x = g_gamepad.lx;
    r->y = g_gamepad.ly;
    r->rx = g_gamepad.rx;
    r->ry = g_gamepad.ry;
}

static void send_report_if_ready(void)
{
    if (!g_gamepad_enabled)
        return;

    if (!tud_ready())
        return;

    if (!tud_hid_n_ready(GAMEPAD_HID_INSTANCE))
        return;

    hid_gamepad_report_t r;
    build_report(&r);

    // Report ID = 0 (no report IDs used).
    (void)tud_hid_n_report(GAMEPAD_HID_INSTANCE, 0, &r, sizeof(r));
}

void usb_gamepad_init(void)
{
    memset(&g_gamepad, 0, sizeof(g_gamepad));
    g_gamepad_enabled = true;
}

void usb_gamepad_set_enabled(bool enabled)
{
    g_gamepad_enabled = enabled;

    // If disabling, send a neutral report so the host doesn't retain a stuck state.
    if (!enabled)
    {
        if (!tud_ready())
            return;
        if (!tud_hid_n_ready(GAMEPAD_HID_INSTANCE))
            return;

        hid_gamepad_report_t r;
        memset(&r, 0, sizeof(r));
        r.hat = 8;
        (void)tud_hid_n_report(GAMEPAD_HID_INSTANCE, 0, &r, sizeof(r));
    }
}

bool usb_gamepad_get_enabled(void)
{
    return g_gamepad_enabled;
}

void usb_gamepad_handle_key(bool pressed, uint16_t key_id)
{
    uint16_t base = (uint16_t)(key_id % 128);

    switch (base)
    {
    case KEY_ID_FORWARD:
        g_gamepad.up = pressed;
        break;
    case KEY_ID_BACK:
        g_gamepad.down = pressed;
        break;
    case KEY_ID_LEFT:
        g_gamepad.left = pressed;
        break;
    case KEY_ID_RIGHT:
        g_gamepad.right = pressed;
        break;

    // Joy-Con face/shoulder keys map to Xbox ABXY/LB/RB.
    case KEY_ID_JOYCON_R:
        g_gamepad.a = pressed;
        break;
    case KEY_ID_JOYCON_L:
        g_gamepad.x = pressed;
        break;
    case KEY_ID_JOYCON_ZR:
        g_gamepad.rb = pressed;
        break;
    case KEY_ID_JOYCON_ZL:
        g_gamepad.lb = pressed;
        break;

    // Common keyboard keys map to Start/Back and sticks.
    case KEY_ID_SPACE:
        g_gamepad.a = pressed;
        break;
    case KEY_ID_ESC:
        g_gamepad.back = pressed;
        break;
    case KEY_ID_SHIFT:
        g_gamepad.l3 = pressed;
        break;
    case KEY_ID_CTRL:
        g_gamepad.r3 = pressed;
        break;
    default:
        break;
    }

    send_report_if_ready();
}

void usb_gamepad_handle_analog(uint8_t device_id, int16_t x, int16_t y)
{
    bool is_right = (device_id & 0x80) != 0;
    uint8_t slot = (uint8_t)(device_id & 0x7F);

    if (slot >= DEVICE_SLOT_COUNT)
        return;

    int16_t sx = scale_axis_i16(x);
    int16_t sy = scale_axis_i16(y);

    if (!is_right)
    {
        g_gamepad.slot_lx[slot] = sx;
        g_gamepad.slot_ly[slot] = sy;
        g_gamepad.lx = g_gamepad.slot_lx[0];
        g_gamepad.ly = g_gamepad.slot_ly[0];
    }
    else
    {
        g_gamepad.slot_rx[slot] = sx;
        g_gamepad.slot_ry[slot] = sy;
        // Prefer slot 0 for right stick; if it's neutral and slot 1 is non-neutral, use slot 1.
        int16_t rx0 = g_gamepad.slot_rx[0];
        int16_t ry0 = g_gamepad.slot_ry[0];
        int16_t rx1 = g_gamepad.slot_rx[1];
        int16_t ry1 = g_gamepad.slot_ry[1];

        if ((rx0 == 0 && ry0 == 0) && (rx1 != 0 || ry1 != 0))
        {
            g_gamepad.rx = rx1;
            g_gamepad.ry = ry1;
        }
        else
        {
            g_gamepad.rx = rx0;
            g_gamepad.ry = ry0;
        }
    }

    send_report_if_ready();
}
