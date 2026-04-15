"""Shared constants for the PyQt6 UI.

Hotspot coordinates, image dimensions, color maps, and keyboard↔HID mappings
extracted from the original Tkinter ``app.py``.
"""
from __future__ import annotations

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
RAINBOW_COLORS: dict[str, str] = {
    "red":    "#ef2f2f",
    "orange": "#ff8a1a",
    "yellow": "#f1d118",
    "green":  "#22d65a",
    "blue":   "#2f86ff",
    "indigo": "#6a3cff",
    "violet": "#c13cff",
}
RAINBOW_NAMES: list[str] = list(RAINBOW_COLORS.keys())
DEFAULT_OVERLAY_COLOR = "violet"

# ---------------------------------------------------------------------------
# Joy-Con hotspot positions — per-theme (normalised 0.0–1.0 over joycons.png)
# ---------------------------------------------------------------------------
KEYMAP_HOTSPOTS: dict[str, list[tuple[str, float, float]]] = {
    "dark": [
        ("ZL",      0.212987, 0.158442),
        ("ZR",      0.789610, 0.159740),
        ("L",       0.212121, 0.210390),
        ("R",       0.789610, 0.211688),
        ("Minus",   0.264941, 0.371534),
        ("Plus",    0.731602, 0.376623),
        ("Capture", 0.251948, 0.668831),
        ("Home",    0.738528, 0.672727),
        ("LStick",  0.230437, 0.436229),
        ("LSUp",    0.230437, 0.436229),
        ("LSDown",  0.230437, 0.436229),
        ("LSLeft",  0.230437, 0.436229),
        ("LSRight", 0.230437, 0.436229),
        ("DUp",     0.232902, 0.537893),
        ("DDown",   0.230437, 0.613678),
        ("DLeft",   0.199630, 0.576710),
        ("DRight",  0.262477, 0.573013),
        ("A",       0.802218, 0.452865),
        ("B",       0.768946, 0.499076),
        ("X",       0.768946, 0.410351),
        ("Y",       0.735675, 0.456562),
        ("RStick",  0.767714, 0.587800),
        ("RSUp",    0.767714, 0.587800),
        ("RSDown",  0.767714, 0.587800),
        ("RSLeft",  0.767714, 0.587800),
        ("RSRight", 0.767714, 0.587800),
        ("Shake",   0.423177, 0.849609),
        ("TiltUp",  0.500000, 0.810547),
        ("TiltDn",  0.500000, 0.888672),
        ("TiltL",   0.455729, 0.849609),
        ("TiltR",   0.544271, 0.849609),
        ("Flick",   0.579427, 0.849609),
        ("SL(L)",   0.406654, 0.458410),
        ("SR(L)",   0.406654, 0.661738),
        ("SL(R)",   0.589610, 0.462338),
        ("SR(R)",   0.591342, 0.663636),
    ],
    "default": [
        ("ZL",      0.212987, 0.158442),
        ("ZR",      0.789610, 0.159740),
        ("L",       0.212121, 0.210390),
        ("R",       0.789610, 0.211688),
        ("Minus",   0.264941, 0.371534),
        ("Plus",    0.731602, 0.376623),
        ("Capture", 0.251948, 0.668831),
        ("Home",    0.738528, 0.672727),
        ("LStick",  0.230437, 0.436229),
        ("LSUp",    0.230437, 0.436229),
        ("LSDown",  0.230437, 0.436229),
        ("LSLeft",  0.230437, 0.436229),
        ("LSRight", 0.230437, 0.436229),
        ("DUp",     0.232902, 0.537893),
        ("DDown",   0.230437, 0.613678),
        ("DLeft",   0.199630, 0.576710),
        ("DRight",  0.262477, 0.573013),
        ("A",       0.802218, 0.452865),
        ("B",       0.768946, 0.499076),
        ("X",       0.768946, 0.410351),
        ("Y",       0.735675, 0.456562),
        ("RStick",  0.767714, 0.587800),
        ("RSUp",    0.767714, 0.587800),
        ("RSDown",  0.767714, 0.587800),
        ("RSLeft",  0.767714, 0.587800),
        ("RSRight", 0.767714, 0.587800),
        ("Shake",   0.423177, 0.849609),
        ("TiltUp",  0.500000, 0.810547),
        ("TiltDn",  0.500000, 0.888672),
        ("TiltL",   0.455729, 0.849609),
        ("TiltR",   0.544271, 0.849609),
        ("Flick",   0.579427, 0.849609),
        ("SL(L)",   0.406654, 0.458410),
        ("SR(L)",   0.406654, 0.661738),
        ("SL(R)",   0.589610, 0.462338),
        ("SR(R)",   0.591342, 0.663636),
    ],
}

