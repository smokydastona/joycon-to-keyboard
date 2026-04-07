"""Redragon M913 Impact Elite mouse configuration over USB HID.

Communicates with the mouse via USB HID Feature Reports using the hidapi
library.  Protocol reverse-engineered by dokutan (mouse_m908) and Qehbr
(m913-ctl).

Anti-cheat safe: all remapping is written to the mouse's onboard memory.
The mouse's own MCU handles everything — no software input injection.
"""

from __future__ import annotations

import configparser
import json
import logging
import os
import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("joycon_helper.m913")

# Try importing hidapi — graceful fallback if not installed
try:
    import hid as _hid  # type: ignore[import-untyped]

    HID_AVAILABLE = True
except ImportError:
    _hid = None  # type: ignore[assignment]
    HID_AVAILABLE = False
    log.warning("hidapi not installed — M913 mouse support disabled")


# ---------------------------------------------------------------------------
# USB identifiers
# ---------------------------------------------------------------------------
M913_VID = 0x25A7
M913_PID = 0xFA07           # 2.4 GHz wireless receiver (wired shares this)
M913_PID_WIRELESS = 0xFA08  # Wireless dongle (alternate PID seen on some units)
M913_PIDS = (M913_PID, M913_PID_WIRELESS)
PACKET_SIZE = 17

# USB control-transfer constants (for reference — hidapi uses feature reports)
CTRL_REQUEST_TYPE = 0x21
CTRL_REQUEST = 0x09  # SET_REPORT
CTRL_VALUE = 0x0308  # Feature report, report ID 8
CTRL_INDEX = 0x0001  # Interface 1

# ---------------------------------------------------------------------------
# Button names (physical → index)
# ---------------------------------------------------------------------------
BUTTON_NAMES: Dict[str, int] = {
    "side1": 0,
    "side2": 1,
    "side3": 2,
    "side4": 3,
    "side5": 4,
    "side6": 5,
    "right": 6,
    "left": 7,
    "side7": 8,
    "side8": 9,
    "middle": 10,
    "fire": 11,
    "side9": 12,
    "side10": 13,
    "side11": 14,
    "side12": 15,
}

BUTTON_INDEX_TO_NAME = {v: k for k, v in BUTTON_NAMES.items()}
BUTTON_DISPLAY_NAMES: Dict[str, str] = {
    "side1": "Side 1",
    "side2": "Side 2",
    "side3": "Side 3",
    "side4": "Side 4",
    "side5": "Side 5",
    "side6": "Side 6",
    "right": "Right Click",
    "left": "Left Click",
    "side7": "Side 7",
    "side8": "Side 8",
    "middle": "Middle Click",
    "fire": "Fire",
    "side9": "Side 9",
    "side10": "Side 10",
    "side11": "Side 11",
    "side12": "Side 12",
}

# ---------------------------------------------------------------------------
# Layout modes — alternative display-name sets for physical mods.
# The button indices / protocol bytes are identical; only UI labels change.
# ---------------------------------------------------------------------------
LAYOUT_MODES: List[str] = ["stock", "incedius"]

INCEDIUS_DISPLAY_NAMES: Dict[str, str] = {
    "left": "Left Click",
    "right": "Right Click",
    "middle": "Middle Click",
    "fire": "Fire",
    "side1": "Thumb 1",
    "side2": "Thumb 2",
    "side3": "Thumb 3",
    "side4": "Thumb 4",
    "side5": "Thumb 5",
    "side6": "Thumb 6",
    "side7": "Finger 1",
    "side8": "Finger 2",
    "side9": "Finger 3",
    "side10": "Finger 4",
    "side11": "Finger 5",
    "side12": "Finger 6",
}

LAYOUT_DISPLAY_NAMES: Dict[str, Dict[str, str]] = {
    "stock": BUTTON_DISPLAY_NAMES,
    "incedius": INCEDIUS_DISPLAY_NAMES,
}

# The 12 side-button keys that can be reassigned in IncediusMod.
INCEDIUS_SIDE_KEYS = [
    "side1", "side2", "side3", "side4", "side5", "side6",
    "side7", "side8", "side9", "side10", "side11", "side12",
]

# All IncediusMod label choices for the side buttons (Thumb 1-6, Finger 1-6).
INCEDIUS_LABEL_CHOICES = [
    "Thumb 1", "Thumb 2", "Thumb 3", "Thumb 4", "Thumb 5", "Thumb 6",
    "Finger 1", "Finger 2", "Finger 3", "Finger 4", "Finger 5", "Finger 6",
]

# Default mapping: side button key → IncediusMod label.
DEFAULT_INCEDIUS_MAP: Dict[str, str] = {
    k: INCEDIUS_DISPLAY_NAMES[k] for k in INCEDIUS_SIDE_KEYS
}

# Ordered for UI display (logical grouping)
BUTTON_ORDER = [
    "left", "right", "middle", "fire",
    "side1", "side2", "side3", "side4", "side5", "side6",
    "side7", "side8", "side9", "side10", "side11", "side12",
]

# ---------------------------------------------------------------------------
# Mouse / special actions (from m913-ctl data.cpp)
# ---------------------------------------------------------------------------
MOUSE_ACTIONS: Dict[str, bytes] = {
    "left":            bytes([0x01, 0x01, 0x00, 0x53]),
    "right":           bytes([0x01, 0x02, 0x00, 0x52]),
    "middle":          bytes([0x01, 0x04, 0x00, 0x50]),
    "backward":        bytes([0x01, 0x08, 0x00, 0x4C]),
    "forward":         bytes([0x01, 0x10, 0x00, 0x44]),
    "dpi-":            bytes([0x02, 0x03, 0x00, 0x50]),
    "dpi+":            bytes([0x02, 0x02, 0x00, 0x51]),
    "dpi-cycle":       bytes([0x02, 0x01, 0x00, 0x52]),
    "led_toggle":      bytes([0x08, 0x00, 0x00, 0x4D]),
    "none":            bytes([0x00, 0x00, 0x00, 0x55]),
    "fire":            bytes([0x04, 0x3A, 0x03, 0x14]),
    "three_click":     bytes([0x04, 0x32, 0x03, 0x1C]),
    "polling_switch":  bytes([0x07, 0x00, 0x00, 0x4E]),
    # Snipe: temporary DPI switch while held (0x9A marker)
    "snipe":           bytes([0x9A, 0x00, 0x00, 0xBB]),
    # Multimedia (use 0x92 marker → keyboard sub-packet mechanism)
    "media_play":      bytes([0x92, 0x00, 0xCD, 0x00]),
    "media_player":    bytes([0x92, 0x01, 0x83, 0x01]),
    "media_next":      bytes([0x92, 0x00, 0xB5, 0x00]),
    "media_prev":      bytes([0x92, 0x00, 0xB6, 0x00]),
    "media_stop":      bytes([0x92, 0x00, 0xB7, 0x00]),
    "media_vol_up":    bytes([0x92, 0x00, 0xE9, 0x00]),
    "media_vol_down":  bytes([0x92, 0x00, 0xEA, 0x00]),
    "media_mute":      bytes([0x92, 0x00, 0xE2, 0x00]),
    "media_email":     bytes([0x92, 0x01, 0x8A, 0x01]),
    "media_calc":      bytes([0x92, 0x01, 0x92, 0x01]),
    "media_computer":  bytes([0x92, 0x01, 0x94, 0x01]),
    "media_home":      bytes([0x92, 0x02, 0x23, 0x02]),
    "media_search":    bytes([0x92, 0x02, 0x21, 0x02]),
    "www_forward":     bytes([0x92, 0x02, 0x25, 0x02]),
    "www_back":        bytes([0x92, 0x02, 0x24, 0x02]),
    "www_stop":        bytes([0x92, 0x02, 0x26, 0x02]),
    "www_refresh":     bytes([0x92, 0x02, 0x27, 0x02]),
    "www_favorites":   bytes([0x92, 0x02, 0x2A, 0x02]),
}

