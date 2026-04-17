#include "uart_proto.h"

#include <string.h>

#include "driver/uart.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#include "esp_log.h"

static const char* TAG = "uart-proto";

#define SYNC0 0xAA
#define SYNC1 0x55

#define CTRL_MARKER   0xFE
#define DEBUG_MARKER  0xFF
#define STATUS_MARKER 0xFD
#define KEY_EX_MARKER 0xFC
#define OTA_RSP_MARKER 0xFB
#define BATTERY_MARKER 0xFA
#define CONTROLLER_INFO_MARKER 0xF9
#define RSSI_MARKER 0xF8
#define ANALOG_MARKER 0xF7
#define GYRO_MARKER 0xF6
#define CTRL_RSP_MARKER 0xF5

// Keep this comfortably under 255 (len is uint8_t) and large enough for
// status frames that include an optional device name.
#define UART_PAYLOAD_MAX 220

// Event queue depth — only needs a few slots since we drain the FIFO in each
// iteration.  The queue wakes the main loop immediately when data arrives.
#define UART_EVENT_QUEUE_DEPTH 8

static QueueHandle_t s_uart_queue = NULL;
static volatile uint32_t s_total_rx_bytes = 0;
static volatile uint32_t s_total_frames = 0;

static SemaphoreHandle_t s_uart_tx_mutex = NULL;
static portMUX_TYPE s_uart_tx_mutex_init_lock = portMUX_INITIALIZER_UNLOCKED;

static void uart_proto_tx_mutex_init_once(void) {
    if (s_uart_tx_mutex) return;
    portENTER_CRITICAL(&s_uart_tx_mutex_init_lock);
    if (!s_uart_tx_mutex) {
        s_uart_tx_mutex = xSemaphoreCreateMutex();
    }
    portEXIT_CRITICAL(&s_uart_tx_mutex_init_lock);
}

static inline uint8_t xor_checksum(uint8_t length, const uint8_t* payload) {
    uint8_t x = length;
    for (uint8_t i = 0; i < length; i++) {
        x ^= payload[i];
    }
    return x;
}