# ---------------------------------------------------------------------------
# Joy-Con button shapes — pixel dimensions at native 1536×1024 resolution
#
# Shape spec formats:
#   ("circle", radius)
#   ("rrect", width, height, corner_radius)
#   ("plus", arm_length, thickness)
#   ("home", size)
#   ("camera", size)
#   ("arrow_up"|"arrow_down"|"arrow_left"|"arrow_right", size)
#   ("arc_top"|"arc_bottom"|"arc_left"|"arc_right", inner_r, outer_r)
# If a button name is absent the default circle of _DOT_RADIUS is used.
# ---------------------------------------------------------------------------
ShapeSpec = tuple

JOYCON_BUTTON_SHAPES: dict[str, ShapeSpec] = {
    # Triggers — wide rounded bumper shapes
    "ZL":      ("rrect", 80, 30, 10),
    "ZR":      ("rrect", 80, 30, 10),
    # Bumpers — slightly narrower
    "L":       ("rrect", 72, 26, 8),
    "R":       ("rrect", 72, 26, 8),
    # Face buttons — circles
    "A":       ("circle", 22),
    "B":       ("circle", 22),
    "X":       ("circle", 22),
    "Y":       ("circle", 22),
    # Thumbsticks — larger circles
    "LStick":  ("circle", 28),
    "RStick":  ("circle", 28),
    # Stick directions — quarter-ring arcs around thumbstick
    "LSUp":    ("arc_top", 30, 48),
    "LSDown":  ("arc_bottom", 30, 48),
    "LSLeft":  ("arc_left", 30, 48),
    "LSRight": ("arc_right", 30, 48),
    "RSUp":    ("arc_top", 30, 48),
    "RSDown":  ("arc_bottom", 30, 48),
    "RSLeft":  ("arc_left", 30, 48),
    "RSRight": ("arc_right", 30, 48),
    # D-pad — directional arrows
    "DUp":     ("arrow_up", 20),
    "DDown":   ("arrow_down", 20),
    "DLeft":   ("arrow_left", 20),
    "DRight":  ("arrow_right", 20),
    # Plus — cross/plus shape, Minus — wide pill
    "Plus":    ("plus", 16, 7),
    "Minus":   ("rrect", 32, 16, 6),
    # Capture — camera shape, Home — house shape
    "Capture": ("camera", 18),
    "Home":    ("home", 18),
    # Side-rail buttons — tall narrow pills
    "SL(L)":   ("rrect", 20, 50, 8),
    "SR(L)":   ("rrect", 20, 50, 8),
    "SL(R)":   ("rrect", 20, 50, 8),
    "SR(R)":   ("rrect", 20, 50, 8),
    # Motion / IMU — circles
    "Shake":   ("circle", 22),
    "TiltUp":  ("circle", 20),
    "TiltDn":  ("circle", 20),
    "TiltL":   ("circle", 20),
    "TiltR":   ("circle", 20),
    "Flick":   ("circle", 22),
}

