"""Generate per-button overlay PNGs for every device in the project.

Each overlay is a transparent PNG (same size as the device image) with a
glowing highlight circle at the button's hotspot position.

Devices and their highlight colours:

  - joycon   — red   (#e04040)   — Joy-Con controller buttons
  - m913     — gold  (#d4a030)   — Stock Redragon M913 mouse
  - incedius — green (#40d860)   — IncediusMod M913 variant
  - keyboard — blue  (#4a90d0)   — Full-size keyboard keys
  - mouse    — purple (#c880e0)  — Generic mouse (future-proof)

Output layout:

    docs/ui/button_overlays/
      joycon/    jc_ZL.png, jc_ZR.png, ...
      m913/      m913_left.png, m913_side1.png, ...
      incedius/  inc_left.png, inc_Thumb1.png, ...
      keyboard/  kbd_Esc.png, kbd_A.png, ...
      mouse/     mouse_Left.png, mouse_Right.png, ...

Usage:
    python tools/generate_button_overlays.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter  # type: ignore
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "docs" / "ui"
OUT_DIR = UI_DIR / "button_overlays"

IMAGE_W = 1536
IMAGE_H = 1024

RADIUS_NORMAL = 22
RADIUS_WIDE = 30
GLOW_EXTRA = 10  # extra pixels for the soft glow ring

# ═══════════════════════════════════════════════════════════════════════════
# Hotspot definitions — one list per device
# Format: (label, pixel_x, pixel_y)
# ═══════════════════════════════════════════════════════════════════════════

# ── Joy-Con (16 buttons) ─────────────────────────────────────────────────
# Matches KEYMAP_HOTSPOTS in app.py — positions on the joycons composites.
JOYCON_HOTSPOTS: list[tuple[str, int, int]] = [
    ("ZL",     420,  150),
    ("ZR",    1115,  150),
    ("Minus",  420,  335),
    ("Plus",  1110,  335),
    ("Capture", 395, 720),
    ("Home",  1140,  720),
    ("LStick", 250,  435),
    ("DUp",    300,  545),
    ("DDown",  300,  665),
    ("DLeft",  225,  605),
    ("DRight", 375,  605),
    ("A",     1330,  460),
    ("B",     1260,  535),
    ("X",     1260,  385),
    ("Y",     1190,  460),
    ("RStick",1260,  605),
]

JOYCON_WIDE = {"ZL", "ZR", "LStick", "RStick"}

# ── M913 Stock (16 buttons) ──────────────────────────────────────────────
# Positions approximate on the composited m913.png (mouse centered ~782, 459).
# Side buttons are the 12-key thumb grid on the left side of the mouse body.
M913_HOTSPOTS: list[tuple[str, int, int]] = [
    # Main buttons
    ("left",    670,  250),
    ("right",   890,  250),
    ("middle",  785,  225),
    ("fire",    700,  360),
    # Side buttons — 4 rows × 3 cols
    ("side1",   530,  380),
    ("side2",   575,  380),
    ("side3",   620,  380),
    ("side4",   530,  435),
    ("side5",   575,  435),
    ("side6",   620,  435),
    ("side7",   530,  490),
    ("side8",   575,  490),
    ("side9",   620,  490),
    ("side10",  530,  540),
    ("side11",  575,  540),
    ("side12",  620,  540),
]

M913_WIDE = {"left", "right"}

# ── Incedius M913 (16 buttons, same physical mouse, different labels) ────
# Uses the same pixel positions as M913 stock but with IncediusMod naming.
INCEDIUS_HOTSPOTS: list[tuple[str, int, int]] = [
    # Main buttons (unchanged)
    ("left",    670,  250),
    ("right",   890,  250),
    ("middle",  785,  225),
    ("fire",    700,  360),
    # Thumb buttons (side1-6 → Thumb 1-6)
    ("Thumb1",  530,  380),
    ("Thumb2",  575,  380),
    ("Thumb3",  620,  380),
    ("Thumb4",  530,  435),
    ("Thumb5",  575,  435),
    ("Thumb6",  620,  435),
    # Finger buttons (side7-12 → Finger 1-6)
    ("Finger1", 530,  490),
    ("Finger2", 575,  490),
    ("Finger3", 620,  490),
    ("Finger4", 530,  540),
    ("Finger5", 575,  540),
    ("Finger6", 620,  540),
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
# mouse silhouette.  These will be refined once a dedicated mouse image is
# created.
MOUSE_HOTSPOTS: list[tuple[str, int, int]] = [
    ("Left",      700,  310),
    ("Right",     850,  310),
    ("Middle",    775,  280),
    ("ScrollUp",  775,  240),
    ("ScrollDn",  775,  330),
    ("Back",      660,  420),
    ("Forward",   660,  370),
]

MOUSE_WIDE = {"Left", "Right"}

# ═══════════════════════════════════════════════════════════════════════════
# Device registry
# ═══════════════════════════════════════════════════════════════════════════

DEVICES: dict[str, dict] = {
    "joycon": {
        "hotspots": JOYCON_HOTSPOTS,
        "color": (224, 64, 64, 180),       # red
        "wide": JOYCON_WIDE,
        "prefix": "jc",
    },
    "m913": {
        "hotspots": M913_HOTSPOTS,
        "color": (212, 160, 48, 180),      # gold
        "wide": M913_WIDE,
        "prefix": "m913",
    },
    "incedius": {
        "hotspots": INCEDIUS_HOTSPOTS,
        "color": (64, 216, 96, 180),       # green
        "wide": INCEDIUS_WIDE,
        "prefix": "inc",
    },
    "keyboard": {
        "hotspots": KBD_HOTSPOTS,
        "color": (74, 144, 208, 180),      # blue
        "wide": KBD_WIDE,
        "prefix": "kbd",
    },
    "mouse": {
        "hotspots": MOUSE_HOTSPOTS,
        "color": (200, 128, 224, 180),     # purple
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
) -> None:
    """Generate a single button overlay image."""
    r = RADIUS_WIDE if label in wide_set else RADIUS_NORMAL
    gr = r + GLOW_EXTRA

    img = Image.new("RGBA", (IMAGE_W, IMAGE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer glow ring (softer, larger)
    glow_color = (color[0], color[1], color[2], color[3] // 3)
    draw.ellipse([px - gr, py - gr, px + gr, py + gr], fill=glow_color)

    # Inner highlight circle
    draw.ellipse(
        [px - r, py - r, px + r, py + r],
        fill=color,
        outline=(255, 255, 255, 200),
        width=2,
    )

    # Gaussian blur for the glow
    img = img.filter(ImageFilter.GaussianBlur(radius=4))

    # Re-draw solid inner circle on top of blur
    draw2 = ImageDraw.Draw(img)
    draw2.ellipse(
        [px - r, py - r, px + r, py + r],
        fill=color,
        outline=(255, 255, 255, 220),
        width=2,
    )

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dst), format="PNG", optimize=True)


def main() -> int:
    total = 0

    for device_name, cfg in DEVICES.items():
        out_dir = OUT_DIR / device_name
        out_dir.mkdir(parents=True, exist_ok=True)

        hotspots = cfg["hotspots"]
        color = cfg["color"]
        wide = cfg["wide"]
        prefix = cfg["prefix"]

        for label, px, py in hotspots:
            fname = f"{prefix}_{_safe_filename(label)}.png"
            dst = out_dir / fname
            _generate_overlay(label, px, py, color, wide, dst)
            total += 1

        print(f"  [{device_name}] {len(hotspots)} overlays → {out_dir.relative_to(REPO_ROOT)}")

    print(f"[button-overlays] Generated {total} overlay PNGs across {len(DEVICES)} devices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