void uart_proto_init(void) {
    const uart_config_t cfg = {
        .baud_rate = CONFIG_BRIDGE_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    uart_port_t port = (uart_port_t)CONFIG_BRIDGE_UART_PORT;

    ESP_ERROR_CHECK(uart_driver_install(port, 2048, 0,
                                        UART_EVENT_QUEUE_DEPTH,
                                        &s_uart_queue, 0));
    ESP_ERROR_CHECK(uart_param_config(port, &cfg));

    // Reset pins to plain GPIO function before routing bridge UART through
    // the GPIO matrix.  This is a safety measure in case the bootloader or
    // another peripheral left an I/O MUX assignment on these pins.
    gpio_reset_pin((gpio_num_t)CONFIG_BRIDGE_UART_TX_GPIO);
    gpio_reset_pin((gpio_num_t)CONFIG_BRIDGE_UART_RX_GPIO);

    ESP_ERROR_CHECK(uart_set_pin(port, CONFIG_BRIDGE_UART_TX_GPIO, CONFIG_BRIDGE_UART_RX_GPIO,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));

    uart_proto_tx_mutex_init_once();

    ESP_LOGI(TAG, "UART ready: port=%d baud=%d RX_GPIO=%d TX_GPIO=%d",
             CONFIG_BRIDGE_UART_PORT,
             CONFIG_BRIDGE_UART_BAUD,
             CONFIG_BRIDGE_UART_RX_GPIO,
             CONFIG_BRIDGE_UART_TX_GPIO);
}

static void uart_proto_send_frame(const uint8_t* payload, uint8_t length) {
    if (!payload || length == 0) {
        return;
    }

    uart_proto_tx_mutex_init_once();
    if (s_uart_tx_mutex) {
        xSemaphoreTake(s_uart_tx_mutex, portMAX_DELAY);
    }

    uart_port_t port = (uart_port_t)CONFIG_BRIDGE_UART_PORT;

    // Frame format: AA 55 <len> <payload...> <checksum>
    uint8_t header[3] = {SYNC0, SYNC1, length};
    uint8_t checksum = xor_checksum(length, payload);

    uart_write_bytes(port, (const char*)header, sizeof(header));
    uart_write_bytes(port, (const char*)payload, length);
    uart_write_bytes(port, (const char*)&checksum, 1);

    if (s_uart_tx_mutex) {
        xSemaphoreGive(s_uart_tx_mutex);
    }
}

bool uart_proto_send_ctrl(uint8_t cmd_id, const uint8_t* data, uint8_t data_len) {
    // payload = 0xFE, cmd_id, data...
    if (data_len > (uint8_t)(UART_PAYLOAD_MAX - 2)) {
        return false;
    }

    static uint8_t buf[UART_PAYLOAD_MAX];
    buf[0] = CTRL_MARKER;
    buf[1] = cmd_id;
    if (data_len && data) {
        memcpy(&buf[2], data, data_len);
    }
    uart_proto_send_frame(buf, (uint8_t)(2 + data_len));
    return true;
}

bool uart_proto_poll_frame(uart_frame_t* out) {
    static uint8_t state = 0;
    static uint8_t length = 0;
    static uint8_t payload[UART_PAYLOAD_MAX];
    static uint8_t payload_i = 0;

    if (!out) return false;

    uart_port_t port = (uart_port_t)CONFIG_BRIDGE_UART_PORT;

    uint8_t b;
    int got;

    while ((got = uart_read_bytes(port, &b, 1, 0)) == 1) {
        s_total_rx_bytes++;
        switch (state) {
            case 0:
                state = (b == SYNC0) ? 1 : 0;
                break;
            case 1:
                state = (b == SYNC1) ? 2 : 0;
                break;
            case 2:
                length = b;
                payload_i = 0;
                if (length == 0 || length > sizeof(payload)) {
                    state = 0;
                } else {
                    state = 3;
                }
                break;
            case 3:
                payload[payload_i++] = b;
                if (payload_i >= length) {
                    state = 4;
                }
                break;
            case 4: {
                uint8_t calc = xor_checksum(length, payload);
                state = 0;
                if (calc != b) {
                    break;
                }

                out->length = length;
                out->payload = payload;

                if (length == 1) {
                    out->type = UART_FRAME_KEY_EVENT;
                } else if (length == 4 && payload[0] == KEY_EX_MARKER) {
                    out->type = UART_FRAME_KEY_EVENT_EX;
                } else if (payload[0] == OTA_RSP_MARKER) {
                    out->type = UART_FRAME_OTA_RSP;
                } else if (payload[0] == BATTERY_MARKER) {
                    out->type = UART_FRAME_BATTERY;
                } else if (payload[0] == CONTROLLER_INFO_MARKER) {
                    out->type = UART_FRAME_CONTROLLER_INFO;
                } else if (payload[0] == RSSI_MARKER) {
                    out->type = UART_FRAME_RSSI;
                } else if (payload[0] == ANALOG_MARKER) {
                    out->type = UART_FRAME_ANALOG;
                } else if (payload[0] == GYRO_MARKER) {
                    out->type = UART_FRAME_GYRO;
                } else if (payload[0] == CTRL_RSP_MARKER) {
                    out->type = UART_FRAME_CTRL_RSP;
                } else if (payload[0] == DEBUG_MARKER) {
                    out->type = UART_FRAME_DEBUG;
                } else if (payload[0] == STATUS_MARKER) {
                    out->type = UART_FRAME_STATUS;
                } else {
                    out->type = UART_FRAME_UNKNOWN;
                }
                s_total_frames++;
                return true;
            }
            default:
                state = 0;
                break;
        }
    }

    return false;
}

bool uart_proto_wait(uint32_t timeout_ticks) {
    if (!s_uart_queue) {
        vTaskDelay(timeout_ticks);
        return false;
    }

    uart_event_t evt;
    // Block until UART data arrives or the timeout expires.
    // We don't inspect the event type — any UART activity (data, parity
    // error, FIFO overflow, etc.) should trigger a poll cycle.
    if (xQueueReceive(s_uart_queue, &evt, (TickType_t)timeout_ticks) == pdTRUE) {
        // Drain any additional queued events so we handle a burst in one
        // poll cycle instead of waking once per event.
        while (xQueueReceive(s_uart_queue, &evt, 0) == pdTRUE) {
            // discard — we'll drain the FIFO in poll_frame anyway
        }
        return true;
    }
    return false;  // timeout
}

void uart_proto_get_diag(uart_diag_t *diag) {
    if (!diag) return;
    memset(diag, 0, sizeof(*diag));

    diag->rx_gpio = CONFIG_BRIDGE_UART_RX_GPIO;
    diag->tx_gpio = CONFIG_BRIDGE_UART_TX_GPIO;
    diag->baud    = CONFIG_BRIDGE_UART_BAUD;
    diag->port    = CONFIG_BRIDGE_UART_PORT;

    // Current logic level on the RX pin (idle UART should be HIGH = 1)
    diag->rx_pin_level = gpio_get_level((gpio_num_t)CONFIG_BRIDGE_UART_RX_GPIO);

    // Bytes already sitting in the driver RX ring buffer
    uart_port_t port = (uart_port_t)CONFIG_BRIDGE_UART_PORT;
    uart_get_buffered_data_len(port, &diag->buffered_bytes);

    // Cumulative counters since boot
    diag->total_rx_bytes = s_total_rx_bytes;
    diag->total_frames   = s_total_frames;

    // Try to grab a few raw bytes with a short timeout (100 ms)
    int n = uart_read_bytes(port, diag->sample, sizeof(diag->sample),
                            pdMS_TO_TICKS(100));
    diag->sample_len = (n > 0) ? n : 0;
}
