"""Built-in default profiles — one per device slot (0-3).

These ship with the app so users have useful starting configurations
out of the box.  Each profile maps Joy-Con buttons to typical PC key
bindings for a given game genre.

Mapping format
--------------
``{"keycode": <HID usage>, "modifier": <HID modifier bitmask>}``

Modifier-only bindings use ``keycode = 0`` with the modifier bitmask.
See ``hid_keycodes.py`` for constants.

Button names must match the hotspot IDs in ``ui/constants.py``
(e.g. ``LStick``, ``ZR``, ``DUp``).
"""

from __future__ import annotations

import copy
from typing import Any

# --- HID modifier bits (same as hid_keycodes.py) -------------------------
_LCTRL = 0x01
_LSHIFT = 0x02
_LALT = 0x04

# --- Common HID keycodes -------------------------------------------------
_A = 0x04
_B = 0x05
_C = 0x06
_D = 0x07
_E = 0x08
_F = 0x09
_G = 0x0A
_H = 0x0B
_I = 0x0C
_M = 0x10
_N = 0x11
_Q = 0x14
_R = 0x15
_S = 0x16
_T = 0x17
_V = 0x19
_W = 0x1A
_X = 0x1B
_Z = 0x1D
_1 = 0x1E
_2 = 0x1F
_3 = 0x20
_4 = 0x21
_ENTER = 0x28
_ESC = 0x29
_TAB = 0x2B
_SPACE = 0x2C
_LEFT = 0x50
_DOWN = 0x51
_UP = 0x52
_RIGHT = 0x4F

# Helpers
def _k(keycode: int, modifier: int = 0) -> dict[str, int]:
    return {"keycode": keycode, "modifier": modifier}

def _mod(modifier: int) -> dict[str, int]:
    return {"keycode": 0, "modifier": modifier}


def _stick_defaults() -> dict[str, Any]:
    return {
        "deadzone_inner": 0.05,
        "deadzone_outer": 1.0,
        "sensitivity": 1.0,
        "curve_type": "linear",
    }


# =====================================================================
# Slot 0 — General / All-Purpose
# =====================================================================
_SLOT_0: dict[str, Any] = {
    "name": "General",
    "mappings": {
        # Left stick: WASD
        "LSUp":    _k(_W),
        "LSDown":  _k(_S),
        "LSLeft":  _k(_A),
        "LSRight": _k(_D),
        "LStick":  _mod(_LCTRL),        # ctrl

        # Right stick: Arrow keys
        "RSUp":    _k(_UP),
        "RSDown":  _k(_DOWN),
        "RSLeft":  _k(_LEFT),
        "RSRight": _k(_RIGHT),
        "RStick":  _k(_ENTER),

        # Face buttons
        "A":  _k(_SPACE),               # confirm / jump
        "B":  _k(_ESC),                 # cancel / back
        "X":  _k(_E),                   # interact
        "Y":  _k(_R),                   # action / reload

        # Shoulders / triggers
        "ZL": _k(_I),                   # I
        "ZR": _mod(_LCTRL),             # crouch
        "L":  _mod(_LSHIFT),            # shift
        "R":  _k(_ENTER),               # confirm

        # D-pad
        "DUp":    _k(_E),               # interact
        "DDown":  _k(0),                # unmapped
        "DLeft":  _k(_F),               # ability
        "DRight": _k(_R),               # ability

        # System
        "Plus":    _k(_ENTER),
        "Minus":   _k(_TAB),
        "Capture": _k(_ESC),
    },
    "macros": [],
    "layers": [],
    "chords": [],
    "stick": _stick_defaults(),
}


# =====================================================================
# Slot 1 — FPS / Shooter
# =====================================================================
_SLOT_1: dict[str, Any] = {
    "name": "FPS / Shooter",
    "mappings": {
        # Left stick: WASD movement
        "LSUp":    _k(_W),
        "LSDown":  _k(_S),
        "LSLeft":  _k(_A),
        "LSRight": _k(_D),
        "LStick":  _mod(_LCTRL),        # ctrl

        # Right stick: arrow keys (camera / look)
        "RSUp":    _k(_UP),
        "RSDown":  _k(_DOWN),
        "RSLeft":  _k(_LEFT),
        "RSRight": _k(_RIGHT),
        "RStick":  _k(_V),              # melee

        # Face buttons
        "A":  _k(_SPACE),               # jump
        "B":  _k(_R),                   # reload
        "X":  _k(_E),                   # interact / use
        "Y":  _k(_G),                   # grenade

        # Shoulders
        "ZL": _k(_I),                   # I
        "ZR": _mod(_LCTRL),             # crouch / ADS
        "L":  _mod(_LSHIFT),            # shift
        "R":  _k(_F),                   # melee / ability

        # D-pad
        "DUp":    _k(_E),               # interact
        "DDown":  _k(0),                # unmapped
        "DLeft":  _k(_F),               # ability
        "DRight": _k(_R),               # ability

        # System
        "Plus":  _k(_ESC),              # pause
        "Minus": _k(_TAB),              # scoreboard
        "Capture": _k(_ESC),
    },
    "macros": [],
    "layers": [],
    "chords": [],
    "stick": _stick_defaults(),
}


