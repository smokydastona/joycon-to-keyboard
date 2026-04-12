#include "tusb.h"

// Device descriptor (non-static so usb_kbd.c can pass it to tinyusb_driver_install)
tusb_desc_device_t const desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,

    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,

    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,

    // NOTE: These VID/PID are placeholders.
    // If you ship hardware, use your own VID/PID.
    .idVendor = 0xCafe,
    .idProduct = 0x4030,
    .bcdDevice = 0x0100,

    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,

    .bNumConfigurations = 0x01,
};

// HID report descriptor: standard boot keyboard (instance 0)
static uint8_t const desc_hid_report_kbd[] = {
    TUD_HID_REPORT_DESC_KEYBOARD(),
};

// HID report descriptor: standard mouse (instance 1)
static uint8_t const desc_hid_report_mouse[] = {
    TUD_HID_REPORT_DESC_MOUSE(),
};

// HID report descriptor: standard gamepad (instance 2)
// 16 buttons + hat switch + X/Y + Rx/Ry axes.
static uint8_t const desc_hid_report_gamepad[] = {
    0x05, 0x01,       // Usage Page (Generic Desktop)
    0x09, 0x05,       // Usage (Game Pad)
    0xA1, 0x01,       // Collection (Application)

    0x05, 0x09,       //   Usage Page (Button)
    0x19, 0x01,       //   Usage Minimum (Button 1)
    0x29, 0x10,       //   Usage Maximum (Button 16)
    0x15, 0x00,       //   Logical Minimum (0)
    0x25, 0x01,       //   Logical Maximum (1)
    0x75, 0x01,       //   Report Size (1)
    0x95, 0x10,       //   Report Count (16)
    0x81, 0x02,       //   Input (Data,Var,Abs)

    0x05, 0x01,       //   Usage Page (Generic Desktop)
    0x09, 0x39,       //   Usage (Hat switch)
    0x15, 0x00,       //   Logical Minimum (0)
    0x25, 0x07,       //   Logical Maximum (7)
    0x35, 0x00,       //   Physical Minimum (0)
    0x46, 0x3B, 0x01, //   Physical Maximum (315)
    0x65, 0x14,       //   Unit (Eng Rot: Degrees)
    0x75, 0x04,       //   Report Size (4)
    0x95, 0x01,       //   Report Count (1)
    0x81, 0x42,       //   Input (Data,Var,Abs,Null)

    0x65, 0x00,       //   Unit (None)
    0x75, 0x04,       //   Report Size (4)
    0x95, 0x01,       //   Report Count (1)
    0x81, 0x03,       //   Input (Const,Var,Abs) padding

    0x16, 0x01, 0x80, //   Logical Minimum (-32767)
    0x26, 0xFF, 0x7F, //   Logical Maximum (32767)
    0x75, 0x10,       //   Report Size (16)
    0x95, 0x04,       //   Report Count (4)
    0x09, 0x30,       //   Usage (X)
    0x09, 0x31,       //   Usage (Y)
    0x09, 0x33,       //   Usage (Rx)
    0x09, 0x34,       //   Usage (Ry)
    0x81, 0x02,       //   Input (Data,Var,Abs)

    0xC0              // End Collection
};

uint8_t const* tud_hid_descriptor_report_cb(uint8_t instance) {
    if (instance == 1) return desc_hid_report_mouse;
    if (instance == 2) return desc_hid_report_gamepad;
    return desc_hid_report_kbd;
}

// Configuration descriptor
enum {
    ITF_NUM_CDC,
    ITF_NUM_CDC_DATA,
    ITF_NUM_HID_KBD,
    ITF_NUM_HID_MOUSE,
    ITF_NUM_HID_GAMEPAD,
    ITF_NUM_TOTAL,
};

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_HID_DESC_LEN + TUD_HID_DESC_LEN + TUD_HID_DESC_LEN)

// Endpoint allocation:
// - CDC: 1x interrupt IN notification, 1x bulk OUT, 1x bulk IN
// - HID keyboard: 1x interrupt IN
// - HID mouse: 1x interrupt IN
#define EPNUM_CDC_NOTIF  0x81
#define EPNUM_CDC_OUT    0x02
#define EPNUM_CDC_IN     0x82
#define EPNUM_HID_KBD    0x83
#define EPNUM_HID_MOUSE  0x84
#define EPNUM_HID_GAMEPAD 0x85

uint8_t const desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_KBD, 5, HID_ITF_PROTOCOL_KEYBOARD, sizeof(desc_hid_report_kbd), EPNUM_HID_KBD, 16, 1),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_MOUSE, 6, HID_ITF_PROTOCOL_MOUSE, sizeof(desc_hid_report_mouse), EPNUM_HID_MOUSE, 16, 1),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_GAMEPAD, 7, HID_ITF_PROTOCOL_NONE, sizeof(desc_hid_report_gamepad), EPNUM_HID_GAMEPAD, 16, 1),
};

_Static_assert(sizeof(desc_configuration) == CONFIG_TOTAL_LEN,
               "CONFIG_TOTAL_LEN must match the actual configuration descriptor size");

// String descriptors (non-static so usb_kbd.c can pass them to tinyusb_driver_install)
char const* string_desc_arr[] = {
    (const char[]){0x09, 0x04},
    "Bind Bandit",
    "Bind Bandit",
    "00000001",
    "Architect",
    "Composer",
    "Forger",
    "Executor",
};

#define STRING_DESC_ARR_SIZE 8
const int string_desc_arr_count = STRING_DESC_ARR_SIZE;

// Required HID callbacks
uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                              uint8_t* buffer, uint16_t reqlen) {
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)reqlen;
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                          uint8_t const* buffer, uint16_t bufsize) {
    // LED output reports (Num Lock, Caps Lock, etc.) are received here.
    // We intentionally ignore them — the Joy-Con bridge has no indicator LEDs
    // on the keyboard side, but we must accept the report so the host
    // doesn't stall.
    (void)instance;
    (void)report_id;
    (void)report_type;
    (void)buffer;
    (void)bufsize;
}
