"""Shared constants for the PyQt6 UI.

Hotspot coordinates, image dimensions, color maps, and keyboard↔HID mappings
extracted from the original Tkinter ``app.py``.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Image dimensions (native resolution of the source PNGs)
# ---------------------------------------------------------------------------
JOYCONS_IMAGE_W = 1536
JOYCONS_IMAGE_H = 1024
JOYCONS_IMAGE_STATE_NAMES = ("none", "left", "right", "both")

KEYBOARD_IMAGE_W = 1536
KEYBOARD_IMAGE_H = 1024

M913_IMAGE_STATE_NAMES = ("none", "connected")
RAZER_IMAGE_STATE_NAMES = ("none", "connected")

M913_IMAGE_W = 1536
M913_IMAGE_H = 1024
MOUSE_IMAGE_W = 1536
MOUSE_IMAGE_H = 1024

# ---------------------------------------------------------------------------
# Rainbow overlay colours — matches generate_button_overlays.py output
# ---------------------------------------------------------------------------
RAINBOW_COLORS: Dict[str, str] = {
    "red":    "#dc3c3c",
    "orange": "#e68c28",
    "yellow": "#d2be28",
    "green":  "#3cb950",
    "blue":   "#3c78dc",
    "indigo": "#5a3cb4",
    "violet": "#a03cc8",
}
RAINBOW_NAMES: List[str] = list(RAINBOW_COLORS.keys())
DEFAULT_OVERLAY_COLOR = "violet"

# ---------------------------------------------------------------------------
# Joy-Con hotspot positions (normalised 0.0–1.0 over joycons.png)
# ---------------------------------------------------------------------------
KEYMAP_HOTSPOTS: List[Tuple[str, float, float]] = [
    ("ZL",   420 / JOYCONS_IMAGE_W,  150 / JOYCONS_IMAGE_H),
    ("ZR",  1115 / JOYCONS_IMAGE_W,  150 / JOYCONS_IMAGE_H),
    ("L",    420 / JOYCONS_IMAGE_W,  220 / JOYCONS_IMAGE_H),
    ("R",   1115 / JOYCONS_IMAGE_W,  220 / JOYCONS_IMAGE_H),
    ("-",    420 / JOYCONS_IMAGE_W,  335 / JOYCONS_IMAGE_H),
    ("+",   1110 / JOYCONS_IMAGE_W,  335 / JOYCONS_IMAGE_H),
    ("CAP",  395 / JOYCONS_IMAGE_W,  720 / JOYCONS_IMAGE_H),
    ("HOME",1140 / JOYCONS_IMAGE_W,  720 / JOYCONS_IMAGE_H),
    ("LSTK", 250 / JOYCONS_IMAGE_W,  435 / JOYCONS_IMAGE_H),
    ("D-UP", 300 / JOYCONS_IMAGE_W,  545 / JOYCONS_IMAGE_H),
    ("D-DN", 300 / JOYCONS_IMAGE_W,  665 / JOYCONS_IMAGE_H),
    ("D-L",  225 / JOYCONS_IMAGE_W,  605 / JOYCONS_IMAGE_H),
    ("D-R",  375 / JOYCONS_IMAGE_W,  605 / JOYCONS_IMAGE_H),
    ("A",   1330 / JOYCONS_IMAGE_W,  460 / JOYCONS_IMAGE_H),
    ("B",   1260 / JOYCONS_IMAGE_W,  535 / JOYCONS_IMAGE_H),
    ("X",   1260 / JOYCONS_IMAGE_W,  385 / JOYCONS_IMAGE_H),
    ("Y",   1190 / JOYCONS_IMAGE_W,  460 / JOYCONS_IMAGE_H),
    ("RSTK",1260 / JOYCONS_IMAGE_W,  605 / JOYCONS_IMAGE_H),
    # Right stick virtual directions
    ("RS-UP",  1260 / JOYCONS_IMAGE_W,  545 / JOYCONS_IMAGE_H),
    ("RS-DN",  1260 / JOYCONS_IMAGE_W,  665 / JOYCONS_IMAGE_H),
    ("RS-L",   1195 / JOYCONS_IMAGE_W,  605 / JOYCONS_IMAGE_H),
    ("RS-R",   1330 / JOYCONS_IMAGE_W,  605 / JOYCONS_IMAGE_H),
    # IMU / motion gestures
    ("Shake",    650 / JOYCONS_IMAGE_W,  870 / JOYCONS_IMAGE_H),
    ("TiltUp",   768 / JOYCONS_IMAGE_W,  830 / JOYCONS_IMAGE_H),
    ("TiltDn",   768 / JOYCONS_IMAGE_W,  910 / JOYCONS_IMAGE_H),
    ("TiltL",    700 / JOYCONS_IMAGE_W,  870 / JOYCONS_IMAGE_H),
    ("TiltR",    836 / JOYCONS_IMAGE_W,  870 / JOYCONS_IMAGE_H),
    ("Flick",    890 / JOYCONS_IMAGE_W,  870 / JOYCONS_IMAGE_H),
]

# ---------------------------------------------------------------------------
# Keyboard hotspot positions (normalised over keyboard.png)
# ---------------------------------------------------------------------------
KBD_HOTSPOTS: List[Tuple[str, float, float]] = [
    # ── Function row ──
    ("Esc",    97 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F1",    207 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F2",    267 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F3",    327 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F4",    387 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F5",    477 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F6",    537 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F7",    597 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F8",    657 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F9",    747 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F10",   807 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F11",   867 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F12",   927 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    # ── Top-right cluster ──
    ("PrtSc",1007 / KEYBOARD_IMAGE_W, 155 / KEYBOARD_IMAGE_H),
    ("ScrLk",1067 / KEYBOARD_IMAGE_W, 155 / KEYBOARD_IMAGE_H),
    ("Pause",1127 / KEYBOARD_IMAGE_W, 155 / KEYBOARD_IMAGE_H),
    # ── Number row ──
    ("`",      97 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("1",     157 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("2",     217 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("3",     277 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("4",     337 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("5",     397 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("6",     457 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("7",     517 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("8",     577 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("9",     637 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("0",     697 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("-",     757 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("=",     817 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("Bksp",  907 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    # ── Nav cluster row 1 ──
    ("Ins",  1007 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("Home", 1067 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("PgUp", 1127 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    # ── Numpad row 1 ──
    ("NumLk",1217 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("KP/",  1277 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("KP*",  1337 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("KP-",  1397 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    # ── QWERTY row ──
    ("Tab",   117 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("Q",     187 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("W",     247 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("E",     307 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("R",     367 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("T",     427 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("Y",     487 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("U",     547 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("I",     607 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("O",     667 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("P",     727 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("[",     787 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("]",     847 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("\\",    917 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    # ── Nav cluster row 2 ──
    ("Del",  1007 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("End",  1067 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("PgDn", 1127 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    # ── Numpad row 2 ──
    ("KP7",  1217 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("KP8",  1277 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("KP9",  1337 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("KP+",  1397 / KEYBOARD_IMAGE_W, 390 / KEYBOARD_IMAGE_H),
    # ── Home row ──
    ("CapsLk",127 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("A",     207 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("S",     267 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("D",     327 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("F",     387 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("G",     447 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("H",     507 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("J",     567 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("K",     627 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("L",     687 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    (";",     747 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("'",     807 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("Enter", 897 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    # ── Numpad row 3 ──
    ("KP4",  1217 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("KP5",  1277 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("KP6",  1337 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    # ── Shift row ──
    ("LShift",137 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("Z",     247 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("X",     307 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("C",     367 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("V",     427 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("B",     487 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("N",     547 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("M",     607 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    (",",     667 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    (".",     727 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("/",     787 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("RShift",887 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    # ── Arrow up ──
    ("Up",   1067 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    # ── Numpad row 4 ──
    ("KP1",  1217 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("KP2",  1277 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("KP3",  1337 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("KPEnt",1397 / KEYBOARD_IMAGE_W, 545 / KEYBOARD_IMAGE_H),
    # ── Bottom row ──
    ("LCtrl", 117 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Win",   187 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("LAlt",  247 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Space", 487 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("RAlt",  667 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Fn",    727 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("RCtrl", 847 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    # ── Arrow keys ──
    ("Left", 1007 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Down", 1067 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Right",1127 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    # ── Numpad bottom ──
    ("KP0",  1247 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("KP.",  1337 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
]

# ---------------------------------------------------------------------------
# M913 Stock hotspot positions (normalised over m913.png, 16 buttons)
# ---------------------------------------------------------------------------
M913_HOTSPOTS: List[Tuple[str, float, float]] = [
    # Main buttons
    ("left",       670 / M913_IMAGE_W,  250 / M913_IMAGE_H),
    ("right",      890 / M913_IMAGE_W,  250 / M913_IMAGE_H),
    ("middle",     785 / M913_IMAGE_W,  225 / M913_IMAGE_H),
    ("fire",       700 / M913_IMAGE_W,  360 / M913_IMAGE_H),
    # Scroll wheel
    ("scroll_up",  785 / M913_IMAGE_W,  190 / M913_IMAGE_H),
    ("scroll_down",785 / M913_IMAGE_W,  260 / M913_IMAGE_H),
    # Side buttons — 4 rows × 3 cols
    ("side1",      530 / M913_IMAGE_W,  380 / M913_IMAGE_H),
    ("side2",      575 / M913_IMAGE_W,  380 / M913_IMAGE_H),
    ("side3",      620 / M913_IMAGE_W,  380 / M913_IMAGE_H),
    ("side4",      530 / M913_IMAGE_W,  435 / M913_IMAGE_H),
    ("side5",      575 / M913_IMAGE_W,  435 / M913_IMAGE_H),
    ("side6",      620 / M913_IMAGE_W,  435 / M913_IMAGE_H),
    ("side7",      530 / M913_IMAGE_W,  490 / M913_IMAGE_H),
    ("side8",      575 / M913_IMAGE_W,  490 / M913_IMAGE_H),
    ("side9",      620 / M913_IMAGE_W,  490 / M913_IMAGE_H),
    ("side10",     530 / M913_IMAGE_W,  540 / M913_IMAGE_H),
    ("side11",     575 / M913_IMAGE_W,  540 / M913_IMAGE_H),
    ("side12",     620 / M913_IMAGE_W,  540 / M913_IMAGE_H),
]

# ---------------------------------------------------------------------------
# Incedius M913 hotspot positions (same physical mouse, IncediusMod labels)
# ---------------------------------------------------------------------------
INCEDIUS_HOTSPOTS: List[Tuple[str, float, float]] = [
    # Main buttons (unchanged)
    ("left",       670 / M913_IMAGE_W,  250 / M913_IMAGE_H),
    ("right",      890 / M913_IMAGE_W,  250 / M913_IMAGE_H),
    ("middle",     785 / M913_IMAGE_W,  225 / M913_IMAGE_H),
    ("fire",       700 / M913_IMAGE_W,  360 / M913_IMAGE_H),
    # Scroll wheel
    ("scroll_up",  785 / M913_IMAGE_W,  190 / M913_IMAGE_H),
    ("scroll_down",785 / M913_IMAGE_W,  260 / M913_IMAGE_H),
    # Thumb buttons (side1-6 → Thumb 1-6)
    ("Thumb1",     530 / M913_IMAGE_W,  380 / M913_IMAGE_H),
    ("Thumb2",     575 / M913_IMAGE_W,  380 / M913_IMAGE_H),
    ("Thumb3",     620 / M913_IMAGE_W,  380 / M913_IMAGE_H),
    ("Thumb4",     530 / M913_IMAGE_W,  435 / M913_IMAGE_H),
    ("Thumb5",     575 / M913_IMAGE_W,  435 / M913_IMAGE_H),
    ("Thumb6",     620 / M913_IMAGE_W,  435 / M913_IMAGE_H),
    # Finger buttons (side7-12 → Finger 1-6)
    ("Finger1",    530 / M913_IMAGE_W,  490 / M913_IMAGE_H),
    ("Finger2",    575 / M913_IMAGE_W,  490 / M913_IMAGE_H),
    ("Finger3",    620 / M913_IMAGE_W,  490 / M913_IMAGE_H),
    ("Finger4",    530 / M913_IMAGE_W,  540 / M913_IMAGE_H),
    ("Finger5",    575 / M913_IMAGE_W,  540 / M913_IMAGE_H),
    ("Finger6",    620 / M913_IMAGE_W,  540 / M913_IMAGE_H),
]

# ---------------------------------------------------------------------------
# Generic Mouse / Razer hotspot positions (normalised, 7 buttons)
# ---------------------------------------------------------------------------
MOUSE_HOTSPOTS: List[Tuple[str, float, float]] = [
    ("left",        700 / MOUSE_IMAGE_W,  310 / MOUSE_IMAGE_H),
    ("right",       850 / MOUSE_IMAGE_W,  310 / MOUSE_IMAGE_H),
    ("middle",      775 / MOUSE_IMAGE_W,  260 / MOUSE_IMAGE_H),
    ("scroll_up",   775 / MOUSE_IMAGE_W,  220 / MOUSE_IMAGE_H),
    ("scroll_down", 775 / MOUSE_IMAGE_W,  310 / MOUSE_IMAGE_H),
    ("back",        645 / MOUSE_IMAGE_W,  430 / MOUSE_IMAGE_H),
    ("forward",     645 / MOUSE_IMAGE_W,  380 / MOUSE_IMAGE_H),
]

# ---------------------------------------------------------------------------
# Keyboard label → HID keycode (positive = keycode, negative = modifier bit)
# ---------------------------------------------------------------------------
KBD_LABEL_TO_KEYCODE: Dict[str, int] = {
    "Esc": 0x29, "F1": 0x3A, "F2": 0x3B, "F3": 0x3C, "F4": 0x3D,
    "F5": 0x3E, "F6": 0x3F, "F7": 0x40, "F8": 0x41,
    "F9": 0x42, "F10": 0x43, "F11": 0x44, "F12": 0x45,
    "PrtSc": 0x46, "ScrLk": 0x47, "Pause": 0x48,
    "`": 0x35, "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21,
    "5": 0x22, "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "-": 0x2D, "=": 0x2E, "Bksp": 0x2A,
    "Ins": 0x49, "Home": 0x4A, "PgUp": 0x4B,
    "NumLk": 0x53, "KP/": 0x54, "KP*": 0x55, "KP-": 0x56,
    "Tab": 0x2B, "Q": 0x14, "W": 0x1A, "E": 0x08, "R": 0x15,
    "T": 0x17, "Y": 0x1C, "U": 0x18, "I": 0x0C, "O": 0x12,
    "P": 0x13, "[": 0x2F, "]": 0x30, "\\": 0x31,
    "Del": 0x4C, "End": 0x4D, "PgDn": 0x4E,
    "KP7": 0x5F, "KP8": 0x60, "KP9": 0x61, "KP+": 0x57,
    "CapsLk": 0x39, "A": 0x04, "S": 0x16, "D": 0x07, "F": 0x09,
    "G": 0x0A, "H": 0x0B, "J": 0x0D, "K": 0x0E, "L": 0x0F,
    ";": 0x33, "'": 0x34, "Enter": 0x28,
    "KP4": 0x5C, "KP5": 0x5D, "KP6": 0x5E,
    "LShift": -0x02, "Z": 0x1D, "X": 0x1B, "C": 0x06, "V": 0x19,
    "B": 0x05, "N": 0x11, "M": 0x10, ",": 0x36, ".": 0x37, "/": 0x38,
    "RShift": -0x20, "Up": 0x52,
    "KP1": 0x59, "KP2": 0x5A, "KP3": 0x5B, "KPEnt": 0x28,
    "LCtrl": -0x01, "Win": -0x08, "LAlt": -0x04,
    "Space": 0x2C, "RAlt": -0x40, "RCtrl": -0x10,
    "Left": 0x50, "Down": 0x51, "Right": 0x4F,
    "KP0": 0x62, "KP.": 0x63,
}

_KEYCODE_TO_KBD_LABEL: Dict[int, str] = {v: k for k, v in KBD_LABEL_TO_KEYCODE.items()}
_MODBITS_TO_KBD_LABELS: Dict[int, List[str]] = {}
for _lbl, _code in KBD_LABEL_TO_KEYCODE.items():
    if _code < 0:
        _MODBITS_TO_KBD_LABELS.setdefault(-_code, []).append(_lbl)