# ---------------------------------------------------------------------------
# Modifier keys and HID keycodes (from m913-ctl data.cpp)
# ---------------------------------------------------------------------------
MODIFIER_BITS: Dict[str, int] = {
    "ctrl_l": 0x01, "shift_l": 0x02, "alt_l": 0x04, "super_l": 0x08,
    "ctrl_r": 0x10, "shift_r": 0x20, "alt_r": 0x40, "super_r": 0x80,
    "ctrl": 0x01, "shift": 0x02, "alt": 0x04, "super": 0x08, "meta": 0x08,
}

KEY_CODES: Dict[str, int] = {
    # Letters
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    # Numbers
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    # Common keys
    "enter": 0x28, "return": 0x28, "escape": 0x29, "esc": 0x29,
    "backspace": 0x2A, "tab": 0x2B, "space": 0x2C,
    "minus": 0x2D, "-": 0x2D, "equal": 0x2E, "=": 0x2E,
    "lbracket": 0x2F, "[": 0x2F, "rbracket": 0x30, "]": 0x30,
    "backslash": 0x31, "\\": 0x31,
    "semicolon": 0x33, ";": 0x33, "quote": 0x34, "'": 0x34,
    "grave": 0x35, "`": 0x35,
    "comma": 0x36, ",": 0x36, "dot": 0x37, ".": 0x37,
    "slash": 0x38, "/": 0x38, "capslock": 0x39,
    # Function keys
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D,
    "f5": 0x3E, "f6": 0x3F, "f7": 0x40, "f8": 0x41,
    "f9": 0x42, "f10": 0x43, "f11": 0x44, "f12": 0x45,
    "f13": 0x68, "f14": 0x69, "f15": 0x6A, "f16": 0x6B,
    "f17": 0x6C, "f18": 0x6D, "f19": 0x6E, "f20": 0x6F,
    "f21": 0x70, "f22": 0x71, "f23": 0x72, "f24": 0x73,
    # Navigation
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48,
    "insert": 0x49, "home": 0x4A, "pageup": 0x4B,
    "delete": 0x4C, "end": 0x4D, "pagedown": 0x4E,
    "right_arrow": 0x4F, "left_arrow": 0x50, "down_arrow": 0x51,
    "up_arrow": 0x52,
    # Numpad
    "num0": 0x62, "num1": 0x59, "num2": 0x5A, "num3": 0x5B,
    "num4": 0x5C, "num5": 0x5D, "num6": 0x5E, "num7": 0x5F,
    "num8": 0x60, "num9": 0x61,
    "numenter": 0x58, "numdot": 0x63, "numplus": 0x57,
    "numminus": 0x56, "nummul": 0x55, "numdiv": 0x54, "numlock": 0x53,
}

ALL_KEY_NAMES = sorted(k for k in KEY_CODES if not any(c in k for c in "\\;',./`=-[]"))


# ---------------------------------------------------------------------------
# DPI code table (DPI value → 3-byte encoding, from m913-ctl protocol.cpp)
# ---------------------------------------------------------------------------
DPI_TABLE: Dict[int, Tuple[int, int, int]] = {
    100: (0x00, 0x00, 0x55), 200: (0x02, 0x02, 0x51),
    300: (0x03, 0x03, 0x4F), 400: (0x04, 0x04, 0x4D),
    500: (0x05, 0x05, 0x4B), 600: (0x06, 0x06, 0x49),
    700: (0x07, 0x07, 0x47), 800: (0x09, 0x09, 0x43),
    900: (0x0A, 0x0A, 0x41), 1000: (0x0B, 0x0B, 0x3F),
    1100: (0x0C, 0x0C, 0x3D), 1200: (0x0D, 0x0D, 0x3B),
    1300: (0x0E, 0x0E, 0x39), 1400: (0x10, 0x10, 0x35),
    1500: (0x11, 0x11, 0x33), 1600: (0x12, 0x12, 0x31),
    1700: (0x13, 0x13, 0x2F), 1800: (0x14, 0x14, 0x2D),
    1900: (0x16, 0x16, 0x29), 2000: (0x17, 0x17, 0x27),
    2100: (0x18, 0x18, 0x25), 2200: (0x19, 0x19, 0x23),
    2300: (0x1A, 0x1A, 0x21), 2400: (0x1B, 0x1B, 0x1F),
    2500: (0x1D, 0x1D, 0x1B), 2600: (0x1E, 0x1E, 0x19),
    2700: (0x1F, 0x1F, 0x17), 2800: (0x20, 0x20, 0x15),
    2900: (0x21, 0x21, 0x13), 3000: (0x23, 0x23, 0x0F),
    3200: (0x26, 0x26, 0x09), 3600: (0x2A, 0x2A, 0x01),
    4000: (0x2F, 0x2F, 0xF7), 4800: (0x39, 0x39, 0xE3),
    5000: (0x3B, 0x3B, 0xDF), 5500: (0x41, 0x41, 0xD3),
    6000: (0x47, 0x47, 0xC7), 6400: (0x4C, 0x4C, 0xBD),
    7000: (0x53, 0x53, 0xAF), 7200: (0x56, 0x56, 0xA9),
    7500: (0x59, 0x59, 0xA3), 8000: (0x5F, 0x5F, 0x97),
    8500: (0x65, 0x65, 0x8B), 9000: (0x6B, 0x6B, 0x7F),
    9600: (0x73, 0x73, 0x6F), 10000: (0x77, 0x77, 0x67),
    11000: (0x83, 0x83, 0x4F), 12000: (0x8F, 0x8F, 0x37),
    13000: (0x9B, 0x9B, 0x1F), 14000: (0xA7, 0xA7, 0x07),
    15000: (0xB3, 0xB3, 0xEF), 16000: (0xBD, 0xBD, 0xDB),
}

VALID_DPI_VALUES = sorted(DPI_TABLE.keys())
M913_DPI_MIN = VALID_DPI_VALUES[0]    # 100
M913_DPI_MAX = VALID_DPI_VALUES[-1]   # 16000


def clamp_dpi(dpi: int) -> int:
    """Snap a DPI value to the nearest valid M913 DPI step."""
    if dpi <= M913_DPI_MIN:
        return M913_DPI_MIN
    if dpi >= M913_DPI_MAX:
        return M913_DPI_MAX
    # Find nearest valid value
    best = M913_DPI_MIN
    for v in VALID_DPI_VALUES:
        if abs(v - dpi) < abs(best - dpi):
            best = v
    return best

# ---------------------------------------------------------------------------
# Protocol data tables (from m913-ctl protocol.cpp)
# ---------------------------------------------------------------------------