# ---------------------------------------------------------------------------
# Keyboard hotspot positions (normalised over keyboard.png)
# ---------------------------------------------------------------------------
_KBD_HOTSPOTS_BASE: list[tuple[str, float, float]] = [
    ("Esc",       0.137511, 0.298956),
    ("F1",        0.199304, 0.296345),
    ("F2",        0.234117, 0.295039),
    ("F3",        0.266319, 0.295039),
    ("F4",        0.300261, 0.297650),
    ("F5",        0.346388, 0.296345),
    ("F6",        0.379460, 0.295039),
    ("F7",        0.411662, 0.293734),
    ("F8",        0.444735, 0.293734),
    ("F9",        0.489991, 0.293734),
    ("F10",       0.523934, 0.293734),
    ("F11",       0.556136, 0.292428),
    ("F12",       0.589208, 0.292428),
    ("PrtSc",     0.636205, 0.295039),
    ("ScrLk",     0.668407, 0.293734),
    ("Pause",     0.702350, 0.295039),
    ("Grave",     0.134900, 0.369452),
    ("1",         0.167972, 0.368146),
    ("2",         0.199304, 0.372063),
    ("3",         0.235857, 0.373368),
    ("4",         0.266319, 0.370757),
    ("5",         0.300261, 0.372063),
    ("6",         0.331593, 0.370757),
    ("7",         0.362924, 0.369452),
    ("8",         0.394256, 0.370757),
    ("9",         0.425587, 0.369452),
    ("0",         0.456049, 0.368146),
    ("Minus",     0.488251, 0.368146),
    ("Equal",     0.517842, 0.370757),
    ("Backspace", 0.577894, 0.370757),
    ("Ins",       0.637076, 0.373368),
    ("Home",      0.670148, 0.373368),
    ("PgUp",      0.702350, 0.372063),
    ("NumLk",     0.747607, 0.370757),
    ("KPDiv",     0.783290, 0.374674),
    ("KPMul",     0.816362, 0.373368),
    ("KPMin",     0.848564, 0.372063),
    ("Tab",       0.142733, 0.421671),
    ("Q",         0.184508, 0.420366),
    ("W",         0.217581, 0.421671),
    ("E",         0.248912, 0.420366),
    ("R",         0.282855, 0.420366),
    ("T",         0.314186, 0.421671),
    ("Y",         0.345518, 0.420366),
    ("U",         0.380331, 0.420366),
    ("I",         0.410792, 0.421671),
    ("O",         0.441253, 0.421671),
    ("P",         0.472585, 0.420366),
    ("LBracket",  0.503046, 0.419060),
    ("RBracket",  0.533507, 0.420366),
    ("Backslash", 0.578764, 0.420366),
    ("Del",       0.635335, 0.422977),
    ("End",       0.670148, 0.422977),
    ("PgDn",      0.703220, 0.422977),
    ("KP7",       0.750218, 0.426893),
    ("KP8",       0.785030, 0.422977),
    ("KP9",       0.818103, 0.419060),
    ("KPPlus",    0.849434, 0.456919),
    ("CapsLk",    0.148825, 0.466057),
    ("A",         0.194952, 0.469974),
    ("S",         0.228024, 0.468668),
    ("D",         0.262837, 0.468668),
    ("F",         0.293299, 0.471279),
    ("G",         0.322889, 0.468668),
    ("H",         0.355091, 0.468668),
    ("J",         0.389904, 0.467363),
    ("K",         0.422977, 0.467363),
    ("L",         0.451697, 0.467363),
    ("Semicolon", 0.484769, 0.466057),
    ("Apostrophe", 0.516971, 0.466057),
    ("Enter",     0.571802, 0.468668),
    ("KP4",       0.749347, 0.472585),
    ("KP5",       0.785030, 0.471279),
    ("KP6",       0.816362, 0.469974),
    ("LShift",    0.160139, 0.519582),
    ("Z",         0.208877, 0.519582),
    ("X",         0.241079, 0.520888),
    ("C",         0.275022, 0.518277),
    ("V",         0.308094, 0.519582),
    ("B",         0.341166, 0.518277),
    ("N",         0.372498, 0.516971),
    ("M",         0.404700, 0.519582),
    ("Comma",     0.436031, 0.519582),
    ("Period",    0.468233, 0.520888),
    ("Slash",     0.498695, 0.519582),
    ("RShift",    0.559617, 0.520888),
    ("Up",        0.670148, 0.519582),
    ("KP1",       0.749347, 0.520888),
    ("KP2",       0.783290, 0.520888),
    ("KP3",       0.817232, 0.520888),
    ("KPEnter",   0.850305, 0.562663),
    ("LCtrl",     0.138381, 0.566580),
    ("Win",       0.180157, 0.567885),
    ("LAlt",      0.224543, 0.566580),
    ("Space",     0.367276, 0.566580),
    ("RAlt",      0.461271, 0.565274),
    ("Fn",        0.543081, 0.565274),
    ("RCtrl",     0.587467, 0.566580),
    ("Left",      0.636205, 0.567885),
    ("Down",      0.669278, 0.569191),
    ("Right",     0.704961, 0.569191),
    ("KP0",       0.765883, 0.567885),
    ("KPDot",     0.818103, 0.570496),
]


