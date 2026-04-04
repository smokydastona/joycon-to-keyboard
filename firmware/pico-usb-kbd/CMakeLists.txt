cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(pico_usb_kbd C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(pico_usb_kbd
    src/main.c
    src/usb_descriptors.c
    src/uart_proto.c
)

target_include_directories(pico_usb_kbd PRIVATE src)

target_link_libraries(pico_usb_kbd
    pico_stdlib
    hardware_uart
    tinyusb_device
    tinyusb_board
)

pico_enable_stdio_uart(pico_usb_kbd 0)
pico_enable_stdio_usb(pico_usb_kbd 0)

pico_add_extra_outputs(pico_usb_kbd)
