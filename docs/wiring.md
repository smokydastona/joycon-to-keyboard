# Wiring (detailed)

This project is designed to be a **single USB dongle** that contains **two boards**:

- **ESP32 (Classic Bluetooth HID host)**: connects wirelessly to your Joy-Con / compatible controller.
- **ESP32-S3 (USB device / keyboard)**: plugs into the PC and enumerates as a **real USB HID keyboard**.

The boards talk over **3.3V UART**. The ESP32-S3 also provides **power** to the ESP32 so the whole adapter can run from **one USB plug**.

## Big picture (what plugs into what)

- **Only the ESP32-S3 plugs into the PC via USB.**
  - The PC sees a keyboard (HID).
  - Optionally, the PC also sees a COM port (USB CDC-ACM) for the helper app.
- The ESP32 (Classic-BT host) is powered inside the dongle and never needs to connect to the PC.

## Minimum required connections (works today)

You need **three wires** for a working adapter:

1) **Power**
	- ESP32-S3 `5V/VUSB` → ESP32 `VIN/5V`
2) **Ground reference**
	- ESP32-S3 `GND` → ESP32 `GND`
3) **UART data (controller → keyboard)**
	- ESP32 `TX` → ESP32-S3 `RX`

That’s enough for: Joy-Con/Binbok → ESP32 → UART → ESP32-S3 → USB keyboard.

## Recommended connections (better / future-proof)

Add the reverse UART line so the ESP32-S3 can send commands back later (optional; not required for basic key output):

- ESP32-S3 `TX` → ESP32 `RX`

## Pin defaults used by this repo

These are the defaults you’ll get without changing `menuconfig`.

### ESP32 (Classic-BT host)

From `firmware/esp32-hid-host-uart/README.md`:

- UART baud: `115200`
- ESP32 `TX`: **GPIO17**
- ESP32 `RX`: **GPIO16** (unused by default)

### Arduino Nano ESP32-S3 (ABX00083)

From `docs/arduino-nano-esp32-setup.md`:

- Nano `RX0` = **GPIO44** (this is what ESP-IDF `menuconfig` wants)
- Nano `TX0` = **GPIO43**

So the default “minimum wiring” becomes:

- ESP32 GPIO17 (TX) → Nano RX0 (GPIO44)
- GND ↔ GND
- Nano 5V/VUSB → ESP32 VIN/5V

## Exact pin-to-pin wiring (matches `pinouts.png`)

If you are using the exact boards shown in `pinouts.png`:

- **Arduino Nano ESP32-S3** (USB HID keyboard side)
- **NodeMCU ESP32-WROOM-32** (Bluetooth host side)

Wire them like this.

### Power (one USB dongle)

This is what makes it a *single dongle*: the Nano powers the NodeMCU.

- Nano **VUSB (OUT)** → NodeMCU **5V**
- Nano **GND** → NodeMCU **GND**

### UART data (ESP32 → ESP32-S3)

- NodeMCU **UART2_TX (GPIO17)** → Nano **D0 / RX0 (GPIO44)**

### Optional return UART (ESP32-S3 → ESP32)

Not required for basic one-way key output.

Required if you want the **helper app to initiate controller connect/scan** (no button presses on the boards).

- Nano **D1 / TX0 (GPIO43)** → NodeMCU **UART2_RX (GPIO16)**

## Voltage levels (important)

- UART signals on both chips are **3.3V logic**.
- **Do not** connect any 5V signal into an RX/TX UART pin.
- Power is **5V** (USB) going into the dev-board regulator on the ESP32 board.

If your ESP32 dev board has a 5V-tolerant *power* pin labeled `VIN` / `5V`, that’s what you want for power.
Do **not** power the ESP32 by feeding 5V into a `3V3` pin.

## One-USB-dongle power model (how it stays “one dongle”)

The ESP32-S3 is the “front” of the dongle:

- PC USB provides 5V to the ESP32-S3 board.
- ESP32-S3 board exposes that 5V on `5V`/`VUSB` header pin.
- That 5V powers the ESP32 board through its `VIN`/`5V` pin.

**Avoid double-powering:** don’t also plug the ESP32 into its own micro-USB while it’s being powered from the ESP32-S3.

## Physical build tips (to make it reliable)

- Keep UART wires short (a few cm) and route `GND` next to the UART line when possible.
- If you see random disconnects or garbage bytes:
  - confirm **common ground** is connected,
  - confirm UART baud is `115200` on both ends,
  - confirm you did not accidentally swap RX/TX,
  - confirm you did not connect to a UART pin that is shared with bootstrapping on your ESP32 dev board.

## Sanity checks (fast)

1) With both boards wired and only the ESP32-S3 plugged into USB:
	- ESP32 power LED should turn on (powered through VIN).
2) PC should enumerate the ESP32-S3 as:
	- a **USB keyboard** (HID)
	- optionally a **COM port** (CDC-ACM)
3) With ESP32 firmware running:
	- you should see BT discovery/connect logs in `idf.py monitor`.

## Where to configure pins

- ESP32-S3 UART GPIOs + baud: `idf.py menuconfig` in `firmware/esp32s3-usb-kbd/`
- ESP32 UART TX/RX GPIOs: `firmware/esp32-hid-host-uart/main/config.h`

See also:

- `docs/serial-protocol.md` (UART frame format)