KBD_HOTSPOTS: dict[str, list[tuple[str, float, float]]] = {
    "dark": list(_KBD_HOTSPOTS_BASE),
    "default": list(_KBD_HOTSPOTS_BASE),
}


def _kbd_shape(width_units: float = 1.0, height_units: float = 1.0) -> ShapeSpec:
    """Return a rounded-rectangle shape aligned to the keyboard art grid."""
    base_width = 54
    base_height = 54
    width = round(base_width + 60 * (width_units - 1.0))
    height = round(base_height + 80 * (height_units - 1.0))
    return ("rrect", width, height, 8)


KBD_BUTTON_SHAPES: dict[str, ShapeSpec] = {
    name: _kbd_shape() for name, _, _ in KBD_HOTSPOTS["default"]
}

for _name in (
    "Esc", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
    "F9", "F10", "F11", "F12", "PrtSc", "ScrLk", "Pause",
):
    KBD_BUTTON_SHAPES[_name] = _kbd_shape(height_units=0.85)

KBD_BUTTON_SHAPES.update({
    "Backspace": _kbd_shape(2.25),
    "Tab": _kbd_shape(1.5),
    "Backslash": _kbd_shape(1.5),
    "CapsLk": _kbd_shape(1.75),
    "Enter": _kbd_shape(2.25),
    "LShift": _kbd_shape(2.25),
    "RShift": _kbd_shape(2.75),
    "LCtrl": _kbd_shape(1.25),
    "Win": _kbd_shape(1.25),
    "LAlt": _kbd_shape(1.25),
    "Space": _kbd_shape(3.75),
    "RAlt": _kbd_shape(1.25),
    "Fn": _kbd_shape(1.25),
    "RCtrl": _kbd_shape(1.25),
    "KP0": _kbd_shape(2.0),
    "KPPlus": _kbd_shape(1.0, 1.5),
    "KPEnter": _kbd_shape(1.0, 1.5),
})

# ---------------------------------------------------------------------------
# M913 Stock hotspot positions (normalised over m913.png, 16 buttons)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# M913 Stock hotspot positions — per-theme (normalised over m913.png)
# ---------------------------------------------------------------------------
M913_HOTSPOTS: dict[str, list[tuple[str, float, float]]] = {
    "dark": [
        ("left",        0.417582, 0.262363),
        ("right",       0.511905, 0.173077),
        ("middle",      0.438645, 0.174451),
        ("fire",        0.352564, 0.245879),
        ("scroll_up",   0.406593, 0.166209),
        ("scroll_down", 0.463370, 0.207418),
        ("side1",       0.374542, 0.439560),
        ("side2",       0.386447, 0.398352),
        ("side3",       0.402015, 0.361264),
        ("side4",       0.404762, 0.478022),
        ("side5",       0.421245, 0.438187),
        ("side6",       0.435897, 0.394231),
        ("side7",       0.430403, 0.509615),
        ("side8",       0.445971, 0.473901),
        ("side9",       0.459707, 0.432692),
        ("side10",      0.454212, 0.546703),
        ("side11",      0.472527, 0.517857),
        ("side12",      0.484432, 0.478022),
    ],
    "default": [
        ("left",        0.417582, 0.262363),
        ("right",       0.511905, 0.173077),
        ("middle",      0.438645, 0.174451),
        ("fire",        0.352564, 0.245879),
        ("scroll_up",   0.406593, 0.166209),
        ("scroll_down", 0.463370, 0.207418),
        ("side1",       0.374542, 0.439560),
        ("side2",       0.386447, 0.398352),
        ("side3",       0.402015, 0.361264),
        ("side4",       0.404762, 0.478022),
        ("side5",       0.421245, 0.438187),
        ("side6",       0.435897, 0.394231),
        ("side7",       0.430403, 0.509615),
        ("side8",       0.445971, 0.473901),
        ("side9",       0.459707, 0.432692),
        ("side10",      0.454212, 0.546703),
        ("side11",      0.472527, 0.517857),
        ("side12",      0.484432, 0.478022),
    ],
}

