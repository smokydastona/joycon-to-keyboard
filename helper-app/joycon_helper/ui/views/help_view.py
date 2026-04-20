"""Help view — searchable, collapsible sections.

Provides 18 sections covering setup, usage, troubleshooting, and reference.
Each section is collapsible and all are filtered by a live search bar.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import ThemeEngine

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.help_view")

# ── Section data ────────────────────────────────────────────────────

_HELP_SECTIONS: list[tuple[str, str, bool]] = []  # populated at module level below


def _sections() -> list[tuple[str, str, bool]]:
    """Return (title, body_text, initially_expanded) tuples."""
    return [
        (
            "🎮 What Is This?",
            (
                "Bind Bandit is an anti-cheat-safe hardware input bridge.\n\n"
                "A wireless controller (Joy-Con / Pro Controller) connects to an ESP32 "
                "board over Bluetooth Classic. That board sends key events over a UART "
                "link to an ESP32-S3 board, which presents itself to the PC as a real "
                "USB HID keyboard + mouse + gamepad.\n\n"
                "## Why hardware?\n"
                "Because the PC sees an actual USB keyboard, not a virtual driver or "
                "injected input, it is fully compatible with anti-cheat systems.\n\n"

                "## Gamepad (Steam / XInput)\n"
                "The ESP32-S3 exposes a standard USB HID gamepad. If you need games to see "
                "an Xbox/XInput controller, enable Steam Input and map this device as an "
                "Xbox controller in Steam.\n\n"
                "This helper app lets you configure key mappings, macros, stick behavior, "
                "and device profiles over a serial connection to the ESP32-S3."
            ),
            True,
        ),
        (
            "🛒 What You Need",
            (
                "## Hardware\n"
                "  ESP32 (Classic Bluetooth) — hosts the Joy-Con/Pro Controller connection\n"
                "  ESP32-S3 (USB OTG) — acts as the USB HID keyboard the PC sees\n"
                "  Two UART wires (TX→RX, RX→TX), two installer wires, plus shared GND between boards\n"
                "  A Joy-Con (L or R) or Nintendo Pro Controller\n"
                "  USB cable for the ESP32 host during first install, then USB-C for the Nano\n"
                "  Passive piezo buzzer (optional — for audible connect/disconnect feedback)\n\n"
                "## Software\n"
                "  ESP-IDF 5.x (for building firmware)\n"
                "  Python 3.10+ (for this helper app)\n"
                "  esptool (bundled with helper app for initial flash)"
            ),
            False,
        ),
        (
            "🔌 Wiring & Connections",
            (
                "## UART wiring between boards\n"
                "  ESP32 GPIO17 (TX) → ESP32-S3 D2 / GPIO5 (RX)\n"
                "  ESP32 GPIO16 (RX) ← ESP32-S3 D3 / GPIO6 (TX)\n"
                "  ESP32 GPIO21 (installer boot) → ESP32-S3 B1 / GPIO0\n"
                "  ESP32 GPIO22 (installer reset) → ESP32-S3 RESET\n"
                "  GND ↔ GND\n\n"
                "## Optional piezo buzzer (ESP32 only)\n"
                "  ESP32 GPIO25 → passive piezo buzzer → GND\n"
                "  Provides audible BT connect/disconnect tones (single chirp on first connect; single chirp when the last device disconnects).\n"
                "  Configurable pin via menuconfig. Can be disabled entirely.\n\n"
                "## USB connection\n"
                "  First install: ESP32 host USB port → PC\n"
                "  Normal use: ESP32-S3 USB port → PC (acts as keyboard + mouse + gamepad + CDC serial)\n\n"
                "## Important\n"
                "The return UART wire (ESP32-S3 TX → ESP32 RX) is required for "
                "helper-app features like bind management, profile sync, and OTA "
                "updates. Without it, basic keyboard output still works.\n\n"
                "Do NOT connect any 5 V signal into the Nano control or UART pins. "
                "Only the Nano VUSB pin should feed the ESP32 VIN/5V power input.\n\n"
                "See docs/wiring.md for a full diagram."
            ),
            False,
        ),
        (
            "📌 Board Pinout Diagram",
            (
                "Refer to docs/wiring.md for detailed pinout diagrams.\n\n"
                "## ESP32 (BT Host)\n"
                "  GPIO16 = UART RX (from S3 TX)\n"
                "  GPIO17 = UART TX (to S3 RX)\n"
                "  GPIO21 = installer BOOT (to Nano B1 / GPIO0)\n"
                "  GPIO22 = installer RESET\n"
                "  GPIO25 = piezo buzzer (optional)\n\n"
                "## ESP32-S3 (USB Device)\n"
                "  GPIO5  = UART RX / D2 (from ESP32 TX)\n"
                "  GPIO6  = UART TX / D3 (to ESP32 RX)\n"
                "  B1 / GPIO0 = installer boot strap input\n"
                "  RESET = installer reset input\n"
                "  USB = HID Keyboard + HID Mouse + HID Gamepad + CDC ACM"
            ),
            False,
        ),
        (
            "💾 Firmware Installation",
            (
                "## First-time flash — Web Flasher (required)\n"
                "Open the Bind Bandit Web Flasher in Chrome or Edge:\n"
                "  https://smokydastona.github.io/joycon-to-keyboard/\n\n"
                "The Web Flasher link is also on the welcome screen of the\n"
                "first-run setup wizard (reopen from Settings → Developer).\n\n"
                "### ESP32 (Bluetooth Host) — NodeMCU-32S / WROOM-32\n"
                "  1. Plug the board in via USB.\n"
                "  2. Hold BOOT, tap RESET, release BOOT.\n"
                "  3. Click 'Install ESP32 Host' and pick the port.\n\n"
                "### ESP32-S3 (USB Keyboard) — Arduino Nano ESP32\n"
                "  1. Wire the installer lines first: ESP32 GPIO21 → Nano B1 / GPIO0, ESP32 GPIO22 → Nano RESET.\n"
                "  2. Replug the ESP32 host normally after flashing it.\n"
                "  3. Click 'Install ESP32-S3 Through Host' and pick the host COM port.\n"
                "  4. The page puts the Nano into download mode and flashes it through the host automatically.\n"
                "  5. Move the USB cable to the Nano for normal use.\n\n"
                "### Direct Nano fallback\n"
                "  If host-assisted flashing fails, double-tap the Nano RESET button quickly (<300 ms) and use the fallback direct-install button in the Web Flasher.\n\n"
                "No drivers, no ESP-IDF install, no command line needed.\n"
                "Erases flash by default (clean NVS).\n\n"
                "## Firmware updates (after initial flash)\n"
                "After first-time setup, updates are handled automatically.\n"
                "When a newer GitHub release is available the oversized ↑ Update button\n"
                "next to the theme toggle starts blinking. Click it whenever you want to update;\n"
                "the app downloads the new release bundle (or .exe), relaunches itself, then blocks normal use\n"
                "until both boards finish flashing to the matching release firmware.\n\n"
                "## Manual build (advanced)\n"
                "  cd firmware/esp32-hid-host-uart\n"
                "  idf.py set-target esp32\n"
                "  idf.py build\n"
                "  idf.py flash monitor\n\n"
                "  cd firmware/esp32s3-usb-kbd\n"
                "  idf.py set-target esp32s3\n"
                "  idf.py build\n"
                "  idf.py flash monitor"
            ),
            False,
        ),
        (
            "✅ First End-to-End Test",
            (
                "1. Flash the ESP32 host, then let it flash the Nano ESP32-S3 via the Web Flasher (see Firmware Installation).\n"
                "2. Move the USB cable to the Nano ESP32-S3 and connect it to the PC.\n"
                "3. Open Bind Bandit — it auto-detects and connects to the ESP32-S3 bridge. "
                "If auto-connect is disabled in Settings, select the COM port manually and click Connect.\n"
                "4. Click Scan for Joy-Con in Mission Control → Quick Actions, "
                "then hold the sync button on your Joy-Con until the lights blink.\n"
                "5. The ESP32 should discover and connect to the Joy-Con.\n"
                "6. Press a button on the Joy-Con — you should see the "
                "corresponding key appear in the Input Test log.\n"
                "7. Open a text editor and verify keystrokes arrive."
            ),
            False,
        ),
        (
            "💻 Using Bind Bandit",
            (
                "## Sidebar Navigation\n"
                "Mission Control — ESP32 connection status, firmware version, connected-device "
                "cards (battery, latency), \u2795 Add Device button to scan for Joy-Cons via ESP32 "
                "Bluetooth or PC USB HID devices (M913, Razer, keyboards, mice, gamepads, etc), quick actions (Ping, Toggle Overlay), "
                "and the live device log\n"
                "Blueprint Layout — interactive hotspot canvas for key binding\n"
                "Operation Scripts — macro editor, layers, chords, stick config\n"
                "Crew Loadouts — save/load/share profiles across 4 slots\n"
                "Target Assets — per-device configuration tabs; only connected devices are shown; "
                "click Configure on a Mission Control device card to jump directly to its tab\n"
                "Forensics — input test, controller info, telemetry, exportable reports\n"
                "Help — you are here\n\n"
                "## Key Binding\n"
                "The Blueprint Layout tab handles all key mapping for Joy-Con, M913, and Razer. "
                "The keyboard picker inside the mapping popup now uses the updated default "
                "keyboard hotspot positions, with hotspot outlines shaped to match the keyboard "
                "keys instead of generic dots. "
                "The M913 section includes a Skin selector (Stock / Incedius) to switch "
                "between the standard M913 layout and the Incedius variant. "
                "Each skin has its own independent hotspot positions so the dots "
                "match the background image. Switching skins preserves any "
                "position edits you've made.\n\n"
                "## Adding Devices\n"
                "Open the Mission Control dashboard and click \u2795 Add Device.\n"
                "- ESP32 Bluetooth tab: enter a device name filter (default \u201cJoy-Con\u201d), choose "
                "Single or Dual, then click Scan. The ESP32 will discover and connect automatically. "
                "Both left and right Joy-Con appear as separate device cards.\n"
                "- PC USB HID tab: lists supported devices (M913 keypad, Razer mice) and also "
                "shows other connected HID devices (keyboards, mice, gamepads, joysticks, etc) for visibility. "
                "Select one and click Add to register it.\n"
                "Previously added devices are remembered in a local cache so they reconnect "
                "faster after firmware updates.\n\n"
                "Click a hotspot to select it and open the Mapping Popup, "
                "or right-click for quick actions (unbind, copy/paste, swap, turbo, "
                "learn). Use Learn Mode to bind by pressing the actual "
                "key on the controller. The popup includes keyboard, mouse, "
                "gamepad, macro, and advanced tabs so you can target either "
                "the HID keyboard, HID mouse, or HID gamepad interface.\n\n"
                "The right side panel is a Profile Quick-Edit area. From here you "
                "can switch profile slots (0–3), rename the current profile, "
                "create a new or duplicate profile, upload/read profiles to/from "
                "the device, save/load profile JSON files, reset to defaults, "
                "and clear all mappings — all without leaving the mapping canvas. "
                "A mapping summary shows how many keys, macros, layers, and chords "
                "are defined. Undo/Redo buttons are also available.\n\n"
                "Each hotspot dot uses a sketch-style button overlay texture "
                "generated from the live hotspot geometry itself, so the artwork "
                "always matches the current hotspot position, size, and shape. "
                "That means Edit Positions, keyboard key-shape changes, and other "
                "layout tweaks stay visually aligned instead of relying on stale "
                "pre-rendered scene overlays. Those generated overlays also carry "
                "handwritten legends or symbols that match the represented physical "
                "button, so the heist-style markers stay intuitive instead of "
                "looking like anonymous blobs. "
                "Change the overlay colour from the Colour dropdown.\n\n"
                "Use **Edit Positions** to drag hotspot dots to match your device. "
                "**Export Positions** saves all devices (including separate M913 "
                "Stock and Incedius entries) to a JSON file. **Import Positions** "
                "loads them back. If a hotspot_positions.json file is found next "
                "to the app on startup, Joy-Con, mouse, gamepad, keyboard, and M913 "
                "positions are loaded automatically.\n\n"
                "## Profiles\n"
                "The app ships with 4 built-in profiles pre-loaded into slots 0-3: "
                "General (slot 0), FPS / Shooter (slot 1), Platformer / Action "
                "(slot 2), and Racing / Driving (slot 3). Each has Joy-Con buttons "
                "mapped to common PC key bindings for that genre.\n\n"
                "Use Import/Export to share profiles as files "
                "or share codes (JCB1: prefix). The App Switcher table lets you "
                "auto-switch profiles by foreground application. Four ways to add a rule:\n"
                "- **🔍 Detect App** — snap the currently focused window.\n"
                "- **📂 Browse…** — pick any .exe from the file system.\n"
                "- **Add Rule** — type an executable name manually.\n"
                "- **🖥 Processes…** — opens a live, searchable list of every process "
                "currently running on the PC; select one and it is added instantly.\n\n"
                "For UWP / Microsoft Store apps, add a 'title' keyword to distinguish "
                "apps that all share ApplicationFrameHost.exe. "
                "Use **Reset to Default** to restore the built-in profile for the current slot.\n\n"
                "## Macros\n"
                "The Operation Scripts tab now features a visual drag-to-reorder step editor. "
                "Add key press/release steps, delays, mouse button steps, or "
                "macro chain steps. Toggle to raw JSON mode for advanced editing. "
                "Use Duplicate to clone macros, or Export/Import to share "
                "them as JSON files.\n\n"
                "## Layers\n"
                "Define up to 4 overlay layers. Each layer is activated by "
                "holding or toggling a controller button, and overrides specific "
                "key mappings while active. Use MappingPopup to configure "
                "layer overrides.\n\n"
                "## Chords\n"
                "Map simultaneous button combos (e.g. A+B) to a single "
                "output keycode. Adjust the timing window (50–500 ms).\n\n"
                "## Overlay\n"
                "Toggle the floating overlay from Mission Control → Quick Actions or the "
                "system tray to see active keys, profile name, layer, and turbo state "
                "on-screen during gameplay. Drag to reposition — the position is "
                "remembered across sessions and clamped to visible screens. "
                "Right-click the overlay for opacity presets, placement presets "
                "(8 screen positions), and compact mode."
                "\n\n"
                "## Forensics\n"
                "The Forensics view keeps a live session telemetry record: total mapped events, "
                "recent throughput, average hold time, active/peak keys, and latency samples from Ping. "
                "It also includes a compact live visualizer that highlights button, stick, layer, macro, "
                "battery, and RSSI state in real time, plus a device-aware active-controls summary and badge-style action chips for abstract inputs "
                "such as Jump, Sprint, Crouch, and multi-device key spaces, along with a short recent-activity strip for "
                "the latest input, layer, and macro events where older entries fade automatically, stay split into Input, Layer, and Macro lanes, and collapse into +N older summaries when a lane gets noisy. Use Copy Summary for a quick shareable snapshot or "
                "Export Report to save a JSON file with controller metadata, calibration assessment, and "
                "the recent event log."
            ),
            False,
        ),
        (
            "⌨️ Default Key Mapping",
            (
                "## Joy-Con (L) — Default Layout\n"
                "  Stick → W / A / S / D    LStick Press → Ctrl\n"
                "  DUp → E    DLeft → F    DRight → R    DDown → Space\n"
                "  L → Shift    ZL → I\n"
                "  Minus → Tab    Capture → Esc\n\n"
                "## Mouse — Back Button\n"
                "  Back → Space (jump)\n"
                "  Left / Right → default (unchanged)\n\n"
                "## Gyro\n"
                "  OFF / unmapped by default.\n\n"
                "All 4 profile slots start from this layout and can be fully\n"
                "customized in the Mapping view."
            ),
            False,
        ),
        (
            "🎮 Advanced Mapping Modes",
            (
                "## Turbo\n"
                "Repeats the key at a configurable rate while held.\n\n"
                "## Sticky\n"
                "First press activates, second press deactivates (toggle).\n\n"
                "## Oneshot Modifier\n"
                "Press modifier, then press another key — modifier applies "
                "only to the next keypress.\n\n"
                "## Tap-Hold\n"
                "Short press sends one key, long hold sends another.\n\n"
                "## Double-Tap\n"
                "Quick double-press sends an alternate key.\n\n"
                "## Auto-Shift\n"
                "Quick tap sends the normal key, holding past a threshold "
                "sends the shifted variant automatically.\n\n"
                "## Sequential / Cycle\n"
                "Each press cycles through a list of outputs.\n\n"
                "## Mouse Button\n"
                "Maps a controller button to a real USB HID mouse button "
                "(left, right, middle, back, forward).\n\n"
                "## Leader Key\n"
                "Press the leader key, then enter a sequence of buttons "
                "within 1 second to trigger an action.\n\n"
                "## Profile Switch\n"
                "Switch the active profile slot on-the-fly from the controller.\n\n"
                "## Sniper Button\n"
                "Hold to temporarily drop mouse sensitivity for precision aiming. "
                "Releases back to normal when let go. Like Razer DPI-shift — but "
                "running entirely on the hardware.\n\n"
                "## DPI Cycle\n"
                "Each press cycles through your sensitivity presets "
                "(e.g. 5 → 10 → 20 → 30 → 50 → 5…). Configure presets "
                "in your profile's dpi_presets array.\n\n"
                "## Mouse Move (Macro Step)\n"
                "Macros can now include mouse_move steps with dx/dy (-127..127) "
                "to move the cursor as part of a hardware macro sequence.\n\n"
                "## Chords\n"
                "Press two or more buttons simultaneously to trigger a "
                "different output.\n\n"
                "## Macro Chaining\n"
                "A macro step can enqueue another macro to run after the "
                "current one finishes, enabling complex multi-phase combos.\n\n"
                "## Humanization\n"
                "Adds slight random delays to key events to appear more "
                "natural.\n\n"
                "## Rapid Trigger\n"
                "In Operation Scripts → Stick → Rapid Trigger, set Activate and "
                "Deactivate thresholds (0–100% of full deflection). The stick button "
                "fires when deflection exceeds Activate %, and releases when it drops "
                "below Deactivate %. Allows sub-zone triggering for faster response."
            ),
            False,
        ),
        (
            "📡 Serial Protocol (Reference)",
            (
                "## UART (ESP32 ↔ ESP32-S3)\n"
                "See docs/serial-protocol.md for the full binary frame spec (including control frames and responses).\n\n"
                "## Helper App ↔ ESP32-S3 (USB CDC)\n"
                "NDJSON — one JSON object per line.\n\n"
                "## Common Commands (app → device)\n"
                "  {\"cmd\":\"ping\"}\n"
                "  {\"cmd\":\"read_profile\",\"slot\":0}\n"
                "  {\"cmd\":\"write_profile\",\"slot\":0,\"profile\":{...}}\n"
                "  {\"cmd\":\"set_active_profile\",\"slot\":0}\n"
                "  {\"cmd\":\"buzzer_get\"}\n"
                "  {\"cmd\":\"buzzer_set\",\"enabled\":true,\"volume\":60,\"discovery_tick\":true,\"tone_mask\":127}\n"
                "  {\"cmd\":\"buzzer_test\",\"tone_id\":1}\n\n"
                "## Common Responses / Events (device → app)\n"
                "  {\"rsp\":\"pong\"}\n"
                "  {\"rsp\":\"read_profile\",\"ok\":true,\"slot\":0,\"profile\":{...}}\n"
                "  {\"evt\":\"mapped_key\",\"pressed\":true,\"key_id\":1}\n"
                "    key_id range: 0..639 (device_id*128 + base_key_id)\n"
                "  {\"evt\":\"battery\",\"device_id\":0,\"level\":3}\n"
                "  {\"evt\":\"bt_status\",\"state\":\"connected\"}\n\n"
                "Errors use: {\"rsp\":\"<cmd>\",\"ok\":false,\"error\":\"...\"} (some commands may also include a numeric status).\n\n"
                "## Calibration Commands\n"
                "  {\"cmd\":\"calibration\",\"action\":\"save\"}   — commit current\n"
                "    stick calibration (center + range) to NVS\n"
                "  {\"cmd\":\"calibration\",\"action\":\"clear\"}  — reset to factory\n"
                "    defaults\n"
                "Triggered from Forensics → Calibrate Stick wizard."
            ),
            False,
        ),
        (
            "🖱️ Mouse Configuration (M913 & Razer)",
            (
                "## M913 Gaming Keypad — Full Stock Software Replacement\n"
                "BindBandit writes directly to the M913's onboard memory over USB HID.\n"
                "No proprietary vendor software is required or used — every option that\n"
                "the stock software exposes is available here, plus extras.\n\n"
                "## Interactive Button Canvas\n"
                "The top panel is a live, clickable diagram of the M913. Each of the\n"
                "16 configurable buttons is shown as a coloured dot on the image.\n"
                "Click any dot to open an action picker for that button — choose from\n"
                "the full action list or type a custom combo (e.g. 'ctrl+shift+t').\n"
                "The currently assigned action is shown as a label next to each dot.\n"
                "scroll_up and scroll_down are display-only and cannot be remapped.\n\n"
                "## Hardware Profile Slots (P1 / P2)\n"
                "The M913 has two independent onboard profiles. Select P1 or P2 in the\n"
                "Profile row before clicking Apply Config — the config is written to\n"
                "that slot and the selection packet is sent first so the mouse switches\n"
                "to that slot automatically. Hold the DPI button on the mouse to cycle\n"
                "between slots without reconnecting.\n\n"
                "## DPI Stage Naming & Colors\n"
                "Each of the five DPI stages has a name (editable text box) and a color\n"
                "(click the swatch button beside it). The name and color are stored in\n"
                "the saved profile and in INI exports — they are UI metadata only and\n"
                "are not sent to the device. Use them to label stages like 'Snipe',\n"
                "'Gaming', 'Office' for quick identification.\n\n"
                "## Active DPI Indicator\n"
                "A thin coloured bar on the left of each DPI row lights up in that\n"
                "stage's color when the M913 reports it as active. This is updated\n"
                "in real time via a background input-reader thread while the device\n"
                "is connected. Note: the indicator tracks physical DPI-cycle button\n"
                "presses — it resets when you reconnect or apply config.\n\n"
                "## Live Apply\n"
                "Enable the Live Apply checkbox to have any change to DPI, LED, polling\n"
                "rate, or button actions automatically sent to the device after a 1.5 s\n"
                "debounce delay. Your preference is saved across app restarts.\n"
                "Live Apply only fires when a device is connected — it is a no-op\n"
                "when no M913 is detected.\n\n"
                "## Factory Reset\n"
                "Click Factory Reset… (Actions row 2) to restore all on-screen settings\n"
                "to the M913's known factory defaults without touching any saved profile\n"
                "files on disk. A confirmation dialog is shown before any data changes.\n\n"
                "## Profile Bundle Export / Import\n"
                "Export Bundle… saves every saved M913 profile to a single .bindbandit\n"
                "ZIP archive so you can migrate configs between machines or share them.\n"
                "Import Bundle… reads that archive and saves each contained profile into\n"
                "the local profile store. Duplicate names are overwritten.\n\n"
                "## Hardware Capability Limits\n"
                "The M913 onboard memory enforces the following hard limits:\n"
                "  • DPI values: 100–16000 CPI in 100 CPI steps.\n"
                "  • DPI stages: exactly 5 (enable/disable per stage, min 1 enabled).\n"
                "  • Polling rate: 125 / 250 / 500 / 1000 Hz.\n"
                "  • Button action bytes: limited to the actions listed in the picker.\n"
                "    Custom key combos use the key-combo syntax (e.g. 'ctrl+c').\n"
                "  • Hardware macros: 15 slots, up to 67 key events each.\n"
                "  • LED modes: off, steady, respiration, rainbow, wave, reactive,\n"
                "    ripple, starlight, breath_single.\n\n"
                "## Hardware Macros\n"
                "Click Manage Macros… to open the macro editor. Select a slot (1–15),\n"
                "add key press/release events, then click Save to Profile and\n"
                "Apply to Device. Assign a slot to a button via action 'macro1'–'macro15'\n"
                "in the Button Mapping grid or the canvas action picker.\n\n"
                "## Razer Mouse\n"
                "Connect a supported Razer mouse via USB. Use the Razer Mouse sub-tab\n"
                "to configure DPI stages (X/Y independent), polling rate, idle timeout,\n"
                "and Hypershift layers.\n\n"
                "## Analog Stick → Mouse\n"
                "The Joy-Con analog stick can move the mouse cursor.\n"
                "Configure sensitivity, deadzone, and response curve in\n"
                "Operation Scripts → Stick."
            ),
            False,
        ),
        (
            "🧭 Gyro Calibration & LED",
            (
                "## Gyro Calibration\n"
                "Open Motion Grid → Calibration & LED tab.\n"
                "Place the controller flat and still, then click Calibrate Gyro.\n"
                "128 gyro samples will be averaged to compute bias offsets (X, Y, Z).\n"
                "The bias is saved to NVS on the ESP32-S3 and restored automatically "
                "on boot.\n\n"
                "You can also read the current bias from the device, or manually set "
                "bias values and push them.\n\n"
                "## LED Control\n"
                "Select a pattern (off / solid / blink / pulse / rainbow), choose an "
                "RGB color, set the animation speed in milliseconds, and click Apply LED.\n"
                "The command is sent over serial to the ESP32-S3, which forwards it "
                "as a UART control frame to the ESP32 host."
            ),
            False,
        ),
        (
            "🔄 OTA Firmware Updates",
            (
                "After the initial flash via the Web Flasher, all firmware updates\n"
                "are handled by Bind Bandit automatically — no need to revisit the\n"
                "web flasher or enter download mode.\n\n"
                "The host-assisted Web Flasher path is only for blank-board installs and recovery.\n\n"
                "When a new release is available:\n"
                "  1. The oversized ↑ Update button next to the theme toggle starts blinking.\n"
                "  2. Click it and confirm to start the update.\n"
                "  3. If no update is cached yet, the button checks GitHub immediately first.\n"
                "  4. The new app is downloaded and the app restarts automatically.\n"
                "  5. After relaunch, firmware is flashed over the existing ESP32-S3 USB serial link (connect first).\n"
                "  6. The ESP32 Bluetooth host is updated through the ESP32-S3 relay path so both boards stay on the same release.\n\n"
                "Bind Bandit verifies the reported firmware version after each flash. If a stage times out or returns an error,\n"
                "the helper log records the failing board, stage, byte offset, and recent serial traffic. Failed OTA sessions also\n"
                "write an ota_failure_*.json report into the logs folder for later diagnosis.\n\n"
                "All exported debug bundles are anonymized before they are written or shared.\n\n"
                "The update covers both the helper app and all firmware in one step.\n\n"
            ),
            False,
        ),
        (
            "🔧 Troubleshooting",
            (
                "## Joy-Con won't pair\n"
                "  Hold sync button for 5+ seconds until LEDs cycle rapidly.\n"
                "  Ensure ESP32 firmware is flashed (not ESP32-S3).\n"
                "  The bridge supports up to 5 connected devices (hard limit).\n\n"
                "## No input on PC\n"
                "  Check UART wiring (TX→RX, RX→TX, GND).\n"
                "  Verify ESP32-S3 enumerates in Device Manager as **Composer** (Keyboards), "
                "**Forger** (Mice and other pointing devices), **Executor** (Human Interface Devices), "
                "and **Architect** (Ports / COM & LPT).\n"
                "  These names are set automatically via MS OS 2.0 descriptors — no driver install needed.\n"
                "  If old names are cached, run **scripts\\\\clear_usb_cache.ps1** as Administrator "
                "(unplug first), then replug.\n"
                "  Try a different USB cable.\n\n"
                "## COM port not found\n"
                "  ESP32-S3 native USB should appear as **Architect (COMx)** without extra drivers.\n"
                "  Firmware v0.1.252+ reports the correct name automatically on first plug-in.\n\n"
                "## Helper app won't connect\n"
                "  Close any other serial monitor (only one app can use the port).\n"
                "  Try a different baud rate (default: 115200).\n\n"
                "## Firmware flash fails\n"
                "  For first-time flash, use the Web Flasher in Chrome/Edge. Flash the ESP32 host first, then use the host-assisted Nano installer.\n"
                "  OTA updates after first install should happen through Bind Bandit while connected to the ESP32-S3.\n"
                "  If an OTA update fails, open Settings → Export Anonymized Debug Bundle and keep the generated ZIP plus the latest helper.log / ota_failure_*.json files.\n"
                "  If you want to report it upstream, use Settings → Open GitHub Debug Issue to open the repo's debug-report issue template with the generated summary prefilled, then attach the anonymized ZIP manually.\n"
                "  Firmware downloaded with an app update stays queued if you skip the prompt or the device is not connected yet, so you can retry on the next launch.\n"
                "  ESP32: Hold BOOT while tapping RESET to enter download mode only for recovery or first-time flash.\n"
                "  Host-assisted Nano install needs the extra wires: ESP32 GPIO21 → Nano B1 / GPIO0 and ESP32 GPIO22 → Nano RESET.\n"
                "  ESP32-S3 (Nano ESP32): Double-tap RESET for download mode only for direct recovery or fallback flashing.\n"
                "  Check that you select the ESP32 host COM port for host-assisted install, and the Nano COM port only for the fallback direct flash.\n\n"
                "## No buzzer sound\n"
                "  Verify the passive piezo buzzer is wired to GPIO25 and GND.\n"
                "  Confirm the buzzer feature is enabled in menuconfig (Bind Bandit → Enable piezo buzzer audio feedback).\n"
                "  Active buzzers (with built-in oscillator) won't produce variable tones — use a passive piezo.\n"
                "  Try a different GPIO if 25 is in use — set via menuconfig → Buzzer GPIO pin.\n\n"
                "## Buzzer too loud / too quiet\n"
                "  Adjust volume via menuconfig → Bind Bandit → Buzzer volume (1–100). Default is 50 (50% duty). "
                "Lower values reduce volume; values above 50 may clip on most passive piezos.\n\n"
                "## Want a beep while scanning?\n"
                "  Enable menuconfig → Bind Bandit → Periodic beep during BT discovery scan. "
                "This plays a short tick every ~3 seconds while an inquiry scan is active."
            ),
            False,
        ),
        (
            "📦 Installing / Updating the Helper App",
            (
                "## From source\n"
                "  git clone <repo-url>\n"
                "  cd helper-app\n"
                "  pip install -r requirements.txt\n"
                "  python -m joycon_helper\n\n"
                "## Standalone executable\n"
                "Download the latest release from the GitHub Releases page. "
                "Run BindBandit.exe (Windows) — no Python required.\n\n"
                "## Updating\n"
                "The app checks for updates on launch, and re-checks periodically (about every 12 hours) while it runs.\n"
                "When a new version is available, the oversized ↑ Update button beside the theme toggle starts blinking.\n"
                "If the main window is open, Bind Bandit also shows a toast notification you can click to start the install.\n"
                "Clicking it with no cached update runs an immediate check first; if nothing newer exists,\n"
                "Bind Bandit shows a popup saying the current version is up to date.\n"
                "If a release is available, the update installs and firmware is updated\n"
                "automatically after relaunch.\n\n"
                "If the ESP32-S3 is not connected yet, or you choose not to flash immediately,\n"
                "the downloaded firmware stays queued and will be offered again on the next launch.\n\n"
                "## Debugging update failures\n"
                "If an update fails, use Settings → Export Anonymized Debug Bundle. The ZIP includes\n"
                "sanitized app logs, crash logs, diagnostics, and firmware OTA failure reports.\n"
                "You can then use Settings → Open GitHub Debug Issue to open the repo's debug-report template\n"
                "and attach the anonymized ZIP manually if you want to report it."
            ),
            False,
        ),
        (
            "⚙ Settings & System Tray",
            (
                "## System tray\n"
                "Bind Bandit places an icon in the Windows system tray on launch. "
                "Double-click the tray icon to show or hide the main window. "
                "Right-click the tray icon for a menu with Show/Hide, profile switching "
                "(Slots 0–3), overlay toggle, auto-switch toggle, Settings, and Quit.\n\n"
                "## Safehouse Config (Settings panel)\n"
                "Open Settings from the Safehouse Config entry in the left sidebar, or from the "
                "system tray right-click menu. This is a scrollable panel with cards:\n"
                "  • General (theme, tray behavior, auto-start, auto-connect, and the InputGoblin Settings button)\n"
                "  • Input & Key Pops (overlay appearance and behavior)\n"
                "  • Profiles (default slot + import/export)\n"
                "  • Developer Tools (log level, debug bundle)\n\n"
                "## InputGoblin Settings dialog\n"
                "In General settings, click InputGoblin Settings… to open a dedicated dialog with tabs:\n"
                "  • Speaker — configure the ESP32 host buzzer (enable, volume, discovery tick, per-tone mask, test tones)\n"
                "  • Serial — app-side serial settings (baud rate, reconnect interval, read timeout)\n\n"
                "Speaker settings are persisted on the ESP32 BT host. The baud rate applies the next time you connect.\n\n"
                "## Toast notifications\n"
                "Non-blocking slide-in notifications appear at the bottom-right for events like connecting, "
                "disconnecting, and quick warnings. Click a toast to dismiss it early."
            ),
            False,
        ),
        (
            "📁 Data & Profiles",
            (
                "Bind Bandit stores all user data in a persistent folder that "
                "survives app updates and reinstalls:\n\n"
                "## Data folder location\n"
                "  Windows:  %APPDATA%\\BindBandit\\\n"
                "  Linux/macOS:  ~/.config/BindBandit/\n\n"
                "## What's stored\n"
                "  logs/              — helper.log, ota_failure_*.json, and other helper diagnostics\n"
                "  crash-logs/        — Unhandled exception crash dumps\n"
                "  profiles/          — Per-slot Joy-Con mapping profiles (auto-saved)\n"
                "  m913/              — M913 keypad profiles & device registry\n"
                "  razer/             — Razer mouse profiles & device registry\n"
                "  device_cache.json  — Remembered devices (quick reconnect list)\n"
                "  app_profiles.json  — App-switcher rules (auto-switch by game)\n"
                "  state.json         — Session state (last slot, COM port, etc.)\n\n"
                "## Auto-save behavior\n"
                "  Your active profile slot and mappings are saved to disk automatically "
                "whenever you make a change. On the next launch, the app restores your "
                "last active slot, COM port, and all per-slot profiles — so you pick up "
                "exactly where you left off.\n\n"
                "## Migration\n"
                "  If you're upgrading from an older version, existing device_cache.json "
                "and app_profiles.json files are automatically migrated into the new "
                "data folder on first launch. Older logs/ and crash-logs/ folders that "
                "used to live next to the app are moved there too."
            ),
            False,
        ),
        (
            "📋 Quick Reference",
            (
                "## Keyboard shortcuts (helper app)\n"
                "  Ctrl+Z — Undo profile change\n"
                "  Ctrl+Y / Ctrl+Shift+Z — Redo\n"
                "  Ctrl+S — Upload profile to device\n"
                "  Ctrl+Shift+S — Save profile to file\n"
                "  Ctrl+O — Read profile from device\n"
                "  Ctrl+N — New profile\n"
                "  Ctrl+F — Focus search (Mapping / Help)\n"
                "  Ctrl+P — Ping device\n"
                "  Ctrl+R — Refresh serial ports\n"
                "  Ctrl+T — Toggle light / dark theme\n"
                "  Ctrl+Shift+O — Toggle overlay\n"
                "  Ctrl+1…7 — Navigate sidebar sections\n"
                "  Ctrl+Q — Quit app\n\n"
                "## Serial commands (cheat sheet)\n"
                "  ping → pong\n"
                "  read_profile → profile JSON\n"
                "  write_profile → OK/error\n"
                "  set_profile_slot → switches active slot\n"
                "  rumble → vibrate controller\n"
                "  bt_reconnect → force BT reconnection\n\n"
                "## Web Flasher quick order\n"
                "  Flash ESP32 host → wire GPIO21/GPIO22 installer leads → Install ESP32-S3 Through Host → move USB to Nano\n\n"
                "## Profile share codes\n"
                "  Prefix: JCB1:\n"
                "  Encoding: JSON → zlib → base64"
            ),
            False,
        ),
    ]


# ── Collapsible section widget ──────────────────────────────────────

class _CollapsibleSection(QWidget):
    """A section with a clickable header that toggles body visibility."""

    def __init__(self, title: str, body_text: str, expanded: bool,
                 theme: ThemeEngine) -> None:
        super().__init__()
        self._theme = theme
        self._expanded = expanded
        self._title_text = title
        self._body_text = body_text

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header row
        header = QWidget()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setStyleSheet(
            f"background: {theme.color('surface2')}; "
            f"border-radius: {theme.radius('card')}px; padding: 6px 12px;"
        )
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(12, 8, 12, 8)

        self._arrow = QLabel("▼" if expanded else "▶")
        self._arrow.setFixedWidth(18)
        h_lay.addWidget(self._arrow)

        self._title_label = QLabel(title)
        self._title_label.setFont(QFont(theme.typo("font_family"), 12, QFont.Weight.Bold))
        h_lay.addWidget(self._title_label, 1)

        header.mousePressEvent = lambda _e: self.toggle()
        lay.addWidget(header)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"color: {theme.color('border')};")
        lay.addWidget(div)

        # Body
        self._body = QWidget()
        b_lay = QVBoxLayout(self._body)
        b_lay.setContentsMargins(16, 8, 16, 12)
        b_lay.setSpacing(4)

        self._body_labels: list[QLabel] = []
        for line in body_text.split("\n"):
            lbl = QLabel()
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            if line.startswith("## "):
                lbl.setText(line[3:])
                lbl.setFont(QFont(theme.typo("font_family"), 11, QFont.Weight.Bold))
                lbl.setStyleSheet(f"margin-top: 8px; color: {theme.color('accent')};")
            elif line.startswith("  "):
                lbl.setText(line)
                lbl.setFont(QFont("Consolas", 10))
                lbl.setStyleSheet(
                    f"background: {theme.color('surface2')}; "
                    f"padding: 2px 6px; border-radius: 3px;"
                )
            else:
                lbl.setText(line)
            self._body_labels.append(lbl)
            b_lay.addWidget(lbl)

        lay.addWidget(self._body)
        self._body.setVisible(expanded)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._arrow.setText("▼" if self._expanded else "▶")

    def matches_search(self, query: str) -> bool:
        if not query:
            return True
        q = query.lower()
        if q in self._title_text.lower():
            return True
        return q in self._body_text.lower()


# ── Help View ───────────────────────────────────────────────────────

class HelpView(QWidget):
    """Searchable, collapsible help sections."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header / search bar
        header = QWidget()
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Help & Setup Guide")
        title.setFont(QFont(
            main.theme.typo("font_family_decorative"),
            main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        h_lay.addWidget(title)
        h_lay.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Search help…")
        self._search.setFixedWidth(260)
        self._search.textChanged.connect(self._filter)
        h_lay.addWidget(self._search)

        layout.addWidget(header)

        # Scrollable sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll)

        container = QWidget()
        self._sections_layout = QVBoxLayout(container)
        self._sections_layout.setContentsMargins(16, 8, 16, 16)
        self._sections_layout.setSpacing(8)

        self._sections: list[_CollapsibleSection] = []
        for title_text, body_text, expanded in _sections():
            section = _CollapsibleSection(title_text, body_text, expanded, main.theme)
            self._sections.append(section)
            self._sections_layout.addWidget(section)

        self._sections_layout.addStretch()
        scroll.setWidget(container)

    def _filter(self, text: str) -> None:
        for section in self._sections:
            section.setVisible(section.matches_search(text))

    # -----------------------------------------------------------------
    # Public interface (required by MainWindow view protocol)
    # -----------------------------------------------------------------

    def device_event(self, obj: dict) -> None:
        pass

    def profile_loaded(self, slot: int, profile: dict) -> None:
        pass

    def profile_updated(self, profile: dict) -> None:
        pass

    def apply_theme(self, theme: ThemeEngine) -> None:
        pass