# =====================================================================
# Slot 2 — Platformer / Action
# =====================================================================
_SLOT_2: dict[str, Any] = {
    "name": "Platformer / Action",
    "mappings": {
        # Left stick: WASD
        "LSUp":    _k(_W),
        "LSDown":  _k(_S),
        "LSLeft":  _k(_A),
        "LSRight": _k(_D),
        "LStick":  _mod(_LCTRL),        # ctrl

        # Right stick: arrow keys
        "RSUp":    _k(_UP),
        "RSDown":  _k(_DOWN),
        "RSLeft":  _k(_LEFT),
        "RSRight": _k(_RIGHT),
        "RStick":  _k(_Z),              # lock-on

        # Face buttons
        "A":  _k(_SPACE),               # jump
        "B":  _k(_X),                   # attack
        "X":  _k(_Z),                   # special
        "Y":  _k(_C),                   # interact / grab

        # Shoulders
        "ZL": _k(_I),                   # I
        "ZR": _mod(_LCTRL),             # crouch / slide
        "L":  _mod(_LSHIFT),            # shift
        "R":  _k(_E),                   # R ability

        # D-pad
        "DUp":    _k(_E),               # interact
        "DDown":  _k(0),                # unmapped
        "DLeft":  _k(_F),               # ability
        "DRight": _k(_R),               # ability

        # System
        "Plus":  _k(_ESC),
        "Minus": _k(_TAB),
        "Capture": _k(_ESC),
    },
    "macros": [],
    "layers": [],
    "chords": [],
    "stick": _stick_defaults(),
}


# =====================================================================
# Slot 3 — Racing / Driving
# =====================================================================
_SLOT_3: dict[str, Any] = {
    "name": "Racing / Driving",
    "mappings": {
        # Triggers: throttle / brake
        "ZR": _k(_W),                   # accelerate
        "ZL": _k(_I),                   # I

        # Left stick: steering
        "LSUp":    _k(_W),
        "LSDown":  _k(_S),
        "LSLeft":  _k(_A),
        "LSRight": _k(_D),
        "LStick":  _mod(_LCTRL),        # ctrl

        # Right stick: camera
        "RSUp":    _k(_UP),
        "RSDown":  _k(_DOWN),
        "RSLeft":  _k(_LEFT),
        "RSRight": _k(_RIGHT),
        "RStick":  _k(_C),              # look back

        # Face buttons
        "A":  _k(_SPACE),               # handbrake / e-brake
        "B":  _k(_N),                   # nitro / boost
        "X":  _k(_TAB),                 # look behind
        "Y":  _k(_ENTER),               # reset / respawn

        # Shoulders
        "L":  _mod(_LSHIFT),            # shift
        "R":  _k(_E),                   # shift up

        # D-pad
        "DUp":    _k(_E),               # interact
        "DDown":  _k(0),                # unmapped
        "DLeft":  _k(_F),               # ability
        "DRight": _k(_R),               # ability

        # System
        "Plus":  _k(_ESC),
        "Minus": _k(_TAB),
        "Capture": _k(_ESC),
    },
    "macros": [],
    "layers": [],
    "chords": [],
    "stick": _stick_defaults(),
}


# =====================================================================
# Public API
# =====================================================================

BUILT_IN_PROFILES: list[dict[str, Any]] = [_SLOT_0, _SLOT_1, _SLOT_2, _SLOT_3]


def get_default_profile(slot: int = 0) -> dict[str, Any]:
    """Return a deep copy of the built-in profile for *slot* (0-3)."""
    idx = max(0, min(slot, len(BUILT_IN_PROFILES) - 1))
    return copy.deepcopy(BUILT_IN_PROFILES[idx])
