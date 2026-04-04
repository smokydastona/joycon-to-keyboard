idf_component_register(
    SRCS
        "app_main.c"
        "bridge_serial.c"
        "uart_proto.c"
        "usb_kbd.c"
        "keymap.c"
        "tusb_desc.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES driver tinyusb nvs_flash json
)
