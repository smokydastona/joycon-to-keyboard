"""USB HID keycode helpers (plus a legacy keysym adapter).

The Bind Bandit UI stores keyboard bindings as USB HID usage IDs plus a
modifier bitmask (see `default_profiles.py`).

This module provides:
- Modifier-bit constants and keycode name helpers used throughout the UI.
- `DEFAULT_KEYMAP` constants matching the firmware's built-in defaults.
- `keysym_to_hid()` as a *legacy* adapter for older Tkinter-era keysym strings.

Note: The current PyQt6 UI does not depend on Tkinter at runtime.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# USB HID modifier bits  (report byte-0 bitmask)
# ---------------------------------------------------------------------------
MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04
MOD_LGUI = 0x08
MOD_RCTRL = 0x10
MOD_RSHIFT = 0x20
MOD_RALT = 0x40
MOD_RGUI = 0x80

# ---------------------------------------------------------------------------
# Tkinter keysym → (modifier, keycode)
#
# For regular keys the modifier is 0 and keycode is the HID usage.
# For modifier-only keys the keycode is 0 and the modifier byte is set.
# ---------------------------------------------------------------------------

_KEYSYM_MAP: dict[str, tuple[int, int]] = {
    # Letters -----------------------------------------------------------------
    "a": (0, 0x04), "b": (0, 0x05), "c": (0, 0x06), "d": (0, 0x07),
    "e": (0, 0x08), "f": (0, 0x09), "g": (0, 0x0A), "h": (0, 0x0B),
    "i": (0, 0x0C), "j": (0, 0x0D), "k": (0, 0x0E), "l": (0, 0x0F),
    "m": (0, 0x10), "n": (0, 0x11), "o": (0, 0x12), "p": (0, 0x13),
    "q": (0, 0x14), "r": (0, 0x15), "s": (0, 0x16), "t": (0, 0x17),
    "u": (0, 0x18), "v": (0, 0x19), "w": (0, 0x1A), "x": (0, 0x1B),
    "y": (0, 0x1C), "z": (0, 0x1D),
    # Upper-case keysyms (Shift held) → same keycode, no modifier stored
    "A": (0, 0x04), "B": (0, 0x05), "C": (0, 0x06), "D": (0, 0x07),
    "E": (0, 0x08), "F": (0, 0x09), "G": (0, 0x0A), "H": (0, 0x0B),
    "I": (0, 0x0C), "J": (0, 0x0D), "K": (0, 0x0E), "L": (0, 0x0F),
    "M": (0, 0x10), "N": (0, 0x11), "O": (0, 0x12), "P": (0, 0x13),
    "Q": (0, 0x14), "R": (0, 0x15), "S": (0, 0x16), "T": (0, 0x17),
    "U": (0, 0x18), "V": (0, 0x19), "W": (0, 0x1A), "X": (0, 0x1B),
    "Y": (0, 0x1C), "Z": (0, 0x1D),

    # Numbers (top row) -------------------------------------------------------
    "1": (0, 0x1E), "2": (0, 0x1F), "3": (0, 0x20), "4": (0, 0x21),
    "5": (0, 0x22), "6": (0, 0x23), "7": (0, 0x24), "8": (0, 0x25),
    "9": (0, 0x26), "0": (0, 0x27),
    # Shifted number keysyms
    "exclam": (0, 0x1E), "at": (0, 0x1F), "numbersign": (0, 0x20),
    "dollar": (0, 0x21), "percent": (0, 0x22), "asciicircum": (0, 0x23),
    "ampersand": (0, 0x24), "asterisk": (0, 0x25), "parenleft": (0, 0x26),
    "parenright": (0, 0x27),

    # Special keys ------------------------------------------------------------
    "Return": (0, 0x28), "KP_Enter": (0, 0x28),
    "Escape": (0, 0x29),
    "BackSpace": (0, 0x2A),
    "Tab": (0, 0x2B),
    "space": (0, 0x2C),
    "minus": (0, 0x2D), "underscore": (0, 0x2D),
    "equal": (0, 0x2E), "plus": (0, 0x2E),
    "bracketleft": (0, 0x2F), "braceleft": (0, 0x2F),
    "bracketright": (0, 0x30), "braceright": (0, 0x30),
    "backslash": (0, 0x31), "bar": (0, 0x31),
    "semicolon": (0, 0x33), "colon": (0, 0x33),
    "apostrophe": (0, 0x34), "quotedbl": (0, 0x34),
    "grave": (0, 0x35), "asciitilde": (0, 0x35),
    "comma": (0, 0x36), "less": (0, 0x36),
    "period": (0, 0x37), "greater": (0, 0x37),
    "slash": (0, 0x38), "question": (0, 0x38),
    "Caps_Lock": (0, 0x39),

    # F-keys ------------------------------------------------------------------
    "F1": (0, 0x3A), "F2": (0, 0x3B), "F3": (0, 0x3C), "F4": (0, 0x3D),
    "F5": (0, 0x3E), "F6": (0, 0x3F), "F7": (0, 0x40), "F8": (0, 0x41),
    "F9": (0, 0x42), "F10": (0, 0x43), "F11": (0, 0x44), "F12": (0, 0x45),
    # Extended function keys (F13–F24)
    "F13": (0, 0x68), "F14": (0, 0x69), "F15": (0, 0x6A), "F16": (0, 0x6B),
    "F17": (0, 0x6C), "F18": (0, 0x6D), "F19": (0, 0x6E), "F20": (0, 0x6F),
    "F21": (0, 0x70), "F22": (0, 0x71), "F23": (0, 0x72), "F24": (0, 0x73),

    # System / navigation -----------------------------------------------------
    "Print": (0, 0x46), "Scroll_Lock": (0, 0x47), "Pause": (0, 0x48),
    "Insert": (0, 0x49), "Home": (0, 0x4A), "Prior": (0, 0x4B),  # Page Up
    "Delete": (0, 0x4C), "End": (0, 0x4D), "Next": (0, 0x4E),    # Page Down
    "Right": (0, 0x4F), "Left": (0, 0x50), "Down": (0, 0x51), "Up": (0, 0x52),

    # Modifier-only keys (keycode=0, modifier byte set) -----------------------
    "Shift_L": (MOD_LSHIFT, 0), "Shift_R": (MOD_RSHIFT, 0),
    "Control_L": (MOD_LCTRL, 0), "Control_R": (MOD_RCTRL, 0),
    "Alt_L": (MOD_LALT, 0), "Alt_R": (MOD_RALT, 0),
    "Super_L": (MOD_LGUI, 0), "Super_R": (MOD_RGUI, 0),
    "Win_L": (MOD_LGUI, 0), "Win_R": (MOD_RGUI, 0),
    "Meta_L": (MOD_LGUI, 0), "Meta_R": (MOD_RGUI, 0),

    # Numpad ------------------------------------------------------------------
    "KP_0": (0, 0x62), "KP_1": (0, 0x59), "KP_2": (0, 0x5A),
    "KP_3": (0, 0x5B), "KP_4": (0, 0x5C), "KP_5": (0, 0x5D),
    "KP_6": (0, 0x5E), "KP_7": (0, 0x5F), "KP_8": (0, 0x60),
    "KP_9": (0, 0x61), "KP_Decimal": (0, 0x63),
    "KP_Divide": (0, 0x54), "KP_Multiply": (0, 0x55),
    "KP_Subtract": (0, 0x56), "KP_Add": (0, 0x57),
    "Num_Lock": (0, 0x53),
}


def keysym_to_hid(keysym: str) -> tuple[int, int] | None:
    """Legacy: convert a Tkinter keysym string to ``(modifier, keycode)``.

    Returns *None* if the keysym is unrecognised.
    """
    return _KEYSYM_MAP.get(keysym)


# ---------------------------------------------------------------------------
# Reverse: (mod, keycode) → human-readable name
# ---------------------------------------------------------------------------

_MOD_NAMES: list[tuple[int, str]] = [
    (MOD_LCTRL, "Ctrl"),
    (MOD_LSHIFT, "Shift"),
    (MOD_LALT, "Alt"),
    (MOD_LGUI, "Win"),
    (MOD_RCTRL, "RCtrl"),
    (MOD_RSHIFT, "RShift"),
    (MOD_RALT, "RAlt"),
    (MOD_RGUI, "RWin"),
]

_KEYCODE_NAMES: dict[int, str] = {
    0x04: "A", 0x05: "B", 0x06: "C", 0x07: "D", 0x08: "E", 0x09: "F",
    0x0A: "G", 0x0B: "H", 0x0C: "I", 0x0D: "J", 0x0E: "K", 0x0F: "L",
    0x10: "M", 0x11: "N", 0x12: "O", 0x13: "P", 0x14: "Q", 0x15: "R",
    0x16: "S", 0x17: "T", 0x18: "U", 0x19: "V", 0x1A: "W", 0x1B: "X",
    0x1C: "Y", 0x1D: "Z",
    0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4", 0x22: "5",
    0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab", 0x2C: "Space",
    0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\",
    0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",", 0x37: ".", 0x38: "/",
    0x39: "CapsLk",
    0x3A: "F1", 0x3B: "F2", 0x3C: "F3", 0x3D: "F4", 0x3E: "F5", 0x3F: "F6",
    0x40: "F7", 0x41: "F8", 0x42: "F9", 0x43: "F10", 0x44: "F11", 0x45: "F12",
    0x46: "PrtSc", 0x47: "ScrLk", 0x48: "Pause",
    # F13–F24 (extended function keys)
    0x68: "F13", 0x69: "F14", 0x6A: "F15", 0x6B: "F16",
    0x6C: "F17", 0x6D: "F18", 0x6E: "F19", 0x6F: "F20",
    0x70: "F21", 0x71: "F22", 0x72: "F23", 0x73: "F24",
    0x49: "Ins", 0x4A: "Home", 0x4B: "PgUp",
    0x4C: "Del", 0x4D: "End", 0x4E: "PgDn",
    0x4F: "Right", 0x50: "Left", 0x51: "Down", 0x52: "Up",
    0x53: "NumLk",
    0x54: "KP/", 0x55: "KP*", 0x56: "KP-", 0x57: "KP+",
    0x59: "KP1", 0x5A: "KP2", 0x5B: "KP3", 0x5C: "KP4", 0x5D: "KP5",
    0x5E: "KP6", 0x5F: "KP7", 0x60: "KP8", 0x61: "KP9", 0x62: "KP0",
    0x63: "KP.",
}

# The built-in default keymap (matches keymap.c on the firmware).
DEFAULT_KEYMAP: dict[int, tuple[int, int]] = {
    1: (0, 0x1A),            # W
    2: (0, 0x16),            # S
    3: (0, 0x04),            # A
    4: (0, 0x07),            # D
    5: (0, 0x2C),            # Space
    6: (MOD_LSHIFT, 0),      # Left Shift
    7: (MOD_LCTRL, 0),       # Left Ctrl
    8: (0, 0x08),            # E
    9: (0, 0x14),            # Q
    10: (0, 0x15),           # R
    11: (0, 0x09),           # F
    12: (0, 0x2B),           # Tab
    13: (0, 0x28),           # Enter
    14: (MOD_RALT, 0),       # Right Alt
    15: (MOD_LALT, 0),       # Left Alt
    16: (0, 0x29),           # Escape
    17: (0, 0x35),           # Grave / Tilde
    # 18: Home capture — unmapped (no keycode)
    19: (0, 0x0A),           # G
    20: (MOD_LSHIFT, 0),     # Left Shift (duplicate)
    21: (0, 0x19),           # V
    22: (0, 0x52),           # Up Arrow
    23: (0, 0x51),           # Down Arrow
    24: (0, 0x50),           # Left Arrow
    25: (0, 0x4F),           # Right Arrow
    26: (0, 0x17),           # T
    27: (0, 0x1E),           # 1
    28: (0, 0x1F),           # 2
    29: (0, 0x20),           # 3
    30: (0, 0x21),           # 4
    31: (0, 0x1B),           # X
    32: (0, 0x22),           # 5  (SL left Joy-Con)
    33: (0, 0x23),           # 6  (SR left Joy-Con)
    34: (0, 0x24),           # 7  (SL right Joy-Con)
    35: (0, 0x25),           # 8  (SR right Joy-Con)
    36: (0, 0x08),           # E  (D-pad up)
    37: (0, 0x2C),           # Space  (D-pad down)
    38: (0, 0x09),           # F  (D-pad left)
    39: (0, 0x15),           # R  (D-pad right)
}


def hid_to_name(mod: int, keycode: int) -> str:
    """Return a short human-readable label for a HID modifier+keycode pair."""
    parts: list[str] = []
    for bit, name in _MOD_NAMES:
        if mod & bit:
            parts.append(name)

    if keycode:
        parts.append(_KEYCODE_NAMES.get(keycode, f"0x{keycode:02X}"))
    elif not parts:
        return "None"

    return "+".join(parts)
