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

// HID report descriptor: combined mouse (Report ID 1) + gamepad (Report ID 2) on instance 1.
//
// Root cause fix: ESP32-S3 USB OTG only has IN endpoints EP1-EP4 (addresses 0x81-0x84).
// Previously the gamepad was on EP5 (0x85) which is out of range, causing Windows
// usbccgp STATUS_UNSUCCESSFUL. Using a single combined HID instance keeps EP usage within limits:
//   EP3-IN (0x83) = KBD (instance 0)
//   EP4-IN (0x84) = Mouse+Gamepad, multiplexed by report ID (instance 1)
//
// Report ID 1 = mouse  (5 bytes: buttons, x, y, wheel, pan)
// Report ID 2 = gamepad (11 bytes: buttons[2], hat+pad[1], x/y/rx/ry[8])
static uint8_t const desc_hid_report_combined[] = {
    // === Mouse (Report ID = 1) ===
    0x05, 0x01,        // Usage Page (Generic Desktop)
    0x09, 0x02,        // Usage (Mouse)
    0xA1, 0x01,        // Collection (Application)
      0x09, 0x01,      //   Usage (Pointer)
      0xA1, 0x00,      //   Collection (Physical)
        0x85, 0x01,    //   Report ID (1)
        // 5 buttons
        0x05, 0x09,    //   Usage Page (Button)
        0x19, 0x01,    //   Usage Minimum (1)
        0x29, 0x05,    //   Usage Maximum (5)
        0x15, 0x00,    //   Logical Minimum (0)
        0x25, 0x01,    //   Logical Maximum (1)
        0x95, 0x05,    //   Report Count (5)
        0x75, 0x01,    //   Report Size (1)
        0x81, 0x02,    //   Input (Data, Var, Absolute)
        // 3 bits padding to complete 1 byte
        0x95, 0x01,    //   Report Count (1)
        0x75, 0x03,    //   Report Size (3)
        0x81, 0x03,    //   Input (Constant)
        // X, Y, Wheel (relative, signed 8-bit)
        0x05, 0x01,    //   Usage Page (Generic Desktop)
        0x09, 0x30,    //   Usage (X)
        0x09, 0x31,    //   Usage (Y)
        0x09, 0x38,    //   Usage (Wheel)
        0x15, 0x81,    //   Logical Minimum (-127)
        0x25, 0x7F,    //   Logical Maximum (127)
        0x75, 0x08,    //   Report Size (8)
        0x95, 0x03,    //   Report Count (3)
        0x81, 0x06,    //   Input (Data, Var, Relative)
        // Horizontal scroll (Consumer AC Pan)
        0x05, 0x0C,    //   Usage Page (Consumer Devices)
        0x0A, 0x38, 0x02, //Usage (AC Pan) — 2-byte usage value
        0x15, 0x81,    //   Logical Minimum (-127)
        0x25, 0x7F,    //   Logical Maximum (127)
        0x75, 0x08,    //   Report Size (8)
        0x95, 0x01,    //   Report Count (1)
        0x81, 0x06,    //   Input (Data, Var, Relative)
      0xC0,            //   End Collection (Physical)
    0xC0,              // End Collection (Application)

    // === Gamepad (Report ID = 2) ===
    // 32 buttons + hat switch (4-bit + 4-bit pad) + X/Y/Rx/Ry axes (int16).
    // Struct layout: buttons[4], hat_pad[1], x[2], y[2], rx[2], ry[2] = 13 bytes.
    0x05, 0x01,        // Usage Page (Generic Desktop)
    0x09, 0x05,        // Usage (Game Pad)
    0xA1, 0x01,        // Collection (Application)
      0x85, 0x02,      //   Report ID (2)
    // 32 buttons
      0x05, 0x09,      //   Usage Page (Button)
      0x19, 0x01,      //   Usage Minimum (Button 1)
    0x29, 0x20,      //   Usage Maximum (Button 32)
      0x15, 0x00,      //   Logical Minimum (0)
      0x25, 0x01,      //   Logical Maximum (1)
      0x75, 0x01,      //   Report Size (1)
    0x95, 0x20,      //   Report Count (32)
      0x81, 0x02,      //   Input (Data, Var, Abs)
      // Hat switch (4 bits, null = 8)
      0x05, 0x01,      //   Usage Page (Generic Desktop)
      0x09, 0x39,      //   Usage (Hat switch)
      0x15, 0x00,      //   Logical Minimum (0)
      0x25, 0x07,      //   Logical Maximum (7)
      0x35, 0x00,      //   Physical Minimum (0)
      0x46, 0x3B, 0x01, //  Physical Maximum (315)
      0x65, 0x14,      //   Unit (Eng Rot: Degrees)
      0x75, 0x04,      //   Report Size (4)
      0x95, 0x01,      //   Report Count (1)
      0x81, 0x42,      //   Input (Data, Var, Abs, Null)
      // 4-bit padding
      0x65, 0x00,      //   Unit (None)
      0x75, 0x04,      //   Report Size (4)
      0x95, 0x01,      //   Report Count (1)
      0x81, 0x03,      //   Input (Const, Var, Abs)
      // X, Y, Rx, Ry axes (signed 16-bit)
      0x16, 0x01, 0x80, //  Logical Minimum (-32767)
      0x26, 0xFF, 0x7F, //  Logical Maximum (32767)
      0x75, 0x10,      //   Report Size (16)
      0x95, 0x04,      //   Report Count (4)
      0x09, 0x30,      //   Usage (X)
      0x09, 0x31,      //   Usage (Y)
      0x09, 0x33,      //   Usage (Rx)
      0x09, 0x34,      //   Usage (Ry)
      0x81, 0x02,      //   Input (Data, Var, Abs)
    0xC0,              // End Collection
};

uint8_t const* tud_hid_descriptor_report_cb(uint8_t instance) {
    if (instance == 1) return desc_hid_report_combined;
    return desc_hid_report_kbd;
}

// Configuration descriptor
enum {
    ITF_NUM_CDC,
    ITF_NUM_CDC_DATA,
    ITF_NUM_HID_KBD,
    ITF_NUM_HID_MOUSE,   // Instance 1: combined mouse (ID 1) + gamepad (ID 2)
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
#define EPNUM_HID_MOUSE  0x84  // Shared: mouse (ID 1) + gamepad (ID 2)

uint8_t const desc_configuration[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_KBD, 5, HID_ITF_PROTOCOL_KEYBOARD, sizeof(desc_hid_report_kbd), EPNUM_HID_KBD, 16, 1),
    TUD_HID_DESCRIPTOR(ITF_NUM_HID_MOUSE, 6, HID_ITF_PROTOCOL_NONE, sizeof(desc_hid_report_combined), EPNUM_HID_MOUSE, 16, 1),
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
};

#define STRING_DESC_ARR_SIZE 7
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
