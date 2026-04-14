#include "installer_console.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <sys/time.h>
#include <unistd.h>

#include "config.h"

#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "installer";

#define HOST_ESCAPE_GUARD_MS 900
#define HOST_LINE_MAX        96

static volatile bool s_passthrough_active = false;

static void console_write_line(const char *line) {
    if (!line) {
        return;
    }
    write(STDOUT_FILENO, line, strlen(line));
    write(STDOUT_FILENO, "\r\n", 2);
}

static void set_passthrough_logging(bool active) {
    s_passthrough_active = active;
    esp_log_level_set("*", active ? ESP_LOG_NONE : (esp_log_level_t)CONFIG_LOG_DEFAULT_LEVEL);
}

static inline int64_t now_ms(void) {
    return esp_timer_get_time() / 1000;
}

static void installer_drive_idle(void) {
    gpio_set_level(INSTALLER_S3_BOOT_GPIO, 1);
    gpio_set_level(INSTALLER_S3_RESET_GPIO, 1);
}

static void installer_enter_download_mode(void) {
    gpio_set_level(INSTALLER_S3_BOOT_GPIO, 0);
    gpio_set_level(INSTALLER_S3_RESET_GPIO, 0);
    vTaskDelay(pdMS_TO_TICKS(50));
    gpio_set_level(INSTALLER_S3_RESET_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(80));
    gpio_set_level(INSTALLER_S3_BOOT_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(80));
}

static void installer_enter_run_mode(void) {
    gpio_set_level(INSTALLER_S3_BOOT_GPIO, 1);
    gpio_set_level(INSTALLER_S3_RESET_GPIO, 0);
    vTaskDelay(pdMS_TO_TICKS(50));
    gpio_set_level(INSTALLER_S3_RESET_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(100));
}

static int read_host_bytes(uint8_t *buf, size_t len, int timeout_ms) {
    if (!buf || len == 0) {
        return 0;
    }

    fd_set rfds;
    FD_ZERO(&rfds);
    FD_SET(STDIN_FILENO, &rfds);

    struct timeval tv = {
        .tv_sec = timeout_ms / 1000,
        .tv_usec = (timeout_ms % 1000) * 1000,
    };

    int ready = select(STDIN_FILENO + 1, &rfds, NULL, NULL, &tv);
    if (ready <= 0 || !FD_ISSET(STDIN_FILENO, &rfds)) {
        return 0;
    }

    int got = (int)read(STDIN_FILENO, buf, len);
    return got > 0 ? got : 0;
}

static void passthrough_loop(void) {
    uint8_t host_buf[128];
    uint8_t bridge_buf[128];
    int plus_count = 0;
    bool plus_armed = false;
    int64_t plus_started_ms = 0;
    int64_t last_host_rx_ms = now_ms();

    set_passthrough_logging(true);

    while (1) {
        size_t pending = 0;
        if (uart_get_buffered_data_len(BRIDGE_UART_PORT, &pending) == ESP_OK && pending > 0) {
            int got_bridge = uart_read_bytes(BRIDGE_UART_PORT, bridge_buf,
                                             pending > sizeof(bridge_buf) ? sizeof(bridge_buf) : pending,
                                             0);
            if (got_bridge > 0) {
                write(STDOUT_FILENO, bridge_buf, (size_t)got_bridge);
            }
        }

        int got_host = read_host_bytes(host_buf, sizeof(host_buf), 10);
        int64_t now = now_ms();

        if (plus_armed && plus_count == 3 && (now - plus_started_ms) >= HOST_ESCAPE_GUARD_MS) {
            break;
        }

        if (got_host <= 0) {
            continue;
        }

        if (plus_armed && plus_count > 0 && plus_count < 3 && (now - plus_started_ms) >= HOST_ESCAPE_GUARD_MS) {
            uart_write_bytes(BRIDGE_UART_PORT, "+", plus_count);
            plus_armed = false;
            plus_count = 0;
        }

        for (int i = 0; i < got_host; i++) {
            uint8_t b = host_buf[i];
            int64_t gap_ms = now - last_host_rx_ms;
            last_host_rx_ms = now;

            if (!plus_armed && b == '+' && gap_ms >= HOST_ESCAPE_GUARD_MS) {
                plus_armed = true;
                plus_started_ms = now;
                plus_count = 1;
                continue;
            }

            if (plus_armed) {
                if (b == '+' && plus_count < 3) {
                    plus_count++;
                    continue;
                }

                if (plus_count > 0) {
                    uart_write_bytes(BRIDGE_UART_PORT, "+", plus_count);
                }
                plus_armed = false;
                plus_count = 0;
            }

            uart_write_bytes(BRIDGE_UART_PORT, (const char *)&b, 1);
        }
    }

    set_passthrough_logging(false);
    console_write_line("BBI OK BRIDGE_STOP");
}

