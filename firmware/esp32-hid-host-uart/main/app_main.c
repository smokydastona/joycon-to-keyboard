#include <stdint.h>

#include "config.h"

#include "driver/uart.h"
#include "esp_log.h"

#include "joycon_mapper.h"
#include "bt_hid_host.h"
#include "bridge_ctrl.h"

static const char* TAG = "joycon-bridge";

static void uart_init_bridge(void) {
    const uart_config_t cfg = {
        .baud_rate = BRIDGE_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    // Previously this was TX-only (RX buffer size 0). For helper-app control
    // commands (ESP32-S3 -> ESP32), RX must be enabled.
    ESP_ERROR_CHECK(uart_driver_install(BRIDGE_UART_PORT, 2048, 2048, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(BRIDGE_UART_PORT, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(BRIDGE_UART_PORT, BRIDGE_UART_TX_GPIO, BRIDGE_UART_RX_GPIO,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
}

void app_main(void) {
    uart_init_bridge();

    ESP_LOGI(TAG, "UART bridge ready (TX=%d RX=%d baud=%d)", BRIDGE_UART_TX_GPIO, BRIDGE_UART_RX_GPIO,
             BRIDGE_UART_BAUD);

    esp_err_t err = bt_hid_host_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "bt_hid_host_start failed: %s", esp_err_to_name(err));
    }

    bridge_ctrl_init();

    // Idle loop
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
