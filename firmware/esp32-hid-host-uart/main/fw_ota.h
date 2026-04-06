#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

// Compile-time firmware version string.
const char *fw_ota_version(void);

// Begin an OTA update.  total_size = expected image size in bytes (or 0 for unknown).
esp_err_t fw_ota_begin(uint32_t total_size);

// Write a chunk of firmware data to the OTA partition.
esp_err_t fw_ota_write(const uint8_t *data, uint32_t len);

// Finalize: validate image, set boot partition.  Caller should reboot afterwards.
esp_err_t fw_ota_end(void);

// Abort an in-progress OTA update.
void fw_ota_abort(void);

// Returns true while an OTA session is open.
bool fw_ota_in_progress(void);

// Mark the running firmware as valid, cancelling automatic rollback.
// Call once early in app_main after basic self-test passes.
void fw_ota_mark_valid(void);
