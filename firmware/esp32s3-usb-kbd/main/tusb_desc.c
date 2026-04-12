#include "tusb.h"

// Device descriptor (non-static so usb_kbd.c can pass it to tinyusb_driver_install)
tusb_desc_device_t const desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0201,  // 2.01 required for BOS descriptor (MS OS 2.0)

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

// ============================================================
// Microsoft OS 2.0 Descriptors
//
// These cause Windows 8.1/10/11 to automatically write the
// correct FriendlyName for each USB interface into the registry
// on first plug-in — no driver installation or registry editing
// needed by the user.
//
// Interface mapping (matches ITF_NUM_* enum):
//   0 = CDC control (Architect -> COM port)
//   2 = HID Keyboard (Composer)
//   3 = HID Mouse    (Forger)
//   4 = HID Gamepad  (Executor)
// ============================================================

#define MS_OS_20_VENDOR_CODE 0x01

// UTF-16LE "DeviceFriendlyName\0" — 18 chars + NUL = 38 bytes
#define U16LE_PROP_NAME \
    'D',0,'e',0,'v',0,'i',0,'c',0,'e',0, \
    'F',0,'r',0,'i',0,'e',0,'n',0,'d',0,'l',0,'y',0, \
    'N',0,'a',0,'m',0,'e',0, 0,0

// Descriptor sizes:
//   SET_HEADER        =  10
//   SUBSET_HEADER_FN  =   8
//   REG_PROP base     =  10 (wLen+wType+wPropDataType+wPropNameLen+wPropDataLen)
//   PropName          =  38 (U16LE "DeviceFriendlyName\0")
//   "Architect\0"     =  20 bytes UTF-16LE
//   "Composer\0"      =  18 bytes UTF-16LE
//   "Forger\0"        =  14 bytes UTF-16LE
//   "Executor\0"      =  18 bytes UTF-16LE
//
//   CDC   subset: 8 + (10+38+20) = 76
//   KBD   subset: 8 + (10+38+18) = 74
//   Mouse subset: 8 + (10+38+14) = 70
//   GPad  subset: 8 + (10+38+18) = 74
//   Total: 10 + 76 + 74 + 70 + 74 = 304 = 0x0130
#define MS_OS_20_DESC_LEN 304

static uint8_t const desc_ms_os_20[] = {
    // MS_OS_20_SET_HEADER_DESCRIPTOR (10 bytes)
    0x0A, 0x00,              // wLength = 10
    0x00, 0x00,              // wDescriptorType = 0 (SET_HEADER)
    0x00, 0x00, 0x03, 0x06, // dwWindowsVersion = 0x06030000 (Win 8.1)
    (MS_OS_20_DESC_LEN & 0xFF), ((MS_OS_20_DESC_LEN >> 8) & 0xFF),  // wTotalLength

    // === CDC "Architect" (bFirstInterface = 0) ===
    0x08, 0x00,              // wLength = 8
    0x02, 0x00,              // wDescriptorType = 2 (SUBSET_HEADER_FUNCTION)
    0x00,                    // bFirstInterface = 0 (ITF_NUM_CDC)
    0x00,                    // bReserved
    0x4C, 0x00,             // wSubsetLength = 76
    // REG_PROPERTY DeviceFriendlyName = "Architect" (68 bytes)
    0x44, 0x00,              // wLength = 68
    0x04, 0x00,              // wDescriptorType = 4 (FEATURE_REG_PROPERTY)
    0x01, 0x00,              // wPropertyDataType = 1 (REG_SZ)
    0x26, 0x00,              // wPropertyNameLength = 38
    U16LE_PROP_NAME,         // "DeviceFriendlyName\0"
    0x14, 0x00,              // wPropertyDataLength = 20
    'A',0,'r',0,'c',0,'h',0,'i',0,'t',0,'e',0,'c',0,'t',0,0,0,

    // === HID Keyboard "Composer" (bFirstInterface = 2) ===
    0x08, 0x00,
    0x02, 0x00,
    0x02,                    // bFirstInterface = 2 (ITF_NUM_HID_KBD)
    0x00,
    0x4A, 0x00,             // wSubsetLength = 74
    // REG_PROPERTY DeviceFriendlyName = "Composer" (66 bytes)
    0x42, 0x00,              // wLength = 66
    0x04, 0x00,
    0x01, 0x00,
    0x26, 0x00,              // wPropertyNameLength = 38
    U16LE_PROP_NAME,
    0x12, 0x00,              // wPropertyDataLength = 18
    'C',0,'o',0,'m',0,'p',0,'o',0,'s',0,'e',0,'r',0,0,0,

    // === HID Mouse "Forger" (bFirstInterface = 3) ===
    0x08, 0x00,
    0x02, 0x00,
    0x03,                    // bFirstInterface = 3 (ITF_NUM_HID_MOUSE)
    0x00,
    0x46, 0x00,             // wSubsetLength = 70
    // REG_PROPERTY DeviceFriendlyName = "Forger" (62 bytes)
    0x3E, 0x00,              // wLength = 62
    0x04, 0x00,
    0x01, 0x00,
    0x26, 0x00,              // wPropertyNameLength = 38
    U16LE_PROP_NAME,
    0x0E, 0x00,              // wPropertyDataLength = 14
    'F',0,'o',0,'r',0,'g',0,'e',0,'r',0,0,0,

    // === HID Gamepad "Executor" (bFirstInterface = 4) ===
    0x08, 0x00,
    0x02, 0x00,
    0x04,                    // bFirstInterface = 4 (ITF_NUM_HID_GAMEPAD)
    0x00,
    0x4A, 0x00,             // wSubsetLength = 74
    // REG_PROPERTY DeviceFriendlyName = "Executor" (66 bytes)
    0x42, 0x00,              // wLength = 66
    0x04, 0x00,
    0x01, 0x00,
    0x26, 0x00,              // wPropertyNameLength = 38
    U16LE_PROP_NAME,
    0x12, 0x00,              // wPropertyDataLength = 18
    'E',0,'x',0,'e',0,'c',0,'u',0,'t',0,'o',0,'r',0,0,0,
};