# Default button-mapping packets (8 × 17 bytes, two buttons per packet)
_DEFAULT_BUTTON_MAPPING: List[bytes] = [
    bytes([0x08,0x07,0x00,0x00,0x60,0x08, 0x00,0x00,0x00,0x55, 0x05,0x00,0x00,0x50, 0x00,0x00,0x34]),
    bytes([0x08,0x07,0x00,0x00,0x68,0x08, 0x05,0x00,0x00,0x50, 0x01,0x08,0x00,0x4C, 0x00,0x00,0x2C]),
    bytes([0x08,0x07,0x00,0x00,0x70,0x08, 0x05,0x00,0x00,0x50, 0x05,0x00,0x00,0x50, 0x00,0x00,0x24]),
    bytes([0x08,0x07,0x00,0x00,0x78,0x08, 0x01,0x02,0x00,0x52, 0x01,0x01,0x00,0x53, 0x00,0x00,0x1C]),
    bytes([0x08,0x07,0x00,0x00,0x80,0x08, 0x05,0x00,0x00,0x50, 0x05,0x00,0x00,0x50, 0x00,0x00,0x14]),
    bytes([0x08,0x07,0x00,0x00,0x88,0x08, 0x01,0x04,0x00,0x50, 0x04,0x3A,0x03,0x14, 0x00,0x00,0x0C]),
    bytes([0x08,0x07,0x00,0x00,0x90,0x08, 0x05,0x00,0x00,0x50, 0x05,0x00,0x00,0x50, 0x00,0x00,0x04]),
    bytes([0x08,0x07,0x00,0x00,0x98,0x08, 0x05,0x00,0x00,0x50, 0x05,0x00,0x00,0x50, 0x00,0x00,0xFC]),
]

# Per-button keyboard-key sub-packet address bytes
_KB_KEY_ADDR: List[Tuple[int, int]] = [
    (0x01, 0x00), (0x01, 0x20), (0x01, 0x40), (0x01, 0x60),
    (0x01, 0x80), (0x01, 0xA0), (0x01, 0xC0), (0x01, 0xE0),
    (0x02, 0x00), (0x02, 0x20), (0x02, 0x40), (0x02, 0x60),
    (0x02, 0x80), (0x02, 0xA0), (0x02, 0xC0), (0x02, 0xE0),
]

# Keyboard-key sub-packet template
_KB_KEY_TEMPLATE = bytes([
    0x08,0x07,0x00,0x01,0x60,0x08,
    0x02,0x81,0x21,0x00,0x41,0x21,0x00,0x4F,
    0x00,0x00,0x88
])

# Keyboard-key action marker in mapping packet
_KB_KEY_ACTION = bytes([0x05, 0x00, 0x00, 0x50])

# DPI config packet templates (4 packets)
_DPI_TEMPLATE: List[bytes] = [
    bytes([0x08,0x07,0x00,0x00,0x0C,0x08, 0x00,0x00,0x00,0x55, 0x02,0x02,0x00,0x51, 0x00,0x00,0x88]),
    bytes([0x08,0x07,0x00,0x00,0x14,0x08, 0x03,0x03,0x00,0x4F, 0x04,0x04,0x00,0x4D, 0x00,0x00,0x80]),
    bytes([0x08,0x07,0x00,0x00,0x1C,0x04, 0x05,0x05,0x00,0x4B, 0x00,0x00,0x00,0x00, 0x00,0x00,0xD1]),
    bytes([0x08,0x07,0x00,0x00,0x02,0x02, 0x05,0x50,0x00,0x00, 0x00,0x00,0x00,0x00, 0x00,0x00,0xED]),
]

# "Unknown_2" packets sent after DPI config (required)
_UNKNOWN2: List[bytes] = [
    bytes([0x08,0x07,0x00,0x00,0x2C,0x08, 0xFF,0x00,0x00,0x56, 0x00,0x00,0xFF,0x56, 0x00,0x00,0x68]),
    bytes([0x08,0x07,0x00,0x00,0x34,0x08, 0x00,0xFF,0x00,0x56, 0xFF,0xFF,0x00,0x57, 0x00,0x00,0x60]),
    bytes([0x08,0x07,0x00,0x00,0x3C,0x04, 0xFF,0x55,0x7D,0x84, 0x00,0x00,0x00,0x00, 0x00,0x00,0xB1]),
]

# LED templates
_LED_OFF = bytes([0x08,0x07,0x00,0x00,0x58,0x02, 0x00,0x55,0x00,0x00, 0x00,0x00,0x00,0x00, 0x00,0x00,0x97])

_LED_BREATHING: List[bytes] = [
    bytes([0x08,0x07,0x00,0x00,0x54,0x08, 0xFF,0x00,0x00,0x57, 0x01,0x54,0xFF,0x56, 0x00,0x00,0xEB]),
    bytes([0x08,0x07,0x00,0x00,0x5C,0x02, 0x03,0x52,0x00,0x00, 0x00,0x00,0x00,0x00, 0x00,0x00,0x93]),
]

_LED_RAINBOW: List[bytes] = [
    bytes([0x08,0x07,0x00,0x00,0x54,0x08, 0xFF,0x00,0xFF,0x57, 0x03,0x52,0x80,0xD5, 0x00,0x00,0xEB]),
    bytes([0x08,0x07,0x00,0x00,0x5C,0x02, 0x03,0x52,0x00,0x00, 0x00,0x00,0x00,0x00, 0x00,0x00,0x93]),
]

_LED_STATIC = bytes([0x08,0x07,0x00,0x00,0x54,0x08, 0xFF,0x00,0x00,0x57, 0x01,0x54,0xFF,0x56, 0x00,0x00,0xEB])


# ---------------------------------------------------------------------------
# Hardware macro constants (from mouse_m908 protocol docs)
# ---------------------------------------------------------------------------
MACRO_SLOT_COUNT = 15        # M913 supports 15 macro slots
MACRO_MAX_ACTIONS = 67       # Max key events per macro slot
MACRO_EVENT_DOWN = 0x81      # Key press event marker
MACRO_EVENT_UP = 0x41        # Key release event marker

# Macro button action marker: macro1–macro15
MACRO_ACTIONS: Dict[str, bytes] = {}
for _mi in range(1, MACRO_SLOT_COUNT + 1):
    _cksum = (0x55 - (0x93 + _mi)) & 0xFF
    MACRO_ACTIONS[f"macro{_mi}"] = bytes([0x93, _mi, 0x00, _cksum])
del _mi, _cksum

# Add macro actions to MOUSE_ACTIONS so parse_action() can find them
MOUSE_ACTIONS.update(MACRO_ACTIONS)
# Rebuild ALL_ACTIONS after adding macros
ALL_ACTIONS = sorted(MOUSE_ACTIONS.keys())


# ===================================================================
# Checksum
# ===================================================================

def compute_checksum(p: bytearray) -> int:
    """Host→device checksum: (0x55 - sum(bytes[0..15])) & 0xFF."""
    return (0x55 - sum(p[:PACKET_SIZE - 1])) & 0xFF


def _packet(src: bytes) -> bytearray:
    """Clone a template into a mutable bytearray."""
    return bytearray(src)


# ===================================================================
# Action parsing  (action string → 4-byte action code)
# ===================================================================