static void handle_command(const char *line) {
    if (!line || strncmp(line, "BBI ", 4) != 0) {
        return;
    }

    const char *cmd = line + 4;
    while (*cmd == ' ') {
        cmd++;
    }

    if (strcmp(cmd, "HELLO") == 0) {
        char rsp[160];
        snprintf(rsp, sizeof(rsp),
                 "BBI OK HELLO fw=%s bridge_tx=%d bridge_rx=%d s3_boot=%d s3_reset=%d mode=%s",
                 FW_VERSION,
                 BRIDGE_UART_TX_GPIO,
                 BRIDGE_UART_RX_GPIO,
                 INSTALLER_S3_BOOT_GPIO,
                 INSTALLER_S3_RESET_GPIO,
                 s_passthrough_active ? "bridge" : "command");
        console_write_line(rsp);
        return;
    }

    if (strcmp(cmd, "STATUS") == 0) {
        char rsp[96];
        snprintf(rsp, sizeof(rsp), "BBI OK STATUS mode=%s", s_passthrough_active ? "bridge" : "command");
        console_write_line(rsp);
        return;
    }

    if (strcmp(cmd, "S3_DOWNLOAD") == 0) {
        installer_enter_download_mode();
        console_write_line("BBI OK S3_DOWNLOAD");
        return;
    }

    if (strcmp(cmd, "S3_RUN") == 0) {
        installer_enter_run_mode();
        console_write_line("BBI OK S3_RUN");
        return;
    }

    if (strcmp(cmd, "BRIDGE_START") == 0) {
        console_write_line("BBI OK BRIDGE_START");
        vTaskDelay(pdMS_TO_TICKS(50));
        passthrough_loop();
        return;
    }

    console_write_line("BBI ERR UNKNOWN_COMMAND");
}

static void installer_console_task(void *arg) {
    (void)arg;

    uint8_t b = 0;
    char line[HOST_LINE_MAX];
    size_t pos = 0;

    console_write_line("BBI READY");

    while (1) {
        int got = (int)read(STDIN_FILENO, &b, 1);
        if (got != 1) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        if (b == '\r' || b == '\n') {
            if (pos > 0) {
                line[pos] = '\0';
                handle_command(line);
                pos = 0;
            }
            continue;
        }

        if (!isprint((int)b)) {
            pos = 0;
            continue;
        }

        if (pos + 1 >= sizeof(line)) {
            pos = 0;
            continue;
        }

        line[pos++] = (char)b;
    }
}

void installer_console_init(void) {
    const gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << INSTALLER_S3_BOOT_GPIO) | (1ULL << INSTALLER_S3_RESET_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_ERROR_CHECK(gpio_config(&cfg));
    installer_drive_idle();

    xTaskCreate(installer_console_task, "installer_console", 6144, NULL, 5, NULL);

    ESP_LOGI(TAG, "Installer console ready on UART0 (S3 BOOT=%d RESET=%d)",
             INSTALLER_S3_BOOT_GPIO, INSTALLER_S3_RESET_GPIO);
}

bool installer_console_passthrough_active(void) {
    return s_passthrough_active;
}