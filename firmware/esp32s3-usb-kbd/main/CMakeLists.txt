idf_component_register(
    SRCS
        "app_main.c"
        "bridge_serial.c"
        "fw_ota.c"
        "profile_runtime.c"
        "uart_proto.c"
        "usb_kbd.c"
        "keymap.c"
        "tusb_desc.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES driver esp_tinyusb nvs_flash json app_update mbedtls
)

# Pass firmware version to code as FW_VERSION macro.
target_compile_definitions(${COMPONENT_LIB} PRIVATE FW_VERSION=\"${PROJECT_VER}\")