def parse_action(action_str: str) -> Optional[bytes]:
    """Parse an action string into 4-byte action code.

    Supports:
      - Mouse actions: "left", "right", "middle", "forward", "backward", ...
      - Keyboard keys: "a"–"z", "f1"–"f24", "0"–"9", ...
      - Combos: "ctrl+c", "shift+f4", "a+b" (max 3 keys)
      - Fire with params: "fire:58:3"

    Returns None if the action is not recognised.
    """
    action = action_str.strip().lower()
    if not action:
        return None

    # Fire with parameters
    if action.startswith("fire:"):
        parts = action.split(":")
        if len(parts) == 3:
            try:
                speed = int(parts[1])
                times = int(parts[2])
                if 3 <= speed <= 255 and 0 <= times <= 3:
                    cksum = (0x55 - (0x04 + speed + times)) & 0xFF
                    return bytes([0x04, speed, times, cksum])
            except ValueError:
                pass
        return None

    # Direct mouse/special action
    if action in MOUSE_ACTIONS:
        return MOUSE_ACTIONS[action]

    # Keyboard action: [modifier+]*key  or  key+key (multi-key)
    parts = [p.strip() for p in action.split("+") if p.strip()]
    if not parts:
        return None

    mods = 0
    keys: List[int] = []
    for part in parts:
        if part in MODIFIER_BITS:
            mods |= MODIFIER_BITS[part]
        elif part in KEY_CODES:
            keys.append(KEY_CODES[part])
        else:
            return None  # unrecognised token

    if not keys and mods:
        # Modifier-only binding
        return bytes([0x90, mods, 0x00, 0x00])
    elif len(keys) == 1:
        return bytes([0x90, mods, keys[0], 0x00])
    elif len(keys) >= 2:
        # Multi-key: key count in byte 3
        return bytes([0x90, mods, keys[0], min(len(keys), 255)])
    return None


def _parse_multikey(action_str: str) -> Optional[Tuple[int, List[int]]]:
    """Parse a multi-key combo into (modifier_byte, [scancode, ...])."""
    parts = [p.strip().lower() for p in action_str.split("+") if p.strip()]
    mods = 0
    keys: List[int] = []
    for part in parts:
        if part in MODIFIER_BITS:
            mods |= MODIFIER_BITS[part]
        elif part in KEY_CODES:
            keys.append(KEY_CODES[part])
        else:
            return None
    return (mods, keys)


# ===================================================================
# Packet builders (ported from m913-ctl protocol.cpp)
# ===================================================================

def build_button_mapping(changes: Dict[int, bytes],
                         multikey_actions: Optional[Dict[int, str]] = None
                         ) -> List[bytearray]:
    """Build the complete button-mapping packet sequence.

    ``changes``: button_index → 4-byte action bytes.
    ``multikey_actions``: button_index → original action string (for multi-key).
    Returns list of 17-byte packets to send (keyboard sub-packets first, then
    the 8 mapping packets).
    """
    buf = [_packet(t) for t in _DEFAULT_BUTTON_MAPPING]
    result: List[bytearray] = []

    for btn_idx, ab in changes.items():
        if btn_idx >= 16:
            continue

        if ab[0] in (0x90, 0x91, 0x92):
            # Keyboard-key / multimedia action — needs sub-packet(s)
            addr_hi, addr_lo = _KB_KEY_ADDR[btn_idx]

            if ab[0] == 0x92:
                # Multimedia key sub-packet
                extra, code, extra2 = ab[1], ab[2], ab[3]
                sub = bytearray(PACKET_SIZE)
                sub[0] = 0x08; sub[1] = 0x07; sub[2] = 0x00
                sub[3] = addr_hi; sub[4] = addr_lo; sub[5] = 0x08
                sub[6] = 0x02; sub[7] = 0x82
                sub[8] = code; sub[9] = extra
                sub[10] = 0x42; sub[11] = code; sub[12] = extra2
                isum = 0x02 + 0x82 + code + extra + 0x42 + code + extra2
                sub[13] = (0x55 - isum) & 0xFF
                sub[16] = compute_checksum(sub)
                result.append(sub)
            else:
                mods_byte = ab[1]
                scancode = ab[2]
                key_count = ab[3]

                # Collect all keys
                keys: List[int] = []
                if key_count > 1 and multikey_actions and btn_idx in multikey_actions:
                    parsed = _parse_multikey(multikey_actions[btn_idx])
                    if parsed and len(parsed[1]) >= 2:
                        mods_byte, keys = parsed[0], parsed[1]
                if not keys:
                    if scancode != 0:
                        keys = [scancode]

                if mods_byte != 0 and not keys:
                    # Modifier-only
                    sub = _packet(_KB_KEY_TEMPLATE)
                    sub[3] = addr_hi; sub[4] = addr_lo
                    sub[7] = 0x80; sub[8] = mods_byte
                    sub[10] = 0x40; sub[11] = mods_byte
                    isum = 0x02 + 0x80 + mods_byte + 0x40 + mods_byte
                    sub[13] = (0x55 - isum) & 0xFF
                    sub[16] = compute_checksum(sub)
                    result.append(sub)

                elif mods_byte == 0 and len(keys) == 1:
                    # Plain single key
                    sub = _packet(_KB_KEY_TEMPLATE)
                    sub[3] = addr_hi; sub[4] = addr_lo
                    sub[8] = keys[0]; sub[11] = keys[0]
                    sub[13] = (0x91 - 2 * keys[0]) & 0xFF
                    sub[16] = compute_checksum(sub)
                    result.append(sub)

                else:
                    # Modifier+key / multi-key
                    MOD_BITS_ORDER = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]
                    evts: List[int] = []
                    for b in MOD_BITS_ORDER:
                        if mods_byte & b:
                            evts.extend([0x80, b, 0x00])
                    for k in keys:
                        evts.extend([0x81, k, 0x00])
                    for b in MOD_BITS_ORDER:
                        if mods_byte & b:
                            evts.extend([0x40, b, 0x00])
                    for k in reversed(keys):
                        evts.extend([0x41, k, 0x00])

                    count = len(evts) // 3
                    isum_val = count + sum(evts)
                    inner_ck = (0x55 - (isum_val & 0xFF)) & 0xFF

                    # Packet 1
                    p1 = bytearray(PACKET_SIZE)
                    p1[0] = 0x08; p1[1] = 0x07; p1[2] = 0x00
                    p1[3] = addr_hi; p1[4] = addr_lo; p1[5] = 0x0A
                    p1[6] = count
                    for i in range(min(9, len(evts))):
                        p1[7 + i] = evts[i]
                    p1[16] = compute_checksum(p1)
                    result.append(p1)

                    # Packet 2
                    p1_evts = min(9, len(evts))
                    remaining = len(evts) - p1_evts
                    p2 = bytearray(PACKET_SIZE)
                    p2[0] = 0x08; p2[1] = 0x07; p2[2] = 0x00
                    p2[3] = addr_hi; p2[4] = (addr_lo + 0x0A) & 0xFF
                    p2[5] = remaining + 1
                    for i in range(remaining):
                        p2[6 + i] = evts[p1_evts + i]
                    p2[6 + remaining] = inner_ck
                    p2[16] = compute_checksum(p2)
                    result.append(p2)

            # Put KB_KEY_ACTION marker in the mapping packet
            pkt = btn_idx // 2
            off = 6 if (btn_idx % 2 == 0) else 10
            for k in range(4):
                buf[pkt][off + k] = _KB_KEY_ACTION[k]
        else:
            # Direct action (mouse button, DPI cycle, etc.)
            pkt = btn_idx // 2
            off = 6 if (btn_idx % 2 == 0) else 10
            for k in range(4):
                buf[pkt][off + k] = ab[k]

    # Recompute all mapping packet checksums
    for p in buf:
        p[16] = compute_checksum(p)

    # Sub-packets first, then the 8 mapping packets
    result.extend(buf)
    return result


