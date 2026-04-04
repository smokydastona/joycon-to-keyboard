# Wiring (default)

## ESP32 ↔ RP2040 UART

Pick a common ground.

- ESP32 `TX` → ESP32-S3 `RX`
- ESP32 `RX` ← ESP32-S3 `TX` (optional; not used by default)
- ESP32 `GND` ↔ ESP32-S3 `GND`

**Voltage levels:**
- Many ESP32 dev boards are 3.3V UART.
- ESP32-S3 UART is 3.3V.
- Do NOT connect 5V UART without level shifting.

## ESP32-S3 → PC

- Plug ESP32-S3 into PC via USB.
- PC should enumerate it as a USB keyboard (and optionally a CDC COM port).

## Notes

Pin numbers are configured per-firmware; see each firmware README.
