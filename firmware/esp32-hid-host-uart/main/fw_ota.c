#include "fw_ota.h"

#include "esp_log.h"
#include "esp_ota_ops.h"

static const char *TAG = "fw-ota";

#ifndef FW_VERSION
#define FW_VERSION "0.0.0-dev"
#endif

static esp_ota_handle_t s_handle = 0;
static const esp_partition_t *s_part = NULL;
static bool s_active = false;

const char *fw_ota_version(void) {
    return FW_VERSION;
}

esp_err_t fw_ota_begin(uint32_t total_size) {
    if (s_active) {
        fw_ota_abort();
    }

    s_part = esp_ota_get_next_update_partition(NULL);
    if (!s_part) {
        ESP_LOGE(TAG, "No OTA update partition found");
        return ESP_ERR_NOT_FOUND;
    }

    esp_err_t err = esp_ota_begin(s_part,
                                  total_size ? (size_t)total_size : OTA_SIZE_UNKNOWN,
                                  &s_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_begin failed: %s", esp_err_to_name(err));
        return err;
    }

    s_active = true;
    ESP_LOGI(TAG, "OTA begin: partition=%s size=%lu",
             s_part->label, (unsigned long)total_size);
    return ESP_OK;
}

esp_err_t fw_ota_write(const uint8_t *data, uint32_t len) {
    if (!s_active) return ESP_ERR_INVALID_STATE;
    return esp_ota_write(s_handle, data, (size_t)len);
}

esp_err_t fw_ota_end(void) {
    if (!s_active) return ESP_ERR_INVALID_STATE;

    esp_err_t err = esp_ota_end(s_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_end (validate) failed: %s", esp_err_to_name(err));
        s_active = false;
        return err;
    }

    err = esp_ota_set_boot_partition(s_part);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "set_boot_partition failed: %s", esp_err_to_name(err));
    } else {
        ESP_LOGI(TAG, "OTA complete – boot partition set to %s", s_part->label);
    }
    s_active = false;
    return err;
}

void fw_ota_abort(void) {
    if (s_active) {
        esp_ota_abort(s_handle);
        s_active = false;
        ESP_LOGW(TAG, "OTA aborted");
    }
}

bool fw_ota_in_progress(void) {
    return s_active;
}