def build_dpi_packets(values: List[int],
                      enabled: Optional[List[bool]] = None) -> List[bytearray]:
    """Build DPI config packets (4 + 3 unknown2 = 7 total).

    ``values``: list of 5 DPI values (use 0 to keep template default).
    ``enabled``: list of 5 booleans (default: all True).
    """
    if enabled is None:
        enabled = [True] * 5

    buf = [_packet(t) for t in _DPI_TEMPLATE]

    def set_level(pkt: int, base_off: int, dpi_val: int) -> None:
        code = DPI_TABLE.get(dpi_val)
        if not code:
            return
        buf[pkt][base_off] = code[0]
        buf[pkt][base_off + 1] = code[1]
        buf[pkt][base_off + 3] = code[2]  # +3 not +2 (0x00 gap)

    if values[0]:
        set_level(0, 6, values[0])
    if values[1]:
        set_level(0, 10, values[1])
    if values[2]:
        set_level(1, 6, values[2])
    if values[3]:
        set_level(1, 10, values[3])
    if values[4]:
        set_level(2, 6, values[4])

    # Enabled levels
    num_enabled = sum(1 for e in enabled if e)
    if num_enabled > 0:
        e1, e2 = 0x05, 0x50
        if not enabled[4]:
            e1, e2 = 0x04, 0x51
        if not enabled[3]:
            e1, e2 = 0x03, 0x52
        if not enabled[2]:
            e1, e2 = 0x02, 0x53
        if not enabled[1]:
            e1, e2 = 0x01, 0x54
        buf[3][6] = e1
        buf[3][7] = e2

    for p in buf:
        p[16] = compute_checksum(p)

    result: List[bytearray] = list(buf)
    for u in _UNKNOWN2:
        result.append(_packet(u))
    return result


def build_led_packets(mode: str, color: int = 0x00FF00,
                      brightness: int = 0xFF,
                      speed: int = 3) -> List[bytearray]:
    """Build LED config packets.

    ``mode``: "off", "steady", "respiration", "rainbow", "wave",
              "reactive", "random", "alternating", "flashing"
    ``color``: 24-bit RGB (0xRRGGBB)
    ``brightness``: 0–255 (steady mode only)
    ``speed``: 1–5 (respiration/wave/flashing mode, 1=slowest)
    """
    mode_lower = mode.lower()

    if mode_lower == "off":
        return [_packet(_LED_OFF)]

    r_val = (color >> 16) & 0xFF
    g_val = (color >> 8) & 0xFF
    b_val = color & 0xFF

    if mode_lower == "respiration":
        p1 = _packet(_LED_BREATHING[0])
        p1[6] = r_val; p1[7] = g_val; p1[8] = b_val
        p1[9] = (0x55 - r_val - g_val - b_val) & 0xFF
        p1[10] = 0x02  # respiration mode
        p1[11] = (0x55 - 0x02) & 0xFF
        p1[12] = brightness
        p1[13] = (0x55 - brightness) & 0xFF
        p1[16] = compute_checksum(p1)

        p2 = _packet(_LED_BREATHING[1])
        p2[6] = speed
        p2[7] = (0x55 - speed) & 0xFF
        p2[16] = compute_checksum(p2)
        return [p1, p2]

    if mode_lower == "rainbow":
        return [_packet(t) for t in _LED_RAINBOW]

    if mode_lower == "wave":
        # Wave: mode byte 0x04, uses speed + color
        p1 = _packet(_LED_BREATHING[0])
        p1[6] = r_val; p1[7] = g_val; p1[8] = b_val
        p1[9] = (0x55 - r_val - g_val - b_val) & 0xFF
        p1[10] = 0x04  # wave mode
        p1[11] = (0x55 - 0x04) & 0xFF
        p1[12] = brightness
        p1[13] = (0x55 - brightness) & 0xFF
        p1[16] = compute_checksum(p1)

        p2 = _packet(_LED_BREATHING[1])
        p2[6] = speed
        p2[7] = (0x55 - speed) & 0xFF
        p2[16] = compute_checksum(p2)
        return [p1, p2]

    if mode_lower == "reactive":
        # Reactive: mode byte 0x05, lights on click then fades
        p1 = _packet(_LED_BREATHING[0])
        p1[6] = r_val; p1[7] = g_val; p1[8] = b_val
        p1[9] = (0x55 - r_val - g_val - b_val) & 0xFF
        p1[10] = 0x05  # reactive mode
        p1[11] = (0x55 - 0x05) & 0xFF
        p1[12] = brightness
        p1[13] = (0x55 - brightness) & 0xFF
        p1[16] = compute_checksum(p1)

        p2 = _packet(_LED_BREATHING[1])
        p2[6] = speed
        p2[7] = (0x55 - speed) & 0xFF
        p2[16] = compute_checksum(p2)
        return [p1, p2]

    if mode_lower == "random":
        # Random: mode byte 0x06, random color cycle
        p1 = _packet(_LED_BREATHING[0])
        p1[6] = r_val; p1[7] = g_val; p1[8] = b_val
        p1[9] = (0x55 - r_val - g_val - b_val) & 0xFF
        p1[10] = 0x06  # random mode
        p1[11] = (0x55 - 0x06) & 0xFF
        p1[12] = brightness
        p1[13] = (0x55 - brightness) & 0xFF
        p1[16] = compute_checksum(p1)

        p2 = _packet(_LED_BREATHING[1])
        p2[6] = speed
        p2[7] = (0x55 - speed) & 0xFF
        p2[16] = compute_checksum(p2)
        return [p1, p2]

    if mode_lower == "alternating":
        # Alternating: mode byte 0x07, alternates between color and secondary
        p1 = _packet(_LED_BREATHING[0])
        p1[6] = r_val; p1[7] = g_val; p1[8] = b_val
        p1[9] = (0x55 - r_val - g_val - b_val) & 0xFF
        p1[10] = 0x07  # alternating mode
        p1[11] = (0x55 - 0x07) & 0xFF
        p1[12] = brightness
        p1[13] = (0x55 - brightness) & 0xFF
        p1[16] = compute_checksum(p1)

        p2 = _packet(_LED_BREATHING[1])
        p2[6] = speed
        p2[7] = (0x55 - speed) & 0xFF
        p2[16] = compute_checksum(p2)
        return [p1, p2]

    if mode_lower == "flashing":
        # Flashing: mode byte 0x08, on/off blink at speed
        p1 = _packet(_LED_BREATHING[0])
        p1[6] = r_val; p1[7] = g_val; p1[8] = b_val
        p1[9] = (0x55 - r_val - g_val - b_val) & 0xFF
        p1[10] = 0x08  # flashing mode
        p1[11] = (0x55 - 0x08) & 0xFF
        p1[12] = brightness
        p1[13] = (0x55 - brightness) & 0xFF
        p1[16] = compute_checksum(p1)

        p2 = _packet(_LED_BREATHING[1])
        p2[6] = speed
        p2[7] = (0x55 - speed) & 0xFF
        p2[16] = compute_checksum(p2)
        return [p1, p2]

    # Steady (static color with brightness)
    p = _packet(_LED_STATIC)
    p[6] = r_val; p[7] = g_val; p[8] = b_val
    p[9] = (0x55 - r_val - g_val - b_val) & 0xFF
    p[10] = 0x01  # steady
    p[11] = (0x55 - 0x01) & 0xFF
    p[12] = brightness
    p[13] = (0x55 - brightness) & 0xFF
    p[16] = compute_checksum(p)
    return [p]