_Static_assert(sizeof(desc_ms_os_20) == MS_OS_20_DESC_LEN,
               "MS_OS_20_DESC_LEN must match the actual descriptor size");

// BOS descriptor — points Windows to the MS OS 2.0 descriptor set.
// Total = 5 (BOS header) + 28 (platform capability) = 33 bytes.
#define BOS_TOTAL_LEN 33

static uint8_t const desc_bos[] = {
    // BOS header (5 bytes)
    0x05,        // bLength
    0x0F,        // bDescriptorType: BOS
    0x21, 0x00,  // wTotalLength: 33
    0x01,        // bNumDeviceCaps: 1

    // Platform Capability Descriptor: MS OS 2.0 (28 bytes)
    0x1C,        // bLength: 28
    0x10,        // bDescriptorType: DEVICE_CAPABILITY
    0x05,        // bDevCapabilityType: PLATFORM
    0x00,        // bReserved
    // MS OS 2.0 Platform Capability UUID: {D8DD60DF-4589-4CC7-9CD2-659D9E648A9F}
    0xDF, 0x60, 0xDD, 0xD8,
    0x89, 0x45,
    0xC7, 0x4C,
    0x9C, 0xD2, 0x65, 0x9D, 0x9E, 0x64, 0x8A, 0x9F,
    // dwWindowsVersion: 0x06030000 (Windows 8.1)
    0x00, 0x00, 0x03, 0x06,
    // wMSOSDescriptorSetTotalLength
    (MS_OS_20_DESC_LEN & 0xFF), ((MS_OS_20_DESC_LEN >> 8) & 0xFF),
    // bMS_VendorCode
    MS_OS_20_VENDOR_CODE,
    // bAltEnumCode
    0x00,
};

_Static_assert(sizeof(desc_bos) == BOS_TOTAL_LEN,
               "BOS_TOTAL_LEN must match the actual BOS descriptor size");

uint8_t const* tud_descriptor_bos_cb(void) {
    return desc_bos;
}

// Vendor control request handler — serves the MS OS 2.0 descriptor set
// when Windows requests it after seeing the BOS descriptor.
bool tud_vendor_control_xfer_cb(uint8_t rhport, uint8_t stage,
                                 tusb_control_request_t const* request) {
    if (stage != CONTROL_STAGE_SETUP) return true;

    if (request->bRequest == MS_OS_20_VENDOR_CODE &&
        request->bmRequestType == 0xC0 &&   // Device-to-Host, Vendor, Device
        request->wIndex == 0x0007)          // MS_OS_20_DESCRIPTOR_INDEX
    {
        return tud_control_xfer(rhport, request,
                                (void*)(uintptr_t)desc_ms_os_20,
                                sizeof(desc_ms_os_20));
    }
    return false;
}

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
