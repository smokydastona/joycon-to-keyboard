"""Generate per-button overlay PNGs for every device in the project.

Each overlay is a transparent PNG (same size as the device image) with a
hand-drawn pencil-sketch highlight at the button's hotspot position.
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
      red/
        joycon/    jc_ZL.png, jc_ZR.png, ..., pale_joycon.png
        m913/      m913_left.png, ..., pale_m913.png
        incedius/  inc_left.png, ..., pale_incedius.png
        keyboard/  kbd_Esc.png, ..., pale_keyboard.png
        mouse/     mouse_Left.png, ..., pale_mouse.png
      orange/
        ...
      yellow/ green/ blue/ indigo/ violet/
        ...

Usage:
    python tools/generate_button_overlays.py
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw  # type: ignore
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]

# Import Joy-Con shapes + positions from the authoritative constants.py
sys.path.insert(0, str(REPO_ROOT / "helper-app"))
from joycon_helper.ui.constants import JOYCON_BUTTON_SHAPES, KEYMAP_HOTSPOTS  # noqa: E402

UI_DIR = REPO_ROOT / "docs" / "ui"
OUT_DIR = UI_DIR / "button_overlays"

IMAGE_W = 1536
IMAGE_H = 1024

RADIUS_NORMAL = 22
RADIUS_WIDE = 30

# Alpha for individual bright overlays vs pale composites
PALE_ALPHA_FRACTION = 0.30

# Reproducible hand-drawn wobble
RNG = random.Random(42)


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
    RNG.seed(hash(f"{cx:.0f},{cy:.0f}") & 0xFFFF_FFFF)
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
JOYCON_HOTSPOTS: list[tuple[str, int, int]] = [
    (name, int(nx * IMAGE_W), int(ny * IMAGE_H))
    for name, nx, ny in KEYMAP_HOTSPOTS["dark"]
]

# ── M913 Stock (16 buttons) ──────────────────────────────────────────────
# Positions approximate on the composited m913.png (mouse centered ~782, 459).
# Side buttons are the 12-key thumb grid on the left side of the mouse body.
M913_HOTSPOTS: list[tuple[str, int, int]] = [
    # Main buttons
    ("left",       898,  648),
    ("right",      928,  527),
    ("middle",     828,  568),
    ("fire",       921,  586),
    # Scroll wheel
    ("scroll_up",  834,  514),
    ("scroll_down",814,  623),
    # Side buttons — 4 rows × 3 cols
    ("side1",      545,  298),
    ("side2",      634,  260),
    ("side3",      711,  239),
    ("side4",      620,  333),
    ("side5",      701,  312),
    ("side6",      682,  381),
    ("side7",      602,  412),
    ("side8",      517,  367),
    ("side9",      701,  443),
    ("side10",     603,  483),
    ("side11",     503,  455),
    ("side12",     600,  576),
]

M913_WIDE = {"left", "right"}

# ── Incedius M913 (16 buttons, same physical mouse, same button IDs) ─────
# Uses the same pixel positions and side1-12 naming as M913 stock.
INCEDIUS_HOTSPOTS: list[tuple[str, int, int]] = [
    # Main buttons
    ("left",       898,  648),
    ("right",      928,  527),
    ("middle",     828,  568),
    ("fire",       921,  586),
    # Scroll wheel
    ("scroll_up",  834,  514),
    ("scroll_down",814,  623),
    # Side buttons (same side1-12 IDs as stock M913)
    ("side1",      545,  298),
    ("side2",      634,  260),
    ("side3",      711,  239),
    ("side4",      620,  333),
    ("side5",      701,  312),
    ("side6",      682,  381),
    ("side7",      602,  412),
    ("side8",      517,  367),
    ("side9",      701,  443),
    ("side10",     603,  483),
    ("side11",     503,  455),
    ("side12",     600,  576),
]

INCEDIUS_WIDE = {"left", "right"}

# ── Keyboard (103 keys) ──────────────────────────────────────────────────
# Must stay in sync with KBD_HOTSPOTS in app.py.
KBD_HOTSPOTS: list[tuple[str, int, int]] = [
    # Function row
    ("Esc",     97,  155),
    ("F1",     207,  155),
    ("F2",     267,  155),
    ("F3",     327,  155),
    ("F4",     387,  155),
    ("F5",     477,  155),
    ("F6",     537,  155),
    ("F7",     597,  155),
    ("F8",     657,  155),
    ("F9",     747,  155),
    ("F10",    807,  155),
    ("F11",    867,  155),
    ("F12",    927,  155),
    # Nav cluster — top row
    ("PrtSc", 1007,  155),
    ("ScrLk", 1067,  155),
    ("Pause", 1127,  155),
    # Number row
    ("Grave",   97,  275),
    ("1",      157,  275),
    ("2",      217,  275),
    ("3",      277,  275),
    ("4",      337,  275),
    ("5",      397,  275),
    ("6",      457,  275),
    ("7",      517,  275),
    ("8",      577,  275),
    ("9",      637,  275),
    ("0",      697,  275),
    ("Minus",  757,  275),
    ("Equal",  817,  275),
    ("Backspace", 907, 275),
    ("Ins",   1007,  275),
    ("Home",  1067,  275),
    ("PgUp",  1127,  275),
    ("NumLk", 1217,  275),
    ("KPDiv", 1277,  275),
    ("KPMul", 1337,  275),
    ("KPMin", 1397,  275),
    # QWERTY row
    ("Tab",    117,  350),
    ("Q",      187,  350),
    ("W",      247,  350),
    ("E",      307,  350),
    ("R",      367,  350),
    ("T",      427,  350),
    ("Y",      487,  350),
    ("U",      547,  350),
    ("I",      607,  350),
    ("O",      667,  350),
    ("P",      727,  350),
    ("LBracket", 787, 350),
    ("RBracket", 847, 350),
    ("Backslash", 917, 350),
    ("Del",   1007,  350),
    ("End",   1067,  350),
    ("PgDn",  1127,  350),
    ("KP7",   1217,  350),
    ("KP8",   1277,  350),
    ("KP9",   1337,  350),
    ("KPPlus",1397,  390),
    # Home row
    ("CapsLk", 127,  430),
    ("A",      207,  430),
    ("S",      267,  430),
    ("D",      327,  430),
    ("F",      387,  430),
    ("G",      447,  430),
    ("H",      507,  430),
    ("J",      567,  430),
    ("K",      627,  430),
    ("L",      687,  430),
    ("Semicolon", 747, 430),
    ("Apostrophe", 807, 430),
    ("Enter",  897,  430),
    ("KP4",   1217,  430),
    ("KP5",   1277,  430),
    ("KP6",   1337,  430),
    # Shift row
    ("LShift", 137,  510),
    ("Z",      247,  510),
    ("X",      307,  510),
    ("C",      367,  510),
    ("V",      427,  510),
    ("B",      487,  510),
    ("N",      547,  510),
    ("M",      607,  510),
    ("Comma",  667,  510),
    ("Period", 727,  510),
    ("Slash",  787,  510),
    ("RShift", 887,  510),
    ("Up",    1067,  510),
    ("KP1",   1217,  510),
    ("KP2",   1277,  510),
    ("KP3",   1337,  510),
    ("KPEnter", 1397, 545),
    # Bottom row
    ("LCtrl",  117,  590),
    ("Win",    187,  590),
    ("LAlt",   247,  590),
    ("Space",  487,  590),
    ("RAlt",   667,  590),
    ("Fn",     727,  590),
    ("RCtrl",  847,  590),
    ("Left",  1007,  590),
    ("Down",  1067,  590),
    ("Right", 1127,  590),
    ("KP0",   1247,  590),
    ("KPDot", 1337,  590),
]

KBD_WIDE = {
    "Backspace", "Tab", "CapsLk", "Enter", "LShift", "RShift",
    "Space", "LCtrl", "RCtrl", "KP0", "KPPlus", "KPEnter",
}

# ── Generic Mouse (7 buttons — future-proof placeholder) ─────────────────
# Positions centered on a 1536×1024 canvas assuming a standard top-down
# mouse silhouette (Razer Basilisk X HyperSpeed layout).
# Labels match razer_device.BUTTON_SLOTS keys for overlay integration.
MOUSE_HOTSPOTS: list[tuple[str, int, int]] = [
    ("left",        700,  310),
    ("right",       850,  310),
    ("middle",      775,  260),
    ("scroll_up",   775,  220),
    ("scroll_down", 775,  310),
    ("back",        645,  430),
    ("forward",     645,  380),
]

MOUSE_WIDE = {"left", "right"}

# ═══════════════════════════════════════════════════════════════════════════
# Rainbow colour palettes — one uniform colour per rainbow hue, all devices
# ═══════════════════════════════════════════════════════════════════════════

# Each entry maps a rainbow colour name → single RGBA used for every device.
RAINBOW_COLORS: dict[str, tuple[int, int, int, int]] = {
    "red":    (220, 60,  60, 170),
    "orange": (230, 140, 40, 170),
    "yellow": (210, 190, 40, 170),
    "green":  (60,  185, 80, 170),
    "blue":   (60,  120, 220, 170),
    "indigo": (90,  60,  180, 170),
    "violet": (160, 60,  200, 170),
}

DEFAULT_RAINBOW = "violet"

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
    },
    "mouse": {
        "hotspots": MOUSE_HOTSPOTS,
        "wide": MOUSE_WIDE,
        "prefix": "mouse",
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# Generation helpers
# ═══════════════════════════════════════════════════════════════════════════


def _safe_filename(label: str) -> str:
    """Convert a hotspot label to a filesystem-safe name component."""
    return label.replace("/", "_").replace("\\", "_").replace(".", "_dot_")


def _generate_overlay(
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
    RNG.seed(hash(label) & 0xFFFF_FFFF)

    if shapes and label in shapes:
        _draw_shape(draw, px, py, label, color, shapes)
    else:
        r = RADIUS_WIDE if label in wide_set else RADIUS_NORMAL
        _draw_circle_overlay(draw, px, py, r, color)

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

    for color_name, color in RAINBOW_COLORS.items():
        for device_name, cfg in DEVICES.items():
            # docs/ui/button_overlays/{color}/{device}/
            out_dir = OUT_DIR / color_name / device_name
            out_dir.mkdir(parents=True, exist_ok=True)

            hotspots = cfg["hotspots"]
            wide = cfg["wide"]
            prefix = cfg["prefix"]
            shapes = cfg.get("shapes")

            for label, px, py in hotspots:
                fname = f"{prefix}_{_safe_filename(label)}.png"
                dst = out_dir / fname
                _generate_overlay(label, px, py, color, wide, dst, shapes=shapes)
                total += 1

            # Generate pale composite (all overlays at reduced opacity)
            _generate_pale_composite(color_name, device_name, cfg, out_dir)
            total += 1

            print(f"  [{color_name}/{device_name}] {len(hotspots)} overlays + pale -> {out_dir.relative_to(REPO_ROOT)}")

    print(f"[button-overlays] Generated {total} overlay PNGs (incl. pale composites) across {len(DEVICES)} devices × {len(RAINBOW_COLORS)} colours (default: {DEFAULT_RAINBOW})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
