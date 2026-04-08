"""Help view — searchable, collapsible sections mirroring the old Help tab.

Provides 16 sections covering setup, usage, troubleshooting, and reference.
Each section is collapsible and all are filtered by a live search bar.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..theme import ThemeEngine

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.help_view")

# ── Section data ────────────────────────────────────────────────────

_HELP_SECTIONS: List[Tuple[str, str, bool]] = []  # populated at module level below


def _sections() -> List[Tuple[str, str, bool]]:
    """Return (title, body_text, initially_expanded) tuples."""
    return [
        (
            "🎮 What Is This?",
            (
                "Bind Bandit is an anti-cheat-safe hardware input bridge.\n\n"
                "A wireless controller (Joy-Con / Pro Controller) connects to an ESP32 "
                "board over Bluetooth Classic. That board sends key events over a UART "
                "link to an ESP32-S3 board, which presents itself to the PC as a real "
                "USB HID keyboard.\n\n"
                "## Why hardware?\n"
                "Because the PC sees an actual USB keyboard, not a virtual driver or "
                "injected input, it is fully compatible with anti-cheat systems.\n\n"
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
                "  Two UART wires (TX→RX, RX→TX) plus shared GND between boards\n"
                "  A Joy-Con (L or R) or Nintendo Pro Controller\n"
                "  USB-C cable from ESP32-S3 to PC\n\n"
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
                "  ESP32 GPIO17 (TX) → ESP32-S3 GPIO44 (RX)\n"
                "  ESP32 GPIO16 (RX) ← ESP32-S3 GPIO43 (TX)\n"
                "  GND ↔ GND\n\n"
                "## USB connection\n"
                "  ESP32-S3 USB port → PC (acts as keyboard + CDC serial)\n\n"
                "## Important\n"
                "The return UART wire (ESP32-S3 TX → ESP32 RX) is required for "
                "helper-app features like bind management, profile sync, and OTA "
                "updates. Without it, basic keyboard output still works.\n\n"
                "Do NOT connect 5 V or 3.3 V power pins between boards unless "
                "they share a common power supply. Only GND + TX/RX are needed.\n\n"
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
                "  GPIO17 = UART TX (to S3 RX)\n\n"
                "## ESP32-S3 (USB Device)\n"
                "  GPIO43 = UART TX (to ESP32 RX)\n"
                "  GPIO44 = UART RX (from ESP32 TX)\n"
                "  USB = HID Keyboard + CDC ACM"
            ),
            False,
        ),
        (
            "💾 Firmware Installation",
            (
                "## First-time flash (blank boards)\n"
                "Use the Diagnostics → Initial Flash section to download and flash "
                "the latest firmware automatically, or flash from local .bin files.\n\n"
                "## Manual build\n"
                "  cd firmware/esp32-hid-host-uart\n"
                "  idf.py set-target esp32\n"
                "  idf.py build\n"
                "  idf.py flash monitor\n\n"
                "  cd firmware/esp32s3-usb-kbd\n"
                "  idf.py set-target esp32s3\n"
                "  idf.py build\n"
                "  idf.py flash monitor\n\n"
                "## OTA updates\n"
                "Once firmware is installed, use Diagnostics → Firmware Update "
                "to update over USB without rebuilding."
            ),
            False,
        ),
        (
            "✅ First End-to-End Test",
            (
                "1. Flash both boards with the correct firmware.\n"
                "2. Connect ESP32-S3 to PC via USB.\n"
                "3. Open Bind Bandit, select the COM port, click Connect.\n"
                "4. Pair your Joy-Con: hold the sync button until lights blink.\n"
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
                "Dashboard — connection status, quick actions\n"
                "Mapping — interactive hotspot canvas for key binding\n"
                "Macros & Stick — macro editor, layers, chords, stick config\n"
                "Profiles — save/load/share profiles across 4 slots\n"
                "Devices — M913 keypad and Razer mouse configuration\n"
                "Diagnostics — input test, firmware update, controller info\n"
                "Help — you are here\n\n"
                "## Key Binding\n"
                "The Mapping tab has device tabs: Joy-Con, M913, and Mouse. "
                "The M913 tab includes a Skin selector (Stock / Incedius) to switch "
                "between the standard M913 layout and the Incedius button labels. "
                "Click a hotspot on the device canvas, then use the quick-bind grid, "
                "type a custom keycode, or open the ⌨ Keyboard Picker pop-up to "
                "visually select a key. Use Learn Mode to bind by pressing the actual "
                "key on the controller.\n\n"
                "## Profiles\n"
                "4 on-device profile slots. Use Import/Export to share as files "
                "or share codes (JCB1: prefix). The App Switcher table lets you "
                "auto-switch profiles by foreground application — browse for .exe "
                "files or detect the currently running app. For UWP / Microsoft Store "
                "apps, add a 'title' keyword to distinguish apps that share "
                "ApplicationFrameHost.exe.\n\n"
                "## Macros\n"
                "The Macros tab now features a visual drag-to-reorder step editor. "
                "Add key press/release steps and delays, or toggle to raw JSON mode "
                "for advanced editing.\n\n"
                "## Overlay\n"
                "Toggle the floating overlay from Dashboard → Quick Actions or the "
                "system tray to see active keys, profile name, layer, and turbo state "
                "on-screen during gameplay. Drag to reposition — the position is "
                "remembered across sessions and clamped to visible screens. "
                "Right-click the overlay for opacity presets "
                "and compact mode."
            ),
            False,
        ),
        (
            "⌨️ Default Key Mapping",
            (
                "## Joy-Con (R)\n"
                "  A → E    B → Q    X → R    Y → F\n"
                "  R → Enter    ZR → Left Alt\n"
                "  SL(R) → 7    SR(R) → 8\n"
                "  Plus → Escape    Home → (unmapped)\n"
                "  RStick Press → V\n\n"
                "## Joy-Con (L)\n"
                "  DUp → W    DDown → S    DLeft → A    DRight → D\n"
                "  L → Tab    ZL → Right Alt\n"
                "  SL(L) → 5    SR(L) → 6\n"
                "  Minus → ` (Grave)    Capture → G\n"
                "  LStick Press → Left Shift\n\n"
                "These defaults can be fully customized in the Mapping view."
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
                "## Chords\n"
                "Press two or more buttons simultaneously to trigger a "
                "different output.\n\n"
                "## Humanization\n"
                "Adds slight random delays to key events to appear more "
                "natural."
            ),
            False,
        ),
        (
            "📡 Serial Protocol (Reference)",
            (
                "## UART (ESP32 ↔ ESP32-S3)\n"
                "See docs/serial-protocol.md for the full binary frame spec.\n\n"
                "## Helper App ↔ ESP32-S3 (USB CDC)\n"
                "NDJSON — one JSON object per line.\n\n"
                "## Common Commands (app → device)\n"
                "  {\"cmd\": \"ping\"}\n"
                "  {\"cmd\": \"read_profile\", \"slot\": 0}\n"
                "  {\"cmd\": \"write_profile\", \"slot\": 0, \"profile\": {...}}\n"
                "  {\"cmd\": \"set_profile_slot\", \"slot\": 0}\n\n"
                "## Common Events (device → app)\n"
                "  {\"event\": \"pong\", \"fw_version\": \"...\"}\n"
                "  {\"event\": \"mapped_key\", \"key_id\": 0, \"action\": \"press\"}\n"
                "  {\"event\": \"read_profile\", \"slot\": 0, \"profile\": {...}}\n"
                "  {\"event\": \"battery\", \"level\": 85}\n"
                "  {\"event\": \"bt_status\", \"connected\": true}"
            ),
            False,
        ),
        (
            "🖱️ Mouse Configuration (M913 & Razer)",
            (
                "## M913 Gaming Keypad\n"
                "Connect the M913 via USB. Use Devices → M913 Keypad to "
                "detect the device, configure DPI stages, remap buttons, "
                "and adjust LED settings.\n\n"
                "## Razer Mouse\n"
                "Connect a supported Razer mouse via USB. Use Devices → "
                "Razer Mouse to configure DPI, polling rate, and "
                "Hypershift layers.\n\n"
                "## Analog Stick → Mouse\n"
                "The Joy-Con analog stick can be configured to move the "
                "mouse cursor. Configure sensitivity, deadzone, and "
                "response curve in Macros & Stick → Stick."
            ),
            False,
        ),
        (
            "🔄 OTA Firmware Updates",
            (
                "1. Connect ESP32-S3 to PC via USB.\n"
                "2. Open Bind Bandit and connect to the COM port.\n"
                "3. Go to Diagnostics → Firmware Update.\n"
                "4. Click 'Check Versions' to see current and available versions.\n"
                "5. If an update is available, click 'Update Firmware'.\n"
                "6. The device will reboot after flashing — wait for reconnection.\n\n"
                "You can also flash a local .bin file with 'Flash from File…'."
            ),
            False,
        ),
        (
            "🔧 Troubleshooting",
            (
                "## Joy-Con won't pair\n"
                "  Hold sync button for 5+ seconds until LEDs cycle rapidly.\n"
                "  Ensure ESP32 firmware is flashed (not ESP32-S3).\n"
                "  Only one Joy-Con can be paired at a time per ESP32.\n\n"
                "## No input on PC\n"
                "  Check UART wiring (TX→RX, RX→TX, GND).\n"
                "  Verify ESP32-S3 enumerates as a USB HID keyboard in Device Manager.\n"
                "  Try a different USB cable.\n\n"
                "## COM port not found\n"
                "  Install CP210x or CH340 drivers if needed.\n"
                "  ESP32-S3 native USB should appear without extra drivers.\n\n"
                "## Helper app won't connect\n"
                "  Close any other serial monitor (only one app can use the port).\n"
                "  Try a different baud rate (default: 115200).\n\n"
                "## Firmware flash fails\n"
                "  Hold BOOT button on the board while clicking flash.\n"
                "  Check that the correct target is selected (esp32 vs esp32s3)."
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
                "The app checks for updates on launch. Click 'Update' in the "
                "toolbar if a new version is available, or pull the latest "
                "source and reinstall."
            ),
            False,
        ),
        (
            "⚙ Settings & System Tray",
            (
                "## System tray\n"
                "Bind Bandit places an icon in the Windows system tray on launch. "
                "Double-click the tray icon to show or hide the main window. "
                "Right-click the tray icon for a menu with Show/Hide, profile "
                "switching (Slots 0–3), overlay toggle, auto-switch toggle, "
                "Settings, and Quit.\n\n"
                "## Settings dialog (tabbed)\n"
                "Open Settings via the ⚙ button in the toolbar, or from the "
                "system tray right-click menu.\n\n"
                "### General tab\n"
                "  Minimize to system tray on close\n"
                "  Start minimized to tray\n"
                "  Start with Windows (registry auto-start)\n"
                "  Auto-connect to last serial port\n\n"
                "### Overlay tab\n"
                "  Default opacity slider (20–100%)\n"
                "  Auto-hide timer (0 = disabled, otherwise seconds of no input)\n\n"
                "### Theme tab\n"
                "  Switch between Dark and Light color schemes\n\n"
                "### Developer tab\n"
                "  Baud rate (must match firmware)\n"
                "  Log level (DEBUG / INFO / WARNING / ERROR)\n"
                "  Re-run the first-time Onboarding Wizard\n\n"
                "## Overlay enhancements\n"
                "The floating overlay (toggle with Ctrl+Shift+O or tray menu) now shows "
                "profile name, active layer, and turbo state. Right-click for opacity "
                "presets and compact mode. Double-click toggles compact mode.\n\n"
                "## First-run wizard\n"
                "On first launch, an onboarding wizard guides you through USB connection, "
                "controller pairing, and input testing. Re-run it from Settings → Developer.\n\n"
                "## Toast notifications\n"
                "Non-blocking slide-in notifications appear at the bottom-right for "
                "events like connecting, disconnecting, and quick warnings. Click a "
                "toast to dismiss it early."
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
        if q in self._body_text.lower():
            return True
        return False


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