# ---------------------------------------------------------------------------
# Incedius M913 hotspot positions — per-theme (same side1-12 IDs as stock)
# ---------------------------------------------------------------------------
INCEDIUS_HOTSPOTS: dict[str, list[tuple[str, float, float]]] = {
    "dark": [
        ("left",        0.585165, 0.633242),
        ("right",       0.604396, 0.515110),
        ("middle",      0.539377, 0.554945),
        ("fire",        0.599817, 0.572802),
        ("scroll_up",   0.543040, 0.502747),
        ("scroll_down", 0.530220, 0.608516),
        ("side1",       0.355311, 0.291209),
        ("side2",       0.413004, 0.254121),
        ("side3",       0.463370, 0.233516),
        ("side4",       0.403846, 0.325549),
        ("side5",       0.456960, 0.304945),
        ("side6",       0.444139, 0.372253),
        ("side7",       0.391941, 0.402473),
        ("side8",       0.336996, 0.358516),
        ("side9",       0.456914, 0.432866),
        ("side10",      0.392857, 0.472527),
        ("side11",      0.327839, 0.445055),
        ("side12",      0.391026, 0.563187),
    ],
    "default": [
        ("left",        0.585165, 0.633242),
        ("right",       0.604396, 0.515110),
        ("middle",      0.539377, 0.554945),
        ("fire",        0.599817, 0.572802),
        ("scroll_up",   0.543040, 0.502747),
        ("scroll_down", 0.530220, 0.608516),
        ("side1",       0.355311, 0.291209),
        ("side2",       0.413004, 0.254121),
        ("side3",       0.463370, 0.233516),
        ("side4",       0.403846, 0.325549),
        ("side5",       0.456960, 0.304945),
        ("side6",       0.444139, 0.372253),
        ("side7",       0.391941, 0.402473),
        ("side8",       0.336996, 0.358516),
        ("side9",       0.456914, 0.432866),
        ("side10",      0.392857, 0.472527),
        ("side11",      0.327839, 0.445055),
        ("side12",      0.391026, 0.563187),
    ],
}

# ---------------------------------------------------------------------------
# Generic Mouse / Razer hotspot positions — per-theme (normalised, 7 buttons)
# ---------------------------------------------------------------------------
MOUSE_HOTSPOTS: dict[str, list[tuple[str, float, float]]] = {
    "dark": [
        ("left",        0.463339, 0.463956),
        ("right",       0.409119, 0.280961),
        ("middle",      0.418977, 0.336414),
        ("scroll_up",   0.373383, 0.353050),
        ("scroll_down", 0.458410, 0.343808),
        ("back",        0.608749, 0.591497),
        ("forward",     0.518792, 0.580407),
    ],
    "default": [
        ("left",        0.463339, 0.463956),
        ("right",       0.409119, 0.280961),
        ("middle",      0.418977, 0.336414),
        ("scroll_up",   0.373383, 0.353050),
        ("scroll_down", 0.458410, 0.343808),
        ("back",        0.608749, 0.591497),
        ("forward",     0.518792, 0.580407),
    ],
}

# ---------------------------------------------------------------------------
# Wide button sets — buttons with larger hit area / overlay radius
# ---------------------------------------------------------------------------
M913_WIDE = {"left", "right"}
INCEDIUS_WIDE = {"left", "right"}
MOUSE_WIDE = {"left", "right"}
KBD_WIDE = {
    "Backspace", "Tab", "CapsLk", "Enter", "LShift", "RShift",
    "Space", "LCtrl", "RCtrl", "KP0", "KPPlus", "KPEnter",
}

