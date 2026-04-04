cmake_minimum_required(VERSION 3.16)

# Helps VS Code IntelliSense by producing build/compile_commands.json
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ESP-IDF build system
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32_hid_host_uart)
