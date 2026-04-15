"""Generate per-button overlay PNGs for every device in the project.

Each overlay is a transparent PNG (same size as the device image) with a
hand-drawn pencil-sketch highlight at the button's hotspot position plus a
matching handwritten legend/symbol for the represented physical control.
Joy-Con overlays use shape-aware drawing matching JOYCON_BUTTON_SHAPES.
Seven rainbow colour variants are generated per button so the user can choose
their preferred highlight colour at runtime:

  red/ orange/ yellow/ green/ blue/ indigo/ violet/

For each colour a **pale composite** image is also generated — a single
1536×1024 PNG that shows *all* buttons drawn at reduced opacity in one image.
These pale images are used by the helper-app canvas as a dim "all buttons"
texture, with the selected button getting its bright individual overlay on top.

The default colour is **violet**.

Output layout:

        docs/ui/button_overlays/
            default/
                red/
                    joycon/    jc_ZL.png, jc_ZR.png, ..., pale_joycon.png
                    ...
                orange/ yellow/ green/ blue/ indigo/ violet/
                    ...
            dark/
                red/ orange/ yellow/ green/ blue/ indigo/ violet/
                    ...

Usage:
    python tools/generate_button_overlays.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import zlib
from functools import lru_cache
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except ImportError as e:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise SystemExit(1) from e

REPO_ROOT = Path(__file__).resolve().parents[1]

# Import shapes + positions from the authoritative constants.py
sys.path.insert(0, str(REPO_ROOT / "helper-app"))
from joycon_helper.ui.constants import (  # noqa: E402  # isort: skip
    GAMEPAD_BUTTON_SHAPES,
    GAMEPAD_HOTSPOTS as _GAMEPAD_NORM,
    GAMEPAD_WIDE,
    INCEDIUS_HOTSPOTS as _INCEDIUS_NORM,
    INCEDIUS_WIDE,
    JOYCON_BUTTON_SHAPES,
    KBD_BUTTON_SHAPES,
    KBD_HOTSPOTS as _KBD_NORM,
    KBD_WIDE,
    KEYMAP_HOTSPOTS,
    M913_HOTSPOTS as _M913_NORM,
    M913_WIDE,
    MOUSE_HOTSPOTS as _MOUSE_NORM,
    MOUSE_WIDE,
)

UI_DIR = REPO_ROOT / "docs" / "ui"
OUT_DIR = UI_DIR / "button_overlays"
DOODLE_FONT = UI_DIR / "fonts" / "Doodle.otf"

IMAGE_W = 1536
IMAGE_H = 1024

RADIUS_NORMAL = 22
RADIUS_WIDE = 30

# Alpha for individual bright overlays vs pale composites
PALE_ALPHA_FRACTION = 0.30

# Reproducible hand-drawn wobble
RNG = random.Random(42)

THEMES = ("default", "dark")


def _load_hotspot_positions_json() -> dict[str, list[tuple[str, float, float]]]:
    """Load repo-root hotspot_positions.json (if present).

    The helper app can import/export per-device hotspot coordinates to this
    file. Using it here keeps the generated PNG overlays aligned with the
    positions the app will actually use.
    """
    path = REPO_ROOT / "hotspot_positions.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, list[tuple[str, float, float]]] = {}
        if not isinstance(raw, dict):
            return {}
        for device, items in raw.items():
            if not isinstance(device, str) or not isinstance(items, list):
                continue
            parsed: list[tuple[str, float, float]] = []
            for row in items:
                if not isinstance(row, list) or len(row) != 3:
                    continue
                name, nx, ny = row
                if not isinstance(name, str):
                    continue
                try:
                    fx = float(nx)
                    fy = float(ny)
                except (TypeError, ValueError):
                    continue
                parsed.append((name, fx, fy))
            if parsed:
                out[device] = parsed
        return out
    except Exception:
        return {}


_HOTSPOTS_JSON = _load_hotspot_positions_json()


def _norm_to_px(norm: list[tuple[str, float, float]]) -> list[tuple[str, int, int]]:
    return [(name, int(nx * IMAGE_W), int(ny * IMAGE_H)) for name, nx, ny in norm]


def _device_norm_positions(device: str) -> list[tuple[str, float, float]] | None:
    return _HOTSPOTS_JSON.get(device)


def _stable_seed(text: str) -> int:
    """Return a stable 32-bit seed for a given string.

    Python's built-in hash() is intentionally randomized per-process; using it
    would make generated PNGs differ between runs and machines.
    """
    return zlib.crc32(text.encode("utf-8")) & 0xFFFF_FFFF


# ═══════════════════════════════════════════════════════════════════════════
# Sketch drawing primitives
# ═══════════════════════════════════════════════════════════════════════════


def _jitter(x: float, amount: float = 1.5) -> float:
    """Add small random displacement to simulate hand-drawn imprecision."""
    return x + RNG.uniform(-amount, amount)


def _draw_sketchy_circle(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float, radius: float,
    stroke: tuple[int, int, int, int],
    width: int = 2,
    passes: int = 3,
) -> None:
    """Draw a wobbly hand-drawn circle outline."""
    segments = max(16, int(radius * 1.2))
    for p in range(passes):
        jit = 1.2 + p * 0.6
        points: list[tuple[float, float]] = []
        for i in range(segments + 1):
            angle = (i / segments) * 2 * math.pi
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)
            if 0 < i < segments:
                px = _jitter(px, jit)
                py = _jitter(py, jit)
            points.append((px, py))
        alpha = stroke[3] - p * 30
        col = (stroke[0], stroke[1], stroke[2], max(40, alpha))
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=col, width=width)


def _draw_crosshatch_fill(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float, radius: float,
    color: tuple[int, int, int, int],
    density: int = 5,
) -> None:
    """Fill a circular area with sketchy cross-hatch lines."""
    spacing = max(3, int(radius * 2 / density))
    for offset in range(-int(radius), int(radius) + 1, spacing):
        half = math.sqrt(max(0, radius ** 2 - offset ** 2))
        if half < 2:
            continue
        # Diagonal hatching (/)
        x0 = cx + offset - half * 0.5
        y0 = cy - half
        x1 = cx + offset + half * 0.5
        y1 = cy + half
        x0, y0 = _jitter(x0, 1.0), _jitter(y0, 1.0)
        x1, y1 = _jitter(x1, 1.0), _jitter(y1, 1.0)
        draw.line([(x0, y0), (x1, y1)], fill=color, width=1)


# ═══════════════════════════════════════════════════════════════════════════
# Shape-aware drawing for Joy-Con buttons
# ═══════════════════════════════════════════════════════════════════════════


def _draw_shape(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    label: str,
    color: tuple[int, int, int, int],
    shapes: dict,
) -> None:
    """Draw the button shape matching JOYCON_BUTTON_SHAPES at (cx, cy)."""
    spec = shapes.get(label)
    if not spec:
        _draw_circle_overlay(draw, cx, cy, RADIUS_NORMAL, color)
        return

    kind = spec[0]

    if kind == "circle":
        _draw_circle_overlay(draw, cx, cy, spec[1], color)

    elif kind == "rrect":
        w, h, cr = spec[1], spec[2], spec[3]
        bbox = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        fill = (color[0], color[1], color[2], color[3] // 3)
        draw.rounded_rectangle(bbox, radius=cr, fill=fill)
        for p in range(3):
            jit = 1.0 + p * 0.5
            alpha = color[3] - p * 30
            col = (color[0], color[1], color[2], max(40, alpha))
            _draw_sketchy_rrect(draw, cx, cy, w, h, cr, col, 2, jit)

    elif kind == "plus":
        arm, t = spec[1], spec[2]
        fill = (color[0], color[1], color[2], color[3] // 3)
        draw.rectangle((cx - arm, cy - t, cx + arm, cy + t), fill=fill)
        draw.rectangle((cx - t, cy - arm, cx + t, cy + arm), fill=fill)
        col = color
        # Horizontal bar outline
        _draw_sketchy_rect_lines(draw, cx - arm, cy - t, cx + arm, cy + t, col)
        # Vertical bar outline
        _draw_sketchy_rect_lines(draw, cx - t, cy - arm, cx + t, cy + arm, col)

    elif kind == "home":
        s = spec[1]
        fill = (color[0], color[1], color[2], color[3] // 3)
        # Triangle roof
        tri = [(cx, cy - s * 1.2), (cx + s, cy - s * 0.1), (cx - s, cy - s * 0.1)]
        draw.polygon(tri, fill=fill, outline=color)
        # Rectangle body
        body = (cx - s * 0.7, cy - s * 0.1, cx + s * 0.7, cy + s)
        draw.rectangle(body, fill=fill, outline=color)

    elif kind == "camera":
        s = spec[1]
        fill = (color[0], color[1], color[2], color[3] // 3)
        # Body
        body = (cx - s * 1.2, cy - s * 0.5, cx + s * 1.2, cy + s * 0.8)
        draw.rounded_rectangle(body, radius=int(s * 0.2), fill=fill, outline=color)
        # Lens bump
        bump = (cx - s * 0.35, cy - s * 0.9, cx + s * 0.35, cy - s * 0.5)
        draw.rectangle(bump, fill=fill, outline=color)

    elif kind.startswith("arrow_"):
        s = spec[1]
        d = kind[6:]
        pts = _arrow_polygon(cx, cy, s, d)
        fill = (color[0], color[1], color[2], color[3] // 3)
        draw.polygon(pts, fill=fill, outline=color)

    elif kind.startswith("arc_"):
        inner_r, outer_r = spec[1], spec[2]
        d = kind[4:]
        _draw_arc_segment(draw, cx, cy, inner_r, outer_r, d, color)

    else:
        _draw_circle_overlay(draw, cx, cy, RADIUS_NORMAL, color)


def _draw_circle_overlay(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float, radius: float,
    color: tuple[int, int, int, int],
) -> None:
    """Draw a sketchy circle overlay (existing style)."""
    RNG.seed(_stable_seed(f"{cx:.0f},{cy:.0f}"))
    fill_color = (color[0], color[1], color[2], color[3] // 3)
    _draw_crosshatch_fill(draw, cx, cy, radius - 2, fill_color, density=5)
    _draw_sketchy_circle(draw, cx, cy, radius, color, width=2, passes=3)
    faint = (color[0], color[1], color[2], color[3] // 4)
    _draw_sketchy_circle(draw, cx, cy, radius + 5, faint, width=1, passes=1)


def _draw_sketchy_rrect(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float, w: float, h: float, cr: float,
    color: tuple[int, int, int, int],
    width: int = 2,
    jit: float = 1.0,
) -> None:
    """Draw a sketchy rounded-rectangle outline."""
    x0, y0 = cx - w / 2, cy - h / 2
    x1, y1 = cx + w / 2, cy + h / 2
    # Top edge
    for i in range(int(cr), int(w - cr), 3):
        px = _jitter(x0 + i, jit)
        py = _jitter(y0, jit)
        px2 = _jitter(x0 + i + 3, jit)
        py2 = _jitter(y0, jit)
        draw.line([(px, py), (px2, py2)], fill=color, width=width)
    # Bottom edge
    for i in range(int(cr), int(w - cr), 3):
        px = _jitter(x0 + i, jit)
        py = _jitter(y1, jit)
        px2 = _jitter(x0 + i + 3, jit)
        py2 = _jitter(y1, jit)
        draw.line([(px, py), (px2, py2)], fill=color, width=width)
    # Left edge
    for i in range(int(cr), int(h - cr), 3):
        px = _jitter(x0, jit)
        py = _jitter(y0 + i, jit)
        px2 = _jitter(x0, jit)
        py2 = _jitter(y0 + i + 3, jit)
        draw.line([(px, py), (px2, py2)], fill=color, width=width)
    # Right edge
    for i in range(int(cr), int(h - cr), 3):
        px = _jitter(x1, jit)
        py = _jitter(y0 + i, jit)
        px2 = _jitter(x1, jit)
        py2 = _jitter(y0 + i + 3, jit)
        draw.line([(px, py), (px2, py2)], fill=color, width=width)


def _draw_sketchy_rect_lines(
    draw: ImageDraw.ImageDraw,
    x0: float, y0: float, x1: float, y1: float,
    color: tuple[int, int, int, int],
) -> None:
    """Draw sketchy outline for a rectangle."""
    for edge in [
        [(x0, y0), (x1, y0)],
        [(x1, y0), (x1, y1)],
        [(x1, y1), (x0, y1)],
        [(x0, y1), (x0, y0)],
    ]:
        draw.line(edge, fill=color, width=2)


def _arrow_polygon(cx: float, cy: float, s: float, d: str) -> list[tuple[float, float]]:
    """Return polygon points for an arrow shape."""
    if d == "up":
        return [
            (cx, cy - s), (cx + s * 0.7, cy + s * 0.1),
            (cx + s * 0.25, cy + s * 0.1), (cx + s * 0.25, cy + s),
            (cx - s * 0.25, cy + s), (cx - s * 0.25, cy + s * 0.1),
            (cx - s * 0.7, cy + s * 0.1),
        ]
    elif d == "down":
        return [
            (cx, cy + s), (cx + s * 0.7, cy - s * 0.1),
            (cx + s * 0.25, cy - s * 0.1), (cx + s * 0.25, cy - s),
            (cx - s * 0.25, cy - s), (cx - s * 0.25, cy - s * 0.1),
            (cx - s * 0.7, cy - s * 0.1),
        ]
    elif d == "left":
        return [
            (cx - s, cy), (cx + s * 0.1, cy - s * 0.7),
            (cx + s * 0.1, cy - s * 0.25), (cx + s, cy - s * 0.25),
            (cx + s, cy + s * 0.25), (cx + s * 0.1, cy + s * 0.25),
            (cx + s * 0.1, cy + s * 0.7),
        ]
    else:  # right
        return [
            (cx + s, cy), (cx - s * 0.1, cy - s * 0.7),
            (cx - s * 0.1, cy - s * 0.25), (cx - s, cy - s * 0.25),
            (cx - s, cy + s * 0.25), (cx - s * 0.1, cy + s * 0.25),
            (cx - s * 0.1, cy + s * 0.7),
        ]


def _draw_arc_segment(
    draw: ImageDraw.ImageDraw,
    cx: float, cy: float,
    inner_r: float, outer_r: float,
    direction: str,
    color: tuple[int, int, int, int],
) -> None:
    """Draw a quarter-ring arc segment using polygon approximation."""
    gap = 8  # degrees between arc segments
    if direction == "top":
        start_deg, sweep_deg = 225 + gap / 2, 90 - gap
    elif direction == "right":
        start_deg, sweep_deg = 315 + gap / 2, 90 - gap
    elif direction == "bottom":
        start_deg, sweep_deg = 45 + gap / 2, 90 - gap
    else:  # left
        start_deg, sweep_deg = 135 + gap / 2, 90 - gap

    segments = 20
    points: list[tuple[float, float]] = []
    # Outer arc
    for i in range(segments + 1):
        angle = math.radians(start_deg + sweep_deg * i / segments)
        points.append((cx + outer_r * math.cos(angle), cy - outer_r * math.sin(angle)))
    # Inner arc (reverse)
    for i in range(segments, -1, -1):
        angle = math.radians(start_deg + sweep_deg * i / segments)
        points.append((cx + inner_r * math.cos(angle), cy - inner_r * math.sin(angle)))

    fill = (color[0], color[1], color[2], color[3] // 3)
    draw.polygon(points, fill=fill, outline=color)


# ═══════════════════════════════════════════════════════════════════════════
# Hotspot definitions — one list per device
# Format: (label, pixel_x, pixel_y)
# ═══════════════════════════════════════════════════════════════════════════

# ── Joy-Con ───────────────────────────────────────────────────────────────
# Computed from the authoritative normalised positions in constants.py.
# Uses "dark" theme positions (identical to "default" for Joy-Con).
_jc_norm = _device_norm_positions("joycon") or KEYMAP_HOTSPOTS["dark"]
JOYCON_HOTSPOTS: list[tuple[str, int, int]] = _norm_to_px(_jc_norm)

# ── M913 Stock (16 buttons) ──────────────────────────────────────────────
# Computed from the authoritative normalised positions in constants.py.
_m913_norm = _device_norm_positions("m913") or _M913_NORM["dark"]
M913_HOTSPOTS: list[tuple[str, int, int]] = _norm_to_px(_m913_norm)

# ── Incedius M913 (16 buttons, same physical mouse, different skin) ──────
# Computed from the authoritative normalised positions in constants.py.
_incedius_norm = _device_norm_positions("incedius") or _INCEDIUS_NORM["dark"]
INCEDIUS_HOTSPOTS: list[tuple[str, int, int]] = _norm_to_px(_incedius_norm)

# ── Keyboard (103 keys) ──────────────────────────────────────────────────
# Computed from the authoritative normalised positions in constants.py.
_kbd_norm = _device_norm_positions("keyboard") or _KBD_NORM["dark"]
KBD_HOTSPOTS: list[tuple[str, int, int]] = _norm_to_px(_kbd_norm)

# ── Generic Mouse (7 buttons) ────────────────────────────────────────────
# Computed from the authoritative normalised positions in constants.py.
_mouse_norm = _device_norm_positions("mouse") or _MOUSE_NORM["dark"]
MOUSE_HOTSPOTS: list[tuple[str, int, int]] = _norm_to_px(_mouse_norm)

# ── Gamepad / Xbox Elite (30 buttons) ────────────────────────────────────
# Computed from the authoritative normalised positions in constants.py.
_gp_norm = _device_norm_positions("gamepad") or _GAMEPAD_NORM["dark"]
GP_HOTSPOTS: list[tuple[str, int, int]] = _norm_to_px(_gp_norm)

# ═══════════════════════════════════════════════════════════════════════════
# Rainbow colour palettes — one uniform colour per rainbow hue, all devices
# ═══════════════════════════════════════════════════════════════════════════

# Each entry maps a rainbow colour name → single RGBA used for every device.
RAINBOW_COLORS: dict[str, tuple[int, int, int, int]] = {
    "red":    (239, 47,  47, 200),
    "orange": (255, 138, 26, 200),
    "yellow": (241, 209, 24, 200),
    "green":  (34,  214, 90, 200),
    "blue":   (47,  134, 255, 200),
    "indigo": (106, 60,  255, 200),
    "violet": (193, 60,  255, 200),
}

DEFAULT_RAINBOW = "violet"

_KEYBOARD_LEGENDS: dict[str, str] = {
    "Esc": "Esc",
    "PrtSc": "Prt",
    "ScrLk": "Scr",
    "Pause": "Pau",
    "Grave": "`",
    "Minus": "-",
    "Equal": "=",
    "Backspace": "Back",
    "Ins": "Ins",
    "Home": "Home",
    "PgUp": "PgUp",
    "NumLk": "Num",
    "KPDiv": "/",
    "KPMul": "*",
    "KPMin": "-",
    "Tab": "Tab",
    "LBracket": "[",
    "RBracket": "]",
    "Backslash": "\\",
    "Del": "Del",
    "End": "End",
    "PgDn": "PgDn",
    "KPPlus": "+",
    "CapsLk": "Caps",
    "Semicolon": ";",
    "Apostrophe": "'",
    "Enter": "Enter",
    "LShift": "Shift",
    "Comma": ",",
    "Period": ".",
    "Slash": "/",
    "RShift": "Shift",
    "Up": "Up",
    "LCtrl": "Ctrl",
    "Win": "Win",
    "LAlt": "Alt",
    "Space": "Space",
    "RAlt": "Alt",
    "Fn": "Fn",
    "RCtrl": "Ctrl",
    "Left": "Lt",
    "Down": "Dn",
    "Right": "Rt",
    "KPDot": ".",
    "KPEnter": "Ent",
}

_JOYCON_LEGENDS: dict[str, str] = {
    "LStick": "LS",
    "RStick": "RS",
    "LSUp": "Up",
    "LSDown": "Dn",
    "LSLeft": "Lt",
    "LSRight": "Rt",
    "RSUp": "Up",
    "RSDown": "Dn",
    "RSLeft": "Lt",
    "RSRight": "Rt",
    "DUp": "Up",
    "DDown": "Dn",
    "DLeft": "Lt",
    "DRight": "Rt",
    "Plus": "+",
    "Minus": "-",
    "Capture": "Cap",
    "Home": "Home",
    "SL(L)": "SL",
    "SR(L)": "SR",
    "SL(R)": "SL",
    "SR(R)": "SR",
    "Shake": "Shk",
    "TiltUp": "Up",
    "TiltDn": "Dn",
    "TiltL": "Lt",
    "TiltR": "Rt",
    "Flick": "Flk",
}

_GAMEPAD_LEGENDS: dict[str, str] = {
    "View": "View",
    "Menu": "Menu",
    "Xbox": "XB",
    "Share": "Shr",
    "LS": "LS",
    "RS": "RS",
    "DUp": "Up",
    "DDown": "Dn",
    "DLeft": "Lt",
    "DRight": "Rt",
}

_MOUSE_LEGENDS: dict[str, str] = {
    "left": "L",
    "right": "R",
    "middle": "M",
    "back": "Bk",
    "forward": "Fwd",
    "scroll_up": "Up",
    "scroll_down": "Dn",
}


def _overlay_legend(device_name: str, label: str) -> str:
    if device_name == "keyboard":
        if label in _KEYBOARD_LEGENDS:
            return _KEYBOARD_LEGENDS[label]
        if label.startswith("KP") and len(label) == 3 and label[-1].isdigit():
            return label[-1]
        return label

    if device_name == "joycon":
        return _JOYCON_LEGENDS.get(label, label)

    if device_name == "gamepad":
        if label in _GAMEPAD_LEGENDS:
            return _GAMEPAD_LEGENDS[label]
        if label.startswith("P") and label[1:].isdigit():
            return label
        return label

    if device_name in {"mouse", "m913", "incedius"}:
        if label in _MOUSE_LEGENDS:
            return _MOUSE_LEGENDS[label]
        if label.startswith("side") and label[4:].isdigit():
            return label[4:]
        if label == "fire":
            return "Fire"
        return label.title()

    return label


def _shape_text_bounds(label: str, shapes: dict | None, wide_set: set[str]) -> tuple[float, float]:
    spec = (shapes or {}).get(label)
    if not spec:
        radius = RADIUS_WIDE if label in wide_set else RADIUS_NORMAL
        return radius * 1.6, radius * 1.2

    kind = spec[0]
    if kind == "circle":
        return spec[1] * 1.55, spec[1] * 1.2
    if kind == "rrect":
        return spec[1] * 0.82, spec[2] * 0.72
    if kind == "plus":
        return spec[1] * 1.35, spec[1] * 1.35
    if kind in {"home", "camera"}:
        size = spec[1]
        return size * 1.7, size * 1.2
    if kind.startswith("arrow_"):
        size = spec[1]
        return size * 1.3, size * 0.9
    if kind.startswith("arc_"):
        return spec[2] * 0.9, (spec[2] - spec[1]) * 1.2

    return RADIUS_NORMAL * 1.6, RADIUS_NORMAL * 1.2


@lru_cache(maxsize=64)
def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if DOODLE_FONT.exists():
        try:
            return ImageFont.truetype(str(DOODLE_FONT), size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit_font(text: str, max_w: float, max_h: float) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, tuple[int, int, int, int]]:
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4), (0, 0, 0, 0)))
    for size in range(int(max_h * 1.35), 9, -1):
        font = _load_font(size)
        bbox = probe.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width <= max_w and height <= max_h:
            return font, bbox
    font = _load_font(10)
    bbox = probe.textbbox((0, 0), text, font=font)
    return font, bbox


def _draw_overlay_legend(
    draw: ImageDraw.ImageDraw,
    theme: str,
    device_name: str,
    label: str,
    px: int,
    py: int,
    color: tuple[int, int, int, int],
    wide_set: set[str],
    shapes: dict | None,
) -> None:
    text = _overlay_legend(device_name, label)
    if not text:
        return

    max_w, max_h = _shape_text_bounds(label, shapes, wide_set)
    font, bbox = _fit_font(text, max_w, max_h)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = px - text_w / 2 - bbox[0]
    y = py - text_h / 2 - bbox[1]

    if theme == "dark":
        base_shadow = (0, 0, 0, 170)
        accent_shadow = (color[0], color[1], color[2], min(240, color[3] + 40))
        fill = (255, 252, 240, 235)
    else:
        base_shadow = (24, 17, 12, 115)
        accent_shadow = (color[0], color[1], color[2], min(220, color[3] + 30))
        fill = (255, 247, 231, 220)
    seed = _stable_seed(f"{device_name}:{label}:legend")
    rng = random.Random(seed)
    for dx, dy, ink in [
        (1, 1, base_shadow),
        (0, 0, accent_shadow),
        (rng.uniform(-1.2, 1.2), rng.uniform(-1.2, 1.2), accent_shadow),
    ]:
        draw.text((x + dx, y + dy), text, font=font, fill=ink)
    draw.text((x, y), text, font=font, fill=fill)

# ═══════════════════════════════════════════════════════════════════════════
# Device registry
# ═══════════════════════════════════════════════════════════════════════════

DEVICES: dict[str, dict] = {
    "joycon": {
        "hotspots": JOYCON_HOTSPOTS,
        "wide": set(),
        "prefix": "jc",
        "shapes": JOYCON_BUTTON_SHAPES,
    },
    "m913": {
        "hotspots": M913_HOTSPOTS,
        "wide": M913_WIDE,
        "prefix": "m913",
    },
    "incedius": {
        "hotspots": INCEDIUS_HOTSPOTS,
        "wide": INCEDIUS_WIDE,
        "prefix": "inc",
    },
    "keyboard": {
        "hotspots": KBD_HOTSPOTS,
        "wide": KBD_WIDE,
        "prefix": "kbd",
        "shapes": KBD_BUTTON_SHAPES,
    },
    "mouse": {
        "hotspots": MOUSE_HOTSPOTS,
        "wide": MOUSE_WIDE,
        "prefix": "mouse",
    },
    "gamepad": {
        "hotspots": GP_HOTSPOTS,
        "wide": GAMEPAD_WIDE,
        "prefix": "gp",
        "shapes": GAMEPAD_BUTTON_SHAPES,
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# Generation helpers
# ═══════════════════════════════════════════════════════════════════════════


def _safe_filename(label: str) -> str:
    """Convert a hotspot label to a filesystem-safe name component."""
    return label.replace("/", "_").replace("\\", "_").replace(".", "_dot_")


def _generate_overlay(
    theme: str,
    device_name: str,
    label: str,
    px: int,
    py: int,
    color: tuple[int, int, int, int],
    wide_set: set[str],
    dst: Path,
    shapes: dict | None = None,
) -> None:
    """Generate a single button overlay image with hand-drawn sketch style.

    If *shapes* is provided and *label* is in it, delegate to shape-aware
    rendering; otherwise fall back to the sketchy-circle approach.
    """
    img = Image.new("RGBA", (IMAGE_W, IMAGE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Seed per-button for reproducible wobble
    RNG.seed(_stable_seed(label))

    if shapes and label in shapes:
        _draw_shape(draw, px, py, label, color, shapes)
    else:
        r = RADIUS_WIDE if label in wide_set else RADIUS_NORMAL
        _draw_circle_overlay(draw, px, py, r, color)

    _draw_overlay_legend(draw, theme, device_name, label, px, py, color, wide_set, shapes)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dst), format="PNG", optimize=True)


def _generate_pale_composite(
    color_name: str,
    device_name: str,
    cfg: dict,
    out_dir: Path,
) -> None:
    """Composite all individual button overlays into a single pale PNG.

    Each per-button overlay is alpha-reduced by *PALE_ALPHA_FRACTION* before
    being composited onto a shared RGBA canvas.  The result is saved as
    ``pale_{device_name}.png`` inside *out_dir*.
    """
    canvas = Image.new("RGBA", (IMAGE_W, IMAGE_H), (0, 0, 0, 0))

    prefix = cfg["prefix"]
    for label, _px, _py in cfg["hotspots"]:
        fname = f"{prefix}_{_safe_filename(label)}.png"
        overlay_path = out_dir / fname
        if not overlay_path.exists():
            continue
        overlay = Image.open(str(overlay_path)).convert("RGBA")
        # Reduce the overlay alpha by PALE_ALPHA_FRACTION
        r, g, b, a = overlay.split()
        a = a.point(lambda v: int(v * PALE_ALPHA_FRACTION))
        faded = Image.merge("RGBA", (r, g, b, a))
        canvas = Image.alpha_composite(canvas, faded)

    dst = out_dir / f"pale_{device_name}.png"
    canvas.save(str(dst), format="PNG", optimize=True)


def main() -> int:
    total = 0

    for theme in THEMES:
        for color_name, color in RAINBOW_COLORS.items():
            for device_name, cfg in DEVICES.items():
                # docs/ui/button_overlays/{theme}/{color}/{device}/
                out_dir = OUT_DIR / theme / color_name / device_name
                out_dir.mkdir(parents=True, exist_ok=True)

                hotspots = cfg["hotspots"]
                wide = cfg["wide"]
                prefix = cfg["prefix"]
                shapes = cfg.get("shapes")

                for label, px, py in hotspots:
                    fname = f"{prefix}_{_safe_filename(label)}.png"
                    dst = out_dir / fname
                    _generate_overlay(theme, device_name, label, px, py, color, wide, dst, shapes=shapes)
                    total += 1

                # Generate pale composite (all overlays at reduced opacity)
                _generate_pale_composite(color_name, device_name, cfg, out_dir)
                total += 1

                print(f"  [{theme}/{color_name}/{device_name}] {len(hotspots)} overlays + pale -> {out_dir.relative_to(REPO_ROOT)}")

    print(f"[button-overlays] Generated {total} overlay PNGs (incl. pale composites) across {len(THEMES)} themes × {len(DEVICES)} devices × {len(RAINBOW_COLORS)} colours (default: {DEFAULT_RAINBOW})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