# ---------------------------------------------------------------------------
# Keyboard label → HID keycode (positive = keycode, negative = modifier bit)
# ---------------------------------------------------------------------------
KBD_LABEL_TO_KEYCODE: dict[str, int] = {
    "Esc": 0x29, "F1": 0x3A, "F2": 0x3B, "F3": 0x3C, "F4": 0x3D,
    "F5": 0x3E, "F6": 0x3F, "F7": 0x40, "F8": 0x41,
    "F9": 0x42, "F10": 0x43, "F11": 0x44, "F12": 0x45,
    "PrtSc": 0x46, "ScrLk": 0x47, "Pause": 0x48,
    "Grave": 0x35, "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21,
    "5": 0x22, "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "Minus": 0x2D, "Equal": 0x2E, "Backspace": 0x2A,
    "Ins": 0x49, "Home": 0x4A, "PgUp": 0x4B,
    "NumLk": 0x53, "KPDiv": 0x54, "KPMul": 0x55, "KPMin": 0x56,
    "Tab": 0x2B, "Q": 0x14, "W": 0x1A, "E": 0x08, "R": 0x15,
    "T": 0x17, "Y": 0x1C, "U": 0x18, "I": 0x0C, "O": 0x12,
    "P": 0x13, "LBracket": 0x2F, "RBracket": 0x30, "Backslash": 0x31,
    "Del": 0x4C, "End": 0x4D, "PgDn": 0x4E,
    "KP7": 0x5F, "KP8": 0x60, "KP9": 0x61, "KPPlus": 0x57,
    "CapsLk": 0x39, "A": 0x04, "S": 0x16, "D": 0x07, "F": 0x09,
    "G": 0x0A, "H": 0x0B, "J": 0x0D, "K": 0x0E, "L": 0x0F,
    "Semicolon": 0x33, "Apostrophe": 0x34, "Enter": 0x28,
    "KP4": 0x5C, "KP5": 0x5D, "KP6": 0x5E,
    "LShift": -0x02, "Z": 0x1D, "X": 0x1B, "C": 0x06, "V": 0x19,
    "B": 0x05, "N": 0x11, "M": 0x10, "Comma": 0x36, "Period": 0x37, "Slash": 0x38,
    "RShift": -0x20, "Up": 0x52,
    "KP1": 0x59, "KP2": 0x5A, "KP3": 0x5B, "KPEnter": 0x28,
    "LCtrl": -0x01, "Win": -0x08, "LAlt": -0x04,
    "Space": 0x2C, "RAlt": -0x40, "RCtrl": -0x10,
    "Left": 0x50, "Down": 0x51, "Right": 0x4F,
    "KP0": 0x62, "KPDot": 0x63,
}

_KEYCODE_TO_KBD_LABEL: dict[int, str] = {v: k for k, v in KBD_LABEL_TO_KEYCODE.items()}
_MODBITS_TO_KBD_LABELS: dict[int, list[str]] = {}
for _lbl, _code in KBD_LABEL_TO_KEYCODE.items():
    if _code < 0:
        _MODBITS_TO_KBD_LABELS.setdefault(-_code, []).append(_lbl)


# ---------------------------------------------------------------------------
# Gamepad (Xbox Elite) image dimensions & state names
# ---------------------------------------------------------------------------
GAMEPAD_IMAGE_W = 1536
GAMEPAD_IMAGE_H = 1024
GAMEPAD_IMAGE_STATE_NAMES = ("none", "connected")

