# Firmware install / flashing guide

This guide covers all the ways to get firmware onto your ESP32 boards.

---

## Web Flasher — First-Time Setup (recommended)

The **Bind Bandit Web Flasher** is the primary way to flash both boards for the first time. No installs, no command line, no drivers needed.

1. Open the Web Flasher: <https://smokydastona.github.io/joycon-to-keyboard/>
2. Use **Google Chrome** or **Microsoft Edge** (Web Serial required).

### ESP32-S3 (USB HID Device) — Arduino Nano ESP32

3. Plug in the board via **USB-C**.
4. **Double-tap the RESET button** quickly (< 300 ms) — a new COM port appears.
5. Click **Connect & Install ESP32-S3** and select the *new* port.

### ESP32 (Bluetooth Host) — NodeMCU-32S / WROOM-32

6. Plug in the board via USB.
7. **Hold BOOT → tap RESET → release BOOT** to enter download mode.
8. Click **Connect & Install ESP32** and select the port (usually "CP210x" or "CH340").

The web flasher erases all flash (clean NVS) by default — recommended for new boards. After flashing, wire the boards together per `docs/wiring.md`.

---

## OTA Updates (after initial flash)

After the initial flash, all firmware updates are handled by the **Bind Bandit helper app** — no need to revisit the web flasher or enter download mode.

1. Connect the ESP32-S3 to your PC via USB.
2. Open Bind Bandit and connect to the COM port.
3. Go to **Diagnostics → Firmware Update → Check Versions**.
4. If an update is available, click **Update Firmware**.

The app automatically checks if firmware matches the app version and prompts for updates when needed.

---

## Manual ESP-IDF Flash (advanced)

This section is intentionally detailed and assumes you want a **single custom USB dongle**:

- The **ESP32-S3** is the only board that plugs into the PC by USB.
- The **ESP32 (Classic BT)** lives inside the dongle, is powered from the ESP32-S3, and connects wirelessly to the controller.

If you haven’t read it yet, start with:

- `docs/wiring.md` (physical wiring + one-USB power model)

---

## What you’re flashing (two firmwares)

### 1) ESP32-S3 (USB HID device)

Folder:

- `firmware/esp32s3-usb-kbd/`

What it does:

- Enumerates as a **real USB HID keyboard** (anti-cheat-safe hardware input)
- Also enumerates as a **USB HID mouse** and **USB HID gamepad** (still hardware HID)
- Receives UART frames from the ESP32 and turns them into HID key events
- Also enumerates as a **USB serial COM port** (CDC-ACM) for the helper app

### 2) ESP32 (Bluetooth Classic HID host)

Folder:

- `firmware/esp32-hid-host-uart/`

What it does:

- Scans for / connects to a controller over **Bluetooth Classic HID**
- Captures incoming HID reports (for evidence-based mapping)
- Emits UART frames to the ESP32-S3

---

## Prerequisites

### Hardware prerequisites

- ESP32-S3 USB device board (example: Arduino Nano ESP32-S3 ABX00083)
- ESP32 Classic-BT capable dev board (example: NodeMCU-32S ESP-WROOM-32)
- UART wiring between the boards (at minimum: power + GND + ESP32 TX → ESP32-S3 RX)

### Software prerequisites

1) **ESP-IDF installed for Windows**

You can install ESP-IDF via Espressif’s installer (recommended on Windows). After installation, you should have an “ESP-IDF PowerShell” (or equivalent) shortcut that opens a shell with the environment set up.

2) **USB drivers (Windows)**

- Many ESP32 dev boards use a USB-to-UART chip (CP2102/CH340). If `idf.py flash` can’t see the port, you may need the correct driver.
- The Arduino Nano ESP32-S3 typically enumerates as a native USB device and may appear as a COM port without extra drivers, but that varies by Windows version.

3) **A working Git checkout of this repo**

You’re already in it.

---

## General workflow: build → flash → monitor

The usual ESP-IDF loop is:

1) `idf.py set-target ...` (only needed once per project folder)
2) `idf.py menuconfig` (configure GPIOs / behavior)
3) `idf.py build`
4) `idf.py flash monitor`

Notes:

- Do **ESP32-S3 first**, because it’s the “front” of the dongle (USB HID device to PC).
- You can do everything from the ESP-IDF PowerShell.

---

## Step-by-step: ESP32-S3 USB HID device firmware

### A) Connect the ESP32-S3 to your PC

- Plug the ESP32-S3 into USB.
- Confirm Windows sees it (Device Manager):
   - it should show a **USB keyboard + mouse + gamepad** device after firmware is flashed
  - and usually a **COM port** (CDC-ACM) once running

If it’s brand new and unflashed, it may not yet enumerate as the final composite device until you flash this repo’s firmware.

### B) Build + flash

From the repo root, open a terminal in:

- `firmware/esp32s3-usb-kbd/`

Then run:

```powershell
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py flash monitor
```

If you get prompted to pick a COM port, choose the port that corresponds to the ESP32-S3.

### C) Required settings (menuconfig)

Open:

- `idf.py menuconfig`

Then check these settings:

1) **UART RX/TX GPIO numbers**

Menu path:

- `Bind Bandit (ESP32-S3 USB Keyboard)`

Set:

- `Bridge UART RX GPIO`
- `Bridge UART TX GPIO` (optional for now, but recommended if you wired it)
- `Bridge UART baud` = `921600`

If you’re using **Arduino Nano ESP32-S3 (ABX00083)**:

- `D2` = `GPIO5`  (bridge RX)
- `D3` = `GPIO6`  (bridge TX)

So set:

- `Bridge UART RX GPIO` = `5`
- `Bridge UART TX GPIO` = `6`

