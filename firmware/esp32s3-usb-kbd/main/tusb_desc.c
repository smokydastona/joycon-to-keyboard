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

uint8_t const* tud_hid_descriptor_report_cb(uint8_t instance) {
    if (instance == 1) return desc_hid_report_mouse;
    return desc_hid_report_kbd;
}

// Configuration descriptor
enum {
    ITF_NUM_CDC,
    ITF_NUM_CDC_DATA,
    ITF_NUM_HID_KBD,
    ITF_NUM_HID_MOUSE,
    ITF_NUM_TOTAL,
};

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_HID_DESC_LEN + TUD_HID_DESC_LEN)

// Endpoint allocation:
// - CDC: 1x interrupt IN notification, 1x bulk OUT, 1x bulk IN
// - HID keyboard: 1x interrupt IN
// - HID mouse: 1x interrupt IN
#define EPNUM_CDC_NOTIF  0x81
#define EPNUM_CDC_OUT    0x02
#define EPNUM_CDC_IN     0x82
#define EPNUM_HID_KBD    0x83
#define EPNUM_HID_MOUSE  0x84

uint8_t const desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_KBD, 0, HID_ITF_PROTOCOL_KEYBOARD, sizeof(desc_hid_report_kbd), EPNUM_HID_KBD, 16, 1),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_MOUSE, 5, HID_ITF_PROTOCOL_MOUSE, sizeof(desc_hid_report_mouse), EPNUM_HID_MOUSE, 16, 1),
};

_Static_assert(sizeof(desc_configuration) == CONFIG_TOTAL_LEN,
               "CONFIG_TOTAL_LEN must match the actual configuration descriptor size");

// String descriptors (non-static so usb_kbd.c can pass them to tinyusb_driver_install)
char const* string_desc_arr[] = {
    (const char[]){0x09, 0x04},
    "Bind Bandit",
    "InputGremlin",
    "00000001",
    "Bind Bandit CDC",
    "Bind Bandit Mouse",
};

#define STRING_DESC_ARR_SIZE 6
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