# ---------------------------------------------------------------------------
# Gamepad hotspot positions — per-theme (normalised over gamepad.png)
#
# Xbox Elite controller layout:
#   Triggers (LT/RT), Bumpers (LB/RB), Sticks (LS/RS + 4 directions each),
#   D-pad (4 directions), Face buttons (A/B/X/Y), Center (Xbox/View/Menu/Share),
#   Back paddles (P1/P2/P3/P4).
# ---------------------------------------------------------------------------
GAMEPAD_HOTSPOTS: dict[str, list[tuple[str, float, float]]] = {
    "dark": [
        # Triggers (top of controller)
        ("LT",       0.265, 0.310),
        ("RT",       0.775, 0.310),
        # Bumpers (just below triggers)
        ("LB",       0.295, 0.345),
        ("RB",       0.745, 0.345),
        # Center cluster
        ("Xbox",     0.520, 0.345),
        ("View",     0.460, 0.400),
        ("Menu",     0.575, 0.400),
        ("Share",    0.520, 0.420),
        # Left stick (upper left quadrant)
        ("LS",       0.340, 0.395),
        ("LSUp",     0.340, 0.395),
        ("LSDown",   0.340, 0.395),
        ("LSLeft",   0.340, 0.395),
        ("LSRight",  0.340, 0.395),
        # D-pad (lower left quadrant)
        ("DUp",      0.445, 0.545),
        ("DDown",    0.445, 0.600),
        ("DLeft",    0.415, 0.572),
        ("DRight",   0.475, 0.572),
        # Face buttons (right quadrant — diamond layout)
        ("Y",        0.735, 0.385),
        ("X",        0.710, 0.415),
        ("B",        0.760, 0.415),
        ("A",        0.735, 0.445),
        # Right stick (lower right)
        ("RS",       0.615, 0.520),
        ("RSUp",     0.615, 0.520),
        ("RSDown",   0.615, 0.520),
        ("RSLeft",   0.615, 0.520),
        ("RSRight",  0.615, 0.520),
        # Back paddles (lower grip area)
        ("P1",       0.255, 0.640),
        ("P2",       0.345, 0.615),
        ("P3",       0.695, 0.615),
        ("P4",       0.785, 0.640),
    ],
    "default": [
        # Triggers (top of controller)
        ("LT",       0.265, 0.310),
        ("RT",       0.775, 0.310),
        # Bumpers (just below triggers)
        ("LB",       0.295, 0.345),
        ("RB",       0.745, 0.345),
        # Center cluster
        ("Xbox",     0.520, 0.345),
        ("View",     0.460, 0.400),
        ("Menu",     0.575, 0.400),
        ("Share",    0.520, 0.420),
        # Left stick (upper left quadrant)
        ("LS",       0.340, 0.395),
        ("LSUp",     0.340, 0.395),
        ("LSDown",   0.340, 0.395),
        ("LSLeft",   0.340, 0.395),
        ("LSRight",  0.340, 0.395),
        # D-pad (lower left quadrant)
        ("DUp",      0.445, 0.545),
        ("DDown",    0.445, 0.600),
        ("DLeft",    0.415, 0.572),
        ("DRight",   0.475, 0.572),
        # Face buttons (right quadrant — diamond layout)
        ("Y",        0.735, 0.385),
        ("X",        0.710, 0.415),
        ("B",        0.760, 0.415),
        ("A",        0.735, 0.445),
        # Right stick (lower right)
        ("RS",       0.615, 0.520),
        ("RSUp",     0.615, 0.520),
        ("RSDown",   0.615, 0.520),
        ("RSLeft",   0.615, 0.520),
        ("RSRight",  0.615, 0.520),
        # Back paddles (lower grip area)
        ("P1",       0.255, 0.640),
        ("P2",       0.345, 0.615),
        ("P3",       0.695, 0.615),
        ("P4",       0.785, 0.640),
    ],
}

# ---------------------------------------------------------------------------
# Gamepad button shapes — matching the Joy-Con-style shape system
# ---------------------------------------------------------------------------
GAMEPAD_BUTTON_SHAPES: dict[str, ShapeSpec] = {
    # Triggers — wide rounded bumper shapes
    "LT":      ("rrect", 80, 30, 10),
    "RT":      ("rrect", 80, 30, 10),
    # Bumpers — slightly narrower
    "LB":      ("rrect", 72, 26, 8),
    "RB":      ("rrect", 72, 26, 8),
    # Face buttons — circles
    "A":       ("circle", 22),
    "B":       ("circle", 22),
    "X":       ("circle", 22),
    "Y":       ("circle", 22),
    # Thumbsticks — larger circles
    "LS":      ("circle", 28),
    "RS":      ("circle", 28),
    # Stick directions — quarter-ring arcs around thumbstick
    "LSUp":    ("arc_top", 30, 48),
    "LSDown":  ("arc_bottom", 30, 48),
    "LSLeft":  ("arc_left", 30, 48),
    "LSRight": ("arc_right", 30, 48),
    "RSUp":    ("arc_top", 30, 48),
    "RSDown":  ("arc_bottom", 30, 48),
    "RSLeft":  ("arc_left", 30, 48),
    "RSRight": ("arc_right", 30, 48),
    # D-pad — directional arrows
    "DUp":     ("arrow_up", 20),
    "DDown":   ("arrow_down", 20),
    "DLeft":   ("arrow_left", 20),
    "DRight":  ("arrow_right", 20),
    # Center buttons — circles
    "Xbox":    ("circle", 24),
    "View":    ("rrect", 28, 16, 6),
    "Menu":    ("rrect", 28, 16, 6),
    "Share":   ("circle", 14),
    # Back paddles — horizontal rounded rectangles rotated to match the rear levers
    "P1":      ("rrect", 56, 24, 8),
    "P2":      ("rrect", 56, 24, 8),
    "P3":      ("rrect", 56, 24, 8),
    "P4":      ("rrect", 56, 24, 8),
}

# ---------------------------------------------------------------------------
# Gamepad wide button set
# ---------------------------------------------------------------------------
GAMEPAD_WIDE: set[str] = {"LT", "RT", "LB", "RB", "P1", "P2", "P3", "P4"}
