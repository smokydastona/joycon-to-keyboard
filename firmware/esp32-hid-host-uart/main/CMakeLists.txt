idf_component_register(
    SRCS
        "app_main.c"
        "bt_hid_host.c"
        "bridge_ctrl.c"
        "fw_ota.c"
        "installer_console.c"
        "uart_framing.c"
        "joycon_mapper.c"
        "joycon_setup.c"
        "nintendo_candidate.c"
        "buzzer.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES bt driver nvs_flash app_update
)

# Pass firmware version to code as FW_VERSION macro.
target_compile_definitions(${COMPONENT_LIB} PRIVATE FW_VERSION=\"${PROJECT_VER}\")
