#pragma once

#include "esp_err.h"

// Initializes Classic Bluetooth + HID Host, scans for Joy-Con, connects,
// and forwards incoming HID reports to joycon_mapper_on_report().
//
// Note: This is a best-effort implementation; Joy-Con pairing/security can vary.
esp_err_t bt_hid_host_start(void);

// Runtime override for the target name substring used during inquiry scan.
// If len==0 or name_substr==NULL, clears the override and falls back to Kconfig.
void bt_hid_host_set_target_substr(const char* name_substr, uint8_t len);

// Triggers a new inquiry scan using the current target substring.
// Safe to call multiple times; cancels an in-progress discovery first.
esp_err_t bt_hid_host_start_discovery(void);