> **Why not D0/D1 (GPIO44/43)?** Those pins are the I/O MUX default for
> UART0. Even with the console disabled, the bootloader briefly
> initialises UART0 on those pins and the I/O MUX assignment shadows the
> GPIO matrix routing used by bridge UART1, silently blocking reception.

2) **UART port selection**

If the project exposes a UART port setting, keep the default unless you know you need a different UART peripheral. The important thing is that the chosen UART is connected to the pins you wired.

### D) Success criteria (ESP32-S3 side)

After flashing, when you plug the ESP32-S3 into the PC:

- It enumerates as a **USB keyboard + mouse + gamepad**.
- If CDC is enabled, it enumerates as a **COM port**.
- `idf.py monitor` shows logs indicating UART receive is running.

---

## Step-by-step: ESP32 Classic-BT HID host firmware

### A) Connect the ESP32 to your PC for flashing

For development you’ll typically flash the ESP32 via its own USB (micro-USB) temporarily.

Important: during development it’s ok to power it from USB while also wired to the ESP32-S3 **as long as you avoid feeding two different 5V sources into VIN**.

The simplest safe approach for flashing:

- Temporarily disconnect the ESP32’s VIN-from-S3 wire while you flash the ESP32 via its own USB.

### B) Build + flash

In a terminal in:

- `firmware/esp32-hid-host-uart/`

Run:

```powershell
idf.py set-target esp32
idf.py menuconfig
idf.py build
idf.py flash monitor
```

Pick the COM port for the ESP32 dev board.

### C) Required settings (menuconfig)

Open:

- `idf.py menuconfig`

Then:

1) **Choose which controller to connect to**

Menu path:

- `Bind Bandit (ESP32 Classic-BT Host)`

Set:

- `Target device name substring`

Defaults to `Joy-Con`.

If you have a third-party controller (Binbok, etc.), set it to something that appears in the device name you see on Windows when pairing, for example:

- `Binbok`
- `Pro Controller`

2) **Discovery scan duration**

If you’re not seeing your device get found, increase:

- `Discovery scan seconds`

3) **Evidence-first report capture (recommended while mapping)**

While you’re still figuring out the HID report layout:

- Keep `Log HID input reports (on change)` enabled.
- Optionally enable `Forward raw HID reports over UART (debug frames)`.

Forwarding over UART is useful when you want to capture reports on the ESP32-S3 side or with the offline decoder in `tools/`.

### D) UART pins (ESP32 side)

The ESP32 firmware’s UART pins are set in:

- `firmware/esp32-hid-host-uart/main/config.h`

Defaults (as of this repo):

- Baud: `921600`
- TX: `GPIO17`
- RX: `GPIO16` (unused)

Make sure your wiring matches.

---

## Put it together as a single dongle (final wiring + power)

Once both firmwares are flashed and validated independently:

1) Unplug the ESP32 from its flashing USB.
2) Wire it for “one dongle” mode:
   - ESP32-S3 `5V/VUSB` → ESP32 `VIN/5V`
   - ESP32-S3 `GND` → ESP32 `GND`
   - ESP32 `TX` → ESP32-S3 `RX`
   - (optional) ESP32-S3 `TX` → ESP32 `RX`
3) Plug only the ESP32-S3 into the PC.

The ESP32 should boot because it’s now powered from the ESP32-S3.

---

## First end-to-end test procedure

This is the fastest way to confirm the whole chain works before any detailed mapping:

1) Plug the ESP32-S3 into the PC.
2) Open `idf.py monitor` for the ESP32-S3 firmware (if you have it connected for logging).
3) Power the ESP32 from the ESP32-S3 (VIN wire connected).
4) Watch the ESP32 logs (during development you can keep it on its own monitor via USB; later you’ll rely less on that).
5) Put the controller into pairing mode and confirm the ESP32 connects.
6) Press buttons and confirm:
   - ESP32 logs show **HID input reports changing**
   - optionally, UART debug frames are present (see `docs/serial-protocol.md`)

At this stage it’s expected that the mapper may not yet emit real keyboard keys; the goal is to confirm you’re receiving stable evidence.

---

## Troubleshooting

### Flashing fails / no COM port found

- Verify the correct Windows driver for the board’s USB-to-UART chip (ESP32 dev boards often need CP210x or CH340 drivers).
- Try a different USB cable (many “charge-only” cables don’t carry data).
- Confirm the COM port number in Device Manager.

### ESP32-S3 flashes but doesn’t enumerate as a keyboard

- Confirm you flashed the `esp32s3-usb-kbd` project (target `esp32s3`).
- If you changed TinyUSB/descriptor settings, double-check enumeration (this repo aims to stay a standard boot keyboard).

### UART garbage / nothing received

- Confirm **GND ↔ GND** between the boards.
- Confirm the baud rate is `921600` on both ends.
- Confirm you did TX → RX (not TX → TX).
- Confirm you used the correct GPIO numbers in `menuconfig` (Nano labels like `D2` are not the same as ESP32-S3 GPIO numbers; for ABX00083 `D2=GPIO5`, `D3=GPIO6`).

### ESP32 finds nothing over Bluetooth

- Increase discovery time in menuconfig.
- Change `Target device name substring` to match your controller’s advertised name.
- Confirm your controller actually uses Bluetooth Classic HID (this repo assumes Classic unless proven BLE HID-over-GATT).

---

## Related docs

- `docs/wiring.md` (detailed wiring + power)
- `docs/serial-protocol.md` (UART frame format)
- `docs/arduino-nano-esp32-setup.md` (Nano pin mapping notes)
- `firmware/esp32-hid-host-uart/README.md` (ESP32 host firmware notes)
- `firmware/esp32s3-usb-kbd/README.md` (ESP32-S3 keyboard firmware notes)