def build_polling_rate_packet(hz: int) -> bytearray:
    """Build polling rate config packet. Valid: 125, 250, 500, 1000 Hz."""
    if hz >= 1000:
        code = 0x01
    elif hz >= 500:
        code = 0x02
    elif hz >= 250:
        code = 0x04
    else:
        code = 0x08  # 125 Hz

    p = bytearray(PACKET_SIZE)
    p[0] = 0x08; p[1] = 0x07
    p[4] = 0x00; p[5] = 0x02
    p[6] = code
    p[7] = (0x55 - code) & 0xFF
    p[16] = compute_checksum(p)
    return p


# ===================================================================
# Macro packet builder (from mouse_m908 macro protocol)
# ===================================================================

@dataclass
class MacroSlot:
    """One hardware macro: a list of key events."""
    events: List[Tuple[int, int]] = field(default_factory=list)
    # Each event is (event_type, scancode)
    # event_type: MACRO_EVENT_DOWN (0x81) or MACRO_EVENT_UP (0x41)

    def to_list(self) -> List[List[int]]:
        return [[t, s] for t, s in self.events]

    @classmethod
    def from_list(cls, data: List[List[int]]) -> "MacroSlot":
        return cls(events=[(e[0], e[1]) for e in data if len(e) == 2])

    def is_empty(self) -> bool:
        return len(self.events) == 0


def build_macro_packets(slot_num: int, macro: MacroSlot) -> List[bytearray]:
    """Build packets to write one macro slot to the device.

    ``slot_num``: 1-based macro slot number (1–15).
    ``macro``: MacroSlot with up to 67 events.

    The M913 macro memory layout:
      Each macro occupies a contiguous block.  We pack events as 3-byte
      tuples (event_type, scancode, 0x00) into the packet data area.
      The macro header packet: [0x08, 0x07, 0x00, addr_hi, addr_lo, count, ...]
    """
    if slot_num < 1 or slot_num > MACRO_SLOT_COUNT:
        return []

    events = macro.events[:MACRO_MAX_ACTIONS]
    if not events:
        return []

    # Macro base address: slot_num determines the address block
    base_addr = 0x0300 + (slot_num - 1) * 0x0100
    addr_hi = (base_addr >> 8) & 0xFF
    addr_lo = base_addr & 0xFF

    # Pack all events into a byte stream
    event_bytes: List[int] = []
    for evt_type, scancode in events:
        event_bytes.extend([evt_type, scancode, 0x00])

    # Header packet: tells the device how many events
    result: List[bytearray] = []
    hdr = bytearray(PACKET_SIZE)
    hdr[0] = 0x08; hdr[1] = 0x07; hdr[2] = 0x00
    hdr[3] = addr_hi; hdr[4] = addr_lo; hdr[5] = 0x02
    hdr[6] = len(events)
    hdr[7] = (0x55 - len(events)) & 0xFF
    hdr[16] = compute_checksum(hdr)
    result.append(hdr)

    # Data packets: 10 event bytes per packet (bytes 6–15)
    offset = 0
    pkt_addr = addr_lo + 0x02
    while offset < len(event_bytes):
        chunk = event_bytes[offset:offset + 10]
        p = bytearray(PACKET_SIZE)
        p[0] = 0x08; p[1] = 0x07; p[2] = 0x00
        p[3] = addr_hi; p[4] = pkt_addr & 0xFF
        p[5] = len(chunk)
        for i, b in enumerate(chunk):
            p[6 + i] = b
        p[16] = compute_checksum(p)
        result.append(p)
        offset += 10
        pkt_addr += len(chunk)

    return result


# ===================================================================
# Device info & profile data classes
# ===================================================================

@dataclass
class M913DeviceInfo:
    """Info about a discovered M913 device."""
    path: bytes  # hidapi device path (unique, opaque)
    serial_number: str
    product_string: str
    interface_number: int
    manufacturer_string: str = ""

    @property
    def display_name(self) -> str:
        sn = self.serial_number or "no-serial"
        return f"M913 ({sn})"

    @property
    def device_id(self) -> str:
        """Stable-ish identifier for config storage (serial preferred)."""
        if self.serial_number:
            return f"m913_{self.serial_number}"
        # Fallback: hash of path (less stable across reconnects)
        return f"m913_path_{hash(self.path) & 0xFFFFFFFF:08x}"


