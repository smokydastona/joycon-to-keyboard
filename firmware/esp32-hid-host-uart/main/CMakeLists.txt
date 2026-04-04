idf_component_register(
    SRCS
        "app_main.c"
        "bt_hid_host.c"
        "uart_framing.c"
        "joycon_mapper.c"
        "nintendo_candidate.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES bt nvs_flash
)
