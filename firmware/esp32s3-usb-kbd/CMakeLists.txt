cmake_minimum_required(VERSION 3.16)

# Helps VS Code IntelliSense by producing build/compile_commands.json
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Firmware version — CI writes version.txt before building.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/version.txt")
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/version.txt" _fw_ver)
    string(STRIP "${_fw_ver}" PROJECT_VER)
else()
    set(PROJECT_VER "0.0.0-dev")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32s3_usb_kbd)
