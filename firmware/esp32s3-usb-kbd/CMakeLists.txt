cmake_minimum_required(VERSION 3.16)

# Helps VS Code IntelliSense by producing build/compile_commands.json
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32s3_usb_kbd)
