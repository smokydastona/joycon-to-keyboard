from __future__ import annotations

import base64
import copy
import json
import logging
import math
import sys
import threading
import tkinter as tk
import tkinter.ttk as ttk
import time
import zlib
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Optional, Tuple

try:
    import winsound  # Windows only
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False

try:
    from PIL import Image as PILImage, ImageTk  # type: ignore
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from serial.tools import list_ports

from .serial_client import SerialClient
from ._version import __version__
from . import updater
from . import fw_updater
from . import initial_flash
from . import hid_keycodes
from . import m913_device
from . import razer_device
from . import app_switcher as app_switcher_mod

log = logging.getLogger("joycon_helper.app")


DEFAULT_UI_THEME: dict = {
    "name": "sketchbook-ink",
    "version": 2,
    "colors": {
        "bg": "#e8d8b8",
        "panel": "#f2e8d0",
        "panel2": "#e2d0a8",
        "text": "#2a1f0e",
        "muted": "#6b5d48",
        "border": "#b09878",
        "accent": "#4a6480",
        "accent2": "#4a7060",
        "danger": "#9e4040",
        "warning": "#8a6830",
        "active": "#4a7060",
        "conflict": "#9e4040",
        "modified": "#8a6830",
        "selected": "#4a6480",
        "pulse_bright": "#60c090",
        "timeline_press": "#2b6a4b",
        "timeline_release": "#6b5d48",
    },
    "typography": {
        # Sketch font matching Joy-Con overlay style. Tkinter falls back to system font if unavailable.
        "font_family": "Segoe Print",
        "font_size": 10,
        "mono_family": "Consolas",
        "mono_size": 10,
    },
    "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16},
    "radii": {"sm": 6, "md": 10, "lg": 14},
}


DARK_UI_THEME: dict = {
    "name": "sketchbook-ink-dark",
    "version": 2,
    "colors": {
        "bg": "#10141c",
        "panel": "#181e2c",
        "panel2": "#202838",
        "text": "#a8bcd0",
        "muted": "#6888aa",
        "border": "#2a3a54",
        "accent": "#5a7890",
        "accent2": "#4a8068",
        "danger": "#a85050",
        "warning": "#988848",
        "active": "#4a8068",
        "conflict": "#a85050",
        "modified": "#988848",
        "selected": "#5a7890",
        "pulse_bright": "#60c898",
        "timeline_press": "#3a8a5c",
        "timeline_release": "#6888aa",
    },
    "typography": {
        "font_family": "Segoe Print",
        "font_size": 10,
        "mono_family": "Consolas",
        "mono_size": 10,
    },
    "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16},
    "radii": {"sm": 6, "md": 10, "lg": 14},
}


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"bad hex color: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend_hex(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, float(t)))
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    rr = int(ar + (br - ar) * t)
    rg = int(ag + (bg - ag) * t)
    rb = int(ab + (bb - ab) * t)
    return _rgb_to_hex((rr, rg, rb))


def _relative_luma(h: str) -> float:
    # Rough relative luminance in [0,1] for contrast decisions.
    r, g, b = _hex_to_rgb(h)
    return (0.2126 * (r / 255.0)) + (0.7152 * (g / 255.0)) + (0.0722 * (b / 255.0))


def _contrast_on(bg: str) -> str:
    # Choose an ink/light color that will read on bg.
    return "#111111" if _relative_luma(bg) > 0.6 else "#fff6e1"


def _load_theme_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("theme.json must be a JSON object")
    if not isinstance(obj.get("colors"), dict) or not isinstance(obj.get("typography"), dict):
        raise ValueError("theme.json missing required keys")
    return obj


def _frozen_bundle_root() -> Optional[Path]:
    base = getattr(sys, "_MEIPASS", None)
    if not isinstance(base, str) or not base:
        return None
    try:
        return Path(base).resolve()
    except Exception:
        log.debug("Failed to resolve _MEIPASS", exc_info=True)
        return None


def _executable_dir() -> Optional[Path]:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except Exception:
        log.debug("Failed to resolve executable dir", exc_info=True)
        return None


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: set[str] = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _ui_bundle_search_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        roots.append(Path.cwd() / ".ui-bundle")
    except Exception:
        pass

    exe_dir = _executable_dir()
    if exe_dir is not None:
        roots.append(exe_dir / ".ui-bundle")

    bundle_root = _frozen_bundle_root()
    if bundle_root is not None:
        roots.append(bundle_root / ".ui-bundle")

    here = Path(__file__).resolve()
    roots.extend(
        [
            here.parents[1] / ".ui-bundle",  # helper-app/.ui-bundle
            here.parents[3] / ".ui-bundle",  # repo root/.ui-bundle
        ]
    )
    return _dedupe_paths(roots)


def _joycons_search_roots(theme: str = "default") -> List[Path]:
    """Return search roots for device images, prioritising the given *theme*.

    *theme* is one of ``"default"``, ``"dark"``.
    The themed ``backgrounds/`` folder is searched first so the pre-baked
    composited images are found before any fallback locations.
    """
    bundle_name = ".ui-bundle-dark" if theme == "dark" else ".ui-bundle"
    roots: List[Path] = []
    try:
        cwd = Path.cwd()
        # Theme-specific composited backgrounds (primary)
        roots.append(cwd / "docs" / "ui" / theme / "backgrounds")
        roots.extend(
            [
                cwd,
                cwd / bundle_name / "backgrounds",
                cwd / bundle_name,
                cwd / ".ui-bundle" / "backgrounds",
                cwd / ".ui-bundle",
            ]
        )
    except Exception:
        pass

    exe_dir = _executable_dir()
    if exe_dir is not None:
        roots.extend([exe_dir, exe_dir / bundle_name / "backgrounds", exe_dir / bundle_name,
                      exe_dir / ".ui-bundle" / "backgrounds", exe_dir / ".ui-bundle"])

    bundle_root = _frozen_bundle_root()
    if bundle_root is not None:
        roots.extend([bundle_root, bundle_root / bundle_name / "backgrounds", bundle_root / bundle_name,
                      bundle_root / ".ui-bundle" / "backgrounds", bundle_root / ".ui-bundle"])

    here = Path(__file__).resolve()
    repo = here.parents[3]
    roots.extend(
        [
            repo / "docs" / "ui" / theme / "backgrounds",  # composited backgrounds (primary)
            here.parents[1],  # helper-app/
            here.parents[1] / bundle_name / "backgrounds",
            here.parents[1] / bundle_name,
            here.parents[1] / ".ui-bundle" / "backgrounds",
            here.parents[1] / ".ui-bundle",
            repo,  # repo root/
            repo / bundle_name / "backgrounds",
            repo / bundle_name,
            repo / ".ui-bundle" / "backgrounds",
            repo / ".ui-bundle",
        ]
    )
    return _dedupe_paths(roots)


def _ensure_profile_defaults(profile: dict) -> dict:
    if not isinstance(profile, dict):
        return {"ver": 1, "name": "default", "mappings": {}, "macros": [], "layers": [], "chords": [], "stick": {}, "ui": {"hotspots": {}}}

    profile.setdefault("ver", 1)
    profile.setdefault("name", "default")
    profile.setdefault("mappings", {})
    profile.setdefault("macros", [])
    profile.setdefault("layers", [])
    profile.setdefault("chords", [])
    profile.setdefault("stick", {})
    profile.setdefault("ui", {"hotspots": {}})

    if not isinstance(profile["mappings"], dict):
        profile["mappings"] = {}
    if not isinstance(profile["macros"], list):
        profile["macros"] = []
    if not isinstance(profile.get("layers"), list):
        profile["layers"] = []
    if not isinstance(profile.get("chords"), list):
        profile["chords"] = []
    if not isinstance(profile["stick"], dict):
        profile["stick"] = {}

    if not isinstance(profile.get("ui"), dict):
        profile["ui"] = {"hotspots": {}}
    profile["ui"].setdefault("hotspots", {})
    if not isinstance(profile["ui"].get("hotspots"), dict):
        profile["ui"]["hotspots"] = {}

    return profile


JOYCONS_IMAGE_W = 1536
JOYCONS_IMAGE_H = 1024
JOYCONS_IMAGE_STATE_NAMES = ("none", "left", "right", "both")

M913_IMAGE_STATE_NAMES = ("none", "connected")
RAZER_IMAGE_STATE_NAMES = ("none", "connected")

KEYBOARD_IMAGE_W = 1536
KEYBOARD_IMAGE_H = 1024

# Rainbow overlay colour choices — hex values matching the overlay PNGs
# generated by tools/generate_button_overlays.py.  The user picks one and
# it is used as the "has custom mapping" hotspot fill colour on every canvas.
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

# Normalized hotspot positions over joycons.png.
# These are intentionally approximate: the recommended flow is to use Learn
# to bind each physical control to its observed input key_id.
KEYMAP_HOTSPOTS: List[Tuple[str, float, float]] = [
    ("ZL", 420 / JOYCONS_IMAGE_W, 150 / JOYCONS_IMAGE_H),
    ("ZR", 1115 / JOYCONS_IMAGE_W, 150 / JOYCONS_IMAGE_H),
    ("-", 420 / JOYCONS_IMAGE_W, 335 / JOYCONS_IMAGE_H),
    ("+", 1110 / JOYCONS_IMAGE_W, 335 / JOYCONS_IMAGE_H),
    ("CAP", 395 / JOYCONS_IMAGE_W, 720 / JOYCONS_IMAGE_H),
    ("HOME", 1140 / JOYCONS_IMAGE_W, 720 / JOYCONS_IMAGE_H),
    ("LSTK", 250 / JOYCONS_IMAGE_W, 435 / JOYCONS_IMAGE_H),
    ("D-UP", 300 / JOYCONS_IMAGE_W, 545 / JOYCONS_IMAGE_H),
    ("D-DN", 300 / JOYCONS_IMAGE_W, 665 / JOYCONS_IMAGE_H),
    ("D-L", 225 / JOYCONS_IMAGE_W, 605 / JOYCONS_IMAGE_H),
    ("D-R", 375 / JOYCONS_IMAGE_W, 605 / JOYCONS_IMAGE_H),
    ("A", 1330 / JOYCONS_IMAGE_W, 460 / JOYCONS_IMAGE_H),
    ("B", 1260 / JOYCONS_IMAGE_W, 535 / JOYCONS_IMAGE_H),
    ("X", 1260 / JOYCONS_IMAGE_W, 385 / JOYCONS_IMAGE_H),
    ("Y", 1190 / JOYCONS_IMAGE_W, 460 / JOYCONS_IMAGE_H),
    ("RSTK", 1260 / JOYCONS_IMAGE_W, 605 / JOYCONS_IMAGE_H),
]

# Keyboard key hotspot positions (normalized to KEYBOARD_IMAGE_W × KEYBOARD_IMAGE_H).
# Each entry is (key_label, norm_x, norm_y).  key_label corresponds to the
# short name shown in the overlay (matches hid_keycodes._KEYCODE_NAMES where
# possible).  Positions map onto the keyboard PNG shipped in docs/ui/*/misc/.
KBD_HOTSPOTS: List[Tuple[str, float, float]] = [
    # ── Function row ──
    ("Esc",   97 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F1",   207 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F2",   267 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F3",   327 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F4",   387 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F5",   477 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F6",   537 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F7",   597 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F8",   657 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F9",   747 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F10",  807 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F11",  867 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    ("F12",  927 / KEYBOARD_IMAGE_W,  155 / KEYBOARD_IMAGE_H),
    # ── Top-right cluster ──
    ("PrtSc", 1007 / KEYBOARD_IMAGE_W, 155 / KEYBOARD_IMAGE_H),
    ("ScrLk", 1067 / KEYBOARD_IMAGE_W, 155 / KEYBOARD_IMAGE_H),
    ("Pause", 1127 / KEYBOARD_IMAGE_W, 155 / KEYBOARD_IMAGE_H),
    # ── Number row ──
    ("`",     97 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("1",    157 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("2",    217 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("3",    277 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("4",    337 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("5",    397 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("6",    457 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("7",    517 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("8",    577 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("9",    637 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("0",    697 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("-",    757 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("=",    817 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    ("Bksp", 907 / KEYBOARD_IMAGE_W,  275 / KEYBOARD_IMAGE_H),
    # ── Nav cluster row 1 ──
    ("Ins",  1007 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("Home", 1067 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("PgUp", 1127 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    # ── Numpad row 1 ──
    ("NumLk", 1217 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("KP/",   1277 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("KP*",   1337 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    ("KP-",   1397 / KEYBOARD_IMAGE_W, 275 / KEYBOARD_IMAGE_H),
    # ── QWERTY row ──
    ("Tab",  117 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("Q",    187 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("W",    247 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("E",    307 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("R",    367 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("T",    427 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("Y",    487 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("U",    547 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("I",    607 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("O",    667 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("P",    727 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("[",    787 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("]",    847 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("\\",   917 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    # ── Nav cluster row 2 ──
    ("Del",  1007 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("End",  1067 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    ("PgDn", 1127 / KEYBOARD_IMAGE_W, 350 / KEYBOARD_IMAGE_H),
    # ── Numpad row 2 ──
    ("KP7", 1217 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("KP8", 1277 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("KP9", 1337 / KEYBOARD_IMAGE_W,  350 / KEYBOARD_IMAGE_H),
    ("KP+", 1397 / KEYBOARD_IMAGE_W,  390 / KEYBOARD_IMAGE_H),
    # ── Home row ──
    ("CapsLk", 127 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    ("A",    207 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("S",    267 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("D",    327 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("F",    387 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("G",    447 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("H",    507 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("J",    567 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("K",    627 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("L",    687 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    (";",    747 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("'",    807 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("Enter", 897 / KEYBOARD_IMAGE_W, 430 / KEYBOARD_IMAGE_H),
    # ── Numpad row 3 ──
    ("KP4", 1217 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("KP5", 1277 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    ("KP6", 1337 / KEYBOARD_IMAGE_W,  430 / KEYBOARD_IMAGE_H),
    # ── Shift row ──
    ("LShift", 137 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    ("Z",    247 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("X",    307 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("C",    367 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("V",    427 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("B",    487 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("N",    547 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("M",    607 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    (",",    667 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    (".",    727 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("/",    787 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("RShift", 887 / KEYBOARD_IMAGE_W, 510 / KEYBOARD_IMAGE_H),
    # ── Arrow up ──
    ("Up",  1067 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    # ── Numpad row 4 ──
    ("KP1", 1217 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("KP2", 1277 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("KP3", 1337 / KEYBOARD_IMAGE_W,  510 / KEYBOARD_IMAGE_H),
    ("KPEnt", 1397 / KEYBOARD_IMAGE_W, 545 / KEYBOARD_IMAGE_H),
    # ── Bottom row ──
    ("LCtrl", 117 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Win",  187 / KEYBOARD_IMAGE_W,  590 / KEYBOARD_IMAGE_H),
    ("LAlt", 247 / KEYBOARD_IMAGE_W,  590 / KEYBOARD_IMAGE_H),
    ("Space", 487 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("RAlt", 667 / KEYBOARD_IMAGE_W,  590 / KEYBOARD_IMAGE_H),
    ("Fn",   727 / KEYBOARD_IMAGE_W,  590 / KEYBOARD_IMAGE_H),
    ("RCtrl", 847 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    # ── Arrow keys ──
    ("Left", 1007 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Down", 1067 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    ("Right", 1127 / KEYBOARD_IMAGE_W, 590 / KEYBOARD_IMAGE_H),
    # ── Numpad bottom ──
    ("KP0", 1247 / KEYBOARD_IMAGE_W,  590 / KEYBOARD_IMAGE_H),
    ("KP.", 1337 / KEYBOARD_IMAGE_W,  590 / KEYBOARD_IMAGE_H),
]

# Mapping from KBD_HOTSPOTS label → HID keycode (from hid_keycodes._KEYCODE_NAMES).
# This lets the keyboard canvas highlight which key each controller hotspot maps to.
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

# Reverse lookup: HID keycode → keyboard label (positive = keycode, negative = modifier bit)
_KEYCODE_TO_KBD_LABEL: Dict[int, str] = {v: k for k, v in KBD_LABEL_TO_KEYCODE.items()}
# Also build a modifier-bit → label map for negative entries
_MODBITS_TO_KBD_LABELS: Dict[int, List[str]] = {}
for _lbl, _code in KBD_LABEL_TO_KEYCODE.items():
    if _code < 0:
        _MODBITS_TO_KBD_LABELS.setdefault(-_code, []).append(_lbl)


def _profile_to_share_code(profile: dict) -> str:
    payload = json.dumps(profile, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(payload, level=9)
    token = base64.urlsafe_b64encode(compressed).decode("ascii")
    return f"JCB1:{token}"


def _share_code_to_profile(code: str) -> dict:
    code = code.strip()
    if not code.startswith("JCB1:"):
        raise ValueError("Invalid code prefix (expected JCB1:...)")
    token = code.split(":", 1)[1]
    compressed = base64.urlsafe_b64decode(token.encode("ascii"))
    payload = zlib.decompress(compressed)
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Decoded profile is not a JSON object")
    return obj


class OverlayWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk, theme: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.title("Bind Bandit Overlay")
        self.geometry("280x120")
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.92)
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._closed = False
        self.slot_var = tk.StringVar(value="-")
        self.last_key_var = tk.StringVar(value="-")
        self.last_macro_var = tk.StringVar(value="-")

        colors = (theme or DEFAULT_UI_THEME).get("colors", DEFAULT_UI_THEME["colors"])
        typo = (theme or DEFAULT_UI_THEME).get("typography", DEFAULT_UI_THEME["typography"])

        self.configure(bg=colors["bg"])

        frm = tk.Frame(self, bg=colors["bg"])
        frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(
            frm,
            text="Bind Bandit Overlay",
            font=(typo.get("font_family", "Segoe UI"), 11, "bold"),
            bg=colors["bg"],
            fg=colors["text"],
        ).pack(anchor="w")
        tk.Label(frm, textvariable=self.slot_var, bg=colors["bg"], fg=colors["text"]).pack(anchor="w", pady=(6, 0))
        tk.Label(frm, textvariable=self.last_key_var, bg=colors["bg"], fg=colors["text"]).pack(anchor="w")
        tk.Label(frm, textvariable=self.last_macro_var, bg=colors["bg"], fg=colors["text"]).pack(anchor="w")

    def _on_close(self) -> None:
        self._closed = True
        try:
            self.destroy()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    def set_slot(self, slot: int) -> None:
        self.slot_var.set(f"Active slot: {slot}")

    def set_last_key(self, pressed: bool, key_id: int) -> None:
        self.last_key_var.set(f"Key event: {'DOWN' if pressed else 'UP'}  key_id={key_id}")

    def set_macro(self, macro_id: str, state: str) -> None:
        self.last_macro_var.set(f"Trick: {macro_id}  ({state})")


class SketchPopup(tk.Toplevel):
    """Themed popup dialog with pencil-sketch aesthetic.

    Opens as a non-modal transient window positioned near the parent.
    Reuse the same instance by calling ``show()`` / ``hide()`` instead
    of creating/destroying.
    """

    def __init__(self, parent: tk.Tk, title: str = "", colors: Optional[dict] = None,
                 typo: Optional[dict] = None, width: int = 420, height: int = 340) -> None:
        super().__init__(parent)
        self._parent = parent
        self._colors = colors or DEFAULT_UI_THEME["colors"]
        self._typo = typo or DEFAULT_UI_THEME["typography"]

        self.title(title)
        self.geometry(f"{width}x{height}")
        self.resizable(True, True)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.hide)

        bg = self._colors.get("bg", "#e8d8b8")
        self.configure(bg=bg)
        try:
            self.attributes("-alpha", 0.96)
        except Exception:
            pass

        # Title bar with sketch font
        title_frame = tk.Frame(self, bg=self._colors.get("panel2", "#e2d0a8"), height=32)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        font_family = self._typo.get("font_family", "Segoe Print")
        tk.Label(
            title_frame, text=title,
            font=(font_family, 11),
            bg=self._colors.get("panel2", "#e2d0a8"),
            fg=self._colors.get("text", "#2a1f0e"),
            padx=10, anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        close_btn = tk.Label(
            title_frame, text=" x ",
            font=(font_family, 10),
            bg=self._colors.get("panel2", "#e2d0a8"),
            fg=self._colors.get("muted", "#6b5d48"),
            cursor="hand2",
        )
        close_btn.pack(side=tk.RIGHT, padx=(0, 6))
        close_btn.bind("<Button-1>", lambda _: self.hide())

        # Divider line
        div = tk.Frame(self, height=2, bg=self._colors.get("border", "#b09878"))
        div.pack(fill=tk.X)

        # Content area — subclasses / callers pack widgets into self.body
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Start hidden
        self.withdraw()

    def show(self) -> None:
        """Show the popup, positioning near the parent if not already placed."""
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide(self) -> None:
        """Hide the popup without destroying it."""
        self.withdraw()

    def toggle(self) -> None:
        """Toggle visibility."""
        if self.winfo_viewable():
            self.hide()
        else:
            self.show()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bind Bandit")
        self.geometry("1280x760")

        # Window icon — look next to the exe (frozen), otherwise next to this file.
        _icon_path = self._find_icon()
        if _icon_path:
            try:
                self.iconbitmap(str(_icon_path))
            except tk.TclError:
                log.debug("iconbitmap failed for %s", _icon_path)

        self._ui_theme = self._load_ui_theme()
        self._colors = self._ui_theme.get("colors", DEFAULT_UI_THEME["colors"])
        self._typo = self._ui_theme.get("typography", DEFAULT_UI_THEME["typography"])

        self._apply_ttk_theme()

        self.client = SerialClient()

        self.port_var = tk.StringVar(value="")
        self.baud_var = tk.StringVar(value="115200")
        self.slot_var = tk.StringVar(value="0")

        self._overlay: Optional[OverlayWindow] = None

        self._recording = tk.BooleanVar(value=False)
        self._record_last_t: Optional[float] = None

        self._mapping_key_id = tk.StringVar(value="1")
        self._mapping_type = tk.StringVar(value="passthrough")
        self._mapping_remap_to = tk.StringVar(value="1")
        self._mapping_macro_id = tk.StringVar(value="")
        self._mapping_macro_pick = tk.StringVar(value="")

        self._stick_deadzone = tk.DoubleVar(value=0.15)
        self._stick_deadzone_shape = tk.StringVar(value="circle")
        self._stick_curve = tk.StringVar(value="linear")
        self._stick_curve_exp = tk.DoubleVar(value=1.0)

        self._bt_target_substr = tk.StringVar(value="Joy-Con")
        self._bt_target_preset = tk.StringVar(value="Either (Joy-Con)")
        self._bt_status = tk.StringVar(value="BT: -")
        self._battery_level: Optional[int] = None  # 0-4 from Joy-Con, None=unknown
        self._rssi_dbm: Optional[int] = None  # BT RSSI in dBm, None=unknown

        # Controller info from firmware (populated by controller_info event).
        self._ctrl_info_type = tk.StringVar(value="\u2014")
        self._ctrl_info_serial = tk.StringVar(value="\u2014")
        self._ctrl_info_body_color: Optional[str] = None
        self._ctrl_info_btn_color: Optional[str] = None
        self._ctrl_info_deadzone = tk.StringVar(value="\u2014")
        self._ctrl_info_range = tk.StringVar(value="\u2014")

        # Track which sides are connected so the UI can reflect Left/Right/Both.
        # Keyed by BDA string when available.
        self._bt_conn_by_bda: Dict[str, str] = {}
        self._bt_connected_left = False
        self._bt_connected_right = False

        # Controller tab background banner widgets.
        self._bt_banner: Optional[tk.Frame] = None
        self._bt_banner_label: Optional[tk.Label] = None

        # Keymap editor (Controller tab)
        self._keymap_status = tk.StringVar(value="Click a target to select it. Use Case to learn its key_id.")
        self._keymap_selected_name: Optional[str] = None
        self._keymap_learn_name: Optional[str] = None
        self._keymap_canvas: Optional[tk.Canvas] = None
        self._keymap_img_state = "none"
        self._keymap_img_paths: Dict[str, Path] = {}
        self._keymap_img_path: Optional[Path] = None
        self._keymap_img_base: Optional[tk.PhotoImage] = None
        self._keymap_img_scaled = None  # tk.PhotoImage or ImageTk.PhotoImage
        self._keymap_pil_base = None  # PIL Image for Pillow composite path
        self._keymap_is_composite = False  # True when using pre-baked composited PNG
        self._keymap_hotspot_px: Dict[str, Tuple[float, float]] = {}

        # M913 mouse overlay image (Mouse tab)
        self._m913_overlay_canvas: Optional[tk.Canvas] = None
        self._m913_img_state: str = "none"
        self._m913_img_paths: Dict[str, Path] = {}
        self._m913_img_path: Optional[Path] = None
        self._m913_img_base: Optional[tk.PhotoImage] = None
        self._m913_img_scaled = None  # tk.PhotoImage or ImageTk.PhotoImage
        self._m913_pil_base = None  # PIL Image for Pillow composite path
        self._m913_is_composite = False  # True when using pre-baked composited PNG

        # Razer mouse overlay image (Razer tab)
        self._razer_overlay_canvas: Optional[tk.Canvas] = None
        self._razer_img_state: str = "none"
        self._razer_img_paths: Dict[str, Path] = {}
        self._razer_img_path: Optional[Path] = None
        self._razer_img_base: Optional[tk.PhotoImage] = None
        self._razer_img_scaled = None  # tk.PhotoImage or ImageTk.PhotoImage
        self._razer_pil_base = None  # PIL Image for Pillow composite path
        self._razer_is_composite = False  # True when using pre-baked composited PNG

        # Keyboard preview canvas (Controller tab — shows mapped PC keys)
        self._kbd_canvas: Optional[tk.Canvas] = None
        self._kbd_pil_base = None  # PIL Image for the keyboard overlay
        self._kbd_img_scaled = None  # tk.PhotoImage or ImageTk.PhotoImage
        self._kbd_img_path: Optional[Path] = None
        self._kbd_hotspot_px: Dict[str, Tuple[float, float]] = {}
        self._kbd_overlay_ox: int = 0
        self._kbd_overlay_oy: int = 0
        self._kbd_overlay_w: int = 0
        self._kbd_overlay_h: int = 0

        # Press-to-bind state
        self._bind_mode = False  # True = waiting for a keyboard key press
        self._bind_hotspot: Optional[str] = None  # hotspot name being bound
        self._bind_overlay_items: List[int] = []  # canvas item ids for visual bind overlay

        # Ink-stamp animation state (quick flash after binding completes)
        self._ink_stamp_anim: Optional[Dict[str, Any]] = None  # {"cx","cy","phase","label","after_id"}

        # Hover glow state
        self._hover_glow_name: Optional[str] = None  # hotspot name with glow ring
        self._hover_glow_items: List[int] = []  # canvas item ids for glow ring

        # User-selected overlay/hotspot highlight colour (rainbow picker)
        self._overlay_color_var = tk.StringVar(value=DEFAULT_OVERLAY_COLOR)
        self._overlay_color_var.trace_add("write", lambda *_: self._on_overlay_color_changed())

        # Live input state: set of currently-pressed key_ids
        self._active_key_ids: set[int] = set()

        # Layer editor state
        self._layer_edit_index = tk.IntVar(value=-1)  # -1 = base layer

        # Pulse animation state for active hotspot highlighting
        self._pulse_phase: float = 0.0
        self._pulse_growing: bool = True

        # Last-known-good profile snapshot (auto-saved on successful device write)
        self._last_good_profile: Optional[str] = None  # JSON string

        # Chord definitions (profile-level, list of {"keys": [int,...], "action": {...}})
        self._chord_entries: List[Dict[str, Any]] = []

        # Event timeline entries for Input Test tab: list of (timestamp, text, color)
        self._event_timeline: List[Tuple[float, str, str]] = []
        self._timeline_canvas: Optional[tk.Canvas] = None

        # Pre-initialize Input Test tab variables (used before tab is built)
        self._input_test_active_var = tk.StringVar(value="(none)")

        # ── Undo / Redo history ──
        self._undo_stack: List[Tuple[str, str]] = []  # (description, json_snapshot)
        self._redo_stack: List[Tuple[str, str]] = []
        self._undo_max = 50
        self._suppress_undo = False  # True during undo/redo to prevent re-push

        # ── Adaptive UI mode (simple / advanced) ──
        self._ui_mode = tk.StringVar(value="advanced")
        self._advanced_widgets: List[tk.Widget] = []  # widgets hidden in simple mode

        # ── Sandbox mode ──
        self._sandbox_active = tk.BooleanVar(value=False)
        self._sandbox_snapshot: Optional[str] = None

        # ── Smart search ──
        self._search_var = tk.StringVar(value="")
        self._search_matches: List[str] = []  # hotspot names matching current search

        # ── Guided wizard state ──
        self._guided_window: Optional[tk.Toplevel] = None

        # ── Calibration wizard state ──
        self._cal_window: Optional[tk.Toplevel] = None
        self._cal_step: int = 0

        # ── Lock critical inputs ──
        self._locked_hotspots: set[str] = set()  # hotspot names that require confirmation to unbind

        # ── Drag-and-drop state ──
        self._drag_source: Optional[str] = None  # keysym being dragged
        self._drag_item: Optional[int] = None  # canvas item id for drag ghost

        # ── Performance: dirty-flag batched keymap redraw ──
        self._keymap_dirty: bool = False  # True = needs redraw on next pulse tick
        self._keymap_canvas_items: Dict[str, list] = {}  # hotspot name → [canvas item ids]
        self._keymap_bg_item: Optional[int] = None  # canvas item id for background image
        self._keymap_last_scale_factor: int = 0  # cached subsample factor
        self._keymap_last_canvas_size: Tuple[int, int] = (0, 0)  # (w, h)

        # ── Performance: cached conflict detection ──
        self._conflict_cache: Optional[Dict[str, List[str]]] = None  # invalidated on profile change
        self._conflict_hotspot_cache: Optional[set] = None

        # ── Performance: cached reverse lookup ──
        self._key_id_to_hotspot_cache: Optional[Dict[int, str]] = None

        # ── Performance: timeline change tracking ──
        self._timeline_last_count: int = 0  # event count at last draw
        self._timeline_last_draw_time: float = 0.0

        # ── Performance: lazy tab loading ──
        self._tabs_built: set[str] = set()  # tab names that have been built

        # ── Performance: latency profiling ──
        self._perf_enabled: bool = False
        self._perf_redraw_times: List[float] = []  # last N redraw durations
        self._perf_input_times: List[Tuple[float, float]] = []  # (recv_time, process_time)
        self._ping_sent_time: Optional[float] = None  # for round-trip latency measurement
        self._latency_ms: Optional[float] = None  # last measured round-trip latency

        # ── Per-app auto-profile switching ──
        self._app_switcher = app_switcher_mod.AppSwitcher(
            on_switch=self._on_app_switch,
            poll_interval=1.0,
        )
        self._app_switcher_enabled = tk.BooleanVar(value=False)
        self._app_switcher_rules: List[Dict[str, Any]] = app_switcher_mod.load_rules()
        self._app_switcher.set_rules(self._app_switcher_rules)

        self._build_ui()
        self._load_background_image()
        self._apply_widget_theme()
        self._refresh_ports()
        self.after(50, self._drain_rx)
        self.after(80, self._pulse_tick)
        self.after(10000, self._latency_ping_tick)

        # Bind undo/redo keyboard shortcuts
        self.bind("<Control-z>", lambda _e: self._undo())
        self.bind("<Control-y>", lambda _e: self._redo())
        self.bind("<Control-Z>", lambda _e: self._undo())
        self.bind("<Control-Y>", lambda _e: self._redo())

        # Check for updates in the background after the UI is visible.
        self._pending_update: Optional[Dict[str, Any]] = None
        self.after(2000, self._start_update_check)

        # Check for firmware left from a previous app update.
        self._pending_fw_files = updater.load_pending_firmware()
        self._pending_fw_offered = False
        if self._pending_fw_files:
            self.after(3000, self._check_pending_fw)

    @staticmethod
    def _find_icon() -> Optional[Path]:
        """Locate icon.ico next to the exe (frozen) or in the helper-app dir."""
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "icon.ico")
        candidates.append(Path(__file__).resolve().parent.parent / "icon.ico")
        for p in candidates:
            if p.is_file():
                return p
        return None

    def _find_background_png(self) -> Optional[Path]:
        """Locate the appropriate background PNG (light or dark) for the app."""
        prefer_dark = self._detect_dark_preference()
        name = "background-dark.png" if prefer_dark else "background.png"

        search_roots = list(_joycons_search_roots())
        # Also check docs/ui/{theme}/backgrounds/ (where background PNGs live).
        here = Path(__file__).resolve()
        prefer_dark = self._detect_dark_preference()
        bg_theme = "dark" if prefer_dark else "default"
        search_roots.append(here.parents[3] / "docs" / "ui" / bg_theme / "backgrounds")
        try:
            search_roots.append(Path.cwd() / "docs" / "ui" / bg_theme / "backgrounds")
        except Exception:
            pass

        for root in _dedupe_paths(search_roots):
            candidate = root / name
            try:
                if candidate.is_file():
                    return candidate
            except Exception:
                continue
        return None

    def _load_background_image(self) -> None:
        """Load the background PNG and place it behind all other widgets."""
        if not _HAS_PIL:
            return

        bg_path = self._find_background_png()
        if not bg_path:
            return

        try:
            self._bg_pil_original = PILImage.open(bg_path).convert("RGBA")
        except Exception:
            log.debug("Failed to load background image %s", bg_path, exc_info=True)
            return

        self._bg_label = tk.Label(self, bd=0, highlightthickness=0)
        self._bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self._bg_label.lower()  # Ensure it stays behind all other widgets.

        self.bind("<Configure>", self._on_resize_bg)
        # Trigger initial draw after the window has been mapped.
        self.after(50, self._refresh_bg)

    def _refresh_bg(self) -> None:
        """Scale the background image to fit the current window size."""
        if not hasattr(self, "_bg_pil_original") or self._bg_pil_original is None:
            return

        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return

        # Avoid redundant resizes.
        if hasattr(self, "_bg_last_size") and self._bg_last_size == (w, h):
            return
        self._bg_last_size = (w, h)

        # Scale to cover the window (crop edges if aspect ratio differs).
        orig_w, orig_h = self._bg_pil_original.size
        scale = max(w / orig_w, h / orig_h)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)

        resized = self._bg_pil_original.resize((new_w, new_h), PILImage.LANCZOS)

        # Center-crop to window size.
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        cropped = resized.crop((left, top, left + w, top + h))

        self._bg_photo = ImageTk.PhotoImage(cropped)
        self._bg_label.configure(image=self._bg_photo)

    def _on_resize_bg(self, event: tk.Event) -> None:
        """Handle window resize to update background image."""
        if event.widget is not self:
            return
        self._refresh_bg()

    # ------------------------------------------------------------------
    # Compositing: fuse device overlay onto background for tab canvases
    # ------------------------------------------------------------------

    def _composite_bg_overlay(
        self,
        overlay_pil: "PILImage.Image",
        canvas_w: int,
        canvas_h: int,
    ) -> "Tuple[ImageTk.PhotoImage, int, int, int, int]":
        """Composite *overlay_pil* centred on the background at *canvas_w* × *canvas_h*.

        Returns ``(photo, ox, oy, overlay_w, overlay_h)`` where *ox/oy* are the
        top-left pixel coords of the (scaled) overlay within the composite —
        needed so hotspot positions can be computed relative to the overlay.

        If no background is loaded the overlay is placed on a solid panel
        colour so the canvas still looks clean.
        """
        # Scale the overlay to fit inside the canvas (contain).
        ov_w, ov_h = overlay_pil.size
        fit_scale = min(canvas_w / max(1, ov_w), canvas_h / max(1, ov_h), 1.0)
        new_ov_w = max(1, int(ov_w * fit_scale))
        new_ov_h = max(1, int(ov_h * fit_scale))
        overlay_scaled = overlay_pil.resize((new_ov_w, new_ov_h), PILImage.LANCZOS)

        ox = (canvas_w - new_ov_w) // 2
        oy = (canvas_h - new_ov_h) // 2

        # Build the canvas-sized background.
        bg_pil = getattr(self, "_bg_pil_original", None)
        if bg_pil is not None:
            orig_w, orig_h = bg_pil.size
            bg_scale = max(canvas_w / orig_w, canvas_h / orig_h)
            bw = int(orig_w * bg_scale)
            bh = int(orig_h * bg_scale)
            bg_resized = bg_pil.resize((bw, bh), PILImage.LANCZOS)
            left = (bw - canvas_w) // 2
            top = (bh - canvas_h) // 2
            composite = bg_resized.crop((left, top, left + canvas_w, top + canvas_h)).convert("RGBA")
        else:
            panel_hex = self._colors.get("panel2", "#f2e8d0")
            r, g, b = int(panel_hex[1:3], 16), int(panel_hex[3:5], 16), int(panel_hex[5:7], 16)
            composite = PILImage.new("RGBA", (canvas_w, canvas_h), (r, g, b, 255))

        # Alpha-composite the overlay onto the background.
        composite.paste(overlay_scaled, (ox, oy), overlay_scaled)

        photo = ImageTk.PhotoImage(composite)
        return photo, ox, oy, new_ov_w, new_ov_h

    def _scale_composite_to_canvas(
        self,
        composite_pil: "PILImage.Image",
        canvas_w: int,
        canvas_h: int,
    ) -> "Tuple[ImageTk.PhotoImage, int, int, int, int]":
        """Scale a pre-baked composite image to cover the canvas.

        Returns the same ``(photo, ox, oy, w, h)`` tuple as
        :meth:`_composite_bg_overlay` so callers can use either
        interchangeably.  *ox/oy* are always 0 because the composite
        already contains the background.
        """
        src_w, src_h = composite_pil.size
        scale = max(canvas_w / max(1, src_w), canvas_h / max(1, src_h))
        new_w = max(1, int(src_w * scale))
        new_h = max(1, int(src_h * scale))
        resized = composite_pil.resize((new_w, new_h), PILImage.LANCZOS)

        # Centre-crop to canvas dimensions.
        left = (new_w - canvas_w) // 2
        top = (new_h - canvas_h) // 2
        cropped = resized.crop((left, top, left + canvas_w, top + canvas_h))

        photo = ImageTk.PhotoImage(cropped)
        return photo, 0, 0, canvas_w, canvas_h

    def _load_ui_theme(self) -> dict:
        # Decide light vs dark: check --dark flag, env var, or Windows dark-mode setting.
        prefer_dark = self._detect_dark_preference()

        if prefer_dark:
            # Try dark bundle first.
            dark_candidates = [root.parent / (root.name + "-dark") / "theme.json"
                               for root in _ui_bundle_search_roots()]
            for c in dark_candidates:
                try:
                    if c.exists():
                        log.info("Loading dark theme from %s", c)
                        return _load_theme_json(c)
                except Exception:
                    log.debug("Failed to load dark theme from %s", c, exc_info=True)
                    continue
            log.info("Using built-in dark theme")
            return DARK_UI_THEME

        # Light: load from bundle or fallback.
        candidates = [root / "theme.json" for root in _ui_bundle_search_roots()]

        for c in candidates:
            try:
                if c.exists():
                    log.info("Loading light theme from %s", c)
                    return _load_theme_json(c)
            except Exception:
                log.debug("Failed to load theme from %s", c, exc_info=True)
                continue

        log.info("Using built-in light theme")
        return DEFAULT_UI_THEME

    @staticmethod
    def _detect_dark_preference() -> bool:
        """Return True if the user/system prefers dark mode."""
        import os
        # Explicit env var override: JOYCON_THEME=dark
        env = os.environ.get("JOYCON_THEME", "").strip().lower()
        if env == "dark":
            return True
        if env == "light":
            return False
        # CLI flag passed via sys.argv
        if "--dark" in sys.argv:
            return True
        # Windows 10+ dark-mode registry check
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return val == 0
        except Exception:
            pass
        return False

    def _apply_ttk_theme(self) -> None:
        colors = self._colors
        typo = self._typo

        try:
            self.configure(bg=colors["bg"])
        except Exception:
            pass

        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        base_font = (typo.get("font_family", "Segoe UI"), int(typo.get("font_size", 10)))

        style.configure("TFrame", background=colors["bg"])
        style.configure("TLabel", background=colors["bg"], foreground=colors["text"], font=base_font)
        style.configure("Muted.TLabel", background=colors["bg"], foreground=colors["muted"], font=base_font)

        # Inputs
        style.configure(
            "TEntry",
            padding=(6, 4),
        )
        style.configure("TCombobox", padding=(6, 3))

        # Buttons (muted — reduced padding and subtle styling)
        style.configure("TButton", padding=(6, 3), font=base_font)
        style.configure("Primary.TButton", padding=(6, 3), font=base_font)

        # Notebook
        try:
            style.configure("TNotebook", background=colors["bg"], borderwidth=0)
            style.configure("TNotebook.Tab", padding=(10, 6))
        except Exception:
            pass

    def _theme_scrolled_text(self, w: ScrolledText) -> None:
        colors = self._colors
        typo = self._typo
        sel_fg = _contrast_on(colors.get("accent", "#2f4a9e"))
        try:
            w.configure(
                bg=colors["panel2"],
                fg=colors["text"],
                insertbackground=colors["text"],
                selectbackground=colors["accent"],
                selectforeground=sel_fg,
                highlightthickness=1,
                highlightbackground=colors["border"],
                highlightcolor=colors["accent"],
                font=(typo.get("mono_family", "Consolas"), int(typo.get("mono_size", 10))),
            )
        except Exception:
            pass

    def _theme_listbox(self, w: tk.Listbox) -> None:
        colors = self._colors
        typo = self._typo
        sel_fg = _contrast_on(colors.get("accent", "#2f4a9e"))
        try:
            w.configure(
                bg=colors["panel2"],
                fg=colors["text"],
                selectbackground=colors["accent"],
                selectforeground=sel_fg,
                highlightthickness=1,
                highlightbackground=colors["border"],
                highlightcolor=colors["accent"],
                font=(typo.get("mono_family", "Consolas"), int(typo.get("mono_size", 10))),
            )
        except Exception:
            pass

    def _apply_widget_theme(self) -> None:
        # Apply token colors to widgets that are not ttk-styled.
        try:
            self._theme_scrolled_text(self.log)
        except Exception:
            pass
        for maybe in ("profile_text", "share_text"):
            w = getattr(self, maybe, None)
            if isinstance(w, ScrolledText):
                self._theme_scrolled_text(w)

        for maybe in ("macro_list", "step_list"):
            w = getattr(self, maybe, None)
            if isinstance(w, tk.Listbox):
                self._theme_listbox(w)

        # Curve canvas
        if hasattr(self, "curve_canvas") and isinstance(self.curve_canvas, tk.Canvas):
            try:
                self.curve_canvas.configure(
                    bg=self._colors["panel2"],
                    highlightthickness=1,
                    highlightbackground=self._colors["border"],
                    highlightcolor=self._colors["accent"],
                )
            except Exception:
                pass

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="Port:").pack(side=tk.LEFT)
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, values=[], width=40, state="readonly")
        self.port_combo.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Button(top, text="Refresh", command=self._refresh_ports).pack(side=tk.LEFT)

        ttk.Label(top, text="Baud:").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(top, textvariable=self.baud_var, width=10).pack(side=tk.LEFT, padx=(4, 8))

        self.connect_btn = ttk.Button(top, text="Connect", command=self._toggle_connect)
        self.connect_btn.pack(side=tk.LEFT)

        # Update icon — hidden until an update is detected.
        self._update_icon_btn = ttk.Button(
            top, text=" \u2191 Update available ",
            command=self._open_update_dialog,
        )
        # Not packed yet — _on_update_result shows it when an update exists.

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(body)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        # Tabs (left)
        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        self.tab_profile = ttk.Frame(self.tabs)
        self.tab_macros = ttk.Frame(self.tabs)
        self.tab_stick = ttk.Frame(self.tabs)
        self.tab_share = ttk.Frame(self.tabs)
        self.tab_overlay = ttk.Frame(self.tabs)
        self.tab_controller = ttk.Frame(self.tabs)
        self.tab_input_test = ttk.Frame(self.tabs)
        self.tab_mouse = ttk.Frame(self.tabs)
        self.tab_razer = ttk.Frame(self.tabs)
        self.tab_help = ttk.Frame(self.tabs)

        self.tabs.add(self.tab_profile, text="Loadout")
        self.tabs.add(self.tab_macros, text="Tricks")
        self.tabs.add(self.tab_stick, text="Stick")
        self.tabs.add(self.tab_share, text="Share")
        self.tabs.add(self.tab_overlay, text="Overlay")
        self.tabs.add(self.tab_controller, text="Controller")
        self.tabs.add(self.tab_input_test, text="Input Test")
        self.tabs.add(self.tab_mouse, text="Mouse")
        self.tabs.add(self.tab_razer, text="Razer")
        self.tabs.add(self.tab_help, text="Help")

        # Build critical tabs eagerly; defer the rest until first selected.
        self._build_profile_tab()
        self._build_controller_tab()

        # Lazy-load remaining tabs on first selection.
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Log view (below tabs)
        ttk.Label(left, text="Device log / events").pack(anchor="w", pady=(6, 0))
        self.log = ScrolledText(left, height=14, state="disabled")
        self.log.pack(fill=tk.BOTH, expand=False)

        # Right side controls
        ttk.Label(right, text="Actions").pack(anchor="w")

        slot_row = ttk.Frame(right)
        slot_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(slot_row, text="Slot:").pack(side=tk.LEFT)
        self.slot_combo = ttk.Combobox(slot_row, textvariable=self.slot_var, values=["0", "1", "2", "3"], width=4, state="readonly")
        self.slot_combo.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(right, text="Ping", command=self._cmd_ping, width=22).pack(pady=(8, 0))
        ttk.Button(right, text="Upload loadout to slot", command=self._cmd_write_profile, width=22).pack(pady=(6, 0))
        ttk.Button(right, text="Upload + Activate", command=self._cmd_upload_and_set_active, width=22).pack(pady=(6, 0))
        ttk.Button(right, text="Read loadout from slot", command=self._cmd_read_profile, width=22).pack(pady=(6, 0))
        ttk.Button(right, text="Set active slot", command=self._cmd_set_active, width=22).pack(pady=(6, 0))
        ttk.Button(right, text="Safe mode (reset slot)", command=self._cmd_safe_mode, width=22).pack(pady=(6, 0))

        ttk.Label(right, text="Raw command (JSON line)").pack(anchor="w", pady=(14, 0))
        self.raw_entry = ttk.Entry(right, width=30)
        self.raw_entry.pack(pady=(4, 0))
        ttk.Button(right, text="Send", command=self._send_raw, width=22).pack(pady=(6, 0))

        # Version label (bottom of right panel)
        ver_frame = ttk.Frame(right)
        ver_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        ttk.Label(ver_frame, text=f"v{__version__}", style="Muted.TLabel").pack(anchor="w")

        # Firmware update section
        fw_frame = ttk.LabelFrame(ver_frame, text="Firmware")
        fw_frame.pack(fill=tk.X, pady=(8, 0))
        self._fw_s3_ver = tk.StringVar(value="S3: —")
        self._fw_esp32_ver = tk.StringVar(value="ESP32: —")
        ttk.Label(fw_frame, textvariable=self._fw_s3_ver, style="Muted.TLabel").pack(anchor="w", padx=4)
        ttk.Label(fw_frame, textvariable=self._fw_esp32_ver, style="Muted.TLabel").pack(anchor="w", padx=4)
        self._fw_status = tk.StringVar(value="")
        ttk.Label(fw_frame, textvariable=self._fw_status, style="Muted.TLabel", wraplength=170).pack(anchor="w", padx=4, pady=(2, 0))
        self._fw_check_btn = ttk.Button(fw_frame, text="Check firmware versions", command=self._fw_check_versions, width=22)
        self._fw_check_btn.pack(pady=(4, 4))
        self._fw_update_btn = ttk.Button(fw_frame, text="Update firmware", command=self._fw_do_update, width=22, state="disabled")
        self._fw_update_btn.pack(pady=(0, 4))
        self._fw_flash_file_btn = ttk.Button(fw_frame, text="Flash from file\u2026", command=self._fw_flash_from_file, width=22)
        self._fw_flash_file_btn.pack(pady=(0, 4))
        self._pending_fw_update: Optional[Dict[str, Any]] = None

        # Initial flash section (esptool — for blank boards)
        init_frame = ttk.LabelFrame(ver_frame, text="Initial Flash (new boards)")
        init_frame.pack(fill=tk.X, pady=(8, 0))
        self._init_flash_status = tk.StringVar(value="For boards without firmware yet.")
        ttk.Label(init_frame, textvariable=self._init_flash_status, style="Muted.TLabel", wraplength=170).pack(anchor="w", padx=4, pady=(2, 0))
        self._init_flash_auto_btn = ttk.Button(init_frame, text="Download \u0026 flash latest", command=self._init_flash_auto, width=22)
        self._init_flash_auto_btn.pack(pady=(4, 2))
        self._init_flash_file_btn = ttk.Button(init_frame, text="Flash files\u2026", command=self._init_flash_from_files, width=22)
        self._init_flash_file_btn.pack(pady=(2, 2))
        self._init_flash_backup_btn = ttk.Button(init_frame, text="Backup flash\u2026", command=self._init_flash_backup, width=22)
        self._init_flash_backup_btn.pack(pady=(2, 4))

        # ── Bottom status bar (mode indicator — always visible) ──
        status_bar = tk.Frame(self, bg=self._colors.get("panel2", "#e2d0a8"), relief="sunken", bd=1)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self._mode_indicator_var = tk.StringVar(value="")
        tk.Label(
            status_bar,
            textvariable=self._mode_indicator_var,
            bg=self._colors.get("panel2", "#e2d0a8"),
            fg=self._colors.get("text", "#2a1f0e"),
            font=(self._typo.get("font_family", "Segoe UI"), 8),
            anchor="w",
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Undo/redo buttons in status bar
        self._redo_btn = ttk.Button(status_bar, text="Redo", command=self._redo, width=5, state="disabled")
        self._redo_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=1)
        self._undo_btn = ttk.Button(status_bar, text="Undo", command=self._undo, width=5, state="disabled")
        self._undo_btn.pack(side=tk.RIGHT, padx=(4, 0), pady=1)

        # UI mode toggle in status bar
        self._ui_mode_btn = ttk.Button(
            status_bar, text="Simple mode",
            command=self._toggle_ui_mode, width=12,
        )
        self._ui_mode_btn.pack(side=tk.RIGHT, padx=(4, 8), pady=1)

        self._undo_history_var = tk.StringVar(value="History: (empty)")

        # Start periodic mode indicator refresh
        self.after(300, self._mode_indicator_tick)

    def _on_tab_changed(self, _event: Any = None) -> None:
        """Lazy-build tab contents on first selection."""
        try:
            tab_id = self.tabs.select()
            tab_name = self.tabs.tab(tab_id, "text")
        except Exception:
            return
        self._ensure_tab_built(tab_name)

    def _ensure_tab_built(self, tab_name: str) -> None:
        """Build a tab's contents if not already built."""
        if tab_name in self._tabs_built:
            return
        self._tabs_built.add(tab_name)
        builders: Dict[str, Any] = {
            "Tricks": self._build_macros_tab,
            "Stick": self._build_stick_tab,
            "Share": self._build_share_tab,
            "Overlay": self._build_overlay_tab,
            "Input Test": self._build_input_test_tab,
            "Mouse": self._build_mouse_tab,
            "Razer": self._build_razer_tab,
            "Help": self._build_help_tab,
        }
        builder = builders.get(tab_name)
        if builder:
            builder()
            self._apply_widget_theme()

    def _build_profile_tab(self) -> None:
        # ── Slot quick-select row ──
        slot_frame = ttk.LabelFrame(self.tab_profile, text="Loadout slots")
        slot_frame.pack(fill=tk.X, pady=(0, 4))
        slot_row = ttk.Frame(slot_frame)
        slot_row.pack(fill=tk.X, padx=8, pady=(4, 4))
        self._slot_buttons: List[ttk.Button] = []
        self._slot_name_vars: List[tk.StringVar] = []
        for i in range(4):
            sv = tk.StringVar(value=f"Slot {i}")
            self._slot_name_vars.append(sv)
            btn = ttk.Button(
                slot_row,
                textvariable=sv,
                command=lambda idx=i: self._slot_select(idx),
                width=16,
            )
            btn.pack(side=tk.LEFT, padx=(0, 6))
            self._slot_buttons.append(btn)
        ttk.Button(slot_row, text="Read all names", command=self._slot_read_all).pack(side=tk.LEFT, padx=(12, 0))

        # Profile management row
        mgmt = ttk.Frame(self.tab_profile)
        mgmt.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(mgmt, text="Name:").pack(side=tk.LEFT)
        self._profile_name_var = tk.StringVar(value="default")
        self._profile_name_entry = ttk.Entry(mgmt, textvariable=self._profile_name_var, width=20)
        self._profile_name_entry.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(mgmt, text="Rename", command=self._profile_rename).pack(side=tk.LEFT)
        ttk.Button(mgmt, text="Duplicate", command=self._profile_duplicate).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(mgmt, text="Reset to defaults", command=self._profile_reset_defaults).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(self.tab_profile, text="Loadout JSON").pack(anchor="w")
        self.profile_text = ScrolledText(self.tab_profile, height=18)
        self.profile_text.pack(fill=tk.BOTH, expand=True)
        self._theme_scrolled_text(self.profile_text)

        initial = _ensure_profile_defaults({"name": "default"})
        self.profile_text.insert("1.0", json.dumps(initial, indent=2))

        prof_btns = ttk.Frame(self.tab_profile)
        prof_btns.pack(fill=tk.X, pady=(6, 6))
        ttk.Button(prof_btns, text="Load…", command=self._load_profile).pack(side=tk.LEFT)
        ttk.Button(prof_btns, text="Save…", command=self._save_profile).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(prof_btns, text="Validate", command=self._validate_profile).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(prof_btns, text="Apply Stick->JSON", command=self._stick_apply_to_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        # ── Per-app auto-profile switching ──
        app_switch_frame = ttk.LabelFrame(self.tab_profile, text="Per-App Auto-Loadout Switching")
        app_switch_frame.pack(fill=tk.X, pady=(6, 4))

        switch_top = ttk.Frame(app_switch_frame)
        switch_top.pack(fill=tk.X, padx=8, pady=(4, 2))
        ttk.Checkbutton(
            switch_top, text="Enable auto-switching",
            variable=self._app_switcher_enabled,
            command=self._toggle_app_switcher,
        ).pack(side=tk.LEFT)
        ttk.Button(switch_top, text="Add rule", command=self._app_switcher_add_rule).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(switch_top, text="Remove selected", command=self._app_switcher_remove_rule).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(switch_top, text="Detect active app", command=self._app_switcher_detect).pack(side=tk.LEFT, padx=(6, 0))

        self._app_switch_list = tk.Listbox(app_switch_frame, height=4)
        self._app_switch_list.pack(fill=tk.X, padx=8, pady=(2, 6))
        self._theme_listbox(self._app_switch_list)
        self._refresh_app_switch_list()

    def _build_macros_tab(self) -> None:
        row = ttk.Frame(self.tab_macros)
        row.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(row)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        right = ttk.Frame(row)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Tricks").pack(anchor="w")
        self.macro_list = tk.Listbox(left, height=18, width=22)
        self.macro_list.pack(fill=tk.Y, expand=False)
        self.macro_list.bind("<<ListboxSelect>>", lambda _e: self._refresh_macro_steps())
        self._theme_listbox(self.macro_list)

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btns, text="New", command=self._macro_new).pack(side=tk.LEFT)
        ttk.Button(btns, text="Delete", command=self._macro_delete).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Checkbutton(left, text="Record mode", variable=self._recording).pack(anchor="w", pady=(10, 0))

        ttk.Label(right, text="Steps").pack(anchor="w")
        self.step_list = tk.Listbox(right, height=14)
        self.step_list.pack(fill=tk.BOTH, expand=True)
        self._theme_listbox(self.step_list)

        step_btns = ttk.Frame(right)
        step_btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(step_btns, text="Add key step", command=self._step_add_key).pack(side=tk.LEFT)
        ttk.Button(step_btns, text="Add delay", command=self._step_add_delay).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(step_btns, text="Delete step", command=self._step_delete).pack(side=tk.LEFT, padx=(6, 0))

        map_box = ttk.LabelFrame(self.tab_macros, text="Heist plan (key_id → action)")
        map_box.pack(fill=tk.X, pady=(10, 0))

        r1 = ttk.Frame(map_box)
        r1.pack(fill=tk.X, padx=8, pady=(6, 0))
        ttk.Label(r1, text="Input key_id:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._mapping_key_id, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Type:").pack(side=tk.LEFT)
        ttk.Combobox(
            r1,
            textvariable=self._mapping_type,
            values=["passthrough", "disable", "remap", "macro"],
            width=14,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Remap to:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._mapping_remap_to, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Trick id:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._mapping_macro_id, width=14).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Pick:").pack(side=tk.LEFT)
        self.macro_pick = ttk.Combobox(
            r1,
            textvariable=self._mapping_macro_pick,
            values=[],
            width=18,
            state="readonly",
        )
        self.macro_pick.pack(side=tk.LEFT, padx=(6, 12))
        self.macro_pick.bind("<<ComboboxSelected>>", lambda _e: self._mapping_pick_macro())

        ttk.Button(r1, text="Execute", command=self._mapping_apply).pack(side=tk.LEFT)

        self._refresh_macro_list()

    def _build_stick_tab(self) -> None:
        info = ttk.Label(
            self.tab_stick,
            text=(
                "These settings are stored in the profile for future use. "
                "They do not affect behavior yet until the UART protocol includes analog values."
            ),
            wraplength=900,
            justify="left",
        )
        info.pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(self.tab_stick)
        row.pack(fill=tk.X)

        ttk.Label(row, text="Deadzone:").pack(side=tk.LEFT)
        tk.Scale(row, from_=0.0, to=0.5, resolution=0.01, orient="horizontal", variable=self._stick_deadzone).pack(
            side=tk.LEFT, padx=(6, 14)
        )

        ttk.Label(row, text="Shape:").pack(side=tk.LEFT)
        ttk.Combobox(
            row,
            textvariable=self._stick_deadzone_shape,
            values=["circle", "square", "hybrid"],
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 14))

        ttk.Label(row, text="Curve:").pack(side=tk.LEFT)
        ttk.Combobox(
            row,
            textvariable=self._stick_curve,
            values=["linear", "exponential", "soft", "hard"],
            width=12,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 14))

        ttk.Label(row, text="Exp:").pack(side=tk.LEFT)
        tk.Scale(row, from_=0.5, to=3.0, resolution=0.1, orient="horizontal", variable=self._stick_curve_exp).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        preview = ttk.LabelFrame(self.tab_stick, text="Curve preview")
        preview.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.curve_canvas = tk.Canvas(preview, height=220)
        self.curve_canvas.pack(fill=tk.BOTH, expand=True)
        try:
            self.curve_canvas.configure(bg=self._colors["panel2"])
        except Exception:
            pass

        for var in (self._stick_deadzone, self._stick_deadzone_shape, self._stick_curve, self._stick_curve_exp):
            var.trace_add("write", lambda *_a: self._draw_curve_preview())
        self._draw_curve_preview()

    def _build_share_tab(self) -> None:
        ttk.Label(self.tab_share, text="Profile share code").pack(anchor="w")
        self.share_text = ScrolledText(self.tab_share, height=10)
        self.share_text.pack(fill=tk.X)
        self._theme_scrolled_text(self.share_text)

        btns = ttk.Frame(self.tab_share)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btns, text="Export from JSON", command=self._share_export).pack(side=tk.LEFT)
        ttk.Button(btns, text="Import to JSON", command=self._share_import).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(
            self.tab_share,
            text=(
                "This is offline-only sharing: a compressed+encoded loadout string. "
                "No network calls, no overlays/hooks, and nothing game-specific."
            ),
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        # ── Built-in community presets ──
        preset_box = ttk.LabelFrame(self.tab_share, text="Quick-start presets")
        preset_box.pack(fill=tk.X, padx=0, pady=(12, 0))
        ttk.Label(
            preset_box,
            text="Load a ready-made heist plan preset. This replaces the current loadout.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(4, 2))
        preset_row = ttk.Frame(preset_box)
        preset_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        for pname, pdesc in [
            ("FPS / Shooter", "WASD + Space jump, Shift sprint, R reload, E interact, mouse-like aiming"),
            ("Platformer", "Left/Right on D-pad, A jump, B attack, triggers for special"),
            ("RPG / Action", "WASD move, 1-4 hotbar, E interact, I inventory, Space roll"),
            ("Minecraft", "WASD move, Space jump, Shift sneak, E inventory, Q drop, 1-4 hotbar"),
            ("Racing", "Up/Down accelerate/brake, Left/Right steer, A nitro, B look-back"),
        ]:
            ttk.Button(preset_row, text=pname, command=lambda n=pname: self._apply_community_preset(n)).pack(
                side=tk.LEFT, padx=(0, 6)
            )

    def _apply_community_preset(self, name: str) -> None:
        """Apply a built-in community preset mapping set."""
        # Each preset defines (hotspot_name → hid_keycode) mappings.
        presets: Dict[str, Dict[str, Tuple[int, int]]] = {
            "FPS / Shooter": {
                "DUp": (0, 0x1A),     # W
                "DDown": (0, 0x16),   # S
                "DLeft": (0, 0x04),   # A
                "DRight": (0, 0x07),  # D
                "A": (0, 0x2C),       # Space (jump)
                "B": (0, 0x06),       # C (crouch)
                "X": (0, 0x15),       # R (reload)
                "Y": (0, 0x08),       # E (interact)
                "L": (0, 0xE1),       # Shift (sprint)
                "R": (0, 0xE0),       # Ctrl (aim)
                "ZL": (0, 0x1D),      # Z
                "ZR": (0, 0x09),      # F
            },
            "Platformer": {
                "DLeft": (0, 0x50),   # Left arrow
                "DRight": (0, 0x4F),  # Right arrow
                "DUp": (0, 0x52),     # Up arrow
                "DDown": (0, 0x51),   # Down arrow
                "A": (0, 0x2C),       # Space (jump)
                "B": (0, 0x1B),       # X (attack)
                "X": (0, 0x1D),       # Z (special)
                "Y": (0, 0x06),       # C (grab)
                "L": (0, 0xE1),       # Shift (run)
                "R": (0, 0xE0),       # Ctrl
            },
            "RPG / Action": {
                "DUp": (0, 0x1A),     # W
                "DDown": (0, 0x16),   # S
                "DLeft": (0, 0x04),   # A
                "DRight": (0, 0x07),  # D
                "A": (0, 0x2C),       # Space (roll/dodge)
                "B": (0, 0x08),       # E (interact)
                "X": (0, 0x0C),       # I (inventory)
                "Y": (0, 0x1E),       # 1 (hotbar)
                "L": (0, 0xE1),       # Shift (sprint)
                "R": (0, 0xE0),       # Ctrl (block)
                "ZL": (0, 0x1F),      # 2 (hotbar)
                "ZR": (0, 0x20),      # 3 (hotbar)
            },
            "Minecraft": {
                "DUp": (0, 0x1A),     # W
                "DDown": (0, 0x16),   # S
                "DLeft": (0, 0x04),   # A
                "DRight": (0, 0x07),  # D
                "A": (0, 0x2C),       # Space (jump)
                "B": (0, 0x08),       # E (inventory)
                "X": (0, 0x14),       # Q (drop)
                "Y": (0, 0x1E),       # 1 (hotbar slot 1)
                "L": (0, 0xE1),       # Shift (sneak)
                "R": (0, 0x1F),       # 2 (hotbar slot 2)
                "ZL": (0, 0x20),      # 3 (hotbar slot 3)
                "ZR": (0, 0x21),      # 4 (hotbar slot 4)
            },
            "Racing": {
                "DUp": (0, 0x52),     # Up arrow (accelerate)
                "DDown": (0, 0x51),   # Down arrow (brake/reverse)
                "DLeft": (0, 0x50),   # Left arrow (steer left)
                "DRight": (0, 0x4F),  # Right arrow (steer right)
                "A": (0, 0x11),       # N (nitro)
                "B": (0, 0x05),       # B (look back)
                "X": (0, 0x15),       # R (reset)
                "Y": (0, 0x10),       # M (map)
                "L": (0, 0xE1),       # Shift (drift)
                "R": (0, 0x2C),       # Space (handbrake)
            },
        }
        preset = presets.get(name)
        if not preset:
            return
        if not messagebox.askyesno("Execute preset", f"Replace current heist plans with '{name}' preset?"):
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        hs = prof.setdefault("ui", {}).setdefault("hotspots", {})
        mappings = prof.setdefault("mappings", {})
        for hotspot, (mod, kc) in preset.items():
            kid = hs.get(hotspot)
            if kid is None:
                continue
            mappings[str(kid)] = {"type": "remap_hid", "mod": mod, "keycode": kc}
        self._set_profile_obj(prof, undo_label=f"preset:{name}")
        self._keymap_redraw()
        self._rebuild_layer_stack()
        self._play_sound("bind")
        self._log_line(f"[host] Applied community preset: {name}")

    def _build_overlay_tab(self) -> None:
        ttk.Label(
            self.tab_overlay,
            text=(
                "Safe overlay: this is just an always-on-top window. "
                "No process hooking, no injection, no memory reads."
            ),
            wraplength=900,
            justify="left",
        ).pack(anchor="w")

        btns = ttk.Frame(self.tab_overlay)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Open overlay", command=self._overlay_open).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close overlay", command=self._overlay_close).pack(side=tk.LEFT, padx=(6, 0))

    def _build_controller_tab(self) -> None:
        # ── 3-panel "Heist Table" layout ──
        heist_table = tk.Frame(self.tab_controller)
        heist_table.pack(fill=tk.BOTH, expand=True)

        # Left panel — Loadout Notebook
        self._loadout_panel = tk.Frame(
            heist_table, width=190,
            bg=self._colors.get("panel2", "#e2d0a8"),
            highlightthickness=1,
            highlightbackground=self._colors.get("border", "#8b7355"),
        )
        self._loadout_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0), pady=4)
        self._loadout_panel.pack_propagate(False)

        # Center panel — Controller canvas + toolbar
        self._controller_center = tk.Frame(heist_table)
        self._controller_center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Right panel — Heist Tools
        self._heist_tools_panel = tk.Frame(
            heist_table, width=220,
            bg=self._colors.get("panel2", "#e2d0a8"),
            highlightthickness=1,
            highlightbackground=self._colors.get("border", "#8b7355"),
        )
        self._heist_tools_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=4)
        self._heist_tools_panel.pack_propagate(False)

        # Build side panels
        self._build_loadout_panel()
        self._build_heist_tools_panel()

        # Connection background banner: left/right/both.
        self._bt_banner = tk.Frame(self._controller_center, bg=self._colors["panel2"])
        self._bt_banner.pack(fill=tk.X, padx=8, pady=(8, 0))
        self._bt_banner_label = tk.Label(
            self._bt_banner,
            textvariable=self._bt_status,
            bg=self._colors["panel2"],
            fg=self._colors["text"],
            padx=10,
            pady=8,
            anchor="w",
        )
        self._bt_banner_label.pack(fill=tk.X)

        box = ttk.LabelFrame(self._controller_center, text="Controller connection")
        box.pack(fill=tk.X, padx=8, pady=8)

        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X, pady=(6, 0), padx=8)
        ttk.Label(row1, text="Preset:").pack(side=tk.LEFT)
        preset = ttk.Combobox(
            row1,
            textvariable=self._bt_target_preset,
            values=["Either (Joy-Con)", "Left (Joy-Con (L))", "Right (Joy-Con (R))", "Both (Joy-Con (L+R))", "Custom"],
            width=20,
            state="readonly",
        )
        preset.pack(side=tk.LEFT, padx=(8, 12))
        preset.bind("<<ComboboxSelected>>", lambda _e: self._bt_apply_preset())

        ttk.Label(row1, text="Target name contains:").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self._bt_target_substr, width=30).pack(side=tk.LEFT, padx=(8, 0))

        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, pady=(10, 6), padx=8)
        ttk.Button(row2, text="Connect / Scan", command=self._cmd_bt_connect, width=18).pack(side=tk.LEFT)
        # Status is shown in the banner above.

        note = (
            "This sends commands to the ESP32 BT host so you don't need to press buttons on the boards. "
            "Your controller may still need to be put into pairing mode (e.g. Joy-Con sync button)."
        )
        ttk.Label(self._controller_center, text=note, wraplength=900, justify="left").pack(anchor="w", padx=12, pady=(4, 0))

        # ── Controller Info Bar ──
        info_box = ttk.LabelFrame(self._controller_center, text="Controller info")
        info_box.pack(fill=tk.X, padx=8, pady=(6, 2))

        info_row = ttk.Frame(info_box)
        info_row.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(info_row, text="Type:").pack(side=tk.LEFT)
        ttk.Label(info_row, textvariable=self._ctrl_info_type, width=10).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(info_row, text="Serial:").pack(side=tk.LEFT)
        ttk.Label(info_row, textvariable=self._ctrl_info_serial, width=18).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(info_row, text="Deadzone:").pack(side=tk.LEFT)
        ttk.Label(info_row, textvariable=self._ctrl_info_deadzone, width=6).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(info_row, text="Range:").pack(side=tk.LEFT)
        ttk.Label(info_row, textvariable=self._ctrl_info_range, width=6).pack(side=tk.LEFT, padx=(2, 10))

        # Color swatches
        ttk.Label(info_row, text="Body:").pack(side=tk.LEFT)
        self._ctrl_body_swatch = tk.Canvas(info_row, width=18, height=18, highlightthickness=1, highlightbackground="#555")
        self._ctrl_body_swatch.pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(info_row, text="Btn:").pack(side=tk.LEFT)
        self._ctrl_btn_swatch = tk.Canvas(info_row, width=18, height=18, highlightthickness=1, highlightbackground="#555")
        self._ctrl_btn_swatch.pack(side=tk.LEFT, padx=(2, 0))

        # ── Rumble & Home LED Controls ──
        ctrl_box = ttk.LabelFrame(self._controller_center, text="Controller features")
        ctrl_box.pack(fill=tk.X, padx=8, pady=(2, 6))

        ctrl_row = ttk.Frame(ctrl_box)
        ctrl_row.pack(fill=tk.X, padx=8, pady=4)

        ttk.Label(ctrl_row, text="Rumble:").pack(side=tk.LEFT)
        ttk.Label(ctrl_row, text="Freq (Hz):").pack(side=tk.LEFT, padx=(8, 0))
        self._rumble_freq_var = tk.IntVar(value=160)
        ttk.Spinbox(ctrl_row, textvariable=self._rumble_freq_var, from_=41, to=1253, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(ctrl_row, text="Amp (%):").pack(side=tk.LEFT, padx=(6, 0))
        self._rumble_amp_var = tk.IntVar(value=50)
        ttk.Spinbox(ctrl_row, textvariable=self._rumble_amp_var, from_=0, to=100, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl_row, text="\U0001f4f3 Test", command=self._cmd_test_rumble, width=8).pack(side=tk.LEFT, padx=(6, 16))

        ttk.Label(ctrl_row, text="Home LED:").pack(side=tk.LEFT)
        self._home_led_var = tk.IntVar(value=8)
        ttk.Scale(ctrl_row, variable=self._home_led_var, from_=0, to=15, orient=tk.HORIZONTAL, length=100).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl_row, text="\U0001f4a1 Set", command=self._cmd_set_home_led, width=6).pack(side=tk.LEFT, padx=(4, 0))

        # Calibration wizard button
        ttk.Button(ctrl_row, text="\U0001f527 Calibrate", command=self._open_calibration_wizard, width=12).pack(side=tk.LEFT, padx=(16, 0))

        self._build_keymap_editor()

        self._update_bt_background()

    # ------------------------------------------------------------------
    # Left panel — Loadout Notebook ("Heist Library")
    # ------------------------------------------------------------------

    def _build_loadout_panel(self) -> None:
        """Build the left-side Loadout Notebook panel."""
        panel = self._loadout_panel
        font_family = self._typo.get("font_family", "Segoe Print")
        bg = self._colors.get("panel2", "#e2d0a8")
        fg = self._colors.get("text", "#2a1f0e")
        border = self._colors.get("border", "#8b7355")

        # Title
        tk.Label(
            panel, text="\U0001f4c2 Heist Library",
            bg=bg, fg=fg,
            font=(font_family, 11, "bold"),
            anchor="w", padx=8, pady=6,
        ).pack(fill=tk.X)

        # Divider
        tk.Frame(panel, height=2, bg=border).pack(fill=tk.X, padx=8)

        # Loadout cards container
        self._loadout_cards_frame = tk.Frame(panel, bg=bg)
        self._loadout_cards_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=8)

        self._loadout_card_frames: List[tk.Frame] = []
        self._loadout_card_name_labels: List[tk.Label] = []
        for i in range(4):
            self._build_loadout_card(i)

        # Bottom actions
        bottom = tk.Frame(panel, bg=bg)
        bottom.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Frame(bottom, height=2, bg=border).pack(fill=tk.X, pady=(0, 6))

        btn_frame = tk.Frame(bottom, bg=bg)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Import", command=self._load_profile, width=8).pack(
            side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_frame, text="Export", command=self._save_profile, width=8).pack(
            side=tk.LEFT)

        self._refresh_loadout_cards()

    def _build_loadout_card(self, slot: int) -> None:
        """Build a single loadout card in the left panel."""
        bg = self._colors.get("panel2", "#e2d0a8")
        fg = self._colors.get("text", "#2a1f0e")
        font_family = self._typo.get("font_family", "Segoe Print")

        card = tk.Frame(
            self._loadout_cards_frame, bg=bg,
            highlightthickness=2,
            highlightbackground=self._colors.get("border", "#8b7355"),
            cursor="hand2",
        )
        card.pack(fill=tk.X, pady=(0, 6))

        inner = tk.Frame(card, bg=bg)
        inner.pack(fill=tk.X, padx=8, pady=6)

        icon_lbl = tk.Label(
            inner, text="\U0001f4d3", bg=bg, fg=fg,
            font=(font_family, 14),
        )
        icon_lbl.pack(side=tk.LEFT)

        name_var = self._slot_name_vars[slot]
        name_lbl = tk.Label(
            inner, textvariable=name_var, bg=bg, fg=fg,
            font=(font_family, 10), anchor="w",
        )
        name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # Click binding
        for widget in (card, inner, icon_lbl, name_lbl):
            widget.bind("<Button-1>", lambda _e, s=slot: self._loadout_card_click(s))

        self._loadout_card_frames.append(card)
        self._loadout_card_name_labels.append(name_lbl)

    def _loadout_card_click(self, slot: int) -> None:
        """Handle click on a loadout card — select that slot."""
        self.slot_var.set(str(slot))
        self._slot_select(slot)
        self._refresh_loadout_cards()

    def _refresh_loadout_cards(self) -> None:
        """Update loadout card visual state (highlight active slot)."""
        if not hasattr(self, "_loadout_card_frames"):
            return
        active = int(self.slot_var.get()) if self.slot_var.get().isdigit() else 0
        accent = self._colors.get("accent", "#6b4c2a")
        border = self._colors.get("border", "#8b7355")
        bg = self._colors.get("panel2", "#e2d0a8")
        sel_bg = self._colors.get("selected", "#d4c4a0")

        for i, card in enumerate(self._loadout_card_frames):
            is_active = i == active
            card.configure(
                highlightbackground=accent if is_active else border,
                highlightthickness=3 if is_active else 2,
            )
            target_bg = sel_bg if is_active else bg
            for child in card.winfo_children():
                try:
                    child.configure(bg=target_bg)
                except Exception:
                    pass
                for sub in child.winfo_children():
                    try:
                        sub.configure(bg=target_bg)
                    except Exception:
                        pass

    # ------------------------------------------------------------------
    # Right panel — Heist Tools
    # ------------------------------------------------------------------

    def _build_heist_tools_panel(self) -> None:
        """Build the right-side Heist Tools context panel."""
        panel = self._heist_tools_panel
        font_family = self._typo.get("font_family", "Segoe Print")
        bg = self._colors.get("panel2", "#e2d0a8")
        fg = self._colors.get("text", "#2a1f0e")
        border = self._colors.get("border", "#8b7355")
        muted = self._colors.get("muted", "#8b7355")

        # Title
        tk.Label(
            panel, text="\U0001f9f0 Heist Tools",
            bg=bg, fg=fg,
            font=(font_family, 11, "bold"),
            anchor="w", padx=8, pady=6,
        ).pack(fill=tk.X)
        tk.Frame(panel, height=2, bg=border).pack(fill=tk.X, padx=8)

        # Default state (shown when no button selected)
        self._heist_default_frame = tk.Frame(panel, bg=bg)
        self._heist_default_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            self._heist_default_frame,
            text="Select a button\nto plan a heist\u2026",
            bg=bg, fg=muted,
            font=(font_family, 11),
            justify="center", wraplength=190,
        ).pack(expand=True)

        # Button card (shown when a hotspot is selected)
        self._heist_card_frame = tk.Frame(panel, bg=bg)
        # Not packed yet — shown by _update_heist_tools

        # Button name header
        self._heist_btn_name_var = tk.StringVar(value="")
        tk.Label(
            self._heist_card_frame, textvariable=self._heist_btn_name_var,
            bg=bg, fg=fg,
            font=(font_family, 13, "bold"),
            anchor="w", padx=8,
        ).pack(fill=tk.X, pady=(8, 2))

        # Current mapping display
        self._heist_current_var = tk.StringVar(value="")
        tk.Label(
            self._heist_card_frame, textvariable=self._heist_current_var,
            bg=bg, fg=muted,
            font=(font_family, 9), anchor="w",
            padx=8, wraplength=190,
        ).pack(fill=tk.X, pady=(0, 8))

        tk.Frame(self._heist_card_frame, height=2, bg=border).pack(fill=tk.X, padx=8)

        # Action buttons
        actions = tk.Frame(self._heist_card_frame, bg=bg)
        actions.pack(fill=tk.X, padx=8, pady=8)

        ttk.Button(
            actions, text="\U0001f3b9 Keyboard",
            command=self._heist_steal_keyboard, width=18,
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Button(
            actions, text="\U0001f5b1\ufe0f Mouse Click",
            command=self._heist_steal_mouse, width=18,
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Button(
            actions, text="\U0001f9ea Trick (Macro)",
            command=self._heist_assign_trick, width=18,
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Button(
            actions, text="\U0001f3ad Mask Shift",
            command=self._heist_mask_shift, width=18,
        ).pack(fill=tk.X, pady=(0, 4))

        tk.Frame(self._heist_card_frame, height=2, bg=border).pack(fill=tk.X, padx=8, pady=(4, 0))

        # Clear button
        clear_frame = tk.Frame(self._heist_card_frame, bg=bg)
        clear_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(
            clear_frame, text="\u2716 CLEAR",
            command=self._keymap_clear_selected, width=18,
        ).pack(fill=tk.X)

        # ── Inline Trick Builder (hidden until toggled) ──
        self._trick_builder_frame = tk.Frame(self._heist_card_frame, bg=bg)
        # Not packed yet — shown by _heist_assign_trick

        tk.Frame(self._trick_builder_frame, height=2, bg=border).pack(fill=tk.X, padx=0)
        tk.Label(
            self._trick_builder_frame, text="\U0001f9ea Trick Builder",
            bg=bg, fg=fg,
            font=(font_family, 10, "bold"),
            anchor="w", padx=4,
        ).pack(fill=tk.X, pady=(6, 4))

        # -- Pick or create trick --
        pick_row = tk.Frame(self._trick_builder_frame, bg=bg)
        pick_row.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._trick_pick_var = tk.StringVar(value="")
        self._trick_pick_combo = ttk.Combobox(
            pick_row, textvariable=self._trick_pick_var,
            values=[], width=14, state="readonly",
        )
        self._trick_pick_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._trick_pick_combo.bind("<<ComboboxSelected>>", lambda _e: self._trick_builder_refresh_steps())
        ttk.Button(pick_row, text="+", width=2, command=self._trick_builder_new).pack(side=tk.LEFT, padx=(4, 0))

        # -- Steps list --
        self._trick_step_listbox = tk.Listbox(
            self._trick_builder_frame, height=5, width=20,
            font=(font_family, 8),
        )
        self._trick_step_listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self._theme_listbox(self._trick_step_listbox)

        # -- Step buttons --
        step_btns = tk.Frame(self._trick_builder_frame, bg=bg)
        step_btns.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Button(step_btns, text="+ Key", width=6, command=self._trick_builder_add_key).pack(side=tk.LEFT)
        ttk.Button(step_btns, text="+ Delay", width=6, command=self._trick_builder_add_delay).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(step_btns, text="\u2716", width=2, command=self._trick_builder_del_step).pack(side=tk.LEFT, padx=(4, 0))

        # -- Assign button --
        ttk.Button(
            self._trick_builder_frame, text="\u2705 Assign to button",
            command=self._trick_builder_assign, width=18,
        ).pack(fill=tk.X, padx=4, pady=(0, 6))

        self._trick_builder_visible = False

        # ── Masks / Disguises section (always visible at bottom of panel) ──
        mask_section = tk.Frame(panel, bg=bg)
        mask_section.pack(side=tk.BOTTOM, fill=tk.X, padx=0, pady=0)

        tk.Frame(mask_section, height=2, bg=border).pack(fill=tk.X, padx=8)
        tk.Label(
            mask_section, text="\U0001f3ad Disguises",
            bg=bg, fg=fg,
            font=(font_family, 10, "bold"),
            anchor="w", padx=8,
        ).pack(fill=tk.X, pady=(6, 4))

        self._mask_cards_frame = tk.Frame(mask_section, bg=bg)
        self._mask_cards_frame.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._mask_card_labels: List[tk.Label] = []
        self._build_mask_cards()

    def _update_heist_tools(self, hotspot_name: Optional[str] = None) -> None:
        """Update the right-panel Heist Tools card for the selected hotspot."""
        if not hasattr(self, "_heist_card_frame"):
            return

        # Collapse inline trick builder on any hotspot change
        if hasattr(self, "_trick_builder_frame") and self._trick_builder_visible:
            self._trick_builder_frame.pack_forget()
            self._trick_builder_visible = False

        if hotspot_name is None:
            # Show default state
            self._heist_card_frame.pack_forget()
            self._heist_default_frame.pack(fill=tk.BOTH, expand=True)
            return

        # Show button card
        self._heist_default_frame.pack_forget()
        self._heist_card_frame.pack(fill=tk.BOTH, expand=True)

        # Update button name
        self._heist_btn_name_var.set(f"\u270f\ufe0f {hotspot_name}")

        # Get current mapping info
        self._heist_current_var.set(self._get_heist_mapping_text(hotspot_name))

    def _get_heist_mapping_text(self, hotspot_name: str) -> str:
        """Get a human-readable description of the current mapping for a hotspot."""
        hs = self._keymap_hotspots()
        key_id = hs.get(hotspot_name)
        if key_id is None:
            return "No key_id learned \u2014 use Case first"

        try:
            prof = self._current_profile()
        except Exception:
            return "No loadout"

        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
        entry = mappings.get(str(key_id))
        if not isinstance(entry, dict):
            return "Passthrough (default)"

        et = entry.get("type", "passthrough")
        if et == "passthrough":
            return "Passthrough (default)"
        if et == "disable":
            return "Disabled"
        if et == "remap":
            to = entry.get("to", "?")
            return f"Remap \u2192 key_id {to}"
        if et == "remap_hid":
            kc = entry.get("keycode", 0)
            name = hid_keycodes.hid_to_name(entry.get("mod", 0), kc) if isinstance(kc, int) else f"0x{kc:02X}"
            return f"Keyboard \u2192 {name}"
        if et == "macro":
            mid = entry.get("id", "?")
            return f"Trick \u2192 {mid}"
        if et == "tap_hold":
            return "Tap / Hold"
        if et == "double_tap":
            return "Double-Tap"
        return f"Type: {et}"

    # Heist Tools action methods

    def _heist_steal_keyboard(self) -> None:
        """Begin steal mode for the selected hotspot (keyboard key)."""
        if self._keymap_selected_name:
            self._keymap_begin_bind()

    def _heist_steal_mouse(self) -> None:
        """Assign a mouse-click remap to the selected hotspot."""
        if self._keymap_selected_name:
            self._mapping_type.set("remap_hid")
            self._mapping_popup.show()

    def _heist_assign_trick(self) -> None:
        """Toggle the inline Trick Builder in the Heist Tools panel."""
        if not self._keymap_selected_name:
            return
        if not hasattr(self, "_trick_builder_frame"):
            return
        if self._trick_builder_visible:
            self._trick_builder_frame.pack_forget()
            self._trick_builder_visible = False
        else:
            self._trick_builder_reload_list()
            self._trick_builder_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
            self._trick_builder_visible = True

    def _trick_builder_reload_list(self) -> None:
        """Refresh the trick picker combo with current profile macros."""
        try:
            macros = self._macros()
        except Exception:
            macros = []
        ids = [m.get("id", "") for m in macros if isinstance(m, dict) and m.get("id")]
        self._trick_pick_combo["values"] = ids
        cur = self._trick_pick_var.get()
        if ids and cur not in ids:
            self._trick_pick_var.set(ids[0])
        self._trick_builder_refresh_steps()

    def _trick_builder_selected_macro(self) -> Optional[Dict[str, Any]]:
        """Return the macro dict selected in the trick picker, or None."""
        mid = self._trick_pick_var.get().strip()
        if not mid:
            return None
        try:
            macros = self._macros()
        except Exception:
            return None
        for m in macros:
            if isinstance(m, dict) and m.get("id") == mid:
                return m
        return None

    def _trick_builder_refresh_steps(self) -> None:
        """Refresh the inline step listbox for the selected trick."""
        if not hasattr(self, "_trick_step_listbox"):
            return
        self._trick_step_listbox.delete(0, "end")
        macro = self._trick_builder_selected_macro()
        if macro is None:
            return
        for st in macro.get("steps", []):
            if not isinstance(st, dict):
                continue
            t = st.get("type")
            if t == "delay":
                self._trick_step_listbox.insert("end", f"  \u23f1 {st.get('ms', 0)}ms")
            elif t == "key":
                arrow = "\u2b07" if st.get("pressed") else "\u2b06"
                self._trick_step_listbox.insert("end", f"  {arrow} key_id {st.get('key_id')}")
            else:
                self._trick_step_listbox.insert("end", f"  ? {st}")

    def _trick_builder_new(self) -> None:
        """Create a new trick from the inline builder."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        new_id = f"macro{int(time.time())}"
        prof["macros"].append({"id": new_id, "steps": []})
        self._set_profile_obj(prof)
        self._trick_builder_reload_list()
        self._trick_pick_var.set(new_id)
        self._trick_builder_refresh_steps()
        # Keep the Tricks tab list in sync
        self._refresh_macro_list()

    def _trick_builder_add_key(self) -> None:
        """Add a key press+release step to the selected trick."""
        macro = self._trick_builder_selected_macro()
        if macro is None:
            return
        key_id_str = simpledialog.askstring("Key step", "Enter key_id (integer):", parent=self)
        if not key_id_str:
            return
        try:
            key_id = int(key_id_str.strip())
        except ValueError:
            messagebox.showerror("Bad key_id", "key_id must be an integer")
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        mid = macro["id"]
        for m in prof["macros"]:
            if m.get("id") == mid:
                m.setdefault("steps", []).append({"type": "key", "key_id": key_id, "pressed": True})
                m["steps"].append({"type": "key", "key_id": key_id, "pressed": False})
                break
        self._set_profile_obj(prof)
        self._trick_builder_refresh_steps()
        self._refresh_macro_steps()

    def _trick_builder_add_delay(self) -> None:
        """Add a delay step to the selected trick."""
        macro = self._trick_builder_selected_macro()
        if macro is None:
            return
        ms = simpledialog.askinteger("Delay", "Delay in ms:", initialvalue=50, minvalue=0, maxvalue=5000, parent=self)
        if ms is None:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        mid = macro["id"]
        for m in prof["macros"]:
            if m.get("id") == mid:
                m.setdefault("steps", []).append({"type": "delay", "ms": int(ms)})
                break
        self._set_profile_obj(prof)
        self._trick_builder_refresh_steps()
        self._refresh_macro_steps()

    def _trick_builder_del_step(self) -> None:
        """Delete the selected step from the inline trick builder."""
        macro = self._trick_builder_selected_macro()
        if macro is None:
            return
        sel = self._trick_step_listbox.curselection()
        if not sel:
            return
        sidx = int(sel[0])
        try:
            prof = self._current_profile()
        except Exception:
            return
        mid = macro["id"]
        for m in prof["macros"]:
            if m.get("id") == mid:
                steps = m.get("steps", [])
                if isinstance(steps, list) and sidx < len(steps):
                    del steps[sidx]
                    m["steps"] = steps
                break
        self._set_profile_obj(prof)
        self._trick_builder_refresh_steps()
        self._refresh_macro_steps()

    def _trick_builder_assign(self) -> None:
        """Assign the selected trick to the currently selected hotspot."""
        mid = self._trick_pick_var.get().strip()
        if not mid:
            messagebox.showerror("No trick", "Select or create a trick first")
            return
        hs_name = self._keymap_selected_name
        if not hs_name:
            return
        hs = self._keymap_hotspots()
        key_id = hs.get(hs_name)
        if key_id is None:
            messagebox.showerror("No key_id", "Use Case first to learn this button")
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings
        mappings[str(key_id)] = {"type": "macro", "id": mid}
        self._set_profile_obj(prof)
        self._keymap_redraw()
        self._update_heist_tools(hs_name)

    def _heist_mask_shift(self) -> None:
        """Open mask/layer config for the selected hotspot."""
        if self._keymap_selected_name:
            self._layers_popup.show()

    def _build_mask_cards(self) -> None:
        """Build mask/layer quick-switch cards in the Heist Tools panel."""
        bg = self._colors.get("panel2", "#e2d0a8")
        fg = self._colors.get("text", "#2a1f0e")
        font_family = self._typo.get("font_family", "Segoe Print")
        border = self._colors.get("border", "#8b7355")

        # Base mask card
        base_lbl = tk.Label(
            self._mask_cards_frame, text="Base Face",
            bg=bg, fg=fg, font=(font_family, 9),
            relief="groove", padx=6, pady=3, cursor="hand2",
        )
        base_lbl.pack(fill=tk.X, pady=(0, 3))
        base_lbl.bind("<Button-1>", lambda _e: self._mask_card_click(-1))
        self._mask_card_labels.append(base_lbl)

        # Layer masks
        for li in range(4):
            lbl = tk.Label(
                self._mask_cards_frame, text=f"+ Mask {li + 1}",
                bg=bg, fg=fg, font=(font_family, 9),
                relief="groove", padx=6, pady=3, cursor="hand2",
            )
            lbl.pack(fill=tk.X, pady=(0, 3))
            lbl.bind("<Button-1>", lambda _e, idx=li: self._mask_card_click(idx))
            self._mask_card_labels.append(lbl)

        self._refresh_mask_cards()

    def _mask_card_click(self, layer_index: int) -> None:
        """Switch to a mask layer from the right panel."""
        self._layer_edit_index.set(layer_index)
        self._keymap_redraw()
        self._refresh_mask_cards()

    def _refresh_mask_cards(self) -> None:
        """Update mask card visual state (highlight active mask)."""
        if not hasattr(self, "_mask_card_labels"):
            return
        active = self._layer_edit_index.get()
        accent = self._colors.get("accent", "#6b4c2a")
        border = self._colors.get("border", "#8b7355")
        bg = self._colors.get("panel2", "#e2d0a8")
        sel_bg = self._colors.get("selected", "#d4c4a0")

        for i, lbl in enumerate(self._mask_card_labels):
            idx = i - 1  # -1 = base, 0 = mask 1, etc.
            is_active = idx == active
            lbl.configure(
                bg=sel_bg if is_active else bg,
                relief="sunken" if is_active else "groove",
            )

    def _joycons_image_state(self) -> str:
        if self._bt_connected_left and self._bt_connected_right:
            return "both"
        if self._bt_connected_left:
            return "left"
        if self._bt_connected_right:
            return "right"
        return "none"

    def _find_joycons_png_variants(self) -> Dict[str, Path]:
        prefer_dark = self._detect_dark_preference()
        theme = "dark" if prefer_dark else "default"

        # Composited and raw filenames are now identical; the theme folder
        # determines light vs dark.  Search roots prioritise the themed
        # ``backgrounds/`` folder so composites are found first.
        variant_names = {
            "none": "joycons-none.png",
            "left": "joycons-left.png",
            "right": "joycons-right.png",
            "both": "joycons-both.png",
        }
        search_roots = _joycons_search_roots(theme)

        found: Dict[str, Path] = {}
        is_composite = False

        for state, file_name in variant_names.items():
            for root in search_roots:
                candidate = root / file_name
                try:
                    if candidate.exists():
                        found[state] = candidate
                        # If found in a themed backgrounds dir, it's composited.
                        if "backgrounds" in str(candidate):
                            is_composite = True
                        break
                except Exception:
                    continue

        self._keymap_is_composite = is_composite

        # Legacy fallbacks (joycons.png / joycons-grey.png at repo root).
        fallback_base: Optional[Path] = None
        fallback_none: Optional[Path] = None
        fallback_candidates = [root / "joycons.png" for root in search_roots]
        none_candidates = [root / "joycons-grey.png" for root in search_roots]
        for candidate in fallback_candidates:
            try:
                if candidate.exists():
                    fallback_base = candidate
                    break
            except Exception:
                continue
        for candidate in none_candidates:
            try:
                if candidate.exists():
                    fallback_none = candidate
                    break
            except Exception:
                continue

        if fallback_base is not None:
            found.setdefault("both", fallback_base)
            found.setdefault("left", fallback_base)
            found.setdefault("right", fallback_base)
        if fallback_none is not None:
            found.setdefault("none", fallback_none)
        elif fallback_base is not None:
            found.setdefault("none", fallback_base)

        return found

    def _set_keymap_image_state(self, state: Optional[str] = None) -> None:
        next_state = state or self._joycons_image_state()
        if next_state not in JOYCONS_IMAGE_STATE_NAMES:
            next_state = "none"

        path = self._keymap_img_paths.get(next_state)
        has_image = self._keymap_pil_base is not None or self._keymap_img_base is not None
        if path == self._keymap_img_path and has_image:
            self._keymap_img_state = next_state
            return

        self._keymap_img_state = next_state
        self._keymap_img_path = path
        self._keymap_img_base = None
        self._keymap_img_scaled = None
        self._keymap_pil_base = None

        if self._keymap_img_path:
            if _HAS_PIL:
                try:
                    self._keymap_pil_base = PILImage.open(str(self._keymap_img_path)).convert("RGBA")
                except Exception:
                    self._keymap_pil_base = None
            # Fallback to tk.PhotoImage when Pillow is unavailable.
            if self._keymap_pil_base is None:
                try:
                    self._keymap_img_base = tk.PhotoImage(file=str(self._keymap_img_path))
                except Exception:
                    self._keymap_img_base = None

    # ------------------------------------------------------------------
    # M913 mouse overlay image helpers
    # ------------------------------------------------------------------

    def _find_m913_png_variants(self, layout: str = "stock") -> Dict[str, Path]:
        prefer_dark = self._detect_dark_preference()

        if layout == "incedius":
            # Incedius composites live in the default/dark theme folders
            # with "m913-incedius" naming.
            if prefer_dark:
                theme = "dark"
            else:
                theme = "default"
            variant_names = {
                "connected": "m913-incedius.png",
                "none": "m913-incedius-none.png",
            }
        else:
            # Stock M913 — light/dark determined by theme folder.
            theme = "dark" if prefer_dark else "default"
            variant_names = {
                "connected": "m913.png",
                "none": "m913-none.png",
            }

        search_roots = _joycons_search_roots(theme)

        found: Dict[str, Path] = {}
        is_composite = False

        for state, file_name in variant_names.items():
            for root in search_roots:
                candidate = root / file_name
                try:
                    if candidate.exists():
                        found[state] = candidate
                        if "backgrounds" in str(candidate):
                            is_composite = True
                        break
                except Exception:
                    continue

        self._m913_is_composite = is_composite

        # Fallback: use connected image for disconnected state if only one exists
        if "connected" in found and "none" not in found:
            found["none"] = found["connected"]
        elif "none" in found and "connected" not in found:
            found["connected"] = found["none"]

        return found

    def _m913_set_image_state(self, state: str = "none") -> None:
        if state not in M913_IMAGE_STATE_NAMES:
            state = "none"

        path = self._m913_img_paths.get(state)
        has_image = self._m913_pil_base is not None or self._m913_img_base is not None
        if path == self._m913_img_path and has_image:
            self._m913_img_state = state
            return

        self._m913_img_state = state
        self._m913_img_path = path
        self._m913_img_base = None
        self._m913_img_scaled = None
        self._m913_pil_base = None

        if self._m913_img_path:
            if _HAS_PIL:
                try:
                    self._m913_pil_base = PILImage.open(str(self._m913_img_path)).convert("RGBA")
                except Exception:
                    self._m913_pil_base = None
            if self._m913_pil_base is None:
                try:
                    self._m913_img_base = tk.PhotoImage(file=str(self._m913_img_path))
                except Exception:
                    self._m913_img_base = None

        self._m913_redraw_overlay()

    def _m913_redraw_overlay(self) -> None:
        c = self._m913_overlay_canvas
        if not c:
            return

        c.delete("all")

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        if not self._m913_pil_base and not self._m913_img_base:
            msg = "M913 mouse image not found" if not self._m913_img_path else "Failed to load M913 image"
            c.create_text(w // 2, h // 2, text=msg, fill=self._colors.get("muted", "#666"))
            return

        # Composite path (Pillow available): fuse overlay onto background.
        if self._m913_pil_base is not None:
            if getattr(self, "_m913_is_composite", False):
                photo, _ox, _oy, _ow, _oh = self._scale_composite_to_canvas(
                    self._m913_pil_base, w, h,
                )
            else:
                photo, _ox, _oy, _ow, _oh = self._composite_bg_overlay(
                    self._m913_pil_base, w, h,
                )
            self._m913_img_scaled = photo  # prevent GC
            c.create_image(0, 0, image=photo, anchor="nw")
            return

        # Legacy fallback: tk.PhotoImage overlay without compositing.
        base_w = self._m913_img_base.width()
        base_h = self._m913_img_base.height()
        factor = max(1, int(math.ceil(base_w / max(1, w))), int(math.ceil(base_h / max(1, h))))

        try:
            self._m913_img_scaled = self._m913_img_base.subsample(factor, factor)
        except Exception:
            self._m913_img_scaled = self._m913_img_base

        img_w = self._m913_img_scaled.width()
        img_h = self._m913_img_scaled.height()
        ox = (w - img_w) / 2.0
        oy = (h - img_h) / 2.0
        c.create_image(ox, oy, image=self._m913_img_scaled, anchor="nw")

    # ------------------------------------------------------------------
    # Razer overlay image helpers
    # ------------------------------------------------------------------

    def _find_razer_png_variants(self) -> Dict[str, Path]:
        """Locate themed mouse.png / mouse-none.png for the Razer tab."""
        prefer_dark = self._detect_dark_preference()
        theme = "dark" if prefer_dark else "default"
        variant_names = {
            "connected": "mouse.png",
            "none": "mouse-none.png",
        }
        search_roots = _joycons_search_roots(theme)
        found: Dict[str, Path] = {}
        is_composite = False
        for state, file_name in variant_names.items():
            for root in search_roots:
                candidate = root / file_name
                try:
                    if candidate.exists():
                        found[state] = candidate
                        if "backgrounds" in str(candidate):
                            is_composite = True
                        break
                except Exception:
                    continue
        self._razer_is_composite = is_composite
        if "connected" in found and "none" not in found:
            found["none"] = found["connected"]
        elif "none" in found and "connected" not in found:
            found["connected"] = found["none"]
        return found

    def _razer_set_image_state(self, state: str = "none") -> None:
        if state not in RAZER_IMAGE_STATE_NAMES:
            state = "none"
        path = self._razer_img_paths.get(state)
        has_image = self._razer_pil_base is not None or self._razer_img_base is not None
        if path == self._razer_img_path and has_image:
            self._razer_img_state = state
            return
        self._razer_img_state = state
        self._razer_img_path = path
        self._razer_img_base = None
        self._razer_img_scaled = None
        self._razer_pil_base = None
        if self._razer_img_path:
            if _HAS_PIL:
                try:
                    self._razer_pil_base = PILImage.open(str(self._razer_img_path)).convert("RGBA")
                except Exception:
                    self._razer_pil_base = None
            if self._razer_pil_base is None:
                try:
                    self._razer_img_base = tk.PhotoImage(file=str(self._razer_img_path))
                except Exception:
                    self._razer_img_base = None
        self._razer_redraw_overlay()

    def _razer_redraw_overlay(self) -> None:
        c = self._razer_overlay_canvas
        if not c:
            return
        c.delete("all")
        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)
        if not self._razer_pil_base and not self._razer_img_base:
            msg = "Mouse image not found" if not self._razer_img_path else "Failed to load mouse image"
            c.create_text(w // 2, h // 2, text=msg, fill=self._colors.get("muted", "#666"))
            return
        if self._razer_pil_base is not None:
            if getattr(self, "_razer_is_composite", False):
                photo, _ox, _oy, _ow, _oh = self._scale_composite_to_canvas(
                    self._razer_pil_base, w, h,
                )
            else:
                photo, _ox, _oy, _ow, _oh = self._composite_bg_overlay(
                    self._razer_pil_base, w, h,
                )
            self._razer_img_scaled = photo
            c.create_image(0, 0, image=photo, anchor="nw")
            return
        base_w = self._razer_img_base.width()
        base_h = self._razer_img_base.height()
        factor = max(1, int(math.ceil(base_w / max(1, w))), int(math.ceil(base_h / max(1, h))))
        try:
            self._razer_img_scaled = self._razer_img_base.subsample(factor, factor)
        except Exception:
            self._razer_img_scaled = self._razer_img_base
        img_w = self._razer_img_scaled.width()
        img_h = self._razer_img_scaled.height()
        ox = (w - img_w) / 2.0
        oy = (h - img_h) / 2.0
        c.create_image(ox, oy, image=self._razer_img_scaled, anchor="nw")

    # ------------------------------------------------------------------
    # Keyboard preview image helpers (Controller tab)
    # ------------------------------------------------------------------

    def _find_keyboard_png(self) -> Optional[Path]:
        """Locate the themed keyboard image (keyboard.png or keyboard-dark.png)."""
        prefer_dark = self._detect_dark_preference()
        if prefer_dark:
            name = "keyboard-dark.png"
            theme = "dark"
        else:
            name = "keyboard.png"
            theme = "default"

        here = Path(__file__).resolve()
        repo = here.parents[3]
        search_roots: List[Path] = []
        try:
            search_roots.append(Path.cwd() / "docs" / "ui" / theme / "misc")
        except Exception:
            pass
        search_roots.append(repo / "docs" / "ui" / theme / "misc")

        # Also check .ui-bundle locations
        for root in _joycons_search_roots(theme):
            search_roots.append(root)

        for root in _dedupe_paths(search_roots):
            candidate = root / name
            try:
                if candidate.is_file():
                    return candidate
            except Exception:
                continue
        return None

    def _load_keyboard_image(self) -> None:
        """Load the keyboard PNG for the current theme."""
        path = self._find_keyboard_png()
        if path == self._kbd_img_path and self._kbd_pil_base is not None:
            return  # Already loaded

        self._kbd_img_path = path
        self._kbd_pil_base = None
        self._kbd_img_scaled = None

        if path and _HAS_PIL:
            try:
                self._kbd_pil_base = PILImage.open(str(path)).convert("RGBA")
            except Exception:
                log.debug("Failed to load keyboard image %s", path, exc_info=True)
                self._kbd_pil_base = None

    def _kbd_mapped_keycodes(self) -> set:
        """Return the set of HID keycodes and modifier bits currently mapped by the profile."""
        mapped: set = set()
        try:
            prof = self._current_profile()
        except Exception:
            return mapped

        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            return mapped

        for _kid, entry in mappings.items():
            if not isinstance(entry, dict):
                continue
            et = entry.get("type", "")
            if et == "remap_hid":
                kc = entry.get("keycode", 0)
                mod = entry.get("mod", 0)
                if kc:
                    mapped.add(kc)
                if mod:
                    # Add negative modifier bits to match KBD_LABEL_TO_KEYCODE convention
                    for bit in [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]:
                        if mod & bit:
                            mapped.add(-bit)
            elif et == "remap":
                to = entry.get("to")
                if isinstance(to, int):
                    dk = hid_keycodes.DEFAULT_KEYMAP.get(to)
                    if dk:
                        kc = dk[1]
                        mod = dk[0]
                        if kc:
                            mapped.add(kc)
                        if mod:
                            for bit in [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]:
                                if mod & bit:
                                    mapped.add(-bit)
            elif et == "passthrough" or et is None:
                # Check default keymap
                try:
                    kid = int(_kid)
                    dk = hid_keycodes.DEFAULT_KEYMAP.get(kid)
                    if dk:
                        kc = dk[1]
                        mod = dk[0]
                        if kc:
                            mapped.add(kc)
                        if mod:
                            for bit in [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]:
                                if mod & bit:
                                    mapped.add(-bit)
                except (ValueError, TypeError):
                    pass
        return mapped

    def _kbd_redraw(self) -> None:
        """Redraw the keyboard preview canvas, highlighting mapped keys."""
        c = self._kbd_canvas
        if not c:
            return

        c.delete("all")

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        if not self._kbd_pil_base:
            c.create_text(
                w // 2, h // 2,
                text="Keyboard image not found",
                fill=self._colors.get("muted", "#666"),
            )
            return

        # Composite keyboard onto background
        photo, ox, oy, img_w, img_h = self._composite_bg_overlay(
            self._kbd_pil_base, w, h,
        )
        self._kbd_img_scaled = photo  # prevent GC
        c.create_image(0, 0, image=photo, anchor="nw")
        self._kbd_overlay_ox = ox
        self._kbd_overlay_oy = oy
        self._kbd_overlay_w = img_w
        self._kbd_overlay_h = img_h

        # Build hotspot pixel positions
        self._kbd_hotspot_px = {}
        for name, nx, ny in KBD_HOTSPOTS:
            px = ox + nx * img_w
            py = oy + ny * img_h
            self._kbd_hotspot_px[name] = (px, py)

        # Determine which keycodes are mapped
        mapped = self._kbd_mapped_keycodes()

        radius = max(10, int(min(img_w, img_h) * 0.015))

        for name, nx, ny in KBD_HOTSPOTS:
            px, py = self._kbd_hotspot_px[name]
            hid_code = KBD_LABEL_TO_KEYCODE.get(name)
            is_mapped = hid_code is not None and hid_code in mapped

            if is_mapped:
                fill = self._overlay_hex()
                outline = fill
                text_col = _contrast_on(fill)
            else:
                fill = ""  # transparent
                outline = self._colors.get("border", "#333")
                text_col = self._colors.get("muted", "#666")

            if is_mapped:
                c.create_oval(
                    px - radius, py - radius, px + radius, py + radius,
                    outline=outline, width=2, fill=fill,
                )
                c.create_text(
                    px, py, text=name,
                    fill=text_col,
                    font=(self._typo.get("font_family", "Segoe UI"), max(7, radius - 2)),
                )
            # Only draw labels for mapped keys to keep the view clean

    # ------------------------------------------------------------------
    # Pulse animation for active hotspot highlighting
    # ------------------------------------------------------------------

    def _pulse_tick(self) -> None:
        """Advance the pulse animation phase and redraw if active keys exist or dirty."""
        if self._active_key_ids:
            step = 0.07
            if self._pulse_growing:
                self._pulse_phase += step
                if self._pulse_phase >= 1.0:
                    self._pulse_phase = 1.0
                    self._pulse_growing = False
            else:
                self._pulse_phase -= step
                if self._pulse_phase <= 0.3:
                    self._pulse_phase = 0.3
                    self._pulse_growing = True
            self._keymap_redraw()
        elif self._keymap_dirty:
            self._keymap_redraw()
        else:
            self._pulse_phase = 0.0
            self._pulse_growing = True
        self.after(80, self._pulse_tick)

    def _keymap_hotspots(self) -> Dict[str, int]:
        try:
            prof = self._current_profile()
        except Exception:
            return {}

        ui = prof.get("ui", {})
        if not isinstance(ui, dict):
            return {}
        hs = ui.get("hotspots", {})
        if not isinstance(hs, dict):
            return {}

        out: Dict[str, int] = {}
        for k, v in hs.items():
            if not isinstance(k, str) or not k:
                continue
            try:
                out[k] = int(v)
            except Exception:
                continue
        return out

    def _keymap_refresh_visuals(self) -> None:
        if not self._keymap_canvas:
            return
        self._invalidate_caches()
        # Force full rebuild by clearing canvas items cache
        self._keymap_canvas_items = {}
        self._keymap_redraw()
        self._kbd_redraw()

    def _mapping_load_from_profile(self, in_id: int) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}

        entry = mappings.get(str(in_id))
        if not isinstance(entry, dict):
            self._mapping_type.set("passthrough")
            self._mapping_remap_to.set(str(in_id if in_id < 128 else (in_id - 128)))
            self._mapping_macro_id.set("")
            return

        et = entry.get("type")
        if et == "disable":
            self._mapping_type.set("disable")
        elif et == "remap":
            self._mapping_type.set("remap")
            to = entry.get("to")
            self._mapping_remap_to.set(str(int(to)) if isinstance(to, (int, float)) else "0")
        elif et == "remap_hid":
            self._mapping_type.set("remap_hid")
            mod = entry.get("mod", 0)
            kc = entry.get("keycode", 0)
            self._mapping_remap_to.set(f"0x{kc:02X}" if isinstance(kc, int) else "0")
        elif et == "macro":
            self._mapping_type.set("macro")
            mid = entry.get("id")
            self._mapping_macro_id.set(str(mid) if isinstance(mid, str) else "")
        elif et == "tap_hold":
            self._mapping_type.set("tap_hold")
            hold = entry.get("hold", {})
            if isinstance(hold, dict):
                kc = hold.get("keycode", 0)
                self._mapping_remap_to.set(f"0x{kc:02X}" if isinstance(kc, int) else "0")
        elif et == "double_tap":
            self._mapping_type.set("double_tap")
            single = entry.get("single", {})
            double = entry.get("double", {})
            if isinstance(single, dict):
                kc = single.get("keycode", 0)
                self._mapping_remap_to.set(f"0x{kc:02X}" if isinstance(kc, int) else "0")
            if isinstance(double, dict):
                kc = double.get("keycode", 0)
                self._mapping_macro_id.set(f"0x{kc:02X}" if isinstance(kc, int) else "0")
        else:
            self._mapping_type.set("passthrough")

    def _build_keymap_editor(self) -> None:
        parent = getattr(self, "_controller_center", self.tab_controller)

        # ── Compact toolbar ──
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, padx=8, pady=(0, 2))

        # Popup trigger buttons (open on-demand panels)
        ttk.Button(toolbar, text="Heist Plan\u2026", command=lambda: self._mapping_popup.toggle(), width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Masks\u2026", command=lambda: self._layers_popup.toggle(), width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Chords\u2026", command=lambda: self._chords_popup.toggle(), width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Keyboard\u2026", command=lambda: self._keyboard_popup.toggle(), width=10).pack(side=tk.LEFT, padx=2)

        sep = ttk.Separator(toolbar, orient=tk.VERTICAL)
        sep.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # Compact action buttons
        ttk.Button(toolbar, text="Setup", command=self._open_guided_wizard).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Quick Job", command=self._apply_smart_defaults).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Case", command=self._keymap_begin_learn).pack(side=tk.LEFT, padx=2)
        self._bind_btn = ttk.Button(toolbar, text="Steal", command=self._keymap_begin_bind)
        self._bind_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clear", command=self._keymap_clear_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Reset", command=self._keymap_reset_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Restore\u2026", command=self._restore_last_good_profile).pack(side=tk.LEFT, padx=2)

        # Right side: colour picker, search + sandbox
        ttk.Checkbutton(
            toolbar, text="Practice Run", variable=self._sandbox_active,
            command=self._toggle_sandbox,
        ).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Entry(toolbar, textvariable=self._search_var, width=14).pack(side=tk.RIGHT, padx=2)
        self._search_var.trace_add("write", self._on_search_changed)
        ttk.Label(toolbar, text="Search:").pack(side=tk.RIGHT)

        # Overlay colour dropdown
        color_combo = ttk.Combobox(
            toolbar, textvariable=self._overlay_color_var,
            values=RAINBOW_NAMES, width=8, state="readonly",
        )
        color_combo.pack(side=tk.RIGHT, padx=2)
        ttk.Label(toolbar, text="\U0001f3a8").pack(side=tk.RIGHT)

        # ── Status line ──
        ttk.Label(parent, textvariable=self._keymap_status, wraplength=700,
                  justify="left").pack(fill=tk.X, padx=8)

        # ── Canvas: DOMINANT — fills all remaining space ──
        self._keymap_canvas = tk.Canvas(parent, highlightthickness=1)
        self._keymap_canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 4))
        try:
            self._keymap_canvas.configure(bg=self._colors["panel2"], highlightbackground=self._colors["border"])
        except Exception:
            pass

        self._keymap_canvas.bind("<Button-1>", self._keymap_on_click)
        self._keymap_canvas.bind("<Button-3>", self._keymap_on_right_click)
        self._keymap_canvas.bind("<Configure>", lambda _e: self._keymap_redraw())
        self._keymap_canvas.bind("<Motion>", self._keymap_on_motion)

        # Bind keyboard events for press-to-bind.
        self.bind("<KeyPress>", self._on_keypress_bind)

        self._keymap_img_paths = self._find_joycons_png_variants()
        self._set_keymap_image_state()
        self._keymap_redraw()

        # ── Visible layer tab bar (sketch-style, below canvas) ──
        self._layer_tab_bar = tk.Frame(parent, bg=self._colors.get("panel2", "#e2d0a8"))
        self._layer_tab_bar.pack(fill=tk.X, padx=8, pady=(0, 2))
        self._layer_tab_buttons: List[tk.Label] = []
        self._build_layer_tab_bar()

        # ── Conflict bar (compact, below layer tabs) ──
        self._conflict_var = tk.StringVar(value="")
        conflict_bar = ttk.Frame(parent)
        conflict_bar.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._conflict_label = ttk.Label(conflict_bar, textvariable=self._conflict_var,
                                          foreground=self._colors.get("danger", "red"))
        self._conflict_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._conflict_fix_btn = ttk.Button(conflict_bar, text="Auto-fix", command=self._conflict_auto_fix)
        self._conflict_fix_btn.pack(side=tk.LEFT, padx=(4, 0))
        self._conflict_fix_btn.pack_forget()  # hidden by default

        # ── Build popup panels ──
        self._build_mapping_popup()
        self._build_layers_popup()
        self._build_chords_popup()
        self._build_keyboard_popup()

    # ------------------------------------------------------------------
    # Keymap editor popup panels (opened via toolbar buttons)
    # ------------------------------------------------------------------

    def _build_mapping_popup(self) -> None:
        """Build the mapping controls popup (input key_id, type, remap, macro)."""
        self._mapping_popup = SketchPopup(
            self, title="Heist Plan", colors=self._colors,
            typo=self._typo, width=520, height=120)
        body = self._mapping_popup.body

        r = ttk.Frame(body)
        r.pack(fill=tk.X, pady=(4, 4))

        ttk.Label(r, text="Input key_id:").pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self._mapping_key_id, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r, text="Type:").pack(side=tk.LEFT)
        ttk.Combobox(
            r, textvariable=self._mapping_type,
            values=["passthrough", "disable", "remap", "remap_hid", "macro", "tap_hold", "double_tap"],
            width=14, state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 12))

        r2 = ttk.Frame(body)
        r2.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(r2, text="Remap to:").pack(side=tk.LEFT)
        ttk.Entry(r2, textvariable=self._mapping_remap_to, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r2, text="Trick id:").pack(side=tk.LEFT)
        ttk.Entry(r2, textvariable=self._mapping_macro_id, width=14).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Button(r2, text="Execute", command=self._mapping_apply).pack(side=tk.LEFT)

    def _build_layers_popup(self) -> None:
        """Build the layers popup (layer selector, config, stack summary)."""
        self._layers_popup = SketchPopup(
            self, title="Masks", colors=self._colors,
            typo=self._typo, width=560, height=260)
        body = self._layers_popup.body

        # Layer selector
        layer_row = ttk.Frame(body)
        layer_row.pack(fill=tk.X, pady=(4, 4))
        ttk.Radiobutton(layer_row, text="Base", variable=self._layer_edit_index, value=-1,
                        command=self._keymap_redraw).pack(side=tk.LEFT)
        for li in range(4):
            ttk.Radiobutton(layer_row, text=f"Mask {li+1}", variable=self._layer_edit_index, value=li,
                            command=self._keymap_redraw).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(layer_row, text="Add", command=self._layer_add).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(layer_row, text="Remove", command=self._layer_remove).pack(side=tk.LEFT, padx=(6, 0))

        # Layer activation config
        self._layer_cfg_frame = ttk.Frame(body)
        self._layer_cfg_frame.pack(fill=tk.X, pady=(0, 4))
        self._advanced_widgets.append(self._layer_cfg_frame)
        ttk.Label(self._layer_cfg_frame, text="Activation key_id:").pack(side=tk.LEFT)
        self._layer_key_id_var = tk.StringVar(value="")
        ttk.Entry(self._layer_cfg_frame, textvariable=self._layer_key_id_var, width=6).pack(side=tk.LEFT, padx=(4, 8))
        self._layer_mode_var = tk.StringVar(value="hold")
        ttk.Label(self._layer_cfg_frame, text="Mode:").pack(side=tk.LEFT)
        ttk.Combobox(self._layer_cfg_frame, textvariable=self._layer_mode_var,
                     values=["hold", "toggle"], width=8, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(self._layer_cfg_frame, text="Name:").pack(side=tk.LEFT)
        self._layer_name_var = tk.StringVar(value="")
        ttk.Entry(self._layer_cfg_frame, textvariable=self._layer_name_var, width=14).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(self._layer_cfg_frame, text="Execute", command=self._layer_apply_config).pack(side=tk.LEFT)

        # Visual layer stack summary
        self._layer_stack_frame = ttk.Frame(body)
        self._layer_stack_frame.pack(fill=tk.X, pady=(0, 4))
        self._layer_stack_labels: list[ttk.Label] = []
        self._advanced_widgets.append(self._layer_stack_frame)
        self._rebuild_layer_stack()

    def _build_chords_popup(self) -> None:
        """Build the chords popup (multi-button combos)."""
        self._chords_popup = SketchPopup(
            self, title="Chords (multi-button combos)", colors=self._colors,
            typo=self._typo, width=500, height=200)
        body = self._chords_popup.body

        ttk.Label(
            body,
            text="Define combos: press multiple controller buttons simultaneously for a different action.",
            wraplength=460, justify="left",
        ).pack(anchor="w", pady=(4, 4))

        chord_row = ttk.Frame(body)
        chord_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(chord_row, text="Keys (comma-sep key_ids):").pack(side=tk.LEFT)
        self._chord_keys_var = tk.StringVar(value="")
        ttk.Entry(chord_row, textvariable=self._chord_keys_var, width=16).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(chord_row, text="Output keycode:").pack(side=tk.LEFT)
        self._chord_output_var = tk.StringVar(value="")
        ttk.Entry(chord_row, textvariable=self._chord_output_var, width=8).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(chord_row, text="Add", command=self._chord_add).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(chord_row, text="Clear all", command=self._chord_clear).pack(side=tk.LEFT, padx=(4, 0))

        self._chord_list_var = tk.StringVar(value="(none)")
        ttk.Label(body, textvariable=self._chord_list_var, wraplength=460, justify="left").pack(
            anchor="w", pady=(0, 4))

    def _build_keyboard_popup(self) -> None:
        """Build the keyboard preview popup (shows which PC keys are mapped)."""
        self._keyboard_popup = SketchPopup(
            self, title="Keyboard Output Preview", colors=self._colors,
            typo=self._typo, width=800, height=320)
        body = self._keyboard_popup.body

        self._kbd_canvas = tk.Canvas(body, height=260, highlightthickness=1)
        self._kbd_canvas.pack(fill=tk.BOTH, expand=True)
        try:
            self._kbd_canvas.configure(
                bg=self._colors["panel2"],
                highlightbackground=self._colors["border"],
            )
        except Exception:
            pass
        self._kbd_canvas.bind("<Configure>", lambda _e: self._kbd_redraw())
        self._load_keyboard_image()
        self._kbd_redraw()

    def _get_mapping_output(self, key_id: int) -> Optional[Tuple[int, int]]:
        """Return the (mod, keycode) output for a key_id, or None if passthrough/default."""
        try:
            prof = self._current_profile()
        except Exception:
            return None
        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            return None
        entry = mappings.get(str(key_id))
        if not isinstance(entry, dict):
            # Passthrough — use default keymap
            return hid_keycodes.DEFAULT_KEYMAP.get(key_id)
        et = entry.get("type")
        if et == "remap_hid":
            mod = entry.get("mod", 0)
            kc = entry.get("keycode", 0)
            if isinstance(mod, int) and isinstance(kc, int):
                return (mod, kc)
        elif et == "remap":
            to = entry.get("to")
            if isinstance(to, int):
                return hid_keycodes.DEFAULT_KEYMAP.get(to)
        elif et == "disable":
            return None
        elif et == "double_tap":
            # Show single-tap output for keyboard preview
            single = entry.get("single", {})
            if isinstance(single, dict):
                mod = single.get("mod", 0)
                kc = single.get("keycode", 0)
                if isinstance(mod, int) and isinstance(kc, int):
                    return (mod, kc)
        return None

    def _invalidate_caches(self) -> None:
        """Invalidate all profile-dependent caches. Call after any profile/mapping change."""
        self._conflict_cache = None
        self._conflict_hotspot_cache = None
        self._key_id_to_hotspot_cache = None

    def _get_hotspot_name(self, key_id: int) -> str:
        """Fast cached reverse lookup: key_id → hotspot name."""
        if self._key_id_to_hotspot_cache is None:
            hs = self._keymap_hotspots()
            self._key_id_to_hotspot_cache = {v: k for k, v in hs.items()}
        return self._key_id_to_hotspot_cache.get(key_id, f"key_id={key_id}")

    def _detect_conflicts(self) -> Dict[str, List[str]]:
        """Return a dict mapping output key name → list of hotspot names that produce it. Cached."""
        if self._conflict_cache is not None:
            return self._conflict_cache
        hs_bindings = self._keymap_hotspots()
        output_map: Dict[str, List[str]] = {}
        for name, key_id in hs_bindings.items():
            out = self._get_mapping_output(key_id)
            if out is None:
                continue
            label = hid_keycodes.hid_to_name(out[0], out[1])
            output_map.setdefault(label, []).append(name)
        self._conflict_cache = {k: v for k, v in output_map.items() if len(v) > 1}
        # Build conflict hotspot set
        conflict_hs: set[str] = set()
        for names in self._conflict_cache.values():
            conflict_hs.update(names)
        self._conflict_hotspot_cache = conflict_hs
        return self._conflict_cache

    def _keymap_redraw(self) -> None:
        t0 = time.monotonic() if self._perf_enabled else 0.0
        c = self._keymap_canvas
        if not c:
            return

        self._keymap_dirty = False

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        # Determine if a full rebuild is needed (layout change) or just a color/pulse update.
        need_full = (w, h) != self._keymap_last_canvas_size or not self._keymap_canvas_items

        if need_full:
            c.delete("all")
            self._keymap_canvas_items = {}
            self._keymap_bg_item = None
            self._keymap_last_canvas_size = (w, h)

        if not self._keymap_pil_base and not self._keymap_img_base:
            state_name = self._keymap_img_state
            msg = (
                f"Joy-Con image for state '{state_name}' not found"
                if not self._keymap_img_path
                else f"Failed to load Joy-Con image for state '{state_name}'"
            )
            if need_full:
                c.create_text(w // 2, h // 2, text=msg, fill=self._colors.get("muted", "#666"))
            self._keymap_hotspot_px = {}
            return

        # Composite path (Pillow available): fuse overlay onto background.
        if self._keymap_pil_base is not None:
            if need_full:
                if getattr(self, "_keymap_is_composite", False):
                    # Pre-baked composite: just scale to fit canvas.
                    photo, ox, oy, img_w, img_h = self._scale_composite_to_canvas(
                        self._keymap_pil_base, w, h,
                    )
                else:
                    # Raw overlay: fuse onto background at runtime.
                    photo, ox, oy, img_w, img_h = self._composite_bg_overlay(
                        self._keymap_pil_base, w, h,
                    )
                self._keymap_img_scaled = photo  # prevent GC
                self._keymap_bg_item = c.create_image(0, 0, image=photo, anchor="nw")
                self._keymap_overlay_ox = ox
                self._keymap_overlay_oy = oy
                self._keymap_overlay_w = img_w
                self._keymap_overlay_h = img_h
            ox = getattr(self, "_keymap_overlay_ox", 0)
            oy = getattr(self, "_keymap_overlay_oy", 0)
            img_w = getattr(self, "_keymap_overlay_w", w)
            img_h = getattr(self, "_keymap_overlay_h", h)
        else:
            # Legacy fallback: tk.PhotoImage overlay without compositing.
            base_w = self._keymap_img_base.width()
            base_h = self._keymap_img_base.height()
            factor = max(1, int(math.ceil(base_w / max(1, w))), int(math.ceil(base_h / max(1, h))))

            if need_full or factor != self._keymap_last_scale_factor:
                self._keymap_last_scale_factor = factor
                try:
                    self._keymap_img_scaled = self._keymap_img_base.subsample(factor, factor)
                except Exception:
                    self._keymap_img_scaled = self._keymap_img_base

            img_w = self._keymap_img_scaled.width()
            img_h = self._keymap_img_scaled.height()
            ox = (w - img_w) / 2.0
            oy = (h - img_h) / 2.0

            if need_full:
                self._keymap_bg_item = c.create_image(ox, oy, image=self._keymap_img_scaled, anchor="nw")

        hs_bindings = self._keymap_hotspots()
        conflicts = self._detect_conflicts()
        conflict_hotspots = self._conflict_hotspot_cache or set()

        # Update conflict label and fix button (only on full rebuild to avoid flicker)
        if need_full and hasattr(self, "_conflict_var"):
            if conflicts:
                parts = [f"{key}: {', '.join(names)}" for key, names in conflicts.items()]
                self._conflict_var.set("Conflicts: " + "; ".join(parts))
                try:
                    self._conflict_fix_btn.pack(side=tk.LEFT, padx=(4, 0))
                except Exception:
                    pass
            else:
                self._conflict_var.set("")
                try:
                    self._conflict_fix_btn.pack_forget()
                except Exception:
                    pass

        self._keymap_hotspot_px = {}
        radius = max(14, int(min(img_w, img_h) * 0.02))

        for name, nx, ny in KEYMAP_HOTSPOTS:
            px = ox + nx * img_w
            py = oy + ny * img_h
            self._keymap_hotspot_px[name] = (px, py)

            selected = (name == self._keymap_selected_name)
            bound_key_id = hs_bindings.get(name)
            is_active = bound_key_id is not None and bound_key_id in self._active_key_ids
            is_conflict = name in conflict_hotspots
            has_mapping = False
            mapping_label = ""

            if bound_key_id is not None:
                try:
                    prof = self._current_profile()
                    entry = prof.get("mappings", {}).get(str(bound_key_id))
                    if isinstance(entry, dict):
                        has_mapping = True
                        et = entry.get("type", "")
                        if et == "remap_hid":
                            mapping_label = hid_keycodes.hid_to_name(
                                entry.get("mod", 0), entry.get("keycode", 0)
                            )
                        elif et == "remap":
                            to = entry.get("to", 0)
                            dk = hid_keycodes.DEFAULT_KEYMAP.get(to)
                            mapping_label = hid_keycodes.hid_to_name(dk[0], dk[1]) if dk else f"→{to}"
                        elif et == "disable":
                            mapping_label = "OFF"
                        elif et == "macro":
                            mapping_label = f"M:{entry.get('id', '?')}"
                        elif et == "tap_hold":
                            hold = entry.get("hold", {})
                            hkc = hold.get("keycode", 0) if isinstance(hold, dict) else 0
                            hmod = hold.get("mod", 0) if isinstance(hold, dict) else 0
                            mapping_label = f"T/H:{hid_keycodes.hid_to_name(hmod, hkc)}"
                        elif et == "double_tap":
                            s = entry.get("single", {})
                            d = entry.get("double", {})
                            skc = s.get("keycode", 0) if isinstance(s, dict) else 0
                            smod = s.get("mod", 0) if isinstance(s, dict) else 0
                            dkc = d.get("keycode", 0) if isinstance(d, dict) else 0
                            dmod = d.get("mod", 0) if isinstance(d, dict) else 0
                            mapping_label = f"DT:{hid_keycodes.hid_to_name(smod, skc)}/{hid_keycodes.hid_to_name(dmod, dkc)}"
                    else:
                        # Passthrough
                        dk = hid_keycodes.DEFAULT_KEYMAP.get(bound_key_id)
                        if dk:
                            mapping_label = hid_keycodes.hid_to_name(dk[0], dk[1])
                except Exception:
                    pass

            # Color coding
            if is_active:
                base_active = self._colors.get("accent2", "#3a8a5c")
                bright = _blend_hex(base_active, "#ffffff", 0.4)
                fill = _blend_hex(base_active, bright, self._pulse_phase)
                outline = fill
            elif is_conflict:
                fill = self._colors.get("danger", "#c84848")
                outline = self._colors.get("danger", "#c84848")
            elif selected:
                fill = self._colors.get("accent", "#4a7cc8")
                outline = self._colors.get("accent", "#4a7cc8")
            elif has_mapping:
                fill = self._overlay_hex()
                outline = self._overlay_hex()
            else:
                fill = self._colors.get("panel", "#fff")
                outline = self._colors.get("border", "#333")

            text_col = _contrast_on(fill)
            label = name
            if mapping_label:
                label = f"{name}\n{mapping_label}"

            existing = self._keymap_canvas_items.get(name)
            if existing and not need_full:
                # Update in-place: recolor oval + pulse ring + text
                oval_id, text_id, search_id, pulse_id = existing
                c.itemconfigure(oval_id, outline=outline, fill=fill)
                c.itemconfigure(text_id, text=label, fill=text_col)

                # Update pulse ring
                if is_active:
                    pulse_r = radius + int(6 * self._pulse_phase)
                    pulse_col = _blend_hex(fill, self._colors.get("bg", "#e8d8b8"), 0.5)
                    if pulse_id:
                        c.coords(pulse_id, px - pulse_r, py - pulse_r, px + pulse_r, py + pulse_r)
                        c.itemconfigure(pulse_id, outline=pulse_col, state="normal")
                    else:
                        pulse_id = c.create_oval(
                            px - pulse_r, py - pulse_r, px + pulse_r, py + pulse_r,
                            outline=pulse_col, width=2, dash=(4, 4),
                        )
                        self._keymap_canvas_items[name] = (oval_id, text_id, search_id, pulse_id)
                elif pulse_id:
                    c.itemconfigure(pulse_id, state="hidden")

                # Search highlight
                is_search_match = name in self._search_matches
                if search_id:
                    c.itemconfigure(search_id, state="normal" if is_search_match else "hidden")
            else:
                # Full create
                is_search_match = name in self._search_matches
                search_id = None
                if is_search_match:
                    sr = radius + 5
                    search_id = c.create_oval(
                        px - sr, py - sr, px + sr, py + sr,
                        outline=self._colors.get("accent", "#4a7cc8"), width=3, dash=(6, 2),
                    )

                oval_id = c.create_oval(
                    px - radius, py - radius, px + radius, py + radius,
                    outline=outline, width=2, fill=fill,
                )

                pulse_id = None
                if is_active:
                    pulse_r = radius + int(6 * self._pulse_phase)
                    pulse_col = _blend_hex(fill, self._colors.get("bg", "#e8d8b8"), 0.5)
                    pulse_id = c.create_oval(
                        px - pulse_r, py - pulse_r, px + pulse_r, py + pulse_r,
                        outline=pulse_col, width=2, dash=(4, 4),
                    )

                text_id = c.create_text(
                    px, py, text=label, fill=text_col,
                    font=(self._typo.get("font_family", "Segoe UI"), 8, "bold"),
                )

                self._keymap_canvas_items[name] = (oval_id, text_id, search_id, pulse_id)

        if self._perf_enabled:
            dt = time.monotonic() - t0
            self._perf_redraw_times.append(dt)
            if len(self._perf_redraw_times) > 60:
                self._perf_redraw_times = self._perf_redraw_times[-60:]

    def _keymap_pick_hotspot(self, x: float, y: float) -> Optional[str]:
        best: Optional[Tuple[str, float]] = None
        for name, (px, py) in self._keymap_hotspot_px.items():
            d2 = (px - x) ** 2 + (py - y) ** 2
            if best is None or d2 < best[1]:
                best = (name, d2)

        if not best:
            return None
        if best[1] > (40.0 * 40.0):
            return None
        return best[0]

    # ── Ghost labels on hover ──
    _hover_ghost_name: Optional[str] = None

    def _keymap_on_motion(self, e: tk.Event) -> None:
        """Show a ghost tooltip and hover glow near the hovered hotspot."""
        name = self._keymap_pick_hotspot(float(getattr(e, "x", 0)), float(getattr(e, "y", 0)))
        # Update hover glow ring (always, even if ghost name unchanged)
        self._update_hover_glow(name)
        if name == self._hover_ghost_name:
            return
        self._hover_ghost_name = name
        c = self._keymap_canvas
        c.delete("ghost_tip")
        if name is None:
            return
        pos = self._keymap_hotspot_px.get(name)
        if pos is None:
            return
        px, py = pos
        hs = self._keymap_hotspots()
        kid = hs.get(name)
        tip_parts = [name]
        if kid is not None:
            try:
                prof = self._current_profile()
                entry = prof.get("mappings", {}).get(str(kid))
                if isinstance(entry, dict):
                    et = entry.get("type", "")
                    if et == "remap_hid":
                        tip_parts.append(hid_keycodes.hid_to_name(entry.get("mod", 0), entry.get("keycode", 0)))
                    elif et == "disable":
                        tip_parts.append("Disabled")
                    elif et == "macro":
                        tip_parts.append(f"Macro {entry.get('id', '?')}")
                    elif et == "tap_hold":
                        tip_parts.append("Tap/Hold")
                    elif et == "double_tap":
                        tip_parts.append("Double-Tap")
                else:
                    dk = hid_keycodes.DEFAULT_KEYMAP.get(kid)
                    if dk:
                        tip_parts.append(hid_keycodes.hid_to_name(dk[0], dk[1]))
            except Exception:
                pass
        tip_text = " → ".join(tip_parts)
        c.create_text(
            px, py - 26, text=tip_text, tags="ghost_tip",
            fill=self._colors.get("muted", "#888"),
            font=(self._typo.get("font_family", "Segoe UI"), 7, "italic"),
        )

    def _keymap_on_click(self, e: tk.Event) -> None:
        name = self._keymap_pick_hotspot(float(getattr(e, "x", 0)), float(getattr(e, "y", 0)))
        if not name:
            return

        self._keymap_selected_name = name
        self._update_heist_tools(name)
        hs = self._keymap_hotspots()
        bound = hs.get(name)
        if bound is None:
            # No key_id → auto-enter learn mode (press controller button)
            self._keymap_learn_name = name
            self._mapping_key_id.set("")
            self._keymap_status.set(
                f"[{name}] Press the controller button now to case its key_id… (or right-click for options)"
            )
        else:
            # Has key_id → auto-enter press-to-bind mode (press keyboard key)
            self._bind_mode = True
            self._bind_hotspot = name
            self._mapping_key_id.set(str(bound))
            self._mapping_load_from_profile(int(bound))
            self._keymap_status.set(
                f"[{name}] Press a keyboard key to steal → key_id={bound}  (Escape to cancel, right-click for more)"
            )
            self._show_bind_overlay(name, int(bound))

        self._keymap_redraw()

    def _keymap_begin_learn(self) -> None:
        if not self._keymap_selected_name:
            self._keymap_status.set("Pick a target first.")
            return
        self._keymap_learn_name = self._keymap_selected_name
        self._keymap_status.set(f"Casing {self._keymap_selected_name}… press that controller button now.")

    def _keymap_on_right_click(self, e: tk.Event) -> None:
        """Show a context menu for the clicked hotspot."""
        name = self._keymap_pick_hotspot(float(getattr(e, "x", 0)), float(getattr(e, "y", 0)))
        if not name:
            return

        self._keymap_selected_name = name
        self._update_heist_tools(name)
        self._keymap_redraw()

        hs = self._keymap_hotspots()
        bound = hs.get(name)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label=f"Case key_id for {name}",
            command=lambda: self._keymap_context_learn(name),
        )
        if bound is not None:
            menu.add_command(
                label=f"Bind keyboard key → {name}",
                command=lambda: self._keymap_context_bind(name),
            )
            menu.add_command(
                label=f"What should {name} do?",
                command=lambda: self._show_intent_menu(name, bound),
            )
            menu.add_separator()
            menu.add_command(
                label=f"Explain {name} heist plan",
                command=lambda: self._show_explain_dialog(name),
            )
            menu.add_separator()
            menu.add_command(
                label=f"Reset {name} to passthrough",
                command=lambda: self._keymap_context_reset(name),
            )
            menu.add_command(
                label=f"Clear {name} steal",
                command=lambda: self._keymap_context_clear(name),
            )
            menu.add_command(
                label=f"Disable {name}",
                command=lambda: self._keymap_context_disable(name),
            )
            menu.add_separator()
            if name in self._locked_hotspots:
                menu.add_command(
                    label=f"Unlock {name}",
                    command=lambda: self._locked_hotspots.discard(name),
                )
            else:
                menu.add_command(
                    label=f"Lock {name} (prevent accidental changes)",
                    command=lambda: self._locked_hotspots.add(name),
                )

        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _keymap_context_learn(self, name: str) -> None:
        self._keymap_selected_name = name
        self._keymap_learn_name = name
        self._keymap_status.set(f"[{name}] Press the controller button now…")

    def _keymap_context_bind(self, name: str) -> None:
        hs = self._keymap_hotspots()
        key_id = hs.get(name)
        if key_id is None:
            return
        self._keymap_selected_name = name
        self._bind_mode = True
        self._bind_hotspot = name
        self._mapping_key_id.set(str(key_id))
        self._keymap_status.set(f"[{name}] Press a keyboard key to steal… (Escape to cancel)")
        self._show_bind_overlay(name, int(key_id))

    def _keymap_context_reset(self, name: str) -> None:
        if not self._check_lock_before_unbind(name, "reset to passthrough"):
            return
        self._keymap_selected_name = name
        self._keymap_reset_selected()

    def _keymap_context_clear(self, name: str) -> None:
        if not self._check_lock_before_unbind(name, "clear binding"):
            return
        self._keymap_selected_name = name
        self._keymap_clear_selected()

    def _keymap_context_disable(self, name: str) -> None:
        """Disable the selected hotspot's output."""
        if not self._check_lock_before_unbind(name, "disable"):
            return
        hs = self._keymap_hotspots()
        key_id = hs.get(name)
        if key_id is None:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings
        mappings[str(key_id)] = {"type": "disable"}
        self._set_profile_obj(prof)
        self._keymap_status.set(f"{name} disabled.")
        self._keymap_redraw()

    # ------------------------------------------------------------------
    # Chording
    # ------------------------------------------------------------------

    def _chord_add(self) -> None:
        """Add a chord definition to the profile."""
        keys_str = self._chord_keys_var.get().strip()
        output_str = self._chord_output_var.get().strip()
        if not keys_str or not output_str:
            messagebox.showerror("Missing fields", "Enter both key_ids and output keycode.")
            return

        try:
            keys = [int(k.strip()) for k in keys_str.split(",") if k.strip()]
        except ValueError:
            messagebox.showerror("Bad key_ids", "Key IDs must be comma-separated integers.")
            return

        if len(keys) < 2:
            messagebox.showerror("Too few keys", "A chord requires at least 2 keys.")
            return

        try:
            kc = int(output_str, 0)
        except ValueError:
            messagebox.showerror("Bad keycode", "Output must be a HID keycode (integer or 0xHH).")
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        chords = prof.setdefault("chords", [])
        if not isinstance(chords, list):
            chords = []
            prof["chords"] = chords

        chords.append({
            "keys": sorted(keys),
            "action": {"type": "remap_hid", "mod": 0, "keycode": kc},
        })
        self._set_profile_obj(prof)
        self._chord_refresh_display()
        self._log_line(f"[host] Added chord: {keys} → 0x{kc:02X}")

    def _chord_clear(self) -> None:
        """Remove all chord definitions."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        prof["chords"] = []
        self._set_profile_obj(prof)
        self._chord_refresh_display()
        self._log_line("[host] Cleared all chords")

    def _chord_refresh_display(self) -> None:
        """Update the chord list display."""
        try:
            prof = self._current_profile()
        except Exception:
            self._chord_list_var.set("(none)")
            return

        chords = prof.get("chords", [])
        if not isinstance(chords, list) or not chords:
            self._chord_list_var.set("(none)")
            return

        parts = []
        for ch in chords:
            keys = ch.get("keys", [])
            action = ch.get("action", {})
            kc = action.get("keycode", 0)
            mod = action.get("mod", 0)
            key_names = [str(k) for k in keys]
            out_name = hid_keycodes.hid_to_name(mod, kc)
            parts.append(f"[{'+'.join(key_names)}] → {out_name}")

        self._chord_list_var.set("  |  ".join(parts))

    # ------------------------------------------------------------------
    # Conflict auto-fix
    # ------------------------------------------------------------------

    def _conflict_auto_fix(self) -> None:
        """Resolve duplicate output bindings by keeping only the first mapping for each output."""
        conflicts = self._detect_conflicts()
        if not conflicts:
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            return

        hs_bindings = self._keymap_hotspots()
        removed = []
        for _output_key, hotspot_names in conflicts.items():
            # Keep the first, remove the rest
            for name in hotspot_names[1:]:
                key_id = hs_bindings.get(name)
                if key_id is not None and str(key_id) in mappings:
                    del mappings[str(key_id)]
                    removed.append(name)

        self._set_profile_obj(prof)
        self._keymap_redraw()
        self._log_line(f"[host] Auto-fix: cleared duplicate mappings for {', '.join(removed)}")

    def _keymap_begin_bind(self) -> None:
        """Start press-to-bind: wait for a keyboard key press to map to the selected hotspot."""
        if not self._keymap_selected_name:
            self._keymap_status.set("Pick a target first.")
            return
        hs = self._keymap_hotspots()
        bound_key_id = hs.get(self._keymap_selected_name)
        if bound_key_id is None:
            self._keymap_status.set(f"Use Case first to assign a key_id to {self._keymap_selected_name}.")
            return
        self._bind_mode = True
        self._bind_hotspot = self._keymap_selected_name
        self._keymap_status.set(f"Press a keyboard key to steal {self._keymap_selected_name}… (Escape to cancel)")
        self._show_bind_overlay(self._keymap_selected_name, int(bound_key_id))

    def _on_keypress_bind(self, event: tk.Event) -> None:
        """Handle keyboard key press for press-to-bind mode."""
        if not self._bind_mode:
            return

        keysym = getattr(event, "keysym", "")
        if keysym == "Escape":
            self._bind_mode = False
            self._bind_hotspot = None
            self._hide_bind_overlay()
            self._keymap_status.set("Heist cancelled.")
            return

        hid = hid_keycodes.keysym_to_hid(keysym)
        if hid is None:
            self._keymap_status.set(f"Unrecognised key: {keysym}. Try another key, or Escape to cancel.")
            return

        mod, keycode = hid
        hotspot = self._bind_hotspot
        self._bind_mode = False
        self._bind_hotspot = None
        self._hide_bind_overlay()

        if not hotspot:
            return

        # Get the key_id for this hotspot
        hs = self._keymap_hotspots()
        key_id = hs.get(hotspot)
        if key_id is None:
            return

        # Apply remap_hid mapping
        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings

        mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": keycode}
        self._set_profile_obj(prof, undo_label=f"bind {hotspot}")

        key_name = hid_keycodes.hid_to_name(mod, keycode)
        self._keymap_status.set(f"STOLEN · {hotspot} → {key_name}")
        self._mapping_key_id.set(str(key_id))
        self._mapping_type.set("remap_hid")
        self._keymap_redraw()
        self._kbd_redraw()
        self._play_sound("bind")
        self._start_ink_stamp(hotspot, key_name)
        self._update_heist_tools(hotspot)

    def _keymap_reset_selected(self) -> None:
        """Remove the mapping for the currently selected hotspot (revert to passthrough)."""
        if not self._keymap_selected_name:
            self._keymap_status.set("Pick a target first.")
            return
        hs = self._keymap_hotspots()
        key_id = hs.get(self._keymap_selected_name)
        if key_id is None:
            self._keymap_status.set(f"{self._keymap_selected_name} has no key_id bound.")
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        mappings = prof.get("mappings", {})
        if isinstance(mappings, dict):
            mappings.pop(str(key_id), None)
        self._set_profile_obj(prof)
        self._mapping_type.set("passthrough")
        self._keymap_status.set(f"Reset {self._keymap_selected_name} to passthrough.")
        self._keymap_redraw()

    def _profile_rename(self) -> None:
        """Rename the current profile using the Name entry field."""
        new_name = self._profile_name_var.get().strip()
        if not new_name:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        prof["name"] = new_name
        self._set_profile_obj(prof)
        self._log_line(f"[host] Profile renamed to '{new_name}'")

    def _profile_duplicate(self) -> None:
        """Duplicate the current profile with a new name and load it into the editor."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        import copy as _copy
        dup = _copy.deepcopy(prof)
        old_name = dup.get("name", "default")
        dup["name"] = f"{old_name} (copy)"
        self._set_profile_obj(dup)
        self._profile_name_var.set(dup["name"])
        self._log_line(f"[host] Duplicated profile '{old_name}' → '{dup['name']}'")

    def _profile_reset_defaults(self) -> None:
        """Reset the profile to a clean default state (keeps name)."""
        try:
            prof = self._current_profile()
        except Exception:
            prof = {}
        name = prof.get("name", "default")
        fresh = _ensure_profile_defaults({"name": name})
        self._set_profile_obj(fresh)
        self._profile_name_var.set(name)
        self._keymap_redraw()
        self._log_line(f"[host] Profile '{name}' reset to defaults.")

    # ------------------------------------------------------------------
    # Profile slot quick-select
    # ------------------------------------------------------------------

    def _slot_select(self, idx: int) -> None:
        """Select a slot, read its profile from the device, and load it."""
        self.slot_var.set(str(idx))
        # Highlight the active slot button
        for i, btn in enumerate(self._slot_buttons):
            try:
                if i == idx:
                    btn.configure(style="Primary.TButton")
                else:
                    btn.configure(style="TButton")
            except Exception:
                pass
        self._cmd_read_profile()
        self._log_line(f"[host] Selected slot {idx}")
        self._refresh_loadout_cards()

    def _slot_read_all(self) -> None:
        """Read profile names from all 4 slots (sends 4 read commands)."""
        for i in range(4):
            self._send_cmd({"cmd": "read_profile", "slot": i})

    def _slot_update_name(self, slot: int, name: str) -> None:
        """Update the slot button label with the profile name."""
        if 0 <= slot < len(self._slot_name_vars):
            display = name[:14] if name else f"Slot {slot}"
            self._slot_name_vars[slot].set(f"{slot}: {display}")

    # ------------------------------------------------------------------
    # Per-app auto-profile switching
    # ------------------------------------------------------------------

    def _on_app_switch(self, slot: int) -> None:
        """Called from app-switcher background thread when a profile switch is needed."""
        # Schedule on the main thread.
        self.after(0, lambda: self._do_app_switch(slot))

    def _do_app_switch(self, slot: int) -> None:
        if not self.client.connected:
            return
        self._send_cmd({"cmd": "set_active_profile", "slot": slot})
        self.slot_var.set(str(slot))
        self._log_line(f"[auto-switch] Active app changed -> slot {slot}")

    def _toggle_app_switcher(self) -> None:
        enabled = self._app_switcher_enabled.get()
        self._app_switcher.enabled = enabled
        state = "enabled" if enabled else "disabled"
        self._log_line(f"[host] App auto-switching {state}")

    def _refresh_app_switch_list(self) -> None:
        lb = getattr(self, "_app_switch_list", None)
        if lb is None:
            return
        lb.delete(0, tk.END)
        for rule in self._app_switcher_rules:
            exe = rule.get("exe", "?")
            slot = rule.get("slot", 0)
            lb.insert(tk.END, f"{exe}  ->  slot {slot}")

    def _app_switcher_add_rule(self) -> None:
        exe = simpledialog.askstring("Add rule", "Executable name (e.g. game.exe):", parent=self)
        if not exe:
            return
        slot = simpledialog.askinteger("Add rule", "Profile slot (0-3):", parent=self, minvalue=0, maxvalue=3)
        if slot is None:
            return
        self._app_switcher_rules.append({"exe": exe.strip().lower(), "slot": slot})
        self._app_switcher.set_rules(self._app_switcher_rules)
        app_switcher_mod.save_rules(self._app_switcher_rules)
        self._refresh_app_switch_list()

    def _app_switcher_remove_rule(self) -> None:
        lb = getattr(self, "_app_switch_list", None)
        if lb is None:
            return
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._app_switcher_rules):
            self._app_switcher_rules.pop(idx)
            self._app_switcher.set_rules(self._app_switcher_rules)
            app_switcher_mod.save_rules(self._app_switcher_rules)
            self._refresh_app_switch_list()

    def _app_switcher_detect(self) -> None:
        """Detect the currently active application and show it."""
        try:
            exe = app_switcher_mod._get_foreground_exe()
            title = app_switcher_mod._get_foreground_title()
        except Exception:
            exe = None
            title = None
        msg = f"Active: {exe or '(unknown)'}"
        if title:
            msg += f"\nTitle: {title}"
        messagebox.showinfo("Active Application", msg, parent=self)

    # ------------------------------------------------------------------
    # Safe mode (reset active slot to defaults on device)
    # ------------------------------------------------------------------

    def _cmd_safe_mode(self) -> None:
        """Reset the active slot to a clean default profile and activate it."""
        confirm = messagebox.askyesno(
            "Safe mode",
            "This will overwrite the current slot with a clean default loadout "
            "and set it as active on the device.\n\n"
            "Use this if your controls become unusable.\n\n"
            "Continue?",
        )
        if not confirm:
            return

        slot = int(self.slot_var.get())
        fresh = _ensure_profile_defaults({"name": f"safe-default-{slot}"})
        self._set_profile_obj(fresh)
        self._send_cmd({"cmd": "write_profile", "slot": slot, "profile": fresh})
        self._send_cmd({"cmd": "set_active_profile", "slot": slot})
        self._log_line(f"[host] Safe mode: slot {slot} reset to defaults and activated \u2014 clean loadout")

    def _layer_add(self) -> None:
        """Add a new layer to the profile."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.setdefault("layers", [])
        if not isinstance(layers, list):
            layers = []
            prof["layers"] = layers
        if len(layers) >= 4:
            messagebox.showinfo("Mask limit", "Maximum 4 masks supported.")
            return
        idx = len(layers)
        layers.append({
            "name": f"layer{idx + 1}",
            "key_id": 0,
            "mode": "hold",
            "mappings": {},
        })
        self._set_profile_obj(prof)
        self._layer_edit_index.set(idx)
        self._keymap_redraw()
        self._rebuild_layer_stack()
        self._log_line(f"[host] Added mask {idx + 1}")

    def _layer_remove(self) -> None:
        """Remove the currently selected layer."""
        idx = self._layer_edit_index.get()
        if idx < 0:
            messagebox.showinfo("Select mask", "Select a mask (not Base) to remove.")
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.get("layers", [])
        if not isinstance(layers, list) or idx >= len(layers):
            return
        removed = layers.pop(idx)
        self._set_profile_obj(prof)
        self._layer_edit_index.set(-1)
        self._keymap_redraw()
        self._rebuild_layer_stack()
        self._log_line(f"[host] Removed mask '{removed.get('name', idx)}'")

    def _layer_apply_config(self) -> None:
        """Apply the layer configuration (activation key_id, mode, name) from the UI."""
        idx = self._layer_edit_index.get()
        if idx < 0:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.get("layers", [])
        if not isinstance(layers, list) or idx >= len(layers):
            return
        try:
            key_id = int(self._layer_key_id_var.get())
        except ValueError:
            messagebox.showerror("Bad key_id", "Activation key_id must be an integer.")
            return
        layers[idx]["key_id"] = key_id
        layers[idx]["mode"] = self._layer_mode_var.get() or "hold"
        name = self._layer_name_var.get().strip()
        if name:
            layers[idx]["name"] = name
        self._set_profile_obj(prof)
        self._log_line(f"[host] Mask {idx + 1} config updated")

    def _rebuild_layer_stack(self) -> None:
        """Rebuild the visual layer stack summary (shows mapping counts per layer)."""
        frame = getattr(self, "_layer_stack_frame", None)
        if frame is None:
            return
        for lbl in self._layer_stack_labels:
            lbl.destroy()
        self._layer_stack_labels.clear()

        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.get("layers", [])
        if not isinstance(layers, list):
            layers = []
        base_count = len(prof.get("mappings", {}))

        desc = f"  Base  ({base_count} heist plans)"
        lbl = ttk.Label(frame, text=desc, relief="ridge", padding=(6, 2))
        lbl.pack(side=tk.LEFT, padx=(0, 4))
        self._layer_stack_labels.append(lbl)

        for i, layer in enumerate(layers):
            name = layer.get("name", f"layer{i+1}")
            mode = layer.get("mode", "hold")
            cnt = len(layer.get("mappings", {}))
            txt = f"  {name} ({mode}, {cnt} overrides)  "
            lbl = ttk.Label(frame, text=txt, relief="groove", padding=(6, 2))
            lbl.pack(side=tk.LEFT, padx=(0, 4))
            self._layer_stack_labels.append(lbl)

        # Also refresh the visible layer tab bar below the canvas
        self._build_layer_tab_bar()

    def _build_layer_tab_bar(self) -> None:
        """Build visible sketch-style layer tab buttons below the controller canvas."""
        bar = getattr(self, "_layer_tab_bar", None)
        if bar is None:
            return

        # Clear old tabs
        for btn in self._layer_tab_buttons:
            btn.destroy()
        self._layer_tab_buttons.clear()

        colors = self._colors
        typo = self._typo
        font_fam = typo.get("font_family", "Segoe Print")
        active_idx = self._layer_edit_index.get()

        try:
            prof = self._current_profile()
        except Exception:
            prof = {}
        layers = prof.get("layers", [])
        if not isinstance(layers, list):
            layers = []
        base_count = len(prof.get("mappings", {}))

        def _make_click(idx: int):
            def _on_click(_e: Any = None) -> None:
                self._layer_edit_index.set(idx)
                self._build_layer_tab_bar()
                self._keymap_redraw()
                self._refresh_mask_cards()
            return _on_click

        # Base layer tab
        is_active = (active_idx == -1)
        base_bg = colors.get("accent", "#4a6480") if is_active else colors.get("panel", "#f2e8d0")
        base_fg = "#fff6e1" if is_active else colors.get("text", "#2a1f0e")
        base_lbl = tk.Label(
            bar, text=f"  Base ({base_count})  ",
            font=(font_fam, 9, "bold" if is_active else ""),
            bg=base_bg, fg=base_fg, cursor="hand2",
            relief="flat", padx=6, pady=2,
        )
        base_lbl.pack(side=tk.LEFT, padx=(0, 2), pady=2)
        base_lbl.bind("<Button-1>", _make_click(-1))
        self._layer_tab_buttons.append(base_lbl)

        # Layer tabs
        for i, layer in enumerate(layers):
            name = layer.get("name", f"Layer {i + 1}")
            mode = layer.get("mode", "hold")
            cnt = len(layer.get("mappings", {}))
            is_active = (active_idx == i)
            tab_bg = colors.get("accent", "#4a6480") if is_active else colors.get("panel", "#f2e8d0")
            tab_fg = "#fff6e1" if is_active else colors.get("text", "#2a1f0e")
            tab_lbl = tk.Label(
                bar, text=f"  {name} ({mode}, {cnt})  ",
                font=(font_fam, 9, "bold" if is_active else ""),
                bg=tab_bg, fg=tab_fg, cursor="hand2",
                relief="flat", padx=6, pady=2,
            )
            tab_lbl.pack(side=tk.LEFT, padx=(0, 2), pady=2)
            tab_lbl.bind("<Button-1>", _make_click(i))
            self._layer_tab_buttons.append(tab_lbl)

        # "+" button to open layers popup for adding/config
        plus_lbl = tk.Label(
            bar, text=" + ",
            font=(font_fam, 9, "bold"), cursor="hand2",
            bg=colors.get("panel", "#f2e8d0"),
            fg=colors.get("muted", "#6b5d48"),
            relief="flat", padx=4, pady=2,
        )
        plus_lbl.pack(side=tk.LEFT, padx=(2, 0), pady=2)
        plus_lbl.bind("<Button-1>", lambda _e: self._layers_popup.toggle())
        self._layer_tab_buttons.append(plus_lbl)

    def _build_input_test_tab(self) -> None:
        """Build the Input Test tab: live event log + visual timeline + active key summary."""
        top = ttk.Frame(self.tab_input_test)
        top.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(top, text="Active keys:").pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self._input_test_active_var, wraplength=700, justify="left").pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(top, text="Clear log", command=self._input_test_clear).pack(side=tk.RIGHT)

        # ── Performance profiling toggle ──
        perf_row = ttk.Frame(self.tab_input_test)
        perf_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._perf_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(perf_row, text="Show performance stats", variable=self._perf_var,
                        command=self._toggle_perf).pack(side=tk.LEFT)
        self._perf_stats_var = tk.StringVar(value="")
        self._perf_label = ttk.Label(perf_row, textvariable=self._perf_stats_var, style="Muted.TLabel")
        self._perf_label.pack(side=tk.LEFT, padx=(12, 0))

        # ── Visual event timeline ──
        tl_frame = ttk.LabelFrame(self.tab_input_test, text="Event timeline (last 5 seconds)")
        tl_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._timeline_canvas = tk.Canvas(tl_frame, height=60, highlightthickness=1)
        self._timeline_canvas.pack(fill=tk.X, padx=4, pady=4)
        try:
            self._timeline_canvas.configure(
                bg=self._colors["panel2"],
                highlightbackground=self._colors["border"],
            )
        except Exception:
            pass

        ttk.Label(self.tab_input_test, text="Event log (newest first)").pack(anchor="w", padx=8)
        self._input_test_log = ScrolledText(self.tab_input_test, height=16, state="disabled")
        self._input_test_log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self._theme_scrolled_text(self._input_test_log)

        # Refresh timeline periodically
        self.after(200, self._timeline_redraw_tick)

    def _input_test_clear(self) -> None:
        if not hasattr(self, "_input_test_log"):
            return
        self._input_test_log.configure(state="normal")
        self._input_test_log.delete("1.0", "end")
        self._input_test_log.configure(state="disabled")

    def _input_test_append(self, line: str) -> None:
        if not hasattr(self, "_input_test_log"):
            return
        log_w = self._input_test_log
        log_w.configure(state="normal")
        log_w.insert("1.0", line + "\n")
        # Trim to 500 lines
        total = int(log_w.index("end-1c").split(".")[0])
        if total > 500:
            log_w.delete(f"{501}.0", "end")
        log_w.configure(state="disabled")

    def _timeline_add_event(self, label: str, color: str) -> None:
        """Record an event for the visual timeline."""
        self._event_timeline.append((time.time(), label, color))
        # Trim old events (>10 seconds)
        cutoff = time.time() - 10.0
        self._event_timeline = [(t, l, c) for t, l, c in self._event_timeline if t > cutoff]

    def _timeline_redraw_tick(self) -> None:
        """Periodically redraw the event timeline canvas — skip if no changes."""
        now = time.time()
        # Only redraw if events changed or old events expired (every ~1s)
        if (len(self._event_timeline) != self._timeline_last_count
                or now - self._timeline_last_draw_time > 1.0):
            self._timeline_redraw()
            self._timeline_last_count = len(self._event_timeline)
            self._timeline_last_draw_time = now
        self.after(200, self._timeline_redraw_tick)

    def _timeline_redraw(self) -> None:
        """Draw the event timeline canvas showing recent events."""
        c = self._timeline_canvas
        if not c:
            return
        c.delete("all")

        w = max(c.winfo_width(), 200)
        h = max(c.winfo_height(), 50)
        now = time.time()
        window_sec = 5.0  # show last 5 seconds
        pad = 4

        # Draw time axis
        axis_col = self._colors.get("border", "#666")
        c.create_line(pad, h - 12, w - pad, h - 12, fill=axis_col)
        for sec in range(int(window_sec) + 1):
            x = pad + (1.0 - sec / window_sec) * (w - 2 * pad)
            c.create_line(x, h - 15, x, h - 9, fill=axis_col)
            c.create_text(x, h - 4, text=f"-{sec}s", fill=self._colors.get("muted", "#999"),
                         font=("Consolas", 7))

        # Trim expired
        cutoff = now - window_sec
        self._event_timeline = [(t, l, cl) for t, l, cl in self._event_timeline if t > cutoff]

        # Draw events as colored marks
        for t, label, color in self._event_timeline:
            age = now - t
            x = pad + (1.0 - age / window_sec) * (w - 2 * pad)
            if x < pad or x > w - pad:
                continue
            c.create_line(x, pad, x, h - 18, fill=color, width=2)
            c.create_text(x, pad + 6, text=label, fill=color,
                         font=(self._typo.get("font_family", "Segoe UI"), 7), anchor="n")

    # ------------------------------------------------------------------
    # Performance profiling display
    # ------------------------------------------------------------------

    def _toggle_perf(self) -> None:
        """Toggle performance stats collection and display."""
        self._perf_enabled = self._perf_var.get()
        if self._perf_enabled:
            self._perf_redraw_times.clear()
            self._perf_input_times.clear()
            self._perf_stats_var.set("Collecting...")
            self._perf_update_tick()
        else:
            self._perf_stats_var.set("")

    def _perf_update_tick(self) -> None:
        """Periodically update profiling stats display."""
        if not self._perf_enabled:
            return
        parts: list[str] = []
        if self._perf_redraw_times:
            recent = self._perf_redraw_times[-50:]
            avg_ms = sum(recent) / len(recent) * 1000
            max_ms = max(recent) * 1000
            parts.append(f"Redraw: avg {avg_ms:.1f}ms, max {max_ms:.1f}ms ({len(recent)} samples)")
        if self._perf_input_times:
            recent = self._perf_input_times[-50:]
            lats = [proc - recv for recv, proc in recent]
            avg_lat = sum(lats) / len(lats) * 1000
            max_lat = max(lats) * 1000
            parts.append(f"Input: avg {avg_lat:.1f}ms, max {max_lat:.1f}ms")
        self._perf_stats_var.set("  |  ".join(parts) if parts else "Collecting...")
        self.after(500, self._perf_update_tick)

    # ------------------------------------------------------------------
    # Mouse tab  (M913 Impact Elite configuration)
    # ------------------------------------------------------------------

    def _build_mouse_tab(self) -> None:
        """Build the Mouse tab: M913 device selection + dominant overlay + popup panels."""
        parent = self.tab_mouse

        # ── Instance state ──
        self._m913_devices: List[m913_device.M913DeviceInfo] = []
        self._m913_open_devs: Dict[str, m913_device.M913Device] = {}  # device_id → open device
        self._m913_profile = m913_device.M913Profile()
        self._m913_button_vars: Dict[str, tk.StringVar] = {}
        self._m913_dpi_vars: List[tk.IntVar] = []
        self._m913_dpi_en_vars: List[tk.BooleanVar] = []
        self._m913_registry = m913_device.load_device_registry()

        # ── Compact toolbar: device + layout + popup triggers ──
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, padx=6, pady=(6, 2))

        ttk.Label(toolbar, text="Device:").pack(side=tk.LEFT)
        self._m913_dev_var = tk.StringVar()
        self._m913_dev_combo = ttk.Combobox(toolbar, textvariable=self._m913_dev_var,
                                            state="readonly", width=24)
        self._m913_dev_combo.pack(side=tk.LEFT, padx=(4, 4))
        self._m913_dev_combo.bind("<<ComboboxSelected>>", lambda _: self._m913_on_device_selected())

        ttk.Button(toolbar, text="Scan", command=self._m913_scan_devices).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Apply", command=self._m913_apply_config).pack(side=tk.LEFT, padx=2)

        sep = ttk.Separator(toolbar, orient=tk.VERTICAL)
        sep.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # Layout selector
        ttk.Label(toolbar, text="Layout:").pack(side=tk.LEFT)
        self._m913_layout_var = tk.StringVar(value=self._m913_profile.layout)
        layout_display = {"stock": "Stock M913", "incedius": "IncediusMod"}
        self._m913_layout_display = layout_display
        self._m913_layout_reverse = {v: k for k, v in layout_display.items()}
        layout_cb = ttk.Combobox(toolbar, textvariable=self._m913_layout_var,
                                 values=list(layout_display.values()),
                                 state="readonly", width=14)
        layout_cb.set(layout_display.get(self._m913_profile.layout, "Stock M913"))
        layout_cb.pack(side=tk.LEFT, padx=4)
        layout_cb.bind("<<ComboboxSelected>>", lambda _: self._m913_on_layout_changed())

        self._m913_edit_layout_btn = ttk.Button(
            toolbar, text="Edit Heist Plan\u2026",
            command=self._m913_edit_incedius_map)
        self._m913_edit_layout_btn.pack(side=tk.LEFT, padx=2)
        self._m913_edit_layout_btn.state(
            ["!disabled"] if self._m913_profile.layout == "incedius" else ["disabled"])

        sep2 = ttk.Separator(toolbar, orient=tk.VERTICAL)
        sep2.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # Popup trigger buttons
        ttk.Button(toolbar, text="Buttons\u2026",
                   command=lambda: self._m913_buttons_popup.toggle()).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="DPI\u2026",
                   command=lambda: self._m913_dpi_popup.toggle()).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="LED\u2026",
                   command=lambda: self._m913_led_popup.toggle()).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Settings\u2026",
                   command=lambda: self._m913_settings_popup.toggle()).pack(side=tk.LEFT, padx=2)

        if not m913_device.HID_AVAILABLE:
            ttk.Label(parent, text="\u26a0 hidapi not installed \u2014 pip install hidapi",
                      foreground=self._colors.get("danger", "red")).pack(padx=6, pady=2)

        # ── Sister profile linking (compact) ──
        link_row = ttk.Frame(parent)
        link_row.pack(fill=tk.X, padx=6)
        ttk.Label(link_row, text="Link to Joy-Con slot:").pack(side=tk.LEFT)
        self._m913_sister_var = tk.StringVar(value="None")
        sister_cb = ttk.Combobox(link_row, textvariable=self._m913_sister_var,
                                 values=["None", "Slot 1", "Slot 2", "Slot 3", "Slot 4"],
                                 state="readonly", width=10)
        sister_cb.pack(side=tk.LEFT, padx=4)
        sister_cb.bind("<<ComboboxSelected>>", lambda _: self._m913_on_sister_changed())

        # ── M913 overlay canvas: DOMINANT — fills all remaining space ──
        self._m913_overlay_canvas = tk.Canvas(parent, highlightthickness=1)
        self._m913_overlay_canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=(3, 3))
        try:
            self._m913_overlay_canvas.configure(
                bg=self._colors.get("panel2", "#f2e8d0"),
                highlightbackground=self._colors.get("border", "#b09878"),
            )
        except Exception:
            pass
        self._m913_overlay_canvas.bind("<Configure>", lambda _e: self._m913_redraw_overlay())
        self._m913_img_paths = self._find_m913_png_variants(self._m913_profile.layout)
        self._m913_set_image_state("none")

        # ── Status label ──
        self._m913_status_var = tk.StringVar(value="Ready \u2014 click Scan to detect M913 devices")
        ttk.Label(parent, textvariable=self._m913_status_var).pack(anchor="w", padx=6, pady=(0, 4))

        # ── Build popup panels ──
        self._build_m913_buttons_popup()
        self._build_m913_dpi_popup()
        self._build_m913_led_popup()
        self._build_m913_settings_popup()

        # Auto-scan on tab open
        self.after(200, self._m913_scan_devices)

    # ------------------------------------------------------------------
    # M913 popup panels
    # ------------------------------------------------------------------

    def _build_m913_buttons_popup(self) -> None:
        """Popup: 16-button mapping grid."""
        self._m913_buttons_popup = SketchPopup(
            self, title="Button Heist Plan (16 buttons)", colors=self._colors,
            typo=self._typo, width=400, height=460)
        body = self._m913_buttons_popup.body

        action_choices = m913_device.ALL_ACTIONS + m913_device.ALL_KEY_NAMES
        self._m913_button_labels: Dict[str, ttk.Label] = {}
        display_names = self._m913_resolved_display_names(self._m913_profile.layout)

        for i, btn_name in enumerate(m913_device.BUTTON_ORDER):
            r = ttk.Frame(body)
            r.pack(fill=tk.X, pady=1)
            display = display_names.get(btn_name, btn_name)
            lbl = ttk.Label(r, text=f"{display}:", width=14, anchor="w")
            lbl.pack(side=tk.LEFT)
            self._m913_button_labels[btn_name] = lbl
            var = tk.StringVar(value=self._m913_profile.buttons.get(btn_name, "none"))
            self._m913_button_vars[btn_name] = var
            cb = ttk.Combobox(r, textvariable=var, values=action_choices, width=24)
            cb.pack(side=tk.LEFT, padx=4)

    def _build_m913_dpi_popup(self) -> None:
        """Popup: DPI levels (5 stages)."""
        self._m913_dpi_popup = SketchPopup(
            self, title="DPI (5 levels, 100\u201316000)", colors=self._colors,
            typo=self._typo, width=320, height=200)
        body = self._m913_dpi_popup.body

        self._m913_dpi_vars = []
        self._m913_dpi_en_vars = []
        for i in range(5):
            r = ttk.Frame(body)
            r.pack(fill=tk.X, pady=1)
            en_var = tk.BooleanVar(value=self._m913_profile.dpi_enabled[i])
            self._m913_dpi_en_vars.append(en_var)
            ttk.Checkbutton(r, variable=en_var).pack(side=tk.LEFT)
            ttk.Label(r, text=f"Level {i + 1}:").pack(side=tk.LEFT, padx=(4, 0))
            dpi_var = tk.IntVar(value=self._m913_profile.dpi_values[i])
            self._m913_dpi_vars.append(dpi_var)
            sb = ttk.Spinbox(r, from_=100, to=16000, increment=100,
                             textvariable=dpi_var, width=8)
            sb.pack(side=tk.LEFT, padx=4)

    def _build_m913_led_popup(self) -> None:
        """Popup: LED mode, color, brightness, speed."""
        self._m913_led_popup = SketchPopup(
            self, title="LED Settings", colors=self._colors,
            typo=self._typo, width=380, height=140)
        body = self._m913_led_popup.body

        lr1 = ttk.Frame(body)
        lr1.pack(fill=tk.X, pady=2)
        ttk.Label(lr1, text="Mode:").pack(side=tk.LEFT)
        self._m913_led_mode_var = tk.StringVar(value=self._m913_profile.led_mode)
        ttk.Combobox(lr1, textvariable=self._m913_led_mode_var,
                     values=["off", "steady", "respiration", "rainbow"],
                     state="readonly", width=14).pack(side=tk.LEFT, padx=4)
        ttk.Label(lr1, text="Color (#hex):").pack(side=tk.LEFT, padx=(8, 0))
        self._m913_led_color_var = tk.StringVar(value=f"{self._m913_profile.led_color:06x}")
        ttk.Entry(lr1, textvariable=self._m913_led_color_var, width=8).pack(side=tk.LEFT, padx=4)

        lr2 = ttk.Frame(body)
        lr2.pack(fill=tk.X, pady=2)
        ttk.Label(lr2, text="Brightness:").pack(side=tk.LEFT)
        self._m913_led_bright_var = tk.IntVar(value=self._m913_profile.led_brightness)
        ttk.Scale(lr2, from_=0, to=255, variable=self._m913_led_bright_var,
                  orient=tk.HORIZONTAL, length=120).pack(side=tk.LEFT, padx=4)
        ttk.Label(lr2, text="Speed (1-5):").pack(side=tk.LEFT, padx=(8, 0))
        self._m913_led_speed_var = tk.IntVar(value=self._m913_profile.led_speed)
        ttk.Spinbox(lr2, from_=1, to=5, textvariable=self._m913_led_speed_var,
                     width=4).pack(side=tk.LEFT, padx=4)

    def _build_m913_settings_popup(self) -> None:
        """Popup: polling rate + profile save/load."""
        self._m913_settings_popup = SketchPopup(
            self, title="Mouse Settings", colors=self._colors,
            typo=self._typo, width=400, height=180)
        body = self._m913_settings_popup.body

        # Polling rate
        ttk.Label(body, text="Polling Rate:").pack(anchor="w", pady=(4, 2))
        pr = ttk.Frame(body)
        pr.pack(fill=tk.X, pady=(0, 6))
        self._m913_poll_var = tk.IntVar(value=self._m913_profile.polling_rate)
        for hz in (125, 250, 500, 1000):
            ttk.Radiobutton(pr, text=f"{hz} Hz", value=hz,
                            variable=self._m913_poll_var).pack(side=tk.LEFT, padx=6)

        # Profile save/load
        ttk.Label(body, text="Profile:").pack(anchor="w", pady=(0, 2))
        pfr = ttk.Frame(body)
        pfr.pack(fill=tk.X)
        ttk.Label(pfr, text="Name:").pack(side=tk.LEFT)
        self._m913_prof_name_var = tk.StringVar(value=self._m913_profile.name)
        ttk.Entry(pfr, textvariable=self._m913_prof_name_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(pfr, text="Save", command=self._m913_save_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(pfr, text="Load", command=self._m913_load_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(pfr, text="Delete", command=self._m913_delete_profile).pack(side=tk.LEFT, padx=2)

    # ------------------------------------------------------------------
    # Help tab
    # ------------------------------------------------------------------

    # ── Help-tab helpers ─────────────────────────────────────────────

    def _help_section(
        self,
        parent: tk.Widget,
        title: str,
        body_lines: List[str],
        *,
        collapsed: bool = True,
        mono: bool = False,
    ) -> tk.Frame:
        """Create a collapsible help section.

        Returns the content frame so callers can pack extra widgets (e.g. images).
        """
        colors = self._colors
        typo = self._typo
        font_fam = typo.get("font_family", "Segoe Print")
        mono_fam = typo.get("mono_family", "Consolas")
        mono_sz = typo.get("mono_size", 10)

        wrapper = tk.Frame(parent, bg=colors.get("bg", "#e8d8b8"))
        wrapper.pack(fill=tk.X, padx=4, pady=(4, 0))

        # Header row (toggle button)
        header = tk.Frame(wrapper, bg=colors.get("panel2", "#e2d0a8"))
        header.pack(fill=tk.X)

        arrow_var = tk.StringVar(value="\u25b6" if collapsed else "\u25bc")
        toggle_btn = tk.Label(
            header, textvariable=arrow_var,
            font=(font_fam, 10), bg=colors.get("panel2", "#e2d0a8"),
            fg=colors.get("accent", "#4a6480"), cursor="hand2", padx=6,
        )
        toggle_btn.pack(side=tk.LEFT)

        tk.Label(
            header, text=title, font=(font_fam, 11, "bold"),
            bg=colors.get("panel2", "#e2d0a8"), fg=colors.get("text", "#2a1f0e"),
            anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Divider
        tk.Frame(wrapper, height=1, bg=colors.get("border", "#b09878")).pack(fill=tk.X)

        # Body
        body = tk.Frame(wrapper, bg=colors.get("bg", "#e8d8b8"))
        if not collapsed:
            body.pack(fill=tk.X, padx=8, pady=(2, 6))

        text_font = (mono_fam, mono_sz) if mono else (font_fam, typo.get("font_size", 10))
        for line in body_lines:
            # Detect sub-headers (lines starting with  ▸ or ##)
            if line.startswith("## "):
                tk.Label(
                    body, text=line[3:], font=(font_fam, 10, "bold"),
                    bg=colors.get("bg", "#e8d8b8"), fg=colors.get("accent", "#4a6480"),
                    anchor="w", justify=tk.LEFT,
                ).pack(anchor="w", pady=(6, 1))
            elif line.startswith("  "):
                # Indented / code-like
                tk.Label(
                    body, text=line, font=(mono_fam, mono_sz),
                    bg=colors.get("bg", "#e8d8b8"), fg=colors.get("muted", "#6b5d48"),
                    anchor="w", justify=tk.LEFT,
                ).pack(anchor="w")
            else:
                tk.Label(
                    body, text=line, font=text_font, wraplength=700,
                    bg=colors.get("bg", "#e8d8b8"), fg=colors.get("text", "#2a1f0e"),
                    anchor="w", justify=tk.LEFT,
                ).pack(anchor="w", pady=1)

        def _toggle(_e: Any = None) -> None:
            if body.winfo_manager():
                body.pack_forget()
                arrow_var.set("\u25b6")
            else:
                body.pack(fill=tk.X, padx=8, pady=(2, 6))
                arrow_var.set("\u25bc")
                # Scroll into view
                parent.update_idletasks()

        toggle_btn.bind("<Button-1>", _toggle)
        header.bind("<Button-1>", _toggle)
        for child in header.winfo_children():
            child.bind("<Button-1>", _toggle)

        return body

    def _build_help_tab(self) -> None:
        """Build the comprehensive Help tab with all setup / usage info."""
        parent = self.tab_help
        colors = self._colors
        typo = self._typo
        font_fam = typo.get("font_family", "Segoe Print")

        # ── Navigation bar ────────────────────────────────────────────
        nav = tk.Frame(parent, bg=colors.get("panel2", "#e2d0a8"))
        nav.pack(fill=tk.X, padx=4, pady=(4, 2))

        tk.Label(
            nav, text="Help & Setup Guide",
            font=(font_fam, 13, "bold"),
            bg=colors.get("panel2", "#e2d0a8"),
            fg=colors.get("text", "#2a1f0e"),
        ).pack(side=tk.LEFT, padx=8, pady=4)

        # Search entry
        search_var = tk.StringVar()
        search_entry = tk.Entry(
            nav, textvariable=search_var, width=28,
            font=(font_fam, 10),
            bg=colors.get("panel", "#f2e8d0"),
            fg=colors.get("text", "#2a1f0e"),
            insertbackground=colors.get("text", "#2a1f0e"),
        )
        search_entry.pack(side=tk.RIGHT, padx=8, pady=4)
        tk.Label(
            nav, text="Search:",
            font=(font_fam, 10),
            bg=colors.get("panel2", "#e2d0a8"),
            fg=colors.get("muted", "#6b5d48"),
        ).pack(side=tk.RIGHT)

        # ── Scrollable content area ───────────────────────────────────
        outer = ttk.Frame(parent)
        outer.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        v_scroll = ttk.Scrollbar(outer, orient=tk.VERTICAL)
        help_canvas = tk.Canvas(
            outer, highlightthickness=0,
            bg=colors.get("bg", "#e8d8b8"),
            yscrollcommand=v_scroll.set,
        )
        v_scroll.configure(command=help_canvas.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        help_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        content = tk.Frame(help_canvas, bg=colors.get("bg", "#e8d8b8"))
        canvas_window = help_canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_configure(_e: Any = None) -> None:
            help_canvas.configure(scrollregion=help_canvas.bbox("all"))

        def _on_canvas_resize(e: Any) -> None:
            help_canvas.itemconfigure(canvas_window, width=e.width)

        content.bind("<Configure>", _on_configure)
        help_canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event: Any) -> None:
            help_canvas.yview_scroll(-event.delta // 120, "units")

        help_canvas.bind("<MouseWheel>", _on_mousewheel)
        content.bind("<MouseWheel>", _on_mousewheel)

        # Propagate mouse-wheel from all children
        def _bind_wheel(widget: tk.Widget) -> None:
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_wheel(child)

        # Keep track of all section wrappers for search filtering
        self._help_sections: List[tk.Frame] = []
        self._help_section_titles: List[str] = []

        def _add(title: str, lines: List[str], **kw: Any) -> tk.Frame:
            body = self._help_section(content, title, lines, **kw)
            wrapper = body.master  # the wrapper Frame
            self._help_sections.append(wrapper)
            self._help_section_titles.append(title.lower())
            return body

        # ══════════════════════════════════════════════════════════════
        # 1. OVERVIEW
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f3ae  What Is This?", [
            "Bind Bandit is the companion app for the Joy-Con \u2192 Hardware Keyboard Bridge.",
            "",
            "The bridge converts wireless controller input (Joy-Con, Binbok, etc.) into",
            "real USB keyboard output that the PC sees as a genuine hardware keyboard.",
            "This is anti-cheat safe \u2014 no virtual drivers, no injected input.",
            "",
            "## How it works",
            "1) An ESP32 board connects wirelessly to your controller via Bluetooth Classic.",
            "2) It sends button events over a UART serial link to an ESP32-S3 board.",
            "3) The ESP32-S3 plugs into the PC and shows up as a USB HID keyboard.",
            "4) This app (Bind Bandit) talks to the ESP32-S3 over a USB serial port",
            "   to configure loadouts, heist plans, tricks, and more.",
        ], collapsed=False)

        # ══════════════════════════════════════════════════════════════
        # 2. WHAT YOU NEED
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f6d2  What You Need", [
            "## Hardware",
            "\u2022 ESP32-S3 dev board (e.g. Arduino Nano ESP32 ABX00083) \u2014 the USB keyboard side",
            "\u2022 ESP32 dev board with Classic Bluetooth (e.g. NodeMCU ESP32-WROOM-32) \u2014 the BT host side",
            "\u2022 3 jumper wires (power + ground + UART data)",
            "\u2022 A Joy-Con, Binbok, or compatible Bluetooth Classic HID controller",
            "\u2022 USB cable to connect the ESP32-S3 to the PC",
            "",
            "## Software",
            "\u2022 ESP-IDF (Espressif IoT Development Framework) for building/flashing firmware",
            "\u2022 Python 3.10+ with pip (for this helper app)",
            "\u2022 USB drivers for your ESP32 dev board (CP210x or CH340 if needed)",
            "",
            "## Important board note",
            "You need TWO separate boards because:",
            "\u2022 ESP32-S3 is great at USB device mode but has NO Classic Bluetooth",
            "\u2022 ESP32 (original) has Classic Bluetooth but no USB device mode",
            "One board cannot do both (unless BLE HID-over-GATT is proven for your controller).",
        ])

        # ══════════════════════════════════════════════════════════════
        # 3. WIRING
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f50c  Wiring & Connections", [
            "Only the ESP32-S3 plugs into the PC. The ESP32 is powered from the ESP32-S3",
            "so the whole adapter runs from one USB cable (single dongle).",
            "",
            "## Minimum wiring (3 wires)",
            "\u2022 Power:  ESP32-S3  5V/VUSB  \u2192  ESP32  VIN/5V",
            "\u2022 Ground: ESP32-S3  GND      \u2192  ESP32  GND",
            "\u2022 Data:   ESP32     TX (GPIO17) \u2192 ESP32-S3 RX (GPIO44)",
            "",
            "## Optional 4th wire (recommended)",
            "\u2022 Return: ESP32-S3  TX (GPIO43) \u2192  ESP32  RX (GPIO16)",
            "  Enables the helper app to send commands back to the ESP32",
            "  (start scan, set target controller, etc.)",
            "",
            "## Default pin assignments",
            "  ESP32 (BT host):",
            "    TX = GPIO17    RX = GPIO16 (optional)",
            "    UART baud = 115200",
            "",
            "  ESP32-S3 (Arduino Nano ESP32):",
            "    RX0 = GPIO44   TX0 = GPIO43",
            "    UART baud = 115200",
            "",
            "## Voltage warning",
            "\u2022 UART signals are 3.3V on both chips \u2014 do NOT connect 5V to RX/TX pins.",
            "\u2022 Power goes through the dev board's VIN/5V pin (feeds into on-board regulator).",
            "\u2022 Do NOT feed 5V into a 3V3 pin.",
            "",
            "## Avoid double-powering",
            "Don\u2019t plug the ESP32 into its own USB while it\u2019s also being powered from",
            "the ESP32-S3 \u2014 two 5V sources on VIN can damage the board.",
            "",
            "## Physical tips",
            "\u2022 Keep UART wires short (a few cm).",
            "\u2022 Route GND next to the data wire to reduce noise.",
            "\u2022 If you see garbage bytes: check common ground, baud rate (115200),",
            "  and that you haven\u2019t swapped RX and TX.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 4. PINOUT DIAGRAM
        # ══════════════════════════════════════════════════════════════
        pinout_body = _add("\U0001f4cc  Board Pinout Diagram", [
            "Arduino Nano ESP32-S3 (USB HID Keyboard)  \u00b7  NodeMCU ESP32-WROOM-32 (BT Host)",
            "",
            "Scroll to pan; Shift+Scroll for horizontal.  Image: pinouts.png",
        ])

        # Embed the pinout image in a scrollable sub-canvas
        pin_canvas_wrap = tk.Frame(pinout_body, bg=colors.get("bg", "#e8d8b8"))
        pin_canvas_wrap.pack(fill=tk.X, pady=(4, 4))

        h_scroll = ttk.Scrollbar(pin_canvas_wrap, orient=tk.HORIZONTAL)
        v_scroll_pin = ttk.Scrollbar(pin_canvas_wrap, orient=tk.VERTICAL)
        pinout_canvas = tk.Canvas(
            pin_canvas_wrap, highlightthickness=0, height=360,
            bg=colors.get("panel", "#f2e8d0"),
            xscrollcommand=h_scroll.set,
            yscrollcommand=v_scroll_pin.set,
        )
        h_scroll.configure(command=pinout_canvas.xview)
        v_scroll_pin.configure(command=pinout_canvas.yview)
        v_scroll_pin.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        pinout_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Load pinouts.png
        self._help_pinout_base: Optional[tk.PhotoImage] = None
        search_roots = list(_joycons_search_roots())
        here = Path(__file__).resolve()
        search_roots.append(here.parents[3] / "docs" / "ui" / "reference")
        try:
            search_roots.append(Path.cwd() / "docs" / "ui" / "reference")
        except Exception:
            pass
        for root in _dedupe_paths(search_roots):
            candidate = root / "pinouts.png"
            try:
                if candidate.exists():
                    self._help_pinout_base = tk.PhotoImage(file=str(candidate))
                    break
            except Exception:
                continue

        if self._help_pinout_base:
            img_w = self._help_pinout_base.width()
            img_h = self._help_pinout_base.height()
            pinout_canvas.create_image(0, 0, image=self._help_pinout_base, anchor="nw")
            pinout_canvas.configure(scrollregion=(0, 0, img_w, img_h))
        else:
            pinout_canvas.create_text(200, 80, text="pinouts.png not found",
                                      fill=colors.get("muted", "#666"))

        def _pin_wheel(event: Any) -> None:
            pinout_canvas.yview_scroll(-event.delta // 120, "units")

        def _pin_shift_wheel(event: Any) -> None:
            pinout_canvas.xview_scroll(-event.delta // 120, "units")

        pinout_canvas.bind("<MouseWheel>", _pin_wheel)
        pinout_canvas.bind("<Shift-MouseWheel>", _pin_shift_wheel)

        # ══════════════════════════════════════════════════════════════
        # 5. FIRMWARE INSTALL
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f4be  Firmware Installation", [
            "You need to flash TWO separate firmwares \u2014 one for each board.",
            "Flash the ESP32-S3 first (it\u2019s the USB \u201cfront\u201d of the dongle).",
            "",
            "## Prerequisites",
            "\u2022 ESP-IDF installed (Espressif installer for Windows recommended)",
            "\u2022 An \u201cESP-IDF PowerShell\u201d terminal (comes with the installer)",
            "\u2022 USB drivers for your dev board\u2019s USB-to-UART chip (CP210x / CH340)",
            "",
            "## General workflow",
            "  idf.py set-target <chip>   (once per project folder)",
            "  idf.py menuconfig          (configure GPIOs / settings)",
            "  idf.py build",
            "  idf.py flash monitor",
            "",
            "## Step 1: Flash ESP32-S3 (USB keyboard)",
            "Folder: firmware/esp32s3-usb-kbd/",
            "",
            "  idf.py set-target esp32s3",
            "  idf.py menuconfig",
            "  idf.py build",
            "  idf.py flash monitor",
            "",
            "Menuconfig settings:",
            "\u2022 Bridge UART RX GPIO = 44  (Arduino Nano RX0)",
            "\u2022 Bridge UART TX GPIO = 43  (Arduino Nano TX0)",
            "\u2022 Bridge UART baud = 115200",
            "",
            "After flashing: PC should see a USB keyboard + COM port.",
            "",
            "## Step 2: Flash ESP32 (Bluetooth host)",
            "Folder: firmware/esp32-hid-host-uart/",
            "",
            "Temporarily disconnect VIN wire if both boards are wired together,",
            "then plug the ESP32 into its own USB for flashing.",
            "",
            "  idf.py set-target esp32",
            "  idf.py menuconfig",
            "  idf.py build",
            "  idf.py flash monitor",
            "",
            "Menuconfig settings:",
            "\u2022 Target device name substring = Joy-Con  (or Binbok, Pro Controller, etc.)",
            "\u2022 Discovery scan seconds \u2014 increase if device isn\u2019t found",
            "\u2022 Log HID input reports = enabled (recommended while mapping)",
            "",
            "UART pins set in firmware/esp32-hid-host-uart/main/config.h:",
            "  TX = GPIO17,  RX = GPIO16,  baud = 115200",
            "",
            "## Step 3: Assemble the dongle",
            "1) Unplug the ESP32 from its flashing USB.",
            "2) Connect the wiring (see Wiring section above).",
            "3) Plug only the ESP32-S3 into the PC.",
            "4) The ESP32 boots from the ESP32-S3\u2019s power.",
            "",
            "## Alternative: Flash from the helper app (no ESP-IDF needed!)",
            "The helper app can flash brand-new boards using the built-in esptool.",
            "",
            "1) Connect the board to your PC via USB.",
            "2) Put it in download mode: hold BOOT, press RESET, release BOOT.",
            "   (Some boards auto-enter download mode via USB \u2014 try without the button dance first.)",
            "3) Select the board\u2019s COM port in the dropdown at the top of the app.",
            "4) In the 'Initial Flash (new boards)' section at the bottom-right:",
            "   \u2022 'Download & flash latest' \u2014 fetches the latest release from GitHub and flashes.",
            "   \u2022 'Flash files\u2026' \u2014 pick local .bin file(s) (bootloader + partition table + app, or app-only).",
            "   \u2022 'Backup flash\u2026' \u2014 save the current flash contents before erasing (recommended).",
            "5) The chip type is auto-detected. The entire flash is erased before writing.",
            "6) After writing, the firmware is read back and verified automatically.",
            "7) After flashing, press RESET or re-plug USB. Flash each board separately.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 6. FIRST TEST
        # ══════════════════════════════════════════════════════════════
        _add("\u2705  First End-to-End Test", [
            "After wiring and flashing both boards:",
            "",
            "1) Plug the ESP32-S3 into the PC.",
            "2) Open the helper app (this app) and connect to the COM port.",
            "3) Put your controller into pairing mode.",
            "4) Watch the Input Test tab \u2014 you should see events when you press buttons.",
            "",
            "## What to check",
            "\u2022 ESP32-S3 enumerates as a USB keyboard (check Device Manager).",
            "\u2022 A COM port appears (CDC-ACM) \u2014 this is what the helper app connects to.",
            "\u2022 ESP32 power LED lights up (powered through VIN from the ESP32-S3).",
            "\u2022 Controller connects via Bluetooth (check ESP32 monitor logs if available).",
            "\u2022 Button presses produce HID report changes in the ESP32 logs.",
            "",
            "At this stage the default key mapping should already work \u2014 pressing buttons",
            "on the controller should type keys on the PC.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 7. HELPER APP USAGE
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f4bb  Using Bind Bandit (This App)", [
            "## Connecting",
            "\u2022 Select the correct COM port from the dropdown at the top of the window.",
            "\u2022 Click Connect. The status bar will show \u201cConnected\u201d.",
            "\u2022 If no COM port appears, check that the ESP32-S3 is plugged in and CDC is enabled.",
            "",
            "## Tabs overview",
            "\u2022 Loadout \u2014 JSON loadout editor, slot quick-switch, rename/duplicate/reset.",
            "\u2022 Tricks \u2014 Record and edit trick sequences (key + delay steps).",
            "\u2022 Stick \u2014 Deadzone / response curve for analog sticks (future analog support).",
            "\u2022 Share \u2014 Export/import loadout codes (compressed base64 strings).",
            "\u2022 Overlay \u2014 Always-on-top translucent status window showing active keys.",
            "\u2022 Controller \u2014 3-panel Heist Table: Heist Library (left, loadout cards), controller diagram (center), Heist Tools + Disguises (right).",
            "\u2022 Input Test \u2014 Live event log, timeline, and active-key display.",
            "\u2022 Mouse (M913) \u2014 Configure Redragon M913 mice: buttons, DPI, LED, polling rate.",
            "\u2022 Razer \u2014 Configure Razer mice: DPI stages, buttons, polling, idle timeout, battery.",
            "\u2022 Help \u2014 This tab.",
            "",
            "## Loadouts",
            "\u2022 4 loadout slots (0\u20133) stored on the ESP32-S3.",
            "\u2022 Each loadout contains: heist plans, remapping rules, tricks, masks, chords.",
            "\u2022 Loadouts can be renamed, duplicated, and reset.",
            "\u2022 Export/import via Share tab for backup or sharing with others.",
            "",
            "## Heist planning (Controller tab \u2014 Heist Tools panel)",
            "Click a button on the Joy-Con diagram to select it. The Heist Tools panel (right)",
            "updates instantly to show the selected button\u2019s name, current mapping, and action buttons:",
            "\u2022 \U0001f3b9 Keyboard \u2014 press a key to steal (remap to that key).",
            "\u2022 \U0001f5b1\ufe0f Mouse Click \u2014 map to any mouse button / HID keycode.",
            "\u2022 \U0001f9ea Trick \u2014 opens the inline Trick Builder to pick/create a trick, edit steps, and assign it.",
            "\u2022 \U0001f3ad Mask Shift \u2014 open mask/layer configuration.",
            "\u2022 \u2716 CLEAR \u2014 remove the mapping entirely.",
            "",
            "Right-click a hotspot for additional options: Case, Steal, Reset, Clear, or Disable.",
            "",
            "## Visual feedback",
            "\u2022 Hover glow \u2014 A hand-drawn ink ring highlights buttons as you move the mouse.",
            "\u2022 Steal overlay \u2014 A floating card appears during press-to-steal showing which button you\u2019re stealing.",
            "\u2022 Ink stamp \u2014 An expanding ring with STOLEN confirms a successful steal.",
            "\u2022 Overlay colour \u2014 Use the \U0001f3a8 dropdown in the toolbar to choose from 7 rainbow",
            "  colours (red, orange, yellow, green, blue, indigo, violet). Default is violet.",
            "",
            "## Masks (Disguises)",
            "Masks let you have multiple sets of steals and switch between them.",
            "\u2022 The Disguises section at the bottom of the Heist Tools panel shows 5 mask cards",
            "  (Base Face + Mask 1\u20134). Click a card to switch the editor to that mask.",
            "\u2022 Mask tabs are also shown below the controller diagram for quick switching.",
            "\u2022 Click the + button in the mask tab bar to add a new mask.",
            "\u2022 Base mask is always present and cannot be removed.",
            "",
            "## Mapping types",
            "\u2022 Passthrough \u2014 forward the button\u2019s default key.",
            "\u2022 Remap / Remap HID \u2014 send a different keyboard key.",
            "\u2022 Trick (macro) \u2014 play a sequence of keys with delays.",
            "\u2022 Double-tap \u2014 single-tap sends one key, quick double-tap sends another.",
            "  Set single keycode in \u2018Remap to\u2019 and double-tap keycode in \u2018Trick id\u2019.",
            "",
            "## Presets (Community profiles)",
            "Five built-in presets are available in the Controller tab:",
            "  FPS/Shooter, Platformer, RPG/Action, Minecraft, Racing.",
            "Click a preset button to apply the mapping instantly.",
            "",
            "## Calibration wizard",
            "Click the \U0001f527 Calibrate button in Controller Features to open a",
            "3-step calibration wizard: center stick, sweep edges, save/clear.",
            "The wizard also offers quick deadzone/curve adjustments.",
            "",
            "## Status bar indicators",
            "\u2022 Signal bars \u2014 BT RSSI strength of the connected controller.",
            "\u2022 \u23f1 RTT \u2014 round-trip latency to the device (auto-pinged every 10 s).",
            "",
            "## Safety",
            "\u2022 Restore \u2014 The toolbar has a Restore\u2026 button that reverts to the last config that was",
            "  successfully written to the device. Useful if you make changes you want to undo.",
            "",
            "The keyboard preview shows which physical keys are currently mapped.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 8. DEFAULT KEY MAP
        # ══════════════════════════════════════════════════════════════
        _add("\u2328\ufe0f  Default Key Mapping", [
            "## Movement (left stick)",
            "  Forward  = W        Back     = S",
            "  Left     = A        Right    = D",
            "  Jump     = Space    Sprint   = Left Shift",
            "  Crouch   = Left Ctrl",
            "",
            "## Face buttons",
            "  A = E    B = Q    X = R    Y = F",
            "",
            "## Shoulders / triggers",
            "  L = Tab     R = Enter",
            "  ZL = Right Alt   ZR = Left Alt",
            "",
            "## System",
            "  Plus = Escape   Minus = ` (Grave)",
            "  Home = (unmapped)   Capture = G",
            "",
            "## Stick clicks",
            "  LStick = Left Shift   RStick = V",
            "",
            "## Right stick directions",
            "  Up = Arrow Up    Down = Arrow Down",
            "  Left = Arrow Left   Right = Arrow Right",
            "",
            "## Motion / IMU gestures",
            "  Shake = 1    Tilt Up = 2    Tilt Down = 3",
            "  Tilt Left = 4    Tilt Right = 5    Flick = 6",
            "",
            "All heist plans are fully customizable in the Controller tab.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 8b. ADVANCED MAPPING MODES
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f3ae  Advanced Mapping Modes", [
            "Beyond simple key remapping, profiles support these advanced modes.",
            "All produce real USB HID keyboard output (anti-cheat safe).",
            "",
            "## Turbo (rapid-fire)",
            "Auto-repeats a key while held at a configurable interval.",
            "  JSON type: \"turbo\"",
            "  Fields: mod, keycode, delay_ms (10\u2013500, default 50)",
            "  Up to 8 turbo keys per profile.",
            "",
            "## Sticky (toggle modifier)",
            "First press activates the key/modifier, second press deactivates.",
            "  JSON type: \"sticky\"",
            "  Fields: mod, keycode",
            "  Useful for held modifiers (Shift, Ctrl, Alt) without physical holding.",
            "",
            "## Tap-Hold",
            "Quick tap fires one action, long hold fires a different action.",
            "  JSON type: \"tap_hold\"",
            "  Fields: tap (sub-mapping), hold (sub-mapping), hold_ms (50\u20132000, default 300)",
            "  Up to 8 tap-hold keys per profile.",
            "",
            "## Double-Tap",
            "Single tap sends one key, quick double-tap sends another.",
            "  JSON type: \"double_tap\"",
            "  Fields: single (mod+keycode), double (mod+keycode), timeout_ms (100\u20131000, default 300)",
            "  Up to 8 double-tap keys per profile.",
            "",
            "## Chords (combos)",
            "Press 2\u20134 buttons simultaneously to trigger a single action.",
            "  Top-level \"chords\" array in the profile JSON.",
            "  Individual key mappings are suppressed while a chord is active.",
            "  Up to 8 chords per profile.",
            "",
            "See helper-app/protocol.md for full JSON schema.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 9. SERIAL PROTOCOL (summary)
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f4e1  Serial Protocol (Reference)", [
            "## Helper app \u2194 ESP32-S3 (USB serial / COM port)",
            "Transport: USB serial, 115200 baud, 8N1, UTF-8 text.",
            "Framing: NDJSON \u2014 one JSON object per line.",
            "",
            "Commands (PC \u2192 device):",
            "  ping, write_profile, read_profile, set_active_profile,",
            "  bt_set_target, bt_connect, fw_version, fw_update_begin/data/end/abort,",
            "  set_stick_curve, calibration (save/clear),",
            "  rumble (device_id, freq, amp), home_led (device_id, brightness)",
            "",
            "Events (device \u2192 PC):",
            "  mapped_key (pressed, key_id), macro (id, state),",
            "  layer (name, active), bt_status (state, name, bda),",
            "  battery (device_id, level 0\u20134),",
            "  controller_info (type, serial, colors, stick params, IMU cal),",
            "  rssi (device_id, rssi dBm)",
            "",
            "## ESP32 \u2194 ESP32-S3 (UART, 3.3V)",
            "Binary framing:  AA 55 <len> <payload...> <checksum>",
            "",
            "Payload types:",
            "  Key event:   bit7=pressed, bits6-0=key_id",
            "  Extended key (0xFC): device_id, pressed, base_key_id",
            "  Status (0xFD): state + BDA + name",
            "  Battery (0xFA): device_id + level (0\u20134)",
            "  Controller info (0xF9): type, serial, colors, stick params, IMU cal",
            "  RSSI (0xF8): device_id + rssi (dBm)",
            "  Debug (0xFF): raw HID report bytes",
            "  Control (0xFE): set target, discovery, stick curve, calibration, rumble, home LED",
            "  OTA (0xFB): firmware update frames",
            "",
            "For full protocol details see docs/serial-protocol.md",
        ])

        # ══════════════════════════════════════════════════════════════
        # 10. MOUSE CONFIG
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f5b1\ufe0f  Mouse Configuration (M913 & Razer)", [
            "Bind Bandit can also configure gaming mice over USB HID \u2014",
            "no additional hardware needed, just plug the mouse in.",
            "",
            "## Redragon M913 (Mouse tab)",
            "\u2022 16 programmable buttons (including 12 side buttons).",
            "\u2022 DPI: up to 5 stages, separate X/Y resolution.",
            "\u2022 LED: color, effect, brightness.",
            "\u2022 Polling rate: 125 / 250 / 500 / 1000 Hz.",
            "\u2022 IncediusMod variant supported (different side button layout).",
            "\u2022 Loadouts: save / load / delete / auto-link per device.",
            "",
            "## Razer mice (Razer tab)",
            "\u2022 Basilisk X HyperSpeed and other supported models.",
            "\u2022 DPI: 5 stages, X/Y independent, 100\u201326000 DPI.",
            "\u2022 7 remappable buttons (keyboard keys, mouse buttons, DPI cycle, disable).",
            "\u2022 Polling rate, idle timeout, battery readback.",
            "\u2022 All settings written to onboard memory \u2014 no drivers needed, anti-cheat safe.",
            "\u2022 Loadouts: save / load / delete / auto-link per device.",
            "",
            "## How it works",
            "Both use USB HID Feature Reports to read/write the mouse\u2019s onboard memory.",
            "No special drivers, no Synapse, no RedragonSoftware.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 11. OTA FIRMWARE UPDATES
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f504  OTA Firmware Updates", [
            "The helper app can push firmware updates to both boards without re-flashing.",
            "",
            "## How to update",
            "1) Connect to the ESP32-S3 via COM port.",
            "2) Use the Loadout tab \u2192 Firmware Update section.",
            "3) Click 'Check firmware versions' to query the boards and check GitHub.",
            "4) If an update is available, click 'Update firmware'. Release notes are shown.",
            "5) The app downloads, verifies (SHA-256), and flashes the binary over serial.",
            "",
            "## Flash from file",
            "Click 'Flash from file\u2026' to pick a local .bin and flash it directly.",
            "The board is auto-detected from the filename. SHA-256 is displayed before flashing.",
            "",
            "## Integrity & rollback",
            "\u2022 Downloaded firmware is verified against sha256sums.txt (if published in the release).",
            "\u2022 Downloads retry up to 3 times with exponential backoff on network errors.",
            "\u2022 After flashing, the new firmware must validate itself on first boot.",
            "\u2022 If validation fails, the bootloader automatically rolls back to the previous version.",
            "",
            "## Requirements",
            "\u2022 Both firmwares must have OTA partitions configured (partitions.csv).",
            "\u2022 The ESP32-S3 relays ESP32 updates over the UART link.",
            "\u2022 Do NOT interrupt power during an OTA update.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 12. TROUBLESHOOTING
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f527  Troubleshooting", [
            "## No COM port found",
            "\u2022 Check USB cable (some are charge-only, no data).",
            "\u2022 Install the USB-to-UART driver (CP210x or CH340).",
            "\u2022 Check Device Manager for the COM port number.",
            "\u2022 Make sure CDC-ACM is enabled in the ESP32-S3 firmware.",
            "",
            "## ESP32-S3 doesn\u2019t show up as a keyboard",
            "\u2022 Confirm you flashed firmware/esp32s3-usb-kbd/ (target esp32s3).",
            "\u2022 If you changed TinyUSB descriptors, check enumeration matches expectations.",
            "",
            "## UART garbage / nothing received",
            "\u2022 Confirm GND is connected between both boards.",
            "\u2022 Confirm baud rate is 115200 on both ends.",
            "\u2022 Confirm TX \u2192 RX (not TX \u2192 TX).",
            "\u2022 Confirm correct GPIO numbers (Arduino Nano labels \u2260 ESP32-S3 GPIO numbers).",
            "\u2022 For Nano ESP32: RX0 = GPIO44, TX0 = GPIO43.",
            "",
            "## Controller not found over Bluetooth",
            "\u2022 Increase discovery scan time in menuconfig.",
            "\u2022 Set \u201cTarget device name substring\u201d to match your controller\u2019s name.",
            "\u2022 Confirm your controller uses Bluetooth Classic HID (not just BLE).",
            "\u2022 Put the controller into pairing mode (hold sync button).",
            "",
            "## Helper app doesn\u2019t connect",
            "\u2022 Select the correct COM port and click Connect.",
            "\u2022 If the port is busy, close other apps using it (idf.py monitor, etc.).",
            "\u2022 Try unplugging and re-plugging the ESP32-S3.",
            "",
            "## Random disconnects / missed key presses",
            "\u2022 Check wiring: short UART wires, solid GND connection.",
            "\u2022 Make sure you\u2019re not double-powering the ESP32 (USB + VIN both live).",
            "\u2022 Check for EMI (keep UART wires away from motors/power cables).",
            "",
            "## Initial flash: 'Could not detect chip'",
            "\u2022 Is the board in download mode? Hold BOOT, press RESET, release BOOT.",
            "\u2022 Some boards auto-enter download mode via USB \u2014 try without the button dance.",
            "\u2022 Check the USB cable \u2014 charge-only cables won\u2019t work (no data lines).",
            "\u2022 Close any app using the COM port (idf.py monitor, PuTTY, serial terminals).",
            "\u2022 Try a different USB port on your PC (front vs back panel).",
            "",
            "## Initial flash: verification failed",
            "\u2022 The data written does not match what was read back.",
            "\u2022 Try a shorter/better USB cable \u2014 long or cheap cables cause data errors.",
            "\u2022 The board\u2019s flash chip may be damaged \u2014 try a different board.",
            "",
            "## Initial flash: 'esptool is not installed'",
            "\u2022 Run: pip install esptool>=4.7",
            "\u2022 If using the standalone .exe, ensure the build bundles esptool.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 13. APP INSTALL / UPDATE
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f4e6  Installing / Updating the Helper App", [
            "## From source (development)",
            "  python -m venv .venv",
            "  .\\.venv\\Scripts\\Activate.ps1",
            "  pip install -r requirements.txt",
            "  python -m joycon_helper",
            "",
            "## Requirements",
            "\u2022 Python 3.10 or later.",
            "\u2022 Pillow (pip install Pillow) \u2014 for image compositing.",
            "\u2022 pyserial (pip install pyserial) \u2014 for COM port communication.",
            "\u2022 hidapi (pip install hidapi) \u2014 for M913/Razer mouse USB HID access.",
            "",
            "## Standalone executable",
            "Pre-built .exe bundles are available from GitHub Releases.",
            "The app auto-checks for updates on startup.",
            "",
            "## Themes",
            "\u2022 Default theme: warm sketchbook / paper aesthetic (light).",
            "\u2022 Dark theme: dark blue-grey with chalk accents.",
            "\u2022 Toggle via the dark mode switch in the toolbar.",
        ])

        # ══════════════════════════════════════════════════════════════
        # 14. QUICK REFERENCE CARD
        # ══════════════════════════════════════════════════════════════
        _add("\U0001f4cb  Quick Reference", [
            "## Board pinouts",
            "  ESP32 TX = GPIO17     ESP32 RX = GPIO16",
            "  Nano RX0 = GPIO44    Nano TX0 = GPIO43",
            "  UART baud = 115200",
            "",
            "## Minimum wiring",
            "  ESP32-S3 5V/VUSB  \u2192  ESP32 VIN/5V",
            "  ESP32-S3 GND      \u2192  ESP32 GND",
            "  ESP32 GPIO17 (TX) \u2192  ESP32-S3 GPIO44 (RX)",
            "",
            "## Firmware flash commands",
            "  ESP32-S3: idf.py set-target esp32s3 && idf.py build && idf.py flash monitor",
            "  ESP32:    idf.py set-target esp32   && idf.py build && idf.py flash monitor",
            "",
            "## Helper app",
            "  python -m joycon_helper",
            "",
            "## Controller tab shortcuts",
            "  Click hotspot        \u2014  Select + start press-to-steal",
            "  Right-click hotspot  \u2014  Context menu (steal, case, reset\u2026)",
            "  Escape during steal  \u2014  Cancel press-to-steal",
            "  Restore\u2026 button     \u2014  Revert to last written config",
            "  Mask tabs (below diagram)   \u2014  Switch active editing mask",
            "",
            "## Key docs",
            "  docs/wiring.md            \u2014 detailed wiring guide",
            "  docs/firmware-install.md   \u2014 full flashing walkthrough",
            "  docs/serial-protocol.md    \u2014 UART + serial protocol spec",
            "  docs/keymap.md             \u2014 key_id \u2192 USB output mapping",
            "  helper-app/protocol.md     \u2014 helper app NDJSON protocol",
        ])

        # ── Wire up search filtering ──────────────────────────────────
        def _filter_sections(*_args: Any) -> None:
            query = search_var.get().strip().lower()
            for wrapper, title in zip(self._help_sections, self._help_section_titles):
                if not query or query in title:
                    wrapper.pack(fill=tk.X, padx=4, pady=(4, 0))
                else:
                    # Check body text labels too
                    found = False
                    for child in wrapper.winfo_children():
                        for sub in child.winfo_children():
                            try:
                                txt = sub.cget("text").lower()
                                if query in txt:
                                    found = True
                                    break
                            except Exception:
                                pass
                        if found:
                            break
                    if found:
                        wrapper.pack(fill=tk.X, padx=4, pady=(4, 0))
                    else:
                        wrapper.pack_forget()
            content.update_idletasks()
            help_canvas.configure(scrollregion=help_canvas.bbox("all"))

        search_var.trace_add("write", _filter_sections)

        # Bind mouse-wheel to all children after building
        content.update_idletasks()
        _bind_wheel(content)

    # ── M913 helpers ──

    def _m913_scan_devices(self) -> None:
        """Scan for connected M913 mice."""
        self._m913_devices = m913_device.M913Device.enumerate()
        names = [d.display_name for d in self._m913_devices]
        self._m913_dev_combo["values"] = names
        if names:
            self._m913_dev_combo.current(0)
            self._m913_status_var.set(f"Found {len(names)} M913 device(s)")
            self._m913_set_image_state("connected")
        else:
            self._m913_dev_var.set("")
            self._m913_status_var.set("No M913 devices found — is the receiver plugged in?")
            self._m913_set_image_state("none")

    def _m913_on_device_selected(self) -> None:
        """When a device is selected in the combo, load any saved profile."""
        idx = self._m913_dev_combo.current()
        if idx < 0 or idx >= len(self._m913_devices):
            return
        dev_info = self._m913_devices[idx]
        dev_id = dev_info.device_id
        reg = self._m913_registry.get(dev_id, {})
        linked_profile = reg.get("profile")
        if linked_profile:
            try:
                self._m913_profile = m913_device.load_profile(linked_profile)
                self._m913_ui_from_profile()
                self._m913_status_var.set(f"Loaded profile '{linked_profile}' for {dev_info.display_name}")
                return
            except Exception:
                pass
        self._m913_status_var.set(f"Selected {dev_info.display_name} (no saved profile)")

    def _m913_on_sister_changed(self) -> None:
        """Update sister slot linkage."""
        val = self._m913_sister_var.get()
        if val.startswith("Slot "):
            try:
                self._m913_profile.sister_slot = int(val.split()[-1])
            except ValueError:
                self._m913_profile.sister_slot = None
        else:
            self._m913_profile.sister_slot = None

    def _m913_on_layout_changed(self) -> None:
        """Switch button display names and overlay image when layout mode changes."""
        selected = self._m913_layout_var.get()
        mode = self._m913_layout_reverse.get(selected, "stock")
        self._m913_profile.layout = mode
        # Enable/disable the Edit Map button
        if hasattr(self, "_m913_edit_layout_btn"):
            self._m913_edit_layout_btn.state(
                ["!disabled"] if mode == "incedius" else ["disabled"])
        display_names = self._m913_resolved_display_names(mode)
        for btn_name, lbl in self._m913_button_labels.items():
            lbl.configure(text=f"{display_names.get(btn_name, btn_name)}:")

        # Reload overlay image to match the selected layout.
        self._m913_img_paths = self._find_m913_png_variants(mode)
        self._m913_img_base = None
        self._m913_img_scaled = None
        self._m913_img_path = None
        self._m913_pil_base = None
        self._m913_set_image_state(self._m913_img_state)

    def _m913_resolved_display_names(self, mode: str) -> Dict[str, str]:
        """Return the effective display-name dict for the given layout mode.

        For 'incedius', overlays the user's custom ``incedius_map`` on top
        of the fixed names (left/right/middle/fire stay constant).
        """
        if mode == "incedius":
            names: Dict[str, str] = {
                "left": "Left Click", "right": "Right Click",
                "middle": "Middle Click", "fire": "Fire",
            }
            names.update(self._m913_profile.incedius_map)
            return names
        return dict(m913_device.BUTTON_DISPLAY_NAMES)

    def _m913_edit_incedius_map(self) -> None:
        """Open a dialog to reassign IncediusMod labels to physical M913 side buttons."""
        dlg = tk.Toplevel(self)
        dlg.title("Edit IncediusMod Button Map")
        dlg.geometry("380x460")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        ttk.Label(dlg, text="Assign each M913 side button to the matching\n"
                            "physical position on your IncediusMod mouse.",
                  justify="center").pack(padx=10, pady=(10, 6))

        frame = ttk.Frame(dlg)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        current_map = dict(self._m913_profile.incedius_map)
        combo_vars: Dict[str, tk.StringVar] = {}
        combos: Dict[str, ttk.Combobox] = {}

        for i, key in enumerate(m913_device.INCEDIUS_SIDE_KEYS):
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            stock_label = m913_device.BUTTON_DISPLAY_NAMES.get(key, key)
            ttk.Label(row, text=f"{stock_label}  →", width=12, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=current_map.get(key, m913_device.DEFAULT_INCEDIUS_MAP[key]))
            combo_vars[key] = var
            cb = ttk.Combobox(row, textvariable=var,
                              values=m913_device.INCEDIUS_LABEL_CHOICES,
                              state="readonly", width=14)
            cb.pack(side=tk.LEFT, padx=4)
            combos[key] = cb

        status_var = tk.StringVar(value="")
        ttk.Label(dlg, textvariable=status_var, foreground="red").pack(pady=(2, 0))

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=(4, 10))

        def _on_reset() -> None:
            for key in m913_device.INCEDIUS_SIDE_KEYS:
                combo_vars[key].set(m913_device.DEFAULT_INCEDIUS_MAP[key])
            status_var.set("")

        def _on_save() -> None:
            new_map: Dict[str, str] = {}
            used_labels: Dict[str, str] = {}
            for key in m913_device.INCEDIUS_SIDE_KEYS:
                label = combo_vars[key].get()
                if label in used_labels:
                    status_var.set(
                        f"Duplicate: {label} is assigned to both "
                        f"{m913_device.BUTTON_DISPLAY_NAMES[used_labels[label]]} "
                        f"and {m913_device.BUTTON_DISPLAY_NAMES[key]}")
                    return
                used_labels[label] = key
                new_map[key] = label
            self._m913_profile.incedius_map = new_map
            self._m913_on_layout_changed()
            dlg.destroy()

        ttk.Button(btn_row, text="Reset to Default", command=_on_reset).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Save", command=_on_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=6)

    def _m913_ui_to_profile(self) -> None:
        """Sync UI widget values into self._m913_profile."""
        p = self._m913_profile
        p.name = self._m913_prof_name_var.get().strip() or "Default"
        selected_layout = self._m913_layout_var.get()
        p.layout = self._m913_layout_reverse.get(selected_layout, "stock")
        for btn_name, var in self._m913_button_vars.items():
            p.buttons[btn_name] = var.get().strip().lower() or "none"
        p.dpi_values = [max(100, min(16000, v.get())) for v in self._m913_dpi_vars]
        p.dpi_enabled = [v.get() for v in self._m913_dpi_en_vars]
        p.led_mode = self._m913_led_mode_var.get()
        try:
            p.led_color = int(self._m913_led_color_var.get().strip().lstrip("#"), 16)
        except ValueError:
            p.led_color = 0x00FF00
        p.led_brightness = max(0, min(255, self._m913_led_bright_var.get()))
        p.led_speed = max(1, min(5, self._m913_led_speed_var.get()))
        p.polling_rate = self._m913_poll_var.get()

    def _m913_ui_from_profile(self) -> None:
        """Sync self._m913_profile values into UI widgets."""
        p = self._m913_profile
        self._m913_prof_name_var.set(p.name)
        for btn_name, var in self._m913_button_vars.items():
            var.set(p.buttons.get(btn_name, "none"))
        for i in range(5):
            self._m913_dpi_vars[i].set(p.dpi_values[i])
            self._m913_dpi_en_vars[i].set(p.dpi_enabled[i])
        self._m913_led_mode_var.set(p.led_mode)
        self._m913_led_color_var.set(f"{p.led_color:06x}")
        self._m913_led_bright_var.set(p.led_brightness)
        self._m913_led_speed_var.set(p.led_speed)
        self._m913_poll_var.set(p.polling_rate)
        if p.sister_slot:
            self._m913_sister_var.set(f"Slot {p.sister_slot}")
        else:
            self._m913_sister_var.set("None")
        # Layout mode
        display = self._m913_layout_display.get(p.layout, "Stock M913")
        self._m913_layout_var.set(display)
        self._m913_on_layout_changed()

    def _m913_apply_config(self) -> None:
        """Apply current UI settings to the selected M913 mouse."""
        idx = self._m913_dev_combo.current()
        if idx < 0 or idx >= len(self._m913_devices):
            self._m913_status_var.set("No device selected")
            return
        dev_info = self._m913_devices[idx]
        self._m913_ui_to_profile()

        dev = m913_device.M913Device()
        try:
            dev.open(dev_info)
            sent, errors = dev.apply_profile(self._m913_profile)
            if errors:
                self._m913_status_var.set(f"Applied with {errors} error(s) — {sent} packets sent")
            else:
                self._m913_status_var.set(f"Applied successfully — {sent} packets sent to {dev_info.display_name}")
            self._log_append(f"[M913] Config applied to {dev_info.display_name}: {sent} packets, {errors} errors")
        except Exception as e:
            self._m913_status_var.set(f"Error: {e}")
            self._log_append(f"[M913] Apply error: {e}")
        finally:
            dev.close()

    def _m913_save_profile(self) -> None:
        """Save current settings as an M913 profile."""
        self._m913_ui_to_profile()
        if not self._m913_profile.name.strip():
            self._m913_profile.name = "Default"
        try:
            path = m913_device.save_profile(self._m913_profile)
            # Update device registry
            idx = self._m913_dev_combo.current()
            if 0 <= idx < len(self._m913_devices):
                dev_id = self._m913_devices[idx].device_id
                self._m913_registry[dev_id] = {"profile": self._m913_profile.name}
                m913_device.save_device_registry(self._m913_registry)
            self._m913_status_var.set(f"Saved profile '{self._m913_profile.name}'")
            self._log_append(f"[M913] Profile saved: {self._m913_profile.name}")
        except Exception as e:
            self._m913_status_var.set(f"Save error: {e}")

    def _m913_load_profile(self) -> None:
        """Show a dialog to load a saved M913 profile."""
        saved = m913_device.list_saved_profiles()
        if not saved:
            self._m913_status_var.set("No saved M913 profiles found")
            return
        name = simpledialog.askstring("Load M913 Profile",
                                      f"Enter profile name:\nAvailable: {', '.join(saved)}",
                                      parent=self)
        if not name or name not in saved:
            return
        try:
            self._m913_profile = m913_device.load_profile(name)
            self._m913_ui_from_profile()
            self._m913_status_var.set(f"Loaded profile '{name}'")
        except Exception as e:
            self._m913_status_var.set(f"Load error: {e}")

    def _m913_delete_profile(self) -> None:
        """Delete a saved M913 profile."""
        saved = m913_device.list_saved_profiles()
        if not saved:
            self._m913_status_var.set("No saved profiles to delete")
            return
        name = simpledialog.askstring("Delete M913 Profile",
                                      f"Enter profile name to delete:\nAvailable: {', '.join(saved)}",
                                      parent=self)
        if not name or name not in saved:
            return
        if messagebox.askyesno("Confirm Delete", f"Delete M913 profile '{name}'?"):
            m913_device.delete_profile(name)
            self._m913_status_var.set(f"Deleted profile '{name}'")

    # ------------------------------------------------------------------
    # Razer Mouse Tab
    # ------------------------------------------------------------------

    def _build_razer_tab(self) -> None:
        """Build the Razer tab: device selection + dominant overlay + popup panels."""
        parent = self.tab_razer

        # ── Instance state ──
        self._razer_devices: List[razer_device.RazerDeviceInfo] = []
        self._razer_open_dev: Optional[razer_device.RazerDevice] = None
        self._razer_profile = razer_device.RazerProfile()
        self._razer_button_vars: Dict[str, tk.StringVar] = {}
        self._razer_dpi_stage_x_vars: List[tk.IntVar] = []
        self._razer_dpi_stage_y_vars: List[tk.IntVar] = []
        self._razer_state: Optional[razer_device.RazerDeviceState] = None
        self._razer_registry = razer_device.load_device_registry()

        # ── Compact toolbar: device + popup triggers ──
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, padx=6, pady=(6, 2))

        ttk.Label(toolbar, text="Device:").pack(side=tk.LEFT)
        self._razer_dev_var = tk.StringVar()
        self._razer_dev_combo = ttk.Combobox(toolbar, textvariable=self._razer_dev_var,
                                             state="readonly", width=24)
        self._razer_dev_combo.pack(side=tk.LEFT, padx=(4, 4))
        self._razer_dev_combo.bind("<<ComboboxSelected>>",
                                   lambda _: self._razer_on_device_selected())

        ttk.Button(toolbar, text="Scan", command=self._razer_scan_devices).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Read State", command=self._razer_read_state).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Apply", command=self._razer_apply_config).pack(side=tk.LEFT, padx=2)

        sep = ttk.Separator(toolbar, orient=tk.VERTICAL)
        sep.pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # Popup trigger buttons
        ttk.Button(toolbar, text="DPI\u2026",
                   command=lambda: self._razer_dpi_popup.toggle()).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Buttons\u2026",
                   command=lambda: self._razer_buttons_popup.toggle()).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Settings\u2026",
                   command=lambda: self._razer_settings_popup.toggle()).pack(side=tk.LEFT, padx=2)

        if not razer_device.HID_AVAILABLE:
            ttk.Label(parent, text="\u26a0 hidapi not installed \u2014 pip install hidapi",
                      foreground=self._colors.get("danger", "red")).pack(padx=6, pady=2)

        # ── Device info bar (compact) ──
        info_bar = ttk.Frame(parent)
        info_bar.pack(fill=tk.X, padx=6)
        ttk.Label(info_bar, text="FW:").pack(side=tk.LEFT)
        self._razer_fw_var = tk.StringVar(value="\u2014")
        ttk.Label(info_bar, textvariable=self._razer_fw_var, width=8).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(info_bar, text="Serial:").pack(side=tk.LEFT)
        self._razer_serial_var = tk.StringVar(value="\u2014")
        ttk.Label(info_bar, textvariable=self._razer_serial_var, width=16).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(info_bar, text="Battery:").pack(side=tk.LEFT)
        self._razer_battery_var = tk.StringVar(value="\u2014")
        ttk.Label(info_bar, textvariable=self._razer_battery_var, width=10).pack(side=tk.LEFT, padx=2)

        # ── Razer overlay canvas: DOMINANT ──
        self._razer_overlay_canvas = tk.Canvas(parent, highlightthickness=1)
        self._razer_overlay_canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=(3, 3))
        try:
            self._razer_overlay_canvas.configure(
                bg=self._colors.get("panel2", "#f2e8d0"),
                highlightbackground=self._colors.get("border", "#b09878"),
            )
        except Exception:
            pass
        self._razer_overlay_canvas.bind("<Configure>", lambda _e: self._razer_redraw_overlay())
        self._razer_img_paths = self._find_razer_png_variants()
        self._razer_set_image_state("none")

        # ── Status ──
        self._razer_status_var = tk.StringVar(value="Ready \u2014 click Scan to detect Razer devices")
        ttk.Label(parent, textvariable=self._razer_status_var).pack(anchor="w", padx=6, pady=(0, 4))

        # ── Build popup panels ──
        self._build_razer_dpi_popup()
        self._build_razer_buttons_popup()
        self._build_razer_settings_popup()

        # Auto-scan on tab open
        self.after(200, self._razer_scan_devices)

    # ------------------------------------------------------------------
    # Razer popup panels
    # ------------------------------------------------------------------

    def _build_razer_dpi_popup(self) -> None:
        """Popup: DPI stages (5 levels, X/Y per stage)."""
        self._razer_dpi_popup = SketchPopup(
            self, title="DPI Stages (5 levels)", colors=self._colors,
            typo=self._typo, width=380, height=220)
        body = self._razer_dpi_popup.body

        self._razer_dpi_stage_x_vars = []
        self._razer_dpi_stage_y_vars = []
        self._razer_dpi_active_var = tk.IntVar(value=self._razer_profile.active_dpi_stage)
        for i in range(5):
            r = ttk.Frame(body)
            r.pack(fill=tk.X, pady=1)
            dx, dy = self._razer_profile.dpi_stages[i] if i < len(self._razer_profile.dpi_stages) else (800, 800)
            ttk.Radiobutton(r, text=f"Stage {i + 1}:", value=i + 1,
                            variable=self._razer_dpi_active_var).pack(side=tk.LEFT)
            ttk.Label(r, text="X:").pack(side=tk.LEFT, padx=(6, 0))
            xvar = tk.IntVar(value=dx)
            self._razer_dpi_stage_x_vars.append(xvar)
            ttk.Spinbox(r, from_=100, to=26000, increment=100,
                        textvariable=xvar, width=7).pack(side=tk.LEFT, padx=2)
            ttk.Label(r, text="Y:").pack(side=tk.LEFT, padx=(4, 0))
            yvar = tk.IntVar(value=dy)
            self._razer_dpi_stage_y_vars.append(yvar)
            ttk.Spinbox(r, from_=100, to=26000, increment=100,
                        textvariable=yvar, width=7).pack(side=tk.LEFT, padx=2)

    def _build_razer_buttons_popup(self) -> None:
        """Popup: button remapping."""
        self._razer_buttons_popup = SketchPopup(
            self, title="Button Heist Plan", colors=self._colors,
            typo=self._typo, width=380, height=320)
        body = self._razer_buttons_popup.body

        action_choices = razer_device.REMAP_ACTIONS
        for name in razer_device.BUTTON_ORDER:
            r = ttk.Frame(body)
            r.pack(fill=tk.X, pady=1)
            display = razer_device.BUTTON_DISPLAY_NAMES.get(name, name)
            ttk.Label(r, text=f"{display}:", width=16, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=self._razer_profile.button_bindings.get(name, "default"))
            self._razer_button_vars[name] = var
            cb = ttk.Combobox(r, textvariable=var, values=action_choices, width=20)
            cb.pack(side=tk.LEFT, padx=4)

    def _build_razer_settings_popup(self) -> None:
        """Popup: polling rate, idle timeout, profile save/load."""
        self._razer_settings_popup = SketchPopup(
            self, title="Razer Settings", colors=self._colors,
            typo=self._typo, width=420, height=220)
        body = self._razer_settings_popup.body

        # Polling rate
        ttk.Label(body, text="Polling Rate:").pack(anchor="w", pady=(4, 2))
        pr = ttk.Frame(body)
        pr.pack(fill=tk.X, pady=(0, 4))
        self._razer_poll_var = tk.IntVar(value=self._razer_profile.poll_rate)
        for hz in (125, 500, 1000):
            ttk.Radiobutton(pr, text=f"{hz} Hz", value=hz,
                            variable=self._razer_poll_var).pack(side=tk.LEFT, padx=6)

        # Idle timeout
        idle_row = ttk.Frame(body)
        idle_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(idle_row, text="Idle timeout (60\u2013900 sec):").pack(side=tk.LEFT)
        self._razer_idle_var = tk.IntVar(value=self._razer_profile.idle_time)
        ttk.Spinbox(idle_row, from_=60, to=900, increment=30,
                    textvariable=self._razer_idle_var, width=7).pack(side=tk.LEFT, padx=4)

        # Profile save/load
        ttk.Label(body, text="Profile:").pack(anchor="w", pady=(0, 2))
        pfr = ttk.Frame(body)
        pfr.pack(fill=tk.X)
        ttk.Label(pfr, text="Name:").pack(side=tk.LEFT)
        self._razer_prof_name_var = tk.StringVar(value=self._razer_profile.name)
        ttk.Entry(pfr, textvariable=self._razer_prof_name_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(pfr, text="Save", command=self._razer_save_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(pfr, text="Load", command=self._razer_load_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(pfr, text="Delete", command=self._razer_delete_profile).pack(side=tk.LEFT, padx=2)

    # ── Razer helpers ────────────────────────────────────────────

    def _razer_scan_devices(self) -> None:
        """Scan for connected Razer mice."""
        self._razer_devices = razer_device.RazerDevice.enumerate()
        names = [d.display_name for d in self._razer_devices]
        self._razer_dev_combo["values"] = names
        if names:
            self._razer_dev_combo.current(0)
            self._razer_status_var.set(f"Found {len(names)} Razer device(s)")
            self._razer_set_image_state("connected")
        else:
            self._razer_dev_var.set("")
            self._razer_status_var.set("No supported Razer devices found")
            self._razer_set_image_state("none")

    def _razer_on_device_selected(self) -> None:
        """Load saved profile when a device is selected."""
        idx = self._razer_dev_combo.current()
        if idx < 0 or idx >= len(self._razer_devices):
            return
        dev_info = self._razer_devices[idx]
        dev_id = dev_info.device_id
        reg = self._razer_registry.get(dev_id, {})
        linked_profile = reg.get("profile")
        if linked_profile:
            try:
                self._razer_profile = razer_device.load_profile(linked_profile)
                self._razer_ui_from_profile()
                self._razer_status_var.set(f"Loaded profile '{linked_profile}' for {dev_info.display_name}")
                return
            except Exception:
                pass
        self._razer_status_var.set(f"Selected {dev_info.display_name} (no saved profile)")

    def _razer_read_state(self) -> None:
        """Read live state from selected device and update UI."""
        idx = self._razer_dev_combo.current()
        if idx < 0 or idx >= len(self._razer_devices):
            self._razer_status_var.set("No device selected")
            return
        dev_info = self._razer_devices[idx]
        dev = razer_device.RazerDevice()
        try:
            dev.open(dev_info)
            state = dev.read_full_state()
            self._razer_state = state
            # Populate info fields
            self._razer_fw_var.set(state.firmware_version or "—")
            self._razer_serial_var.set(state.serial or "—")
            if state.battery_level >= 0:
                charge = " ⚡" if state.battery_charging else ""
                self._razer_battery_var.set(f"{state.battery_level}%{charge}")
            else:
                self._razer_battery_var.set("N/A")
            # Populate profile from live state
            if state.dpi_stages:
                self._razer_profile.dpi_stages = list(state.dpi_stages)
                self._razer_profile.active_dpi_stage = state.active_dpi_stage
            if state.poll_rate:
                self._razer_profile.poll_rate = state.poll_rate
            if state.idle_time:
                self._razer_profile.idle_time = state.idle_time
            if state.button_bindings:
                for name, action in state.button_bindings.items():
                    self._razer_profile.button_bindings[name] = action
            self._razer_ui_from_profile()
            self._razer_status_var.set(f"Read state from {dev_info.display_name}")
            self._log_append(f"[Razer] State read: FW={state.firmware_version}, "
                             f"DPI={state.dpi_x}x{state.dpi_y}, "
                             f"Poll={state.poll_rate}Hz, Battery={state.battery_level}%")
        except Exception as e:
            self._razer_status_var.set(f"Read error: {e}")
            self._log_append(f"[Razer] Read error: {e}")
        finally:
            dev.close()

    def _razer_ui_to_profile(self) -> None:
        """Sync UI values into the profile dataclass."""
        self._razer_profile.name = self._razer_prof_name_var.get().strip() or "Default"
        self._razer_profile.active_dpi_stage = self._razer_dpi_active_var.get()
        stages = []
        for i in range(5):
            x = self._razer_dpi_stage_x_vars[i].get()
            y = self._razer_dpi_stage_y_vars[i].get()
            stages.append((x, y))
        self._razer_profile.dpi_stages = stages
        self._razer_profile.poll_rate = self._razer_poll_var.get()
        self._razer_profile.idle_time = self._razer_idle_var.get()
        for name, var in self._razer_button_vars.items():
            self._razer_profile.button_bindings[name] = var.get()

    def _razer_ui_from_profile(self) -> None:
        """Sync profile values into UI widgets."""
        self._razer_prof_name_var.set(self._razer_profile.name)
        self._razer_dpi_active_var.set(self._razer_profile.active_dpi_stage)
        for i in range(5):
            if i < len(self._razer_profile.dpi_stages):
                dx, dy = self._razer_profile.dpi_stages[i]
            else:
                dx, dy = 800, 800
            self._razer_dpi_stage_x_vars[i].set(dx)
            self._razer_dpi_stage_y_vars[i].set(dy)
        self._razer_poll_var.set(self._razer_profile.poll_rate)
        self._razer_idle_var.set(self._razer_profile.idle_time)
        for name, var in self._razer_button_vars.items():
            var.set(self._razer_profile.button_bindings.get(name, "default"))

    def _razer_apply_config(self) -> None:
        """Apply current UI settings to the selected Razer mouse."""
        idx = self._razer_dev_combo.current()
        if idx < 0 or idx >= len(self._razer_devices):
            self._razer_status_var.set("No device selected")
            return
        dev_info = self._razer_devices[idx]
        self._razer_ui_to_profile()

        dev = razer_device.RazerDevice()
        try:
            dev.open(dev_info)
            ok, errors = dev.apply_profile(self._razer_profile)
            if errors:
                self._razer_status_var.set(f"Applied with {errors} error(s) — {ok} commands ok")
            else:
                self._razer_status_var.set(f"Applied successfully — {ok} commands sent to {dev_info.display_name}")
            self._log_append(f"[Razer] Config applied to {dev_info.display_name}: {ok} ok, {errors} errors")
        except Exception as e:
            self._razer_status_var.set(f"Error: {e}")
            self._log_append(f"[Razer] Apply error: {e}")
        finally:
            dev.close()

    def _razer_save_profile(self) -> None:
        """Save current settings as a Razer profile."""
        self._razer_ui_to_profile()
        if not self._razer_profile.name.strip():
            self._razer_profile.name = "Default"
        try:
            razer_device.save_profile(self._razer_profile)
            idx = self._razer_dev_combo.current()
            if 0 <= idx < len(self._razer_devices):
                dev_id = self._razer_devices[idx].device_id
                self._razer_registry[dev_id] = {"profile": self._razer_profile.name}
                razer_device.save_device_registry(self._razer_registry)
            self._razer_status_var.set(f"Saved profile '{self._razer_profile.name}'")
            self._log_append(f"[Razer] Profile saved: {self._razer_profile.name}")
        except Exception as e:
            self._razer_status_var.set(f"Save error: {e}")

    def _razer_load_profile(self) -> None:
        """Show a dialog to load a saved Razer profile."""
        saved = razer_device.list_saved_profiles()
        if not saved:
            self._razer_status_var.set("No saved Razer profiles found")
            return
        name = simpledialog.askstring("Load Razer Profile",
                                      f"Enter profile name:\nAvailable: {', '.join(saved)}",
                                      parent=self)
        if not name or name not in saved:
            return
        try:
            self._razer_profile = razer_device.load_profile(name)
            self._razer_ui_from_profile()
            self._razer_status_var.set(f"Loaded profile '{name}'")
        except Exception as e:
            self._razer_status_var.set(f"Load error: {e}")

    def _razer_delete_profile(self) -> None:
        """Delete a saved Razer profile."""
        saved = razer_device.list_saved_profiles()
        if not saved:
            self._razer_status_var.set("No saved profiles to delete")
            return
        name = simpledialog.askstring("Delete Razer Profile",
                                      f"Enter profile name to delete:\nAvailable: {', '.join(saved)}",
                                      parent=self)
        if not name or name not in saved:
            return
        if messagebox.askyesno("Confirm Delete", f"Delete Razer profile '{name}'?"):
            razer_device.delete_profile(name)
            self._razer_status_var.set(f"Deleted profile '{name}'")

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        # Save current state to redo stack
        current = self.profile_text.get("1.0", "end").strip()
        desc, snapshot = self._undo_stack.pop()
        self._redo_stack.append((desc, current))
        self._suppress_undo = True
        try:
            self.profile_text.delete("1.0", "end")
            self.profile_text.insert("1.0", snapshot)
            try:
                prof = json.loads(snapshot)
                self._refresh_macro_list()
                self._stick_load_from_profile(prof)
                self._keymap_refresh_visuals()
            except Exception:
                pass
        finally:
            self._suppress_undo = False
        self._update_undo_ui()
        self._play_sound("undo")
        self._log_line(f"[host] Undo: {desc}")

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        current = self.profile_text.get("1.0", "end").strip()
        desc, snapshot = self._redo_stack.pop()
        self._undo_stack.append((desc, current))
        self._suppress_undo = True
        try:
            self.profile_text.delete("1.0", "end")
            self.profile_text.insert("1.0", snapshot)
            try:
                prof = json.loads(snapshot)
                self._refresh_macro_list()
                self._stick_load_from_profile(prof)
                self._keymap_refresh_visuals()
            except Exception:
                pass
        finally:
            self._suppress_undo = False
        self._update_undo_ui()
        self._play_sound("undo")
        self._log_line(f"[host] Redo: {desc}")

    def _update_undo_ui(self) -> None:
        """Update undo/redo button states and history display."""
        try:
            if hasattr(self, "_undo_btn"):
                self._undo_btn.configure(state="normal" if self._undo_stack else "disabled")
            if hasattr(self, "_redo_btn"):
                self._redo_btn.configure(state="normal" if self._redo_stack else "disabled")
            if hasattr(self, "_undo_history_var"):
                if self._undo_stack:
                    last_5 = self._undo_stack[-5:]
                    lines = [f"  {d}" for d, _s in reversed(last_5)]
                    self._undo_history_var.set("History: " + " ← ".join(lines))
                else:
                    self._undo_history_var.set("History: (empty)")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mode indicator / status bar
    # ------------------------------------------------------------------

    def _update_mode_indicator(self) -> None:
        """Update the always-visible status bar at bottom."""
        if not hasattr(self, "_mode_indicator_var"):
            return
        parts = []

        # Connected device
        try:
            if self.client.connected:
                parts.append(f"🔌 {self.port_var.get()}")
            else:
                parts.append("⚠ Disconnected")
        except Exception:
            parts.append("⚠ Disconnected")

        # Active slot
        try:
            parts.append(f"Slot {self.slot_var.get()}")
        except Exception:
            pass

        # Current layer
        try:
            li = self._layer_edit_index.get()
            if li < 0:
                parts.append("🎭 Base Mask")
            else:
                parts.append(f"🎭 Mask {li + 1}")
        except Exception:
            pass

        # Bind mode
        if self._bind_mode:
            parts.append("STEAL MODE")
        elif self._keymap_learn_name:
            parts.append("CASE MODE")

        # Sandbox
        if self._sandbox_active.get():
            parts.append("PRACTICE RUN")

        # Battery level
        if self._battery_level is not None:
            bars = "\u2588" * self._battery_level + "\u2591" * (4 - self._battery_level)
            parts.append(f"\U0001f50b {bars}")

        # BT signal strength
        if self._rssi_dbm is not None:
            rssi = self._rssi_dbm
            if rssi >= -50:
                signal = "\u2588\u2588\u2588\u2588"  # excellent
            elif rssi >= -65:
                signal = "\u2588\u2588\u2588\u2591"  # good
            elif rssi >= -80:
                signal = "\u2588\u2588\u2591\u2591"  # fair
            else:
                signal = "\u2588\u2591\u2591\u2591"  # weak
            parts.append(f"\U0001f4f6 {signal} {rssi}dBm")

        # Latency indicator
        if self._latency_ms is not None:
            parts.append(f"\u23f1 {self._latency_ms:.0f}ms RTT")
        if self._perf_enabled and self._perf_redraw_times:
            avg_ms = sum(self._perf_redraw_times[-10:]) / min(len(self._perf_redraw_times), 10) * 1000
            parts.append(f"⏱ {avg_ms:.0f}ms")

        # UI mode
        parts.append(f"UI: {self._ui_mode.get()}")

        # Undo depth
        if self._undo_stack:
            parts.append(f"Undo: {len(self._undo_stack)}")

        self._mode_indicator_var.set("  │  ".join(parts))

    def _mode_indicator_tick(self) -> None:
        self._update_mode_indicator()
        self.after(300, self._mode_indicator_tick)

    def _latency_ping_tick(self) -> None:
        """Periodically send a ping to measure round-trip latency."""
        if self._ser and self._ser.is_open:
            self._cmd_ping()
        self.after(10000, self._latency_ping_tick)

    # ------------------------------------------------------------------
    # Adaptive UI — simple / advanced mode
    # ------------------------------------------------------------------

    def _toggle_ui_mode(self) -> None:
        if self._ui_mode.get() == "advanced":
            self._ui_mode.set("simple")
            self._ui_mode_btn.configure(text="Advanced mode")
        else:
            self._ui_mode.set("advanced")
            self._ui_mode_btn.configure(text="Simple mode")
        self._apply_ui_mode()

    def _apply_ui_mode(self) -> None:
        """Show/hide widgets based on current UI mode."""
        simple = self._ui_mode.get() == "simple"
        for w in self._advanced_widgets:
            try:
                if simple:
                    w.pack_forget()
                else:
                    w.pack(fill=tk.X, padx=8, pady=(0, 4))
            except Exception:
                pass

        # Hide/show full tabs in simple mode
        try:
            if simple:
                # Hide Macros, Stick, Share tabs (keep Profile, Controller, Input Test, Overlay)
                for tab_name in ("Tricks", "Stick", "Share"):
                    for i in range(self.tabs.index("end")):
                        if self.tabs.tab(i, "text") == tab_name:
                            self.tabs.hide(i)
                            break
            else:
                # Show all tabs
                for i in range(self.tabs.index("end")):
                    self.tabs.add(self.tabs.tabs()[i])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Sandbox mode
    # ------------------------------------------------------------------

    def _toggle_sandbox(self) -> None:
        if self._sandbox_active.get():
            # Entering sandbox: snapshot current profile
            self._sandbox_snapshot = self.profile_text.get("1.0", "end").strip()
            self._log_line("[host] Practice Run ON — changes are temporary")
        else:
            # Exiting sandbox without applying
            if self._sandbox_snapshot is not None:
                confirm = messagebox.askyesno(
                    "Exit Practice Run",
                    "Apply practice run changes to the real loadout?\n\n"
                    "Yes = keep changes\nNo = discard changes",
                )
                if not confirm and self._sandbox_snapshot:
                    self.profile_text.delete("1.0", "end")
                    self.profile_text.insert("1.0", self._sandbox_snapshot)
                    try:
                        prof = json.loads(self._sandbox_snapshot)
                        self._refresh_macro_list()
                        self._stick_load_from_profile(prof)
                        self._keymap_refresh_visuals()
                    except Exception:
                        pass
                    self._log_line("[host] Practice run changes discarded")
                else:
                    self._log_line("[host] Practice run changes applied")
            self._sandbox_snapshot = None

    # ------------------------------------------------------------------
    # Smart Search
    # ------------------------------------------------------------------

    def _on_search_changed(self, *_args: Any) -> None:
        """Filter and highlight hotspots matching the search query."""
        query = self._search_var.get().strip().lower()
        if not query:
            self._search_matches = []
            self._keymap_redraw()
            return

        hs = self._keymap_hotspots()
        matches: List[str] = []

        for name, _nx, _ny in KEYMAP_HOTSPOTS:
            # Match against hotspot name
            if query in name.lower():
                matches.append(name)
                continue

            # Match against output key name
            key_id = hs.get(name)
            if key_id is not None:
                out = self._get_mapping_output(key_id)
                if out is not None:
                    out_name = hid_keycodes.hid_to_name(out[0], out[1]).lower()
                    if query in out_name:
                        matches.append(name)
                        continue

                # Match against mapping type
                try:
                    prof = self._current_profile()
                    entry = prof.get("mappings", {}).get(str(key_id))
                    if isinstance(entry, dict):
                        et = entry.get("type", "")
                        if query in et.lower():
                            matches.append(name)
                            continue
                except Exception:
                    pass

        self._search_matches = matches
        self._keymap_redraw()

    # ------------------------------------------------------------------
    # Guided Mapping Wizard
    # ------------------------------------------------------------------

    # Common action presets for the guided wizard and intent-based mapping
    INTENT_PRESETS: List[Tuple[str, str, int, int]] = [
        # (label, description, mod, keycode)
        ("Move Forward", "W key", 0, 0x1A),
        ("Move Back", "S key", 0, 0x16),
        ("Move Left", "A key", 0, 0x04),
        ("Move Right", "D key", 0, 0x07),
        ("Jump", "Space", 0, 0x2C),
        ("Sprint", "Left Shift", 0x02, 0),
        ("Crouch", "Left Ctrl", 0x01, 0),
        ("Reload", "R key", 0, 0x15),
        ("Interact", "E key", 0, 0x08),
        ("Melee", "V key", 0, 0x19),
        ("Aim / ADS", "Right Mouse (not HID — use custom)", 0, 0),
        ("Open Map", "M key", 0, 0x10),
        ("Inventory", "Tab", 0, 0x2B),
        ("Custom key…", "Press any key to bind", 0, 0),
    ]

    def _open_guided_wizard(self) -> None:
        """Open the guided mapping setup wizard."""
        if self._guided_window is not None:
            try:
                self._guided_window.lift()
            except Exception:
                self._guided_window = None
            if self._guided_window is not None:
                return

        win = tk.Toplevel(self)
        win.title("Guided Setup — Let's set up your controller")
        win.geometry("500x400")
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_guided_wizard(win))
        self._guided_window = win

        colors = self._colors
        win.configure(bg=colors["bg"])

        self._guided_steps = [
            ("Move Forward", "Push the stick or press the button for FORWARD", "D-UP"),
            ("Move Back", "Press the button for BACK", "D-DN"),
            ("Move Left", "Press the button for LEFT", "D-L"),
            ("Move Right", "Press the button for RIGHT", "D-R"),
            ("Jump", "Press the button for JUMP", "A"),
            ("Sprint", "Press the button for SPRINT", "ZL"),
            ("Crouch", "Press the button for CROUCH", "ZR"),
        ]
        self._guided_step_idx = 0
        self._guided_results: List[Tuple[str, str, int]] = []  # (action, hotspot, key_id)

        tk.Label(
            win, text="🎮 Guided Controller Setup",
            bg=colors["bg"], fg=colors["text"],
            font=(self._typo.get("font_family", "Segoe UI"), 14, "bold"),
        ).pack(pady=(16, 8))

        self._guided_prompt_var = tk.StringVar(value="")
        self._guided_progress_var = tk.StringVar(value="")

        tk.Label(
            win, textvariable=self._guided_progress_var,
            bg=colors["bg"], fg=colors["muted"],
            font=(self._typo.get("font_family", "Segoe UI"), 9),
        ).pack()

        tk.Label(
            win, textvariable=self._guided_prompt_var,
            bg=colors["bg"], fg=colors["text"],
            font=(self._typo.get("font_family", "Segoe UI"), 12),
            wraplength=440,
        ).pack(pady=(20, 10))

        self._guided_status_var = tk.StringVar(value="Waiting for controller input…")
        tk.Label(
            win, textvariable=self._guided_status_var,
            bg=colors["bg"], fg=colors["accent2"],
            font=(self._typo.get("font_family", "Segoe UI"), 10),
        ).pack(pady=(10, 0))

        btn_frame = tk.Frame(win, bg=colors["bg"])
        btn_frame.pack(side=tk.BOTTOM, pady=(0, 16))
        ttk.Button(btn_frame, text="Skip this step", command=self._guided_skip).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Cancel", command=lambda: self._close_guided_wizard(win)).pack(side=tk.LEFT)

        self._guided_advance_prompt()

    def _guided_advance_prompt(self) -> None:
        if self._guided_step_idx >= len(self._guided_steps):
            self._guided_finish()
            return

        action, prompt, _hotspot = self._guided_steps[self._guided_step_idx]
        total = len(self._guided_steps)
        self._guided_progress_var.set(f"Step {self._guided_step_idx + 1} of {total}")
        self._guided_prompt_var.set(prompt)
        self._guided_status_var.set("Press the controller button now…")
        # Set learn mode for the guided hotspot
        self._keymap_learn_name = _hotspot
        self._keymap_selected_name = _hotspot
        self._keymap_redraw()

    def _guided_on_input(self, key_id: int) -> None:
        """Called when a controller button is pressed during guided setup."""
        if self._guided_window is None or self._guided_step_idx >= len(self._guided_steps):
            return

        action, _prompt, hotspot = self._guided_steps[self._guided_step_idx]
        self._guided_results.append((action, hotspot, key_id))
        self._guided_status_var.set(f"Got key_id={key_id} for {action}!")

        # Bind the hotspot
        self._keymap_bind_selected(key_id)

        # Apply default mapping for this action
        defaults = {
            "Move Forward": (0, 0x1A),  # W
            "Move Back": (0, 0x16),  # S
            "Move Left": (0, 0x04),  # A
            "Move Right": (0, 0x07),  # D
            "Jump": (0, 0x2C),  # Space
            "Sprint": (0x02, 0),  # Left Shift
            "Crouch": (0x01, 0),  # Left Ctrl
        }
        if action in defaults:
            mod, kc = defaults[action]
            try:
                prof = self._current_profile()
                mappings = prof.setdefault("mappings", {})
                if not isinstance(mappings, dict):
                    mappings = {}
                    prof["mappings"] = mappings
                mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": kc}
                self._set_profile_obj(prof, undo_label=f"guided: {action}")
            except Exception:
                pass

        self._guided_step_idx += 1
        self.after(300, self._guided_advance_prompt)  # Auto-advance quickly

    def _guided_skip(self) -> None:
        self._keymap_learn_name = None
        self._guided_step_idx += 1
        self._guided_advance_prompt()

    def _guided_finish(self) -> None:
        if self._guided_window is None:
            return
        self._guided_prompt_var.set("Setup complete!")
        self._guided_status_var.set(
            f"Mapped {len(self._guided_results)} buttons. You can fine-tune in the Controller tab."
        )
        self._guided_progress_var.set("Done!")
        self._keymap_learn_name = None
        self._keymap_redraw()
        self._log_line(f"[host] Guided setup complete: {len(self._guided_results)} buttons mapped")

    def _close_guided_wizard(self, win: tk.Toplevel) -> None:
        self._keymap_learn_name = None
        self._guided_window = None
        try:
            win.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Calibration Wizard
    # ------------------------------------------------------------------

    def _open_calibration_wizard(self) -> None:
        """Open the stick calibration wizard."""
        if self._cal_window is not None:
            try:
                self._cal_window.lift()
            except Exception:
                self._cal_window = None
            if self._cal_window is not None:
                return

        win = tk.Toplevel(self)
        win.title("Stick Calibration Wizard")
        win.geometry("520x440")
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_cal_wizard(win))
        self._cal_window = win

        colors = self._colors
        win.configure(bg=colors["bg"])

        self._cal_step = 0

        tk.Label(
            win, text="\U0001f3af Stick Calibration",
            bg=colors["bg"], fg=colors["text"],
            font=(self._typo.get("font_family", "Segoe UI"), 14, "bold"),
        ).pack(pady=(16, 4))

        # Current stick info display
        info_frame = tk.Frame(win, bg=colors["bg"])
        info_frame.pack(fill=tk.X, padx=20, pady=(4, 8))

        tk.Label(
            info_frame, text="Current stick parameters from controller:",
            bg=colors["bg"], fg=colors["muted"],
            font=(self._typo.get("font_family", "Segoe UI"), 9),
        ).pack(anchor="w")

        params_frame = tk.Frame(info_frame, bg=colors["bg"])
        params_frame.pack(fill=tk.X, pady=(2, 0))
        tk.Label(params_frame, text=f"Deadzone: ", bg=colors["bg"], fg=colors["text"]).pack(side=tk.LEFT)
        self._cal_dz_label = tk.Label(params_frame, textvariable=self._ctrl_info_deadzone, bg=colors["bg"], fg=colors["accent2"])
        self._cal_dz_label.pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(params_frame, text=f"Range: ", bg=colors["bg"], fg=colors["text"]).pack(side=tk.LEFT)
        self._cal_range_label = tk.Label(params_frame, textvariable=self._ctrl_info_range, bg=colors["bg"], fg=colors["accent2"])
        self._cal_range_label.pack(side=tk.LEFT)

        # Step progress
        self._cal_progress_var = tk.StringVar(value="Step 1 of 3")
        tk.Label(
            win, textvariable=self._cal_progress_var,
            bg=colors["bg"], fg=colors["muted"],
            font=(self._typo.get("font_family", "Segoe UI"), 9),
        ).pack()

        # Prompt
        self._cal_prompt_var = tk.StringVar(value="")
        tk.Label(
            win, textvariable=self._cal_prompt_var,
            bg=colors["bg"], fg=colors["text"],
            font=(self._typo.get("font_family", "Segoe UI"), 12),
            wraplength=460,
        ).pack(pady=(16, 6))

        # Details / instructions
        self._cal_detail_var = tk.StringVar(value="")
        tk.Label(
            win, textvariable=self._cal_detail_var,
            bg=colors["bg"], fg=colors["muted"],
            font=(self._typo.get("font_family", "Segoe UI"), 9),
            wraplength=460,
            justify="left",
        ).pack(pady=(0, 10))

        # Status
        self._cal_status_var = tk.StringVar(value="")
        tk.Label(
            win, textvariable=self._cal_status_var,
            bg=colors["bg"], fg=colors["accent2"],
            font=(self._typo.get("font_family", "Segoe UI"), 10),
        ).pack(pady=(6, 0))

        # Deadzone / curve quick-adjust section
        adj_frame = ttk.LabelFrame(win, text="Quick adjust (applied to profile)")
        adj_frame.pack(fill=tk.X, padx=20, pady=(10, 6))
        adj_row = ttk.Frame(adj_frame)
        adj_row.pack(fill=tk.X, padx=8, pady=4)

        ttk.Label(adj_row, text="Deadzone:").pack(side=tk.LEFT)
        self._cal_dz_scale = tk.Scale(
            adj_row, from_=0.0, to=0.5, resolution=0.01, orient="horizontal",
            variable=self._stick_deadzone, length=100,
        )
        self._cal_dz_scale.pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(adj_row, text="Curve:").pack(side=tk.LEFT)
        self._cal_curve_combo = ttk.Combobox(
            adj_row, textvariable=self._stick_curve,
            values=["linear", "exponential", "soft", "hard"], width=10, state="readonly",
        )
        self._cal_curve_combo.pack(side=tk.LEFT, padx=(4, 12))

        ttk.Label(adj_row, text="Exp:").pack(side=tk.LEFT)
        self._cal_exp_scale = tk.Scale(
            adj_row, from_=0.5, to=3.0, resolution=0.1, orient="horizontal",
            variable=self._stick_curve_exp, length=80,
        )
        self._cal_exp_scale.pack(side=tk.LEFT, padx=(4, 0))

        # Buttons
        btn_frame = tk.Frame(win, bg=colors["bg"])
        btn_frame.pack(side=tk.BOTTOM, pady=(0, 16))
        self._cal_next_btn = ttk.Button(btn_frame, text="Next \u25B6", command=self._cal_next_step)
        self._cal_next_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Cancel", command=lambda: self._close_cal_wizard(win)).pack(side=tk.LEFT)

        self._cal_show_step()

    def _cal_show_step(self) -> None:
        """Update wizard UI for the current calibration step."""
        steps = [
            (
                "Center your stick",
                "Release the analog stick and let it rest at the center position. "
                "The firmware auto-calibration captures the center point.",
                "Let the stick rest at center for a few seconds, then click Next.",
            ),
            (
                "Move stick to all edges",
                "Slowly rotate the stick around the full edge of its range — "
                "a full 360\u00B0 circle. This teaches the firmware the stick's full range of motion.",
                "Move the stick slowly in all directions, then click Next.",
            ),
            (
                "Save or clear calibration",
                "Choose an action:\n"
                "\u2022 Save — persist the current auto-calibration to NVS (survives reboot)\n"
                "\u2022 Clear — erase saved calibration (return to factory defaults)\n"
                "\u2022 Skip — leave calibration as-is",
                "Use the buttons below to save or clear, or click Done to finish.",
            ),
        ]

        if self._cal_step >= len(steps):
            return

        title, prompt, detail = steps[self._cal_step]
        self._cal_progress_var.set(f"Step {self._cal_step + 1} of {len(steps)}")
        self._cal_prompt_var.set(f"{title}")
        self._cal_detail_var.set(detail)

        if self._cal_step < 2:
            self._cal_status_var.set("Follow the instructions, then click Next.")
            self._cal_next_btn.configure(text="Next \u25B6")
        else:
            self._cal_status_var.set("")
            self._cal_next_btn.configure(text="Done \u2714")
            # Add save/clear buttons
            self._cal_add_action_buttons()

    def _cal_add_action_buttons(self) -> None:
        """Add Save / Clear calibration buttons for the final step."""
        if self._cal_window is None:
            return
        colors = self._colors

        action_frame = tk.Frame(self._cal_window, bg=colors["bg"])
        action_frame.pack(pady=(4, 0))
        self._cal_action_frame = action_frame

        ttk.Button(
            action_frame, text="\U0001f4be Save Calibration",
            command=self._cal_cmd_save, width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            action_frame, text="\U0001f5d1 Clear Calibration",
            command=self._cal_cmd_clear, width=18,
        ).pack(side=tk.LEFT)

    def _cal_cmd_save(self) -> None:
        """Send calibration save command to firmware."""
        self._send_cmd({"cmd": "calibration", "action": "save"})
        if self._cal_window:
            self._cal_status_var.set("\u2705 Calibration saved to NVS!")
        self._log_line("[host] Calibration saved via wizard")

    def _cal_cmd_clear(self) -> None:
        """Send calibration clear command to firmware."""
        self._send_cmd({"cmd": "calibration", "action": "clear"})
        if self._cal_window:
            self._cal_status_var.set("\u2705 Calibration cleared (factory defaults).")
        self._log_line("[host] Calibration cleared via wizard")

    def _cal_next_step(self) -> None:
        """Advance to the next calibration step or finish."""
        self._cal_step += 1
        if self._cal_step >= 3:
            self._cal_finish()
            return
        # Clean up action buttons if present from previous step
        if hasattr(self, "_cal_action_frame"):
            try:
                self._cal_action_frame.destroy()
            except Exception:
                pass
        self._cal_show_step()

    def _cal_finish(self) -> None:
        """Close the calibration wizard."""
        if self._cal_window is None:
            return
        self._log_line("[host] Calibration wizard completed")
        self._close_cal_wizard(self._cal_window)

    def _close_cal_wizard(self, win: tk.Toplevel) -> None:
        self._cal_window = None
        try:
            win.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Intent-Based Mapping
    # ------------------------------------------------------------------

    def _show_intent_menu(self, hotspot: str, key_id: int) -> None:
        """Show 'What should this button do?' menu for intent-based mapping."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="─ What should this button do? ─", state="disabled")
        menu.add_separator()

        for label, desc, mod, kc in self.INTENT_PRESETS:
            if label == "Custom key…":
                menu.add_separator()
                menu.add_command(
                    label=f"{label}  ({desc})",
                    command=lambda h=hotspot: self._keymap_context_bind(h),
                )
            elif kc == 0 and mod == 0:
                # Not a valid HID mapping (like "Aim / ADS")
                menu.add_command(label=f"{label}  ({desc})", state="disabled")
            else:
                menu.add_command(
                    label=f"{label}  →  {desc}",
                    command=lambda m=mod, k=kc, lbl=label: self._apply_intent(hotspot, key_id, m, k, lbl),
                )

        try:
            # Show at hotspot position
            px, py = self._keymap_hotspot_px.get(hotspot, (0, 0))
            cx = self._keymap_canvas.winfo_rootx() + int(px)
            cy = self._keymap_canvas.winfo_rooty() + int(py)
            menu.tk_popup(cx, cy)
        except Exception:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _apply_intent(self, hotspot: str, key_id: int, mod: int, keycode: int, label: str) -> None:
        """Apply an intent-based mapping."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings
        mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": keycode}
        self._set_profile_obj(prof, undo_label=f"intent: {label}")
        key_name = hid_keycodes.hid_to_name(mod, keycode)
        self._keymap_status.set(f"Mapped {hotspot} → {label} ({key_name})")
        self._keymap_redraw()

    # ------------------------------------------------------------------
    # Smart Defaults
    # ------------------------------------------------------------------

    def _apply_smart_defaults(self) -> None:
        """Apply sensible default mappings when profile is empty."""
        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.get("mappings", {})
        if isinstance(mappings, dict) and mappings:
            # Profile already has mappings, don't overwrite
            return

        hs = self._keymap_hotspots()
        if not hs:
            return

        defaults: Dict[str, Tuple[int, int]] = {
            "D-UP": (0, 0x1A),  # W
            "D-DN": (0, 0x16),  # S
            "D-L": (0, 0x04),  # A
            "D-R": (0, 0x07),  # D
            "A": (0, 0x2C),  # Space
            "B": (0, 0x08),  # E
            "X": (0, 0x15),  # R
            "Y": (0, 0x19),  # V
            "ZL": (0x02, 0),  # LShift
            "ZR": (0x01, 0),  # LCtrl
        }

        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings

        applied = 0
        for name, (mod, kc) in defaults.items():
            key_id = hs.get(name)
            if key_id is not None and str(key_id) not in mappings:
                mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": kc}
                applied += 1

        if applied > 0:
            self._set_profile_obj(prof, undo_label="smart defaults")
            self._log_line(f"[host] Smart defaults applied: {applied} mappings")

    # ------------------------------------------------------------------
    # Lock Critical Inputs
    # ------------------------------------------------------------------

    def _is_locked(self, hotspot: str) -> bool:
        return hotspot in self._locked_hotspots

    def _check_lock_before_unbind(self, hotspot: str, action: str) -> bool:
        """Return True if the action is allowed. Shows confirmation for locked hotspots."""
        if hotspot not in self._locked_hotspots:
            return True
        return messagebox.askyesno(
            "Locked Input",
            f"'{hotspot}' is marked as a critical input.\n\n"
            f"Are you sure you want to {action}?",
        )

    # ------------------------------------------------------------------
    # Debug Chain View ("Why isn't this working?")
    # ------------------------------------------------------------------

    def _explain_mapping(self, hotspot: str) -> str:
        """Build a human-readable explanation of the full mapping chain for a hotspot."""
        hs = self._keymap_hotspots()
        key_id = hs.get(hotspot)

        lines: List[str] = [f"=== {hotspot} Heist Chain ===", ""]

        if key_id is None:
            lines.append(f"1. Input: {hotspot} — NO key_id learned")
            lines.append("   Status: Not configured. Use Case to assign a controller button.")
            return "\n".join(lines)

        lines.append(f"1. Input: {hotspot} → key_id = {key_id}")

        # Check if active
        if key_id in self._active_key_ids:
            lines.append("   Status: ACTIVE (button is held down)")
        else:
            lines.append("   Status: idle")

        # Check mapping
        try:
            prof = self._current_profile()
        except Exception:
            lines.append("2. Heist plan: ERROR — could not read loadout")
            return "\n".join(lines)

        mappings = prof.get("mappings", {})
        entry = mappings.get(str(key_id)) if isinstance(mappings, dict) else None

        if entry is None or not isinstance(entry, dict):
            lines.append("2. Heist plan: passthrough (default keymap.c)")
            dk = hid_keycodes.DEFAULT_KEYMAP.get(key_id)
            if dk:
                lines.append(f"3. Output: {hid_keycodes.hid_to_name(dk[0], dk[1])}")
                lines.append("   Status: OK — key will be sent via default heist plan")
            else:
                lines.append(f"3. Output: NONE (key_id {key_id} not in default keymap)")
                lines.append("   Status: WARNING — this key_id has no default output")
        else:
            et = entry.get("type", "?")
            lines.append(f"2. Heist plan: {et}")

            if et == "disable":
                lines.append("3. Output: DISABLED — input is ignored")
                lines.append("   Status: Intentionally disabled")
            elif et == "remap_hid":
                mod = entry.get("mod", 0)
                kc = entry.get("keycode", 0)
                lines.append(f"3. Output: {hid_keycodes.hid_to_name(mod, kc)} (mod=0x{mod:02X} keycode=0x{kc:02X})")
                lines.append("   Status: OK — direct HID output")
            elif et == "remap":
                to = entry.get("to", 0)
                dk = hid_keycodes.DEFAULT_KEYMAP.get(to)
                if dk:
                    lines.append(f"3. Output: remap to key_id={to} → {hid_keycodes.hid_to_name(dk[0], dk[1])}")
                else:
                    lines.append(f"3. Output: remap to key_id={to} → NOT IN KEYMAP")
                    lines.append("   Status: WARNING — remap target not in default keymap")
            elif et == "macro":
                mid = entry.get("id", "?")
                lines.append(f"3. Output: triggers trick '{mid}'")
                macros = prof.get("macros", [])
                found = any(m.get("id") == mid for m in macros if isinstance(m, dict))
                if found:
                    lines.append("   Status: OK — trick exists in loadout")
                else:
                    lines.append(f"   Status: ERROR — trick '{mid}' not found in loadout!")
            elif et == "tap_hold":
                tap = entry.get("tap", {})
                hold = entry.get("hold", {})
                hold_ms = entry.get("hold_ms", 300)
                lines.append(f"3. Output (tap <{hold_ms}ms): {tap.get('type', '?')}")
                if isinstance(hold, dict) and hold.get("type") == "remap_hid":
                    hkc = hold.get("keycode", 0)
                    hmod = hold.get("mod", 0)
                    lines.append(f"   Output (hold >={hold_ms}ms): {hid_keycodes.hid_to_name(hmod, hkc)}")
                lines.append("   Status: OK — dual-action mapping")
            elif et == "double_tap":
                single = entry.get("single", {})
                double = entry.get("double", {})
                timeout = entry.get("timeout_ms", 300)
                if isinstance(single, dict):
                    skc = single.get("keycode", 0)
                    smod = single.get("mod", 0)
                    lines.append(f"3. Output (single tap): {hid_keycodes.hid_to_name(smod, skc)}")
                if isinstance(double, dict):
                    dkc = double.get("keycode", 0)
                    dmod = double.get("mod", 0)
                    lines.append(f"   Output (double tap <{timeout}ms): {hid_keycodes.hid_to_name(dmod, dkc)}")
                lines.append("   Status: OK — double-tap mapping")

        # Check for conflicts
        conflicts = self._detect_conflicts()
        for output_key, names in conflicts.items():
            if hotspot in names:
                others = [n for n in names if n != hotspot]
                lines.append(f"")
                lines.append(f"⚠ CONFLICT: Same output '{output_key}' shared with: {', '.join(others)}")

        # Check layer overrides
        layers = prof.get("layers", [])
        if isinstance(layers, list):
            for i, layer in enumerate(layers):
                if isinstance(layer, dict):
                    lm = layer.get("mappings", {})
                    if isinstance(lm, dict) and str(key_id) in lm:
                        lname = layer.get("name", f"Layer {i+1}")
                        lines.append(f"")
                        lines.append(f"Layer override: '{lname}' overrides this key_id")

        return "\n".join(lines)

    def _show_explain_dialog(self, hotspot: str) -> None:
        """Show the mapping explanation in a dialog."""
        text = self._explain_mapping(hotspot)
        win = tk.Toplevel(self)
        win.title(f"Mapping Details — {hotspot}")
        win.geometry("500x350")
        win.attributes("-topmost", True)
        colors = self._colors
        win.configure(bg=colors["bg"])

        txt = ScrolledText(win, height=18, wrap="word")
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._theme_scrolled_text(txt)
        txt.insert("1.0", text)
        txt.configure(state="disabled")

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 8))

    # ── Feedback sounds ──
    _sounds_enabled: bool = True

    # ── Overlay colour helpers ──

    def _overlay_hex(self) -> str:
        """Return the hex colour string for the user's selected overlay colour."""
        name = self._overlay_color_var.get()
        return RAINBOW_COLORS.get(name, RAINBOW_COLORS[DEFAULT_OVERLAY_COLOR])

    def _on_overlay_color_changed(self) -> None:
        """Redraw all canvases when the user changes overlay colour."""
        self._keymap_redraw(force=True)

    def _play_sound(self, kind: str = "bind") -> None:
        """Play a short feedback sound (non-blocking). kind: bind, unbind, error, undo."""
        if not _HAS_WINSOUND or not self._sounds_enabled:
            return
        freq_map = {"bind": (800, 60), "unbind": (400, 60), "error": (300, 120), "undo": (600, 50)}
        freq, dur = freq_map.get(kind, (600, 60))
        threading.Thread(target=winsound.Beep, args=(freq, dur), daemon=True).start()

    # ── Visual bind overlay on canvas ──

    def _show_bind_overlay(self, hotspot_name: str, key_id: int) -> None:
        """Draw a floating 'Press a key...' card on the controller canvas."""
        c = self._keymap_canvas
        if not c:
            return
        self._hide_bind_overlay()
        colors = self._colors
        typo = self._typo
        font_fam = typo.get("font_family", "Segoe Print")

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)
        cx, cy = w // 2, h // 2

        # Position near the hotspot if visible
        pos = self._keymap_hotspot_px.get(hotspot_name)
        if pos:
            cx = int(pos[0])
            cy = max(60, int(pos[1]) - 50)

        card_w, card_h = 260, 72
        x1, y1 = cx - card_w // 2, cy - card_h // 2
        x2, y2 = cx + card_w // 2, cy + card_h // 2

        # Clamp to canvas bounds
        if x1 < 4:
            x1, x2 = 4, 4 + card_w
        if x2 > w - 4:
            x1, x2 = w - 4 - card_w, w - 4
        if y1 < 4:
            y1, y2 = 4, 4 + card_h
        if y2 > h - 4:
            y1, y2 = h - 4 - card_h, h - 4

        tag = "bind_overlay"
        # Shadow
        self._bind_overlay_items.append(
            c.create_rectangle(x1 + 3, y1 + 3, x2 + 3, y2 + 3,
                               fill="#00000030", outline="", tags=tag))
        # Card background
        bg = colors.get("panel", "#f2e8d0")
        border = colors.get("accent", "#4a6480")
        self._bind_overlay_items.append(
            c.create_rectangle(x1, y1, x2, y2, fill=bg, outline=border, width=2, tags=tag))
        # Title
        self._bind_overlay_items.append(
            c.create_text((x1 + x2) // 2, y1 + 18,
                          text=f"\u2328  Press a key to steal {hotspot_name}",
                          fill=colors.get("text", "#2a1f0e"),
                          font=(font_fam, 10, "bold"), tags=tag))
        # Subtitle
        self._bind_overlay_items.append(
            c.create_text((x1 + x2) // 2, y1 + 40,
                          text=f"key_id={key_id}  \u00b7  Escape to cancel",
                          fill=colors.get("muted", "#6b5d48"),
                          font=(font_fam, 8), tags=tag))
        # Decorative ink dash line
        self._bind_overlay_items.append(
            c.create_line(x1 + 12, y1 + 56, x2 - 12, y1 + 56,
                          fill=colors.get("border", "#b09878"), dash=(6, 4), tags=tag))

    def _hide_bind_overlay(self) -> None:
        """Remove the bind overlay from the canvas."""
        c = self._keymap_canvas
        if c:
            c.delete("bind_overlay")
        self._bind_overlay_items.clear()

    # ── Ink-stamp animation on bind complete ──

    def _start_ink_stamp(self, hotspot_name: str, label: str) -> None:
        """Start a brief ink-stamp animation at the given hotspot."""
        pos = self._keymap_hotspot_px.get(hotspot_name)
        if not pos:
            return
        cx, cy = int(pos[0]), int(pos[1])
        self._ink_stamp_anim = {
            "cx": cx, "cy": cy, "phase": 0, "label": label,
            "max_phase": 8, "after_id": None,
        }
        self._ink_stamp_tick()

    def _ink_stamp_tick(self) -> None:
        """Animate one frame of the ink-stamp effect."""
        anim = self._ink_stamp_anim
        if anim is None:
            return
        c = self._keymap_canvas
        if not c:
            self._ink_stamp_anim = None
            return

        c.delete("ink_stamp")
        phase = anim["phase"]
        max_phase = anim["max_phase"]

        if phase > max_phase:
            c.delete("ink_stamp")
            self._ink_stamp_anim = None
            return

        cx, cy = anim["cx"], anim["cy"]
        t = phase / max_phase  # 0..1

        # Expanding ring that fades out
        radius = int(14 + 30 * t)
        alpha_approx = max(0.0, 1.0 - t * 1.2)
        ring_col = _blend_hex(self._overlay_hex(), self._colors.get("bg", "#e8d8b8"), 1.0 - alpha_approx)
        c.create_oval(
            cx - radius, cy - radius, cx + radius, cy + radius,
            outline=ring_col, width=max(1, int(3 * (1 - t))), dash=(4, 2), tags="ink_stamp",
        )

        # "Stamp" label floats upward and fades
        label_y = cy - 30 - int(20 * t)
        text_col = _blend_hex(self._overlay_hex(), self._colors.get("bg", "#e8d8b8"), t * 0.8)
        c.create_text(
            cx, label_y, text=f"STOLEN \u00b7 {anim['label']}",
            fill=text_col,
            font=(self._typo.get("font_family", "Segoe Print"), 9, "bold"),
            tags="ink_stamp",
        )

        anim["phase"] = phase + 1
        anim["after_id"] = self.after(50, self._ink_stamp_tick)

    # ── Hover glow effect on hotspots ──

    def _update_hover_glow(self, name: Optional[str]) -> None:
        """Draw or clear the hover glow ring around a hotspot."""
        if name == self._hover_glow_name:
            return
        self._hover_glow_name = name
        c = self._keymap_canvas
        if not c:
            return

        # Clear previous glow
        c.delete("hover_glow")
        self._hover_glow_items.clear()

        if name is None:
            return
        pos = self._keymap_hotspot_px.get(name)
        if not pos:
            return
        px, py = pos
        colors = self._colors
        radius = max(14, int(min(
            getattr(self, "_keymap_overlay_w", 400),
            getattr(self, "_keymap_overlay_h", 300),
        ) * 0.02))

        # Outer glow ring (soft, larger)
        glow_r = radius + 8
        glow_col = _blend_hex(self._overlay_hex(), colors.get("bg", "#e8d8b8"), 0.4)
        self._hover_glow_items.append(
            c.create_oval(
                px - glow_r, py - glow_r, px + glow_r, py + glow_r,
                outline=glow_col, width=3, dash=(3, 3), tags="hover_glow",
            ))
        # Inner highlight ring
        inner_r = radius + 3
        inner_col = self._overlay_hex()
        self._hover_glow_items.append(
            c.create_oval(
                px - inner_r, py - inner_r, px + inner_r, py + inner_r,
                outline=inner_col, width=2, tags="hover_glow",
            ))

    # ── Last-known-good profile (safety) ──

    def _save_last_good_profile(self) -> None:
        """Snapshot the current profile as the last-known-good state."""
        try:
            raw = self.profile_text.get("1.0", "end").strip()
            if raw:
                self._last_good_profile = raw
        except Exception:
            pass

    def _restore_last_good_profile(self) -> None:
        """Restore the last-known-good profile snapshot."""
        if not self._last_good_profile:
            messagebox.showinfo("No backup", "No last-known-good loadout saved yet.\n\n"
                                "A snapshot is saved automatically each time the loadout\n"
                                "is successfully written to the device.")
            return
        if not messagebox.askyesno("Restore",
                                   "Restore the last loadout that was successfully written to the device?\n\n"
                                   "Current loadout will be replaced (undo is available)."):
            return
        try:
            obj = json.loads(self._last_good_profile)
            self._set_profile_obj(obj, undo_label="restore last good")
            self._keymap_redraw()
            self._kbd_redraw()
            self._keymap_status.set("Restored last-known-good loadout.")
            self._play_sound("undo")
        except Exception as e:
            messagebox.showerror("Restore failed", str(e))

    def _keymap_bind_selected(self, key_id: int) -> None:
        if not self._keymap_learn_name:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return

        ui = prof.setdefault("ui", {})
        if not isinstance(ui, dict):
            ui = {}
            prof["ui"] = ui
        hs = ui.setdefault("hotspots", {})
        if not isinstance(hs, dict):
            hs = {}
            ui["hotspots"] = hs

        hs[self._keymap_learn_name] = int(key_id)
        learned_name = self._keymap_learn_name
        self._keymap_learn_name = None
        self._keymap_selected_name = learned_name
        self._set_profile_obj(prof)

        self._mapping_key_id.set(str(int(key_id)))
        self._mapping_load_from_profile(int(key_id))
        self._keymap_status.set(f"STOLEN · {learned_name} → key_id={int(key_id)}")
        self._play_sound("bind")

        # Auto-advance: select the next unbound hotspot for fast sequential mapping.
        if self._guided_window is None:
            self._auto_advance_to_next_unbound(learned_name)

    def _auto_advance_to_next_unbound(self, current_name: str) -> None:
        """Select the next unbound hotspot in the KEYMAP_HOTSPOTS order."""
        hs = self._keymap_hotspots()
        names = [n for n, _x, _y in KEYMAP_HOTSPOTS]
        try:
            idx = names.index(current_name)
        except ValueError:
            return
        # Scan forward from current+1, wrapping around
        for offset in range(1, len(names)):
            candidate = names[(idx + offset) % len(names)]
            if candidate not in hs:
                self._keymap_selected_name = candidate
                self._keymap_status.set(
                    f"Auto-selected '{candidate}' — press Case to steal, or click another."
                )
                self._keymap_dirty = True
                return

    def _keymap_clear_selected(self) -> None:
        if not self._keymap_selected_name:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        ui = prof.get("ui", {})
        if not isinstance(ui, dict):
            return
        hs = ui.get("hotspots", {})
        if not isinstance(hs, dict):
            return

        hs.pop(self._keymap_selected_name, None)
        self._set_profile_obj(prof)
        self._mapping_key_id.set("")
        self._keymap_status.set(f"Cleared steal for {self._keymap_selected_name}.")

    def _update_bt_background(self) -> None:
        if not self._bt_banner or not self._bt_banner_label:
            return

        # Theme-matched colors (see tools/generate_ui_bundle.py for the theme.json tokens)
        neutral_bg = self._colors["panel2"]
        neutral_fg = _contrast_on(neutral_bg)
        left_bg = self._colors["accent"]
        right_bg = self._colors["accent2"]
        both_bg = _blend_hex(left_bg, right_bg, 0.5)

        if self._bt_connected_left and self._bt_connected_right:
            bg = both_bg
        elif self._bt_connected_left:
            bg = left_bg
        elif self._bt_connected_right:
            bg = right_bg
        else:
            bg = neutral_bg

        self._bt_banner.configure(bg=bg)
        self._bt_banner_label.configure(bg=bg, fg=_contrast_on(bg))
        self._set_keymap_image_state()
        self._keymap_refresh_visuals()

    def _bt_apply_preset(self) -> None:
        p = self._bt_target_preset.get().strip()
        if p == "Either (Joy-Con)":
            self._bt_target_substr.set("Joy-Con")
        elif p == "Left (Joy-Con (L))":
            self._bt_target_substr.set("Joy-Con (L)")
        elif p == "Right (Joy-Con (R))":
            self._bt_target_substr.set("Joy-Con (R)")
        elif p == "Both (Joy-Con (L+R))":
            self._bt_target_substr.set("Joy-Con (")
        # Custom: leave the text box alone

    def _refresh_ports(self) -> None:
        ports = [p.device for p in list_ports.comports()]
        if not ports:
            ports = [""]

        try:
            self.port_combo["values"] = ports
        except Exception:
            pass

        if self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def _toggle_connect(self) -> None:
        if self.client.is_connected:
            log.info("Disconnecting serial")
            self.client.disconnect()
            self.connect_btn.config(text="Connect")
            self._log_line("[host] disconnected")
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("No port", "Select a COM port first")
            return

        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            messagebox.showerror("Bad baud", "Baud must be an integer")
            return

        log.info("Connecting to %s @ %d", port, baud)
        try:
            self.client.connect(port, baud)
        except Exception as e:
            log.error("Serial connect failed: %s", e, exc_info=True)
            messagebox.showerror("Connect failed", str(e))
            return

        self.connect_btn.config(text="Disconnect")
        self._log_line(f"[host] connected to {port} @ {baud}")

    def _validate_profile(self) -> dict:
        raw = self.profile_text.get("1.0", "end").strip()
        try:
            obj = json.loads(raw)
        except Exception as e:
            messagebox.showerror("Invalid JSON", str(e))
            raise
        return _ensure_profile_defaults(obj)

    def _set_profile_obj(self, obj: dict, undo_label: str = "edit") -> None:
        # Push current state to undo stack before overwriting
        if not self._suppress_undo:
            try:
                old_raw = self.profile_text.get("1.0", "end").strip()
                if old_raw:
                    self._undo_stack.append((undo_label, old_raw))
                    if len(self._undo_stack) > self._undo_max:
                        self._undo_stack = self._undo_stack[-self._undo_max:]
                    self._redo_stack.clear()
            except Exception:
                pass
            self._update_undo_ui()

        obj = _ensure_profile_defaults(obj)
        self.profile_text.delete("1.0", "end")
        self.profile_text.insert("1.0", json.dumps(obj, indent=2, ensure_ascii=False))
        self._invalidate_caches()
        self._refresh_macro_list()
        self._stick_load_from_profile(obj)
        self._keymap_refresh_visuals()

    def _load_profile(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*")])
        if not path:
            return
        log.info("Loading profile from %s", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            log.error("Profile load failed: %s", e, exc_info=True)
            messagebox.showerror("Load failed", str(e))
            return
        self.profile_text.delete("1.0", "end")
        self.profile_text.insert("1.0", data)
        try:
            prof = self._validate_profile()
            self._refresh_macro_list()
            self._stick_load_from_profile(prof)
        except Exception:
            log.warning("Loaded profile failed validation", exc_info=True)

    def _save_profile(self) -> None:
        try:
            self._validate_profile()
        except Exception:
            return

        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        log.info("Saving profile to %s", path)
        data = self.profile_text.get("1.0", "end").strip() + "\n"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception as e:
            log.error("Profile save failed: %s", e, exc_info=True)
            messagebox.showerror("Save failed", str(e))

    def _cmd_ping(self) -> None:
        self._ping_sent_time = time.monotonic()
        self._send_cmd({"cmd": "ping"})

    def _cmd_bt_connect(self) -> None:
        target = self._bt_target_substr.get().strip()
        self._send_cmd({"cmd": "bt_set_target", "name_substr": target})
        both = (self._bt_target_preset.get().strip() == "Both (Joy-Con (L+R))")
        self._send_cmd({"cmd": "bt_connect", "both": both})

    def _cmd_test_rumble(self) -> None:
        freq = max(41, min(1253, self._rumble_freq_var.get()))
        amp = max(0, min(100, self._rumble_amp_var.get()))
        self._send_cmd({"cmd": "rumble", "device_id": 0, "freq": freq, "amp": amp})

    def _cmd_set_home_led(self) -> None:
        brightness = max(0, min(15, self._home_led_var.get()))
        self._send_cmd({"cmd": "home_led", "device_id": 0, "brightness": brightness})

    def _cmd_upload_and_set_active(self) -> None:
        try:
            profile = self._validate_profile()
        except Exception:
            return
        slot = int(self.slot_var.get())
        self._send_cmd({"cmd": "write_profile", "slot": slot, "profile": profile})
        self._cmd_set_active()

    def _cmd_set_active(self) -> None:
        slot = int(self.slot_var.get())
        self._send_cmd({"cmd": "set_active_profile", "slot": slot})
        if self._overlay and not self._overlay.is_closed:
            self._overlay.set_slot(slot)

    def _cmd_write_profile(self) -> None:
        try:
            profile = self._validate_profile()
        except Exception:
            return
        self._send_cmd({"cmd": "write_profile", "slot": int(self.slot_var.get()), "profile": profile})
        self._save_last_good_profile()

    def _cmd_read_profile(self) -> None:
        self._send_cmd({"cmd": "read_profile", "slot": int(self.slot_var.get())})

    def _send_raw(self) -> None:
        raw = self.raw_entry.get().strip()
        if not raw:
            return
        if raw.startswith("{"):
            try:
                obj = json.loads(raw)
            except Exception as e:
                messagebox.showerror("Invalid JSON", str(e))
                return
            self._send_cmd(obj)
        else:
            self._send_text(raw)

    def _send_cmd(self, obj: dict) -> None:
        log.debug("TX cmd: %s", obj)
        try:
            self.client.send_obj(obj)
        except Exception as e:
            log.error("Send cmd failed: %s", e, exc_info=True)
            messagebox.showerror("Send failed", str(e))
            return
        self._log_line(f"[host->dev] {json.dumps(obj, ensure_ascii=False)}")

    def _send_text(self, text: str) -> None:
        log.debug("TX text: %s", text)
        try:
            self.client.send_text_line(text)
        except Exception as e:
            log.error("Send text failed: %s", e, exc_info=True)
            messagebox.showerror("Send failed", str(e))
            return
        self._log_line(f"[host->dev] {text}")

    def _drain_rx(self) -> None:
        try:
            while True:
                line = self.client.rx.get_nowait()
                if line.parsed is not None:
                    self._log_line(f"[dev] {json.dumps(line.parsed, ensure_ascii=False)}")
                    self._handle_dev_obj(line.parsed)
                else:
                    self._log_line(f"[dev] {line.raw}")
        except Exception as exc:
            # queue.Empty is expected when the queue is drained; only log real errors.
            import queue as _q
            if not isinstance(exc, _q.Empty):
                log.warning("Unexpected error in _drain_rx: %s", exc, exc_info=True)
        self.after(50, self._drain_rx)

    def _handle_dev_obj(self, obj: dict) -> None:
        evt = obj.get("evt")

        # Handle command responses (rsp)
        rsp = obj.get("rsp")
        if rsp == "pong":
            if self._ping_sent_time is not None:
                rtt = (time.monotonic() - self._ping_sent_time) * 1000
                self._latency_ms = rtt
                self._ping_sent_time = None
        if rsp == "read_profile":
            slot = obj.get("slot")
            profile = obj.get("profile")
            if isinstance(slot, int) and isinstance(profile, dict):
                name = profile.get("name", f"(slot {slot})")
                self._slot_update_name(slot, str(name))
                # If this is the actively selected slot, load the profile into the editor
                try:
                    if int(self.slot_var.get()) == slot:
                        self._set_profile_obj(_ensure_profile_defaults(profile))
                        self._profile_name_var.set(str(name))
                except Exception:
                    pass
            elif isinstance(slot, int):
                self._slot_update_name(slot, "(empty)")

        if evt == "mapped_key":
            try:
                pressed = bool(obj.get("pressed"))
                key_id = int(obj.get("key_id"))
            except Exception:
                return

            if self._overlay and not self._overlay.is_closed:
                self._overlay.set_last_key(pressed, key_id)

            if self._recording.get():
                self._record_macro_event(pressed, key_id)

            # Guided wizard captures input before normal learn flow.
            if pressed and self._guided_window is not None:
                self._guided_on_input(key_id)

            # Keymap editor learn mode: bind hotspot -> observed input key_id.
            if pressed and self._keymap_learn_name:
                self._keymap_bind_selected(key_id)

            # Live input visualization: track active keys for hotspot highlighting.
            if pressed:
                self._active_key_ids.add(key_id)
            else:
                self._active_key_ids.discard(key_id)
            self._keymap_dirty = True  # Batched: redrawn on next pulse tick (≤80ms)

            # Input test tab: log the event and update active display.
            try:
                recv_t = time.monotonic()
                ts = time.strftime("%H:%M:%S")
                action = "pressed" if pressed else "released"
                # Use cached reverse lookup
                name = self._get_hotspot_name(key_id)
                self._input_test_append(f"[{ts}] {name} {action}")

                # Add to visual timeline
                tl_color = self._colors.get("accent2", "#3a8a5c") if pressed else self._colors.get("muted", "#888")
                self._timeline_add_event(name, tl_color)

                if self._active_key_ids:
                    names = [self._get_hotspot_name(kid) for kid in sorted(self._active_key_ids)]
                    self._input_test_active_var.set(", ".join(names))
                else:
                    self._input_test_active_var.set("(none)")

                # Record latency for profiling
                if self._perf_enabled:
                    self._perf_input_times.append((recv_t, time.monotonic()))
                    if len(self._perf_input_times) > 100:
                        self._perf_input_times = self._perf_input_times[-100:]
            except Exception:
                pass

        if evt == "layer":
            # Layer state change from firmware.
            name = obj.get("name", "?")
            active = obj.get("active", False)
            ts = time.strftime("%H:%M:%S")
            state_str = "activated" if active else "deactivated"
            self._log_line(f"[device] Mask '{name}' {state_str}")
            try:
                self._input_test_append(f"[{ts}] Mask '{name}' {state_str}")
            except Exception:
                pass

        if evt == "macro":
            macro_id = str(obj.get("id", ""))
            state = str(obj.get("state", ""))
            if self._overlay and not self._overlay.is_closed:
                self._overlay.set_macro(macro_id, state)

        if evt == "bt_status":
            state = str(obj.get("state", "-"))
            name = obj.get("name")
            bda = obj.get("bda")

            suffix = ""
            if isinstance(name, str) and name:
                suffix += f"  name={name}"
            if isinstance(bda, str) and bda:
                suffix += f"  bda={bda}"
            self._bt_status.set(f"BT: {state}{suffix}")

            # Reset battery and controller info on disconnect.
            if state == "disconnected":
                self._battery_level = None
                self._rssi_dbm = None
                self._ctrl_info_type.set("\u2014")
                self._ctrl_info_serial.set("\u2014")
                self._ctrl_info_deadzone.set("\u2014")
                self._ctrl_info_range.set("\u2014")
                self._ctrl_info_body_color = None
                self._ctrl_info_btn_color = None
                try:
                    if hasattr(self, "_ctrl_body_swatch"):
                        self._ctrl_body_swatch.configure(bg=self._colors.get("bg", "#d4c5a0"))
                    if hasattr(self, "_ctrl_btn_swatch"):
                        self._ctrl_btn_swatch.configure(bg=self._colors.get("bg", "#d4c5a0"))
                except Exception:
                    pass

            # Track side connectivity by BDA to drive the background.
            def _side_from_name(n: object) -> Optional[str]:
                if not isinstance(n, str):
                    return None
                if "(L)" in n:
                    return "L"
                if "(R)" in n:
                    return "R"
                return None

            if state == "connected":
                side = _side_from_name(name)
                if side is None:
                    # If we don't know, assume left unless left is already taken.
                    side = "R" if self._bt_connected_left and not self._bt_connected_right else "L"

                if isinstance(bda, str) and bda:
                    self._bt_conn_by_bda[bda] = side

                if side == "L":
                    self._bt_connected_left = True
                elif side == "R":
                    self._bt_connected_right = True

                # Auto-apply smart defaults if profile is mostly empty.
                self.after(500, self._apply_smart_defaults)

            elif state == "disconnected":
                side = None
                if isinstance(bda, str) and bda:
                    side = self._bt_conn_by_bda.pop(bda, None)

                if side == "L":
                    self._bt_connected_left = False
                elif side == "R":
                    self._bt_connected_right = False
                else:
                    # Unknown disconnect (no bda): clear both.
                    self._bt_connected_left = False
                    self._bt_connected_right = False

            self._update_bt_background()

        if evt == "battery":
            try:
                level = int(obj.get("level", -1))
                if 0 <= level <= 4:
                    self._battery_level = level
            except (ValueError, TypeError):
                pass

        if evt == "controller_info":
            ctrl_type = obj.get("type", "unknown")
            serial = obj.get("serial", "")
            body_color = obj.get("body_color")
            button_color = obj.get("button_color")
            deadzone = obj.get("stick_deadzone")
            range_ratio = obj.get("stick_range_ratio")

            type_labels = {"joycon_l": "Joy-Con (L)", "joycon_r": "Joy-Con (R)", "pro": "Pro Controller"}
            self._ctrl_info_type.set(type_labels.get(ctrl_type, ctrl_type))
            self._ctrl_info_serial.set(serial if serial else "\u2014")

            if isinstance(deadzone, (int, float)):
                self._ctrl_info_deadzone.set(str(int(deadzone)))
            if isinstance(range_ratio, (int, float)):
                self._ctrl_info_range.set(str(int(range_ratio)))

            # Update color swatches.
            self._ctrl_info_body_color = body_color
            self._ctrl_info_btn_color = button_color
            try:
                if body_color and hasattr(self, "_ctrl_body_swatch"):
                    self._ctrl_body_swatch.configure(bg=body_color)
                if button_color and hasattr(self, "_ctrl_btn_swatch"):
                    self._ctrl_btn_swatch.configure(bg=button_color)
            except Exception:
                pass

            self._log_line(f"[device] Controller info: {ctrl_type} serial={serial} body={body_color} btn={button_color}")

        if evt == "rssi":
            try:
                rssi = int(obj.get("rssi", 0))
                self._rssi_dbm = rssi
            except (ValueError, TypeError):
                pass

    def _current_profile(self) -> dict:
        return self._validate_profile()

    def _macros(self) -> List[Dict[str, Any]]:
        prof = self._current_profile()
        macros = prof.get("macros", [])
        return macros if isinstance(macros, list) else []

    def _refresh_macro_list(self) -> None:
        if not hasattr(self, "macro_list"):
            return
        try:
            macros = self._macros()
        except Exception:
            macros = []

        self.macro_list.delete(0, "end")
        ids: List[str] = []
        for m in macros:
            mid = m.get("id")
            if isinstance(mid, str) and mid:
                self.macro_list.insert("end", mid)
                ids.append(mid)

        if hasattr(self, "macro_pick"):
            try:
                self.macro_pick["values"] = ids
            except Exception:
                pass
            if ids and self._mapping_macro_pick.get() not in ids:
                self._mapping_macro_pick.set(ids[0])

        if self.macro_list.size() > 0 and not self.macro_list.curselection():
            self.macro_list.selection_set(0)
        self._refresh_macro_steps()

    def _mapping_pick_macro(self) -> None:
        picked = self._mapping_macro_pick.get().strip()
        if picked:
            self._mapping_macro_id.set(picked)

    def _selected_macro_index(self) -> Optional[int]:
        if not hasattr(self, "macro_list"):
            return None
        sel = self.macro_list.curselection()
        if not sel:
            return None
        return int(sel[0])

    def _refresh_macro_steps(self) -> None:
        if not hasattr(self, "step_list"):
            return
        self.step_list.delete(0, "end")
        idx = self._selected_macro_index()
        if idx is None:
            return

        macros = self._macros()
        if idx < 0 or idx >= len(macros):
            return

        steps = macros[idx].get("steps", [])
        if not isinstance(steps, list):
            return

        for st in steps:
            if not isinstance(st, dict):
                continue
            t = st.get("type")
            if t == "delay":
                self.step_list.insert("end", f"delay {st.get('ms', 0)}ms")
            elif t == "key":
                self.step_list.insert(
                    "end",
                    f"key key_id={st.get('key_id')} {'DOWN' if st.get('pressed') else 'UP'}",
                )
            else:
                self.step_list.insert("end", f"(unknown) {st}")

    def _macro_new(self) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return

        new_id = f"macro{int(time.time())}"
        prof["macros"].append({"id": new_id, "steps": []})
        self._set_profile_obj(prof)

        self.macro_list.selection_clear(0, "end")
        self.macro_list.selection_set(self.macro_list.size() - 1)
        self._refresh_macro_steps()

    def _macro_delete(self) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        macros = prof.get("macros", [])
        if not isinstance(macros, list) or idx >= len(macros):
            return

        del macros[idx]
        prof["macros"] = macros
        self._set_profile_obj(prof)

    def _step_add_key(self) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            messagebox.showerror("No macro", "Select a macro first")
            return

        try:
            key_id = int(self._mapping_key_id.get())
        except ValueError:
            messagebox.showerror("Bad key_id", "Input key_id must be an integer")
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        prof["macros"][idx].setdefault("steps", []).append({"type": "key", "key_id": key_id, "pressed": True})
        prof["macros"][idx]["steps"].append({"type": "key", "key_id": key_id, "pressed": False})
        self._set_profile_obj(prof)

    def _step_add_delay(self) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            messagebox.showerror("No macro", "Select a macro first")
            return

        ms = simpledialog.askinteger("Delay", "Delay in ms:", initialvalue=50, minvalue=0, maxvalue=5000)
        if ms is None:
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        prof["macros"][idx].setdefault("steps", []).append({"type": "delay", "ms": int(ms)})
        self._set_profile_obj(prof)

    def _step_delete(self) -> None:
        midx = self._selected_macro_index()
        if midx is None:
            return
        sel = self.step_list.curselection()
        if not sel:
            return
        sidx = int(sel[0])

        try:
            prof = self._current_profile()
        except Exception:
            return

        steps = prof["macros"][midx].get("steps", [])
        if not isinstance(steps, list) or sidx >= len(steps):
            return
        del steps[sidx]
        prof["macros"][midx]["steps"] = steps
        self._set_profile_obj(prof)

    def _record_macro_event(self, pressed: bool, key_id: int) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            return

        now = time.time()
        if self._record_last_t is not None:
            dt_ms = int((now - self._record_last_t) * 1000.0)
        else:
            dt_ms = 0
        self._record_last_t = now

        try:
            prof = self._current_profile()
        except Exception:
            return

        steps = prof["macros"][idx].setdefault("steps", [])
        if dt_ms > 0:
            steps.append({"type": "delay", "ms": min(dt_ms, 5000)})
        # Macro step key_ids are output-space (0..127). When key_id is in the
        # right-side input namespace (128..255), record the base id.
        rec_key_id = int(key_id)
        if rec_key_id >= 128:
            rec_key_id -= 128
        steps.append({"type": "key", "key_id": rec_key_id, "pressed": bool(pressed)})
        self._set_profile_obj(prof)

    def _mapping_apply(self) -> None:
        try:
            in_id = int(self._mapping_key_id.get())
        except ValueError:
            messagebox.showerror("Bad key_id", "Input key_id must be an integer")
            return
        if in_id < 0 or in_id > 255:
            messagebox.showerror("Bad key_id", "Input key_id must be 0..255")
            return

        mtype = self._mapping_type.get()

        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings

        key = str(in_id)
        if mtype == "passthrough":
            mappings.pop(key, None)
        elif mtype == "disable":
            mappings[key] = {"type": "disable"}
        elif mtype == "remap":
            try:
                to = int(self._mapping_remap_to.get())
            except ValueError:
                messagebox.showerror("Bad remap", "Remap-to must be an integer")
                return
            if to < 0 or to > 127:
                messagebox.showerror("Bad remap", "Remap-to must be 0..127")
                return
            mappings[key] = {"type": "remap", "to": to}
        elif mtype == "macro":
            macro_id = self._mapping_macro_id.get().strip()
            if not macro_id:
                messagebox.showerror("Bad macro", "Macro id is required")
                return
            mappings[key] = {"type": "macro", "id": macro_id}
        elif mtype == "remap_hid":
            # Use the Remap-to field as the HID keycode (hex or int)
            rto = self._mapping_remap_to.get().strip()
            try:
                kc = int(rto, 0)  # Accept hex (0x1A) or decimal
            except ValueError:
                messagebox.showerror("Bad keycode", "Remap-to must be a HID keycode (integer or 0xHH)")
                return
            if kc < 0 or kc > 255:
                messagebox.showerror("Bad keycode", "HID keycode must be 0..255")
                return
            mappings[key] = {"type": "remap_hid", "mod": 0, "keycode": kc}
        elif mtype == "tap_hold":
            # Tap → passthrough (quick press), Hold → remap_hid (long press)
            rto = self._mapping_remap_to.get().strip()
            try:
                kc = int(rto, 0)
            except ValueError:
                messagebox.showerror("Bad keycode", "Remap-to (hold action) must be a HID keycode")
                return
            if kc < 0 or kc > 255:
                messagebox.showerror("Bad keycode", "HID keycode must be 0..255")
                return
            hold_ms = 300  # default threshold
            mappings[key] = {
                "type": "tap_hold",
                "tap": {"type": "passthrough"},
                "hold": {"type": "remap_hid", "mod": 0, "keycode": kc},
                "hold_ms": hold_ms,
            }
        elif mtype == "double_tap":
            # Single-tap keycode in "Remap to", double-tap keycode in "Trick id"
            rto_s = self._mapping_remap_to.get().strip()
            rto_d = self._mapping_macro_id.get().strip()
            try:
                kc_single = int(rto_s, 0)
            except ValueError:
                messagebox.showerror("Bad keycode", "Remap-to (single-tap keycode) must be a HID keycode")
                return
            try:
                kc_double = int(rto_d, 0)
            except ValueError:
                messagebox.showerror("Bad keycode", "Trick id (double-tap keycode) must be a HID keycode")
                return
            if kc_single < 0 or kc_single > 255 or kc_double < 0 or kc_double > 255:
                messagebox.showerror("Bad keycode", "HID keycodes must be 0..255")
                return
            mappings[key] = {
                "type": "double_tap",
                "single": {"mod": 0, "keycode": kc_single},
                "double": {"mod": 0, "keycode": kc_double},
                "timeout_ms": 300,
            }

        self._set_profile_obj(prof, undo_label="apply mapping")
        self._keymap_redraw()
        self._kbd_redraw()
        self._rebuild_layer_stack()
        self._play_sound("bind")

    def _share_export(self) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return
        code = _profile_to_share_code(prof)
        self.share_text.delete("1.0", "end")
        self.share_text.insert("1.0", code)

    def _share_import(self) -> None:
        code = self.share_text.get("1.0", "end").strip()
        if not code:
            return
        try:
            prof = _share_code_to_profile(code)
        except Exception as e:
            messagebox.showerror("Import failed", str(e))
            return
        self._set_profile_obj(prof)

    def _overlay_open(self) -> None:
        if self._overlay and not self._overlay.is_closed:
            try:
                self._overlay.lift()
            except Exception:
                pass
            return
        self._overlay = OverlayWindow(self, theme=self._ui_theme)
        try:
            self._overlay.set_slot(int(self.slot_var.get()))
        except Exception:
            pass

    def _overlay_close(self) -> None:
        if not self._overlay:
            return
        try:
            self._overlay.destroy()
        except Exception:
            pass
        self._overlay = None

    def _stick_load_from_profile(self, prof: dict) -> None:
        stick = prof.get("stick", {})
        if not isinstance(stick, dict):
            return
        dz = stick.get("deadzone")
        if isinstance(dz, (int, float)):
            self._stick_deadzone.set(float(dz))
        shape = stick.get("shape")
        if isinstance(shape, str):
            self._stick_deadzone_shape.set(shape)
        curve = stick.get("curve")
        if isinstance(curve, str):
            self._stick_curve.set(curve)
        exp = stick.get("exp")
        if isinstance(exp, (int, float)):
            self._stick_curve_exp.set(float(exp))

    def _stick_apply_to_profile(self) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return
        stick = prof.setdefault("stick", {})
        if not isinstance(stick, dict):
            stick = {}
            prof["stick"] = stick

        stick["deadzone"] = round(float(self._stick_deadzone.get()), 3)
        stick["shape"] = str(self._stick_deadzone_shape.get())
        stick["curve"] = str(self._stick_curve.get())
        stick["exp"] = round(float(self._stick_curve_exp.get()), 3)

        self._set_profile_obj(prof)

    def _draw_curve_preview(self) -> None:
        c = self.curve_canvas
        c.delete("all")

        w = max(c.winfo_width(), 320)
        h = max(c.winfo_height(), 220)
        pad = 20

        axis = self._colors.get("border", "#22314f")
        curve_col = self._colors.get("accent", "#2b63ff")

        # axes
        c.create_line(pad, h - pad, w - pad, h - pad, fill=axis)
        c.create_line(pad, h - pad, pad, pad, fill=axis)

        deadzone = float(self._stick_deadzone.get())
        curve = self._stick_curve.get()
        exp = float(self._stick_curve_exp.get())

        def f(x: float) -> float:
            # x in [0,1]
            if x <= deadzone:
                return 0.0
            xn = (x - deadzone) / max(1e-6, (1.0 - deadzone))
            if curve == "linear":
                y = xn
            elif curve == "exponential":
                y = xn**exp
            elif curve == "soft":
                y = xn ** max(0.8, exp * 0.7)
            elif curve == "hard":
                y = xn ** max(1.2, exp * 1.3)
            else:
                y = xn
            return max(0.0, min(1.0, y))

        pts = []
        for i in range(0, 101):
            x = i / 100.0
            y = f(x)
            px = pad + x * (w - 2 * pad)
            py = (h - pad) - y * (h - 2 * pad)
            pts.append((px, py))

        for i in range(1, len(pts)):
            c.create_line(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], fill=curve_col)

    def _start_update_check(self) -> None:
        """Kick off a background update check."""
        def _on_result(info: Optional[Dict[str, Any]]) -> None:
            # Called from a background thread → schedule onto the Tk main loop.
            self.after(0, self._on_update_result, info)

        updater.check_in_background(_on_result)

    def _on_update_result(self, info: Optional[Dict[str, Any]]) -> None:
        if info is None:
            return
        self._pending_update = info
        # Show the update icon in the top bar.
        self._update_icon_btn.configure(text=f" \u2191 Update to {info['version']} ")
        self._update_icon_btn.pack(side=tk.LEFT, padx=(12, 0))
        log.info("Update available: %s \u2192 %s", __version__, info["version"])

    # ------------------------------------------------------------------
    # Update dialog — download, install, relaunch
    # ------------------------------------------------------------------

    def _open_update_dialog(self) -> None:
        """Open a modal dialog to download and install the update."""
        info = self._pending_update
        if not info:
            return

        if not updater.is_frozen():
            import webbrowser
            url = info.get("html_url", "")
            if url:
                webbrowser.open(url)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Update Bind Bandit")
        dlg.geometry("440x280")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 440) // 2
        y = self.winfo_y() + (self.winfo_height() - 280) // 2
        dlg.geometry(f"+{x}+{y}")

        pad = ttk.Frame(dlg, padding=16)
        pad.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            pad, text="Update Available",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            pad, text=f"v{__version__}  \u2192  v{info['version']}",
        ).pack(anchor="w", pady=(4, 12))

        step_var = tk.StringVar(value="Ready to update.")
        ttk.Label(pad, textvariable=step_var, wraplength=400).pack(
            anchor="w", pady=(0, 4),
        )

        progress = ttk.Progressbar(pad, length=400, mode="determinate")
        progress.pack(fill=tk.X, pady=(0, 4))

        detail_var = tk.StringVar(value="")
        ttk.Label(pad, textvariable=detail_var, style="Muted.TLabel").pack(anchor="w")

        btn_frame = ttk.Frame(pad)
        btn_frame.pack(fill=tk.X, pady=(12, 0))

        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=dlg.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        install_btn = ttk.Button(
            btn_frame, text="Download & Install",
            command=lambda: self._run_update_flow(
                dlg, info, step_var, progress, detail_var,
                install_btn, cancel_btn,
            ),
        )
        install_btn.pack(side=tk.RIGHT)

        dlg._updating = False  # type: ignore[attr-defined]

        def _on_close() -> None:
            if getattr(dlg, "_updating", False):
                return
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", _on_close)

    def _run_update_flow(
        self,
        dlg: tk.Toplevel,
        info: Dict[str, Any],
        step_var: tk.StringVar,
        progress: ttk.Progressbar,
        detail_var: tk.StringVar,
        install_btn: ttk.Button,
        cancel_btn: ttk.Button,
    ) -> None:
        """Execute the full download \u2192 install \u2192 relaunch pipeline on a thread."""
        dlg._updating = True  # type: ignore[attr-defined]
        install_btn.configure(state="disabled")
        cancel_btn.configure(state="disabled")

        def _set(step: str = "", detail: str = "", pct: int = 0) -> None:
            def _apply() -> None:
                step_var.set(step)
                detail_var.set(detail)
                progress.configure(value=pct)
            self.after(0, _apply)

        def _worker() -> None:
            try:
                # 1. Download app executable
                _set("Downloading app update\u2026", "", 0)

                def _app_cb(dl: int, tot: int) -> None:
                    pct = int(dl * 100 / tot) if tot else 0
                    _set(
                        "Downloading app update\u2026",
                        f"{dl // 1024} / {tot // 1024} KB",
                        pct,
                    )

                exe_bytes = updater.download_bytes(
                    info["download_url"], progress_cb=_app_cb,
                )

                # 2. Download firmware assets (if any in this release)
                fw_assets = info.get("fw_assets", {})
                fw_data: Dict[str, bytes] = {}
                for name, asset_info in fw_assets.items():
                    _set(f"Downloading firmware ({name})\u2026", "", 0)

                    def _fw_cb(dl: int, tot: int, n: str = name) -> None:
                        pct = int(dl * 100 / tot) if tot else 0
                        _set(
                            f"Downloading firmware ({n})\u2026",
                            f"{dl // 1024} / {tot // 1024} KB",
                            pct,
                        )

                    fw_data[name] = updater.download_bytes(
                        asset_info["url"], progress_cb=_fw_cb,
                    )

                # 3. Save firmware for post-relaunch flashing
                if fw_data:
                    _set("Saving firmware\u2026", "", 0)
                    for fname, fdata in fw_data.items():
                        updater.save_pending_firmware(fname, fdata)

                # 4. Install new exe
                _set("Installing update\u2026", "Swapping executable\u2026", 50)
                updater.install_exe(exe_bytes)
                _set("Installing update\u2026", "Done!", 100)

                # 5. Relaunch
                _set("Restarting\u2026", "The app will relaunch now.", 100)
                self.after(1200, updater.relaunch)

            except Exception as e:
                log.error("Update flow failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_update_flow_error(
                    dlg, str(e), install_btn, cancel_btn,
                ))

        threading.Thread(target=_worker, name="update-flow", daemon=True).start()

    def _on_update_flow_error(
        self,
        dlg: tk.Toplevel,
        error: str,
        install_btn: ttk.Button,
        cancel_btn: ttk.Button,
    ) -> None:
        dlg._updating = False  # type: ignore[attr-defined]
        install_btn.configure(state="normal")
        cancel_btn.configure(state="normal", text="Close")
        messagebox.showerror("Update failed", error, parent=dlg)

    # ------------------------------------------------------------------
    # Pending firmware flash (runs after a successful app update + relaunch)
    # ------------------------------------------------------------------

    def _check_pending_fw(self) -> None:
        """Periodically check whether we should offer to flash pending firmware."""
        if not self._pending_fw_files:
            return
        if not self.serial.is_connected:
            # Not connected yet — retry later.
            self.after(5000, self._check_pending_fw)
            return
        if self._pending_fw_offered:
            return
        self._pending_fw_offered = True
        self.after(500, self._offer_pending_fw_flash)

    def _offer_pending_fw_flash(self) -> None:
        files = self._pending_fw_files
        board_names: List[str] = []
        if updater.FW_ASSET_S3 in files:
            board_names.append("ESP32-S3")
        if updater.FW_ASSET_ESP32 in files:
            board_names.append("ESP32")

        if not board_names:
            updater.clear_pending_firmware()
            self._pending_fw_files = {}
            return

        confirm = messagebox.askyesno(
            "Firmware Update Ready",
            f"Updated firmware is ready for: {', '.join(board_names)}.\n\n"
            "Flash now?\n\n"
            "Do not disconnect during the update.",
        )
        if not confirm:
            updater.clear_pending_firmware()
            self._pending_fw_files = {}
            return

        self._flash_pending_fw()

    def _flash_pending_fw(self) -> None:
        """Flash saved firmware binaries with a progress dialog."""
        dlg = tk.Toplevel(self)
        dlg.title("Flashing Firmware")
        dlg.geometry("440x200")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 440) // 2
        y = self.winfo_y() + (self.winfo_height() - 200) // 2
        dlg.geometry(f"+{x}+{y}")

        pad = ttk.Frame(dlg, padding=16)
        pad.pack(fill=tk.BOTH, expand=True)

        step_var = tk.StringVar(value="Preparing\u2026")
        ttk.Label(
            pad, textvariable=step_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        progress = ttk.Progressbar(pad, length=400, mode="determinate")
        progress.pack(fill=tk.X, pady=(8, 4))

        detail_var = tk.StringVar(value="")
        ttk.Label(pad, textvariable=detail_var, style="Muted.TLabel").pack(anchor="w")

        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        def _set(step: str = "", detail: str = "", pct: int = 0) -> None:
            def _apply() -> None:
                step_var.set(step)
                detail_var.set(detail)
                progress.configure(value=pct)
            self.after(0, _apply)

        files = self._pending_fw_files
        boards_to_flash: List[Tuple[str, Path]] = []
        if updater.FW_ASSET_S3 in files:
            boards_to_flash.append((fw_updater.BOARD_S3, files[updater.FW_ASSET_S3]))
        if updater.FW_ASSET_ESP32 in files:
            boards_to_flash.append((fw_updater.BOARD_ESP32, files[updater.FW_ASSET_ESP32]))

        def _worker() -> None:
            try:
                flasher = fw_updater.FirmwareFlasher(self.serial)
                for board, fw_path in boards_to_flash:
                    _set(f"Flashing {board}\u2026", "Reading firmware\u2026", 0)
                    fw_bytes = fw_path.read_bytes()

                    def _progress(done: int, total: int, b: str = board) -> None:
                        pct = int(done * 100 / total) if total else 0
                        _set(
                            f"Flashing {b}\u2026",
                            f"{done // 1024} / {total // 1024} KB",
                            pct,
                        )

                    flasher.flash(board, fw_bytes, progress_cb=_progress)

                _set("Firmware update complete!", "Device will reboot.", 100)
                updater.clear_pending_firmware()
                self._pending_fw_files = {}
                self.after(2000, dlg.destroy)
                self.after(2100, lambda: messagebox.showinfo(
                    "Firmware Updated",
                    "Firmware has been updated successfully.\n"
                    "The device will reboot. You may need to reconnect.",
                ))
            except Exception as e:
                log.error("Pending FW flash failed: %s", e, exc_info=True)
                _set(f"Error: {e}", "", 0)
                updater.clear_pending_firmware()
                self._pending_fw_files = {}
                self.after(3000, dlg.destroy)
                self.after(3100, lambda: messagebox.showerror(
                    "Firmware Flash Failed", str(e),
                ))

        threading.Thread(target=_worker, name="pending-fw-flash", daemon=True).start()

    # ------------------------------------------------------------------
    # Firmware version check & OTA update
    # ------------------------------------------------------------------

    def _fw_check_versions(self) -> None:
        """Query firmware versions from both boards over serial."""
        if not self.serial.is_connected:
            self._fw_status.set("Not connected.")
            return

        self._fw_check_btn.configure(state="disabled")
        self._fw_status.set("Querying…")

        def _worker() -> None:
            flasher = fw_updater.FirmwareFlasher(self.serial)
            s3_ver = flasher.get_version(fw_updater.BOARD_S3)
            esp32_ver = flasher.get_version(fw_updater.BOARD_ESP32)
            self.after(0, lambda: self._on_fw_versions(s3_ver, esp32_ver))

        import threading
        threading.Thread(target=_worker, name="fw-version-check", daemon=True).start()

    def _on_fw_versions(self, s3_ver: Optional[str], esp32_ver: Optional[str]) -> None:
        self._fw_check_btn.configure(state="normal")
        self._fw_s3_ver.set(f"S3: {s3_ver or '—'}")
        self._fw_esp32_ver.set(f"ESP32: {esp32_ver or '—'}")

        if not s3_ver and not esp32_ver:
            self._fw_status.set("Could not read versions.")
            return

        # Check for updates against GitHub Releases.
        self._fw_status.set("Checking for updates…")

        def _check() -> None:
            info = fw_updater.check_firmware_updates(
                current_s3=s3_ver, current_esp32=esp32_ver
            )
            self.after(0, lambda: self._on_fw_update_check(info))

        import threading
        threading.Thread(target=_check, name="fw-update-check", daemon=True).start()

    def _on_fw_update_check(self, info: Optional[Dict[str, Any]]) -> None:
        if info is None or not info.get("boards"):
            self._fw_status.set("Firmware up to date.")
            self._fw_update_btn.configure(state="disabled")
            self._pending_fw_update = None
            return

        boards = info["boards"]
        parts = []
        if fw_updater.BOARD_S3 in boards:
            parts.append("S3")
        if fw_updater.BOARD_ESP32 in boards:
            parts.append("ESP32")
        self._fw_status.set(f"Update available for: {', '.join(parts)} → {info['version']}")
        self._fw_update_btn.configure(state="normal")
        self._pending_fw_update = info

    def _fw_do_update(self) -> None:
        info = self._pending_fw_update
        if not info or not self.serial.is_connected:
            return

        boards = info.get("boards", {})
        board_names = [b for b in [fw_updater.BOARD_S3, fw_updater.BOARD_ESP32] if b in boards]
        if not board_names:
            return

        # Build confirmation message with release notes.
        msg = (
            f"Update firmware for {', '.join(board_names)} to v{info['version']}?\n\n"
            "The device(s) will reboot after flashing.\n"
            "Do not disconnect during the update."
        )
        notes = info.get("release_notes", "")
        if notes:
            preview = notes[:600]
            if len(notes) > 600:
                preview += "\n\n(truncated)"
            msg += f"\n\n--- Release Notes ---\n{preview}"

        confirm = messagebox.askyesno("Firmware update", msg)
        if not confirm:
            return

        self._fw_update_btn.configure(state="disabled")
        self._fw_check_btn.configure(state="disabled")
        self._fw_status.set("Downloading…")

        def _run() -> None:
            try:
                flasher = fw_updater.FirmwareFlasher(self.serial)
                for board in board_names:
                    b_info = boards[board]
                    self.after(0, lambda b=board: self._fw_status.set(f"Downloading {b}…"))

                    fw_bytes = fw_updater.download_firmware(
                        b_info["download_url"],
                        progress_cb=lambda dl, tot, b=board: self.after(
                            0, lambda: self._fw_status.set(
                                f"Downloading {b}… {int(dl * 100 / tot)}%"
                            )
                        ),
                        expected_sha256=b_info.get("expected_sha256"),
                        expected_size=b_info.get("size", 0),
                    )

                    self.after(0, lambda b=board: self._fw_status.set(f"Flashing {b}…"))

                    flasher.flash(
                        board, fw_bytes,
                        progress_cb=lambda done, tot, b=board: self.after(
                            0, lambda: self._fw_status.set(
                                f"Flashing {b}… {int(done * 100 / tot)}%"
                            )
                        ),
                    )

                self.after(0, self._on_fw_update_done)
            except Exception as e:
                log.error("Firmware update failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_fw_update_failed(str(e)))

        import threading
        threading.Thread(target=_run, name="fw-update", daemon=True).start()

    def _fw_flash_from_file(self) -> None:
        """Let the user pick a local .bin file and flash it to a board."""
        from tkinter import filedialog

        if not self.serial.is_connected:
            self._fw_status.set("Not connected.")
            return

        path = filedialog.askopenfilename(
            title="Select firmware binary",
            filetypes=[("Firmware binary", "*.bin"), ("All files", "*.*")],
        )
        if not path:
            return

        # Determine target board.
        board = fw_updater.BOARD_S3
        name_lower = path.lower()
        if "esp32-hid" in name_lower or "hid-host" in name_lower or name_lower.endswith("esp32.bin"):
            board = fw_updater.BOARD_ESP32

        from pathlib import Path as P
        data = P(path).read_bytes()
        sha = fw_updater.compute_sha256(data)

        confirm = messagebox.askyesno(
            "Flash from file",
            f"Flash '{P(path).name}' to {board}?\n\n"
            f"Size: {len(data):,} bytes\n"
            f"SHA-256: {sha[:16]}…\n\n"
            "Do not disconnect during flashing.",
        )
        if not confirm:
            return

        self._fw_flash_file_btn.configure(state="disabled")
        self._fw_status.set(f"Flashing {board}…")

        def _run() -> None:
            try:
                flasher = fw_updater.FirmwareFlasher(self.serial)
                flasher.flash(
                    board, data,
                    progress_cb=lambda done, tot: self.after(
                        0, lambda: self._fw_status.set(
                            f"Flashing {board}… {int(done * 100 / tot)}%"
                        )
                    ),
                )
                self.after(0, self._on_fw_file_flash_done)
            except Exception as e:
                log.error("Local firmware flash failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_fw_file_flash_failed(str(e)))

        import threading
        threading.Thread(target=_run, name="fw-file-flash", daemon=True).start()

    def _on_fw_file_flash_done(self) -> None:
        self._fw_flash_file_btn.configure(state="normal")
        self._fw_status.set("Flashed from file! Device rebooting…")
        messagebox.showinfo(
            "Flash complete",
            "Firmware flashed successfully from file.\n\n"
            "The device will reboot. You may need to reconnect.",
        )

    def _on_fw_file_flash_failed(self, error: str) -> None:
        self._fw_flash_file_btn.configure(state="normal")
        self._fw_status.set(f"Flash failed: {error}")
        messagebox.showerror("Flash failed", error)

    # ------------------------------------------------------------------
    # Initial flash (esptool — for blank / new boards)
    # ------------------------------------------------------------------

    def _init_flash_auto(self) -> None:
        """Download the latest release and flash a blank board via esptool."""
        port = self.port_var.get()
        if not port:
            messagebox.showerror("No port", "Select a COM port first.")
            return

        confirm = messagebox.askyesno(
            "Initial Flash",
            f"This will ERASE the entire flash of the board on {port} "
            "and write the latest firmware from GitHub.\n\n"
            "The board must be in download mode:\n"
            "  \u2022 Hold BOOT, press RESET, release BOOT\n"
            "  \u2022 (Some boards enter download mode automatically via USB)\n\n"
            "Continue?",
        )
        if not confirm:
            return

        self._init_flash_auto_btn.configure(state="disabled")
        self._init_flash_file_btn.configure(state="disabled")
        self._init_flash_backup_btn.configure(state="disabled")
        self._init_flash_status.set("Starting\u2026")

        def _run() -> None:
            try:
                initial_flash.download_and_flash_initial(
                    port,
                    progress_cb=lambda msg: self.after(
                        0, lambda: self._init_flash_status.set(msg)
                    ),
                )
                self.after(0, self._on_init_flash_done)
            except Exception as e:
                log.error("Initial flash failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_init_flash_failed(str(e)))

        import threading
        threading.Thread(target=_run, name="init-flash-auto", daemon=True).start()

    def _init_flash_from_files(self) -> None:
        """Let the user pick firmware files and flash a blank board via esptool."""
        from tkinter import filedialog

        port = self.port_var.get()
        if not port:
            messagebox.showerror("No port", "Select a COM port first.")
            return

        # Let user pick files.
        files = filedialog.askopenfilenames(
            title="Select firmware file(s)",
            filetypes=[("Firmware binary", "*.bin"), ("All files", "*.*")],
        )
        if not files:
            return

        # Classify files by name.
        from pathlib import Path as P
        app_bin: Optional[str] = None
        bl_bin: Optional[str] = None
        pt_bin: Optional[str] = None
        merged_bin: Optional[str] = None

        for f in files:
            name = P(f).name.lower()
            if "bootloader" in name:
                bl_bin = f
            elif "partition" in name:
                pt_bin = f
            elif "merged" in name:
                merged_bin = f
            else:
                app_bin = f

        if not app_bin and not merged_bin:
            messagebox.showerror(
                "No app binary",
                "Select at least an app firmware binary (e.g. esp32s3-usb-kbd.bin).\n\n"
                "Optionally also select bootloader + partition-table files.",
            )
            return

        # Summarize what will be flashed.
        parts = []
        if merged_bin:
            parts.append(f"Merged: {P(merged_bin).name}")
        else:
            if bl_bin:
                parts.append(f"Bootloader: {P(bl_bin).name}")
            if pt_bin:
                parts.append(f"Partition table: {P(pt_bin).name}")
            if app_bin:
                parts.append(f"App: {P(app_bin).name}")

        confirm = messagebox.askyesno(
            "Initial Flash from files",
            f"Flash to {port}:\n" + "\n".join(f"  \u2022 {p}" for p in parts) + "\n\n"
            "The board must be in download mode.\n"
            "The entire flash will be erased first.\n\n"
            "Continue?",
        )
        if not confirm:
            return

        self._init_flash_auto_btn.configure(state="disabled")
        self._init_flash_file_btn.configure(state="disabled")
        self._init_flash_backup_btn.configure(state="disabled")
        self._init_flash_status.set("Flashing\u2026")

        def _run() -> None:
            try:
                initial_flash.flash_firmware(
                    port,
                    app_bin=app_bin,
                    bootloader_bin=bl_bin,
                    partition_table_bin=pt_bin,
                    merged_bin=merged_bin,
                    erase_all=True,
                    progress_cb=lambda msg: self.after(
                        0, lambda: self._init_flash_status.set(msg)
                    ),
                )
                self.after(0, self._on_init_flash_done)
            except Exception as e:
                log.error("Initial flash from files failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_init_flash_failed(str(e)))

        import threading
        threading.Thread(target=_run, name="init-flash-file", daemon=True).start()

    def _on_init_flash_done(self) -> None:
        self._init_flash_auto_btn.configure(state="normal")
        self._init_flash_file_btn.configure(state="normal")
        self._init_flash_backup_btn.configure(state="normal")
        self._init_flash_status.set("Flash complete (verified)! Reset the board.")
        messagebox.showinfo(
            "Initial flash complete",
            "Firmware has been flashed and verified successfully.\n\n"
            "Reset the board (press RESET or re-plug USB).\n"
            "After booting, it should appear as a USB keyboard + COM port.",
        )

    def _on_init_flash_failed(self, error: str) -> None:
        self._init_flash_auto_btn.configure(state="normal")
        self._init_flash_file_btn.configure(state="normal")
        self._init_flash_backup_btn.configure(state="normal")
        self._init_flash_status.set(f"Flash failed.")
        messagebox.showerror(
            "Initial flash failed",
            f"{error}",
        )

    def _init_flash_backup(self) -> None:
        """Read and save the current flash contents before erasing."""
        from tkinter import filedialog

        port = self.port_var.get()
        if not port:
            messagebox.showerror("No port", "Select a COM port first.")
            return

        dest = filedialog.asksaveasfilename(
            title="Save flash backup",
            defaultextension=".bin",
            filetypes=[("Firmware binary", "*.bin"), ("All files", "*.*")],
            initialfile="flash_backup.bin",
        )
        if not dest:
            return

        confirm = messagebox.askyesno(
            "Backup Flash",
            f"Read 4 MB from the flash chip on {port} and save to:\n"
            f"{dest}\n\n"
            "The board must be in download mode.\n"
            "This may take about a minute.\n\n"
            "Continue?",
        )
        if not confirm:
            return

        self._init_flash_auto_btn.configure(state="disabled")
        self._init_flash_file_btn.configure(state="disabled")
        self._init_flash_backup_btn.configure(state="disabled")
        self._init_flash_status.set("Backing up\u2026")

        def _run() -> None:
            try:
                initial_flash.backup_firmware(
                    port,
                    dest,
                    progress_cb=lambda msg: self.after(
                        0, lambda: self._init_flash_status.set(msg)
                    ),
                )
                self.after(0, lambda: self._on_backup_done(dest))
            except Exception as e:
                log.error("Flash backup failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_init_flash_failed(str(e)))

        import threading
        threading.Thread(target=_run, name="init-flash-backup", daemon=True).start()

    def _on_backup_done(self, path: str) -> None:
        self._init_flash_auto_btn.configure(state="normal")
        self._init_flash_file_btn.configure(state="normal")
        self._init_flash_backup_btn.configure(state="normal")
        self._init_flash_status.set("Backup saved.")
        messagebox.showinfo(
            "Backup complete",
            f"Flash contents saved to:\n{path}\n\n"
            "You can restore this backup later using 'Flash files\u2026' if needed.",
        )

    def _on_fw_update_done(self) -> None:
        self._fw_check_btn.configure(state="normal")
        self._fw_status.set("Firmware updated! Device rebooting…")
        self._pending_fw_update = None
        messagebox.showinfo(
            "Firmware updated",
            "Firmware has been updated successfully.\n\n"
            "The device will reboot. You may need to reconnect.",
        )

    def _on_fw_update_failed(self, error: str) -> None:
        self._fw_check_btn.configure(state="normal")
        self._fw_update_btn.configure(state="normal")
        self._fw_status.set(f"Update failed: {error}")
        messagebox.showerror("Firmware update failed", error)

    def _log_line(self, text: str) -> None:
        log.debug("SERIAL: %s", text)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> None:
    log.info("Starting Bind Bandit")
    try:
        app = App()
    except Exception as e:
        log.critical("Startup failed: %s", e, exc_info=True)
        messagebox.showerror("Startup failed", str(e))
        raise
    log.info("UI mainloop starting")
    try:
        app.mainloop()
    finally:
        log.info("Application exiting")