@dataclass
class M913Profile:
    """A complete M913 configuration (ready to apply to a device)."""
    name: str = "Default"
    buttons: Dict[str, str] = field(default_factory=lambda: {
        "left": "left", "right": "right", "middle": "middle",
        "fire": "fire", "side1": "none", "side2": "none",
        "side3": "none", "side4": "none", "side5": "none", "side6": "none",
        "side7": "none", "side8": "none", "side9": "none", "side10": "none",
        "side11": "none", "side12": "none",
    })
    dpi_values: List[int] = field(default_factory=lambda: [800, 1600, 3200, 6400, 16000])
    dpi_enabled: List[bool] = field(default_factory=lambda: [True, True, True, True, True])
    led_mode: str = "steady"     # off, steady, respiration, rainbow
    led_color: int = 0x00FF00    # 24-bit RGB
    led_brightness: int = 255
    led_speed: int = 3           # 1–5 (respiration only)
    polling_rate: int = 1000     # 125, 250, 500, 1000

    # Hardware macros: slot_num (1–15) → MacroSlot
    macros: Dict[int, MacroSlot] = field(default_factory=dict)

    # Sister profile linking: which Joy-Con slot this should auto-apply with
    sister_slot: Optional[int] = None  # 1–4, or None

    # Layout mode: "stock" (default M913) or "incedius" (IncediusMod)
    layout: str = "stock"

    # Custom IncediusMod button assignments (side key → label).
    # Users physically rewire the M913, so the button IDs may not match
    # the default Incedius mapping.  This lets each user match the UI to
    # their specific wiring.
    incedius_map: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_INCEDIUS_MAP)
    )

    def to_dict(self) -> dict:
        macros_out: Dict[str, Any] = {}
        for slot_num, ms in self.macros.items():
            if not ms.is_empty():
                macros_out[str(slot_num)] = ms.to_list()
        return {
            "ver": 2,
            "name": self.name,
            "layout": self.layout,
            "buttons": dict(self.buttons),
            "dpi": {
                "values": list(self.dpi_values),
                "enabled": list(self.dpi_enabled),
            },
            "led": {
                "mode": self.led_mode,
                "color": f"{self.led_color:06x}",
                "brightness": self.led_brightness,
                "speed": self.led_speed,
            },
            "polling_rate": self.polling_rate,
            "macros": macros_out,
            "sister_slot": self.sister_slot,
            "incedius_map": dict(self.incedius_map),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "M913Profile":
        p = cls()
        p.name = d.get("name", "Default")
        p.buttons = d.get("buttons", p.buttons)
        dpi = d.get("dpi", {})
        p.dpi_values = dpi.get("values", p.dpi_values)
        p.dpi_enabled = dpi.get("enabled", p.dpi_enabled)
        led = d.get("led", {})
        p.led_mode = led.get("mode", "steady")
        color_str = led.get("color", "00ff00")
        if isinstance(color_str, int):
            p.led_color = color_str
        else:
            p.led_color = int(color_str, 16)
        p.led_brightness = led.get("brightness", 255)
        p.led_speed = led.get("speed", 3)
        p.polling_rate = d.get("polling_rate", 1000)
        # Hardware macros (v2+)
        raw_macros = d.get("macros", {})
        if isinstance(raw_macros, dict):
            for k, v in raw_macros.items():
                try:
                    slot_num = int(k)
                    if 1 <= slot_num <= MACRO_SLOT_COUNT and isinstance(v, list):
                        p.macros[slot_num] = MacroSlot.from_list(v)
                except (ValueError, TypeError):
                    pass
        p.sister_slot = d.get("sister_slot", None)
        layout = d.get("layout", "stock")
        p.layout = layout if layout in LAYOUT_MODES else "stock"
        raw_map = d.get("incedius_map", None)
        if isinstance(raw_map, dict):
            merged = dict(DEFAULT_INCEDIUS_MAP)
            for k, v in raw_map.items():
                if k in INCEDIUS_SIDE_KEYS and v in INCEDIUS_LABEL_CHOICES:
                    merged[k] = v
            p.incedius_map = merged
        return p

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        log.info("Saved M913 profile '%s' → %s", self.name, path)

    @classmethod
    def load(cls, path: str) -> "M913Profile":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ===================================================================
# Device communication
# ===================================================================

class M913Device:
    """Manages USB HID communication with one M913 mouse."""

    def __init__(self) -> None:
        self._dev: Any = None
        self._info: Optional[M913DeviceInfo] = None

    @property
    def is_open(self) -> bool:
        return self._dev is not None

    @property
    def info(self) -> Optional[M913DeviceInfo]:
        return self._info

    # ── Enumeration ──────────────────────────────────────────────

    @staticmethod
    def enumerate() -> List[M913DeviceInfo]:
        """Find all connected M913 devices.

        Returns one entry per physical device (filtered to interface 1,
        which is the config channel).  Checks both wired and wireless PIDs.
        """
        if not HID_AVAILABLE:
            return []

        results: List[M913DeviceInfo] = []
        for pid in M913_PIDS:
            try:
                devs = _hid.enumerate(M913_VID, pid)
            except Exception as e:
                log.error("HID enumerate failed for PID 0x%04X: %s", pid, e)
                continue

            for d in devs:
                # We only need Interface 1 (the config channel)
                iface = d.get("interface_number", -1)
                if iface != 1:
                    continue
                path = d.get("path")
                if not path:
                    continue
                results.append(M913DeviceInfo(
                    path=path,
                    serial_number=d.get("serial_number", "") or "",
                    product_string=d.get("product_string", "") or "",
                    interface_number=iface,
                    manufacturer_string=d.get("manufacturer_string", "") or "",
                ))

        log.info("Found %d M913 device(s)", len(results))
        return results

    # ── Open / Close ─────────────────────────────────────────────

    def open(self, device_info: M913DeviceInfo) -> None:
        """Open a specific M913 device by path."""
        if not HID_AVAILABLE:
            raise RuntimeError("hidapi not installed — cannot open M913")
        self.close()
        self._dev = _hid.device()
        self._dev.open_path(device_info.path)
        self._info = device_info
        log.info("Opened M913 at %s", device_info.display_name)

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None
            self._info = None

    # ── Low-level send/recv ──────────────────────────────────────

    def send_packet(self, packet: bytearray) -> None:
        """Send a 17-byte feature report to the mouse."""
        if self._dev is None:
            raise RuntimeError("Device not open")
        # hidapi send_feature_report: data[0] = report ID (0x08)
        try:
            self._dev.send_feature_report(bytes(packet))
        except Exception as e:
            log.error("M913 HID write failed: %s", e)
            raise RuntimeError(f"M913 USB write failed (device disconnected?): {e}") from e

    def recv_packet(self, timeout_ms: int = 2000) -> Optional[bytes]:
        """Read a 17-byte response from the interrupt endpoint."""
        if self._dev is None:
            raise RuntimeError("Device not open")
        data = self._dev.read(PACKET_SIZE, timeout_ms)
        if data:
            return bytes(data)
        return None

    def send_recv(self, packet: bytearray) -> Optional[bytes]:
        """Send a packet and read back the ACK response."""
        self.send_packet(packet)
        return self.recv_packet()

    # ── High-level apply methods ─────────────────────────────────

    def apply_profile(self, profile: M913Profile) -> Tuple[int, int]:
        """Apply a full profile to the device. Returns (sent, errors)."""
        sent = 0
        errors = 0
        # Buttons
        try:
            s, e = self.apply_buttons(profile.buttons)
            sent += s; errors += e
        except Exception as ex:
            log.error("Button mapping failed: %s", ex)
            errors += 1

        # DPI
        try:
            s, e = self.apply_dpi(profile.dpi_values, profile.dpi_enabled)
            sent += s; errors += e
        except Exception as ex:
            log.error("DPI config failed: %s", ex)
            errors += 1

        # LED
        try:
            s, e = self.apply_led(profile.led_mode, profile.led_color,
                                  profile.led_brightness, profile.led_speed)
            sent += s; errors += e
        except Exception as ex:
            log.error("LED config failed: %s", ex)
            errors += 1

        # Polling rate
        try:
            s, e = self.apply_polling_rate(profile.polling_rate)
            sent += s; errors += e
        except Exception as ex:
            log.error("Polling rate failed: %s", ex)
            errors += 1

        # Hardware macros
        if profile.macros:
            try:
                s, e = self.apply_macros(profile.macros)
                sent += s; errors += e
            except Exception as ex:
                log.error("Macro config failed: %s", ex)
                errors += 1

        log.info("Profile '%s' applied: %d packets sent, %d errors",
                 profile.name, sent, errors)
        return sent, errors

    def apply_buttons(self, buttons: Dict[str, str]) -> Tuple[int, int]:
        """Apply button mappings. Returns (sent, errors)."""
        changes: Dict[int, bytes] = {}
        multikey: Dict[int, str] = {}
        for name, action_str in buttons.items():
            idx = BUTTON_NAMES.get(name)
            if idx is None:
                continue
            action_bytes = parse_action(action_str)
            if action_bytes is None:
                log.warning("Unknown action '%s' for button '%s'", action_str, name)
                continue
            changes[idx] = action_bytes
            # Track multi-key actions for sub-packet generation
            if action_bytes[0] == 0x90 and action_bytes[3] > 1:
                multikey[idx] = action_str

        packets = build_button_mapping(changes, multikey)
        return self._send_packets(packets)

    def apply_dpi(self, values: List[int],
                  enabled: Optional[List[bool]] = None) -> Tuple[int, int]:
        """Apply DPI configuration. Returns (sent, errors)."""
        packets = build_dpi_packets(values, enabled)
        return self._send_packets(packets)

    def apply_led(self, mode: str, color: int = 0x00FF00,
                  brightness: int = 0xFF, speed: int = 3) -> Tuple[int, int]:
        """Apply LED configuration. Returns (sent, errors)."""
        packets = build_led_packets(mode, color, brightness, speed)
        return self._send_packets(packets)

    def apply_polling_rate(self, hz: int) -> Tuple[int, int]:
        """Apply polling rate. Returns (sent, errors)."""
        pkt = build_polling_rate_packet(hz)
        return self._send_packets([pkt])

    def apply_macros(self, macros: Dict[int, MacroSlot]) -> Tuple[int, int]:
        """Apply hardware macros. Returns (sent, errors)."""
        sent = 0
        errors = 0
        for slot_num, macro in macros.items():
            if macro.is_empty():
                continue
            packets = build_macro_packets(slot_num, macro)
            s, e = self._send_packets(packets)
            sent += s
            errors += e
        return sent, errors

    def _send_packets(self, packets: List[bytearray],
                      retries: int = 2) -> Tuple[int, int]:
        """Send a sequence of packets with retry and ACK verification.

        Each packet is retried up to ``retries`` times on failure.
        Returns (sent, errors).
        """
        sent = 0
        errors = 0
        for pkt in packets:
            success = False
            for attempt in range(retries + 1):
                try:
                    self.send_packet(pkt)
                    ack = self.recv_packet(timeout_ms=500)
                    if ack is not None:
                        success = True
                        break
                    # No ACK — might be normal for some packets
                    if attempt == 0:
                        success = True  # accept first silent success
                        break
                except Exception as e:
                    log.warning("Packet send attempt %d/%d failed: %s",
                                attempt + 1, retries + 1, e)
                    if attempt < retries:
                        time.sleep(0.05)
            if success:
                sent += 1
            else:
                log.error("Packet failed after %d retries", retries + 1)
                errors += 1
        return sent, errors


# ===================================================================
# Profile storage helpers
# ===================================================================

def get_profiles_dir() -> Path:
    """Get the M913 profiles directory (per-user, created if needed)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", ""))
    else:
        base = Path.home() / ".config"
    d = base / "BindBandit" / "m913"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_saved_profiles() -> List[str]:
    """List saved M913 profile names (without extension)."""
    d = get_profiles_dir()
    return sorted(p.stem for p in d.glob("*.json"))


def save_profile(profile: M913Profile) -> str:
    """Save a profile and return the file path."""
    path = get_profiles_dir() / f"{profile.name}.json"
    profile.save(str(path))
    return str(path)


def load_profile(name: str) -> M913Profile:
    """Load a saved profile by name."""
    path = get_profiles_dir() / f"{name}.json"
    return M913Profile.load(str(path))


def delete_profile(name: str) -> None:
    """Delete a saved profile."""
    path = get_profiles_dir() / f"{name}.json"
    if path.exists():
        path.unlink()
        log.info("Deleted M913 profile '%s'", name)


# ===================================================================
# Device registry (remembers per-device settings)
# ===================================================================

def _registry_path() -> Path:
    return get_profiles_dir() / "_devices.json"


def load_device_registry() -> Dict[str, dict]:
    """Load saved device→profile associations."""
    p = _registry_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_device_registry(registry: Dict[str, dict]) -> None:
    """Save device→profile associations."""
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ===================================================================
# INI import / export  (m913-ctl compatible format)
# ===================================================================

# Reverse lookup: 4-byte action → action name
_ACTION_BYTES_TO_NAME: Dict[bytes, str] = {v: k for k, v in MOUSE_ACTIONS.items()}


def export_ini(profile: M913Profile, path: str) -> None:
    """Export an M913Profile to an INI file (m913-ctl compatible).

    Format::

        [profile]
        name = Default
        button_left = left
        button_right = right
        ...
        dpi_1 = 800
        ...
        dpi_enabled = 1,1,1,1,1
        led_mode = steady
        led_color = 00ff00
        led_brightness = 255
        led_speed = 3
        polling_rate = 1000
    """
    cp = configparser.ConfigParser()
    section = "profile"
    cp.add_section(section)

    cp.set(section, "name", profile.name)

    # Buttons
    for btn_name in BUTTON_ORDER:
        action = profile.buttons.get(btn_name, "none")
        cp.set(section, f"button_{btn_name}", action)

    # DPI
    for i, val in enumerate(profile.dpi_values[:5]):
        cp.set(section, f"dpi_{i + 1}", str(val))
    cp.set(section, "dpi_enabled",
           ",".join("1" if e else "0" for e in profile.dpi_enabled[:5]))

    # LED
    cp.set(section, "led_mode", profile.led_mode)
    cp.set(section, "led_color", f"{profile.led_color:06x}")
    cp.set(section, "led_brightness", str(profile.led_brightness))
    cp.set(section, "led_speed", str(profile.led_speed))

    # Polling
    cp.set(section, "polling_rate", str(profile.polling_rate))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)
    log.info("Exported M913 INI → %s", path)


def import_ini(path: str) -> M913Profile:
    """Import an M913Profile from an INI file (m913-ctl compatible).

    Tolerates missing fields — any absent key keeps the default value.
    """
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")

    section = "profile"
    if not cp.has_section(section):
        # Fallback: try first section
        sections = cp.sections()
        if sections:
            section = sections[0]
        else:
            raise ValueError(f"No sections found in INI file: {path}")

    p = M913Profile()
    p.name = cp.get(section, "name", fallback=p.name)

    # Buttons
    for btn_name in BUTTON_ORDER:
        key = f"button_{btn_name}"
        if cp.has_option(section, key):
            action = cp.get(section, key).strip()
            # Validate: must be a known action or key combo
            if parse_action(action) is not None:
                p.buttons[btn_name] = action
            else:
                log.warning("INI import: unknown action '%s' for %s", action, key)

    # DPI
    for i in range(5):
        key = f"dpi_{i + 1}"
        if cp.has_option(section, key):
            try:
                val = int(cp.get(section, key))
                p.dpi_values[i] = clamp_dpi(val)
            except ValueError:
                pass
    if cp.has_option(section, "dpi_enabled"):
        parts = cp.get(section, "dpi_enabled").split(",")
        for i, tok in enumerate(parts[:5]):
            p.dpi_enabled[i] = tok.strip() == "1"

    # LED
    p.led_mode = cp.get(section, "led_mode", fallback=p.led_mode)
    if cp.has_option(section, "led_color"):
        try:
            p.led_color = int(cp.get(section, "led_color").strip(), 16)
        except ValueError:
            pass
    if cp.has_option(section, "led_brightness"):
        try:
            p.led_brightness = max(0, min(255, int(cp.get(section, "led_brightness"))))
        except ValueError:
            pass
    if cp.has_option(section, "led_speed"):
        try:
            p.led_speed = max(1, min(5, int(cp.get(section, "led_speed"))))
        except ValueError:
            pass

    # Polling
    if cp.has_option(section, "polling_rate"):
        try:
            hz = int(cp.get(section, "polling_rate"))
            if hz in (125, 250, 500, 1000):
                p.polling_rate = hz
        except ValueError:
            pass

    log.info("Imported M913 INI ← %s  (profile '%s')", path, p.name)
    return p
