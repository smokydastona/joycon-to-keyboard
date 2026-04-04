# pico-usb-kbd (RP2040)

RP2040 firmware that enumerates as a **USB HID keyboard** and consumes key events over UART from the ESP32.

## Requirements

- Pico SDK installed
- A CMake toolchain (e.g. `arm-none-eabi-gcc`)

## Build (typical)

On Windows you can use a Developer PowerShell:

1) Set `PICO_SDK_PATH`
2) Configure + build:

```powershell
mkdir build
cd build
cmake ..
cmake --build .
```

This produces a `.uf2` you can drag onto the Pico when it’s in BOOTSEL mode.

## UART pins (default)

- UART0 RX: GPIO 1
- UART0 TX: GPIO 0 (unused by default)
- Baud: 115200

You can change these in `src/config.h`.
