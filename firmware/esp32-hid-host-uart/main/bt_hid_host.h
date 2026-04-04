#pragma once

#include "esp_err.h"

// Initializes Classic Bluetooth + HID Host, scans for Joy-Con, connects,
// and forwards incoming HID reports to joycon_mapper_on_report().
//
// Note: This is a best-effort implementation; Joy-Con pairing/security can vary.
esp_err_t bt_hid_host_start(void);
