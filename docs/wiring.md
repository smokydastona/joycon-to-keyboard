# Wiring (default)

## ESP32 ↔ RP2040 UART

Pick a common ground.

- ESP32 `TX` → RP2040 `RX`
- ESP32 `RX` ← RP2040 `TX` (optional; not used by default)
- ESP32 `GND` ↔ RP2040 `GND`

**Voltage levels:**
- Many ESP32 dev boards are 3.3V UART.
- RP2040 UART is 3.3V.
- Do NOT connect 5V UART to RP2040 without level shifting.

## RP2040 → PC

- Plug RP2040 into PC via USB.
- PC should enumerate it as a USB keyboard.

## Notes

Pin numbers are configured per-firmware; see each firmware README.
