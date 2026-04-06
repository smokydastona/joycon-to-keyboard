"""Generate keyboard button overlay PNGs for each key.

Each overlay is a transparent PNG (same size as the keyboard image) with a
glowing highlight circle at the key's hotspot position.  Themes control the
highlight colour:

  - default  — warm gold (#d4a030)
  - dark     — cool blue (#4a90d0)
  - incedius — vivid green (#40d860)

Usage:
    python tools/generate_keyboard_overlays.py
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

IMAGE_W = 1536
IMAGE_H = 1024

# Theme highlight colours (RGBA)
THEME_COLORS: dict[str, tuple[int, int, int, int]] = {
    "default": (212, 160, 48, 180),
    "dark": (74, 144, 208, 180),
    "incedius": (64, 216, 96, 180),
}

# Keyboard hotspot definitions — must stay in sync with app.py KBD_HOTSPOTS.
KBD_HOTSPOTS: list[tuple[str, float, float]] = [
    ("Esc",    97 / IMAGE_W,  155 / IMAGE_H),
    ("F1",    207 / IMAGE_W,  155 / IMAGE_H),
    ("F2",    267 / IMAGE_W,  155 / IMAGE_H),
    ("F3",    327 / IMAGE_W,  155 / IMAGE_H),
    ("F4",    387 / IMAGE_W,  155 / IMAGE_H),
    ("F5",    477 / IMAGE_W,  155 / IMAGE_H),
    ("F6",    537 / IMAGE_W,  155 / IMAGE_H),
    ("F7",    597 / IMAGE_W,  155 / IMAGE_H),
    ("F8",    657 / IMAGE_W,  155 / IMAGE_H),
    ("F9",    747 / IMAGE_W,  155 / IMAGE_H),
    ("F10",   807 / IMAGE_W,  155 / IMAGE_H),
    ("F11",   867 / IMAGE_W,  155 / IMAGE_H),
    ("F12",   927 / IMAGE_W,  155 / IMAGE_H),
    ("PrtSc", 1007 / IMAGE_W, 155 / IMAGE_H),
    ("ScrLk", 1067 / IMAGE_W, 155 / IMAGE_H),
    ("Pause", 1127 / IMAGE_W, 155 / IMAGE_H),
    ("Grave",  97 / IMAGE_W,  275 / IMAGE_H),
    ("1",     157 / IMAGE_W,  275 / IMAGE_H),
    ("2",     217 / IMAGE_W,  275 / IMAGE_H),
    ("3",     277 / IMAGE_W,  275 / IMAGE_H),
    ("4",     337 / IMAGE_W,  275 / IMAGE_H),
    ("5",     397 / IMAGE_W,  275 / IMAGE_H),
    ("6",     457 / IMAGE_W,  275 / IMAGE_H),
    ("7",     517 / IMAGE_W,  275 / IMAGE_H),
    ("8",     577 / IMAGE_W,  275 / IMAGE_H),
    ("9",     637 / IMAGE_W,  275 / IMAGE_H),
    ("0",     697 / IMAGE_W,  275 / IMAGE_H),
    ("Minus", 757 / IMAGE_W,  275 / IMAGE_H),
    ("Equal", 817 / IMAGE_W,  275 / IMAGE_H),
    ("Backspace", 907 / IMAGE_W, 275 / IMAGE_H),
    ("Ins",   1007 / IMAGE_W, 275 / IMAGE_H),
    ("Home",  1067 / IMAGE_W, 275 / IMAGE_H),
    ("PgUp",  1127 / IMAGE_W, 275 / IMAGE_H),
    ("NumLk", 1217 / IMAGE_W, 275 / IMAGE_H),
    ("KPDiv", 1277 / IMAGE_W, 275 / IMAGE_H),
    ("KPMul", 1337 / IMAGE_W, 275 / IMAGE_H),
    ("KPMin", 1397 / IMAGE_W, 275 / IMAGE_H),
    ("Tab",   117 / IMAGE_W,  350 / IMAGE_H),
    ("Q",     187 / IMAGE_W,  350 / IMAGE_H),
    ("W",     247 / IMAGE_W,  350 / IMAGE_H),
    ("E",     307 / IMAGE_W,  350 / IMAGE_H),
    ("R",     367 / IMAGE_W,  350 / IMAGE_H),
    ("T",     427 / IMAGE_W,  350 / IMAGE_H),
    ("Y",     487 / IMAGE_W,  350 / IMAGE_H),
    ("U",     547 / IMAGE_W,  350 / IMAGE_H),
    ("I",     607 / IMAGE_W,  350 / IMAGE_H),
    ("O",     667 / IMAGE_W,  350 / IMAGE_H),
    ("P",     727 / IMAGE_W,  350 / IMAGE_H),
    ("LBracket", 787 / IMAGE_W, 350 / IMAGE_H),
    ("RBracket", 847 / IMAGE_W, 350 / IMAGE_H),
    ("Backslash", 917 / IMAGE_W, 350 / IMAGE_H),
    ("Del",   1007 / IMAGE_W, 350 / IMAGE_H),
    ("End",   1067 / IMAGE_W, 350 / IMAGE_H),
    ("PgDn",  1127 / IMAGE_W, 350 / IMAGE_H),
    ("KP7",   1217 / IMAGE_W, 350 / IMAGE_H),
    ("KP8",   1277 / IMAGE_W, 350 / IMAGE_H),
    ("KP9",   1337 / IMAGE_W, 350 / IMAGE_H),
    ("KPPlus", 1397 / IMAGE_W, 390 / IMAGE_H),
    ("CapsLk", 127 / IMAGE_W, 430 / IMAGE_H),
    ("A",     207 / IMAGE_W,  430 / IMAGE_H),
    ("S",     267 / IMAGE_W,  430 / IMAGE_H),
    ("D",     327 / IMAGE_W,  430 / IMAGE_H),
    ("F",     387 / IMAGE_W,  430 / IMAGE_H),
    ("G",     447 / IMAGE_W,  430 / IMAGE_H),
    ("H",     507 / IMAGE_W,  430 / IMAGE_H),
    ("J",     567 / IMAGE_W,  430 / IMAGE_H),
    ("K",     627 / IMAGE_W,  430 / IMAGE_H),
    ("L",     687 / IMAGE_W,  430 / IMAGE_H),
    ("Semicolon", 747 / IMAGE_W, 430 / IMAGE_H),
    ("Apostrophe", 807 / IMAGE_W, 430 / IMAGE_H),
    ("Enter", 897 / IMAGE_W,  430 / IMAGE_H),
    ("KP4",   1217 / IMAGE_W, 430 / IMAGE_H),
    ("KP5",   1277 / IMAGE_W, 430 / IMAGE_H),
    ("KP6",   1337 / IMAGE_W, 430 / IMAGE_H),
    ("LShift", 137 / IMAGE_W, 510 / IMAGE_H),
    ("Z",     247 / IMAGE_W,  510 / IMAGE_H),
    ("X",     307 / IMAGE_W,  510 / IMAGE_H),
    ("C",     367 / IMAGE_W,  510 / IMAGE_H),
    ("V",     427 / IMAGE_W,  510 / IMAGE_H),
    ("B",     487 / IMAGE_W,  510 / IMAGE_H),
    ("N",     547 / IMAGE_W,  510 / IMAGE_H),
    ("M",     607 / IMAGE_W,  510 / IMAGE_H),
    ("Comma", 667 / IMAGE_W,  510 / IMAGE_H),
    ("Period", 727 / IMAGE_W, 510 / IMAGE_H),
    ("Slash", 787 / IMAGE_W,  510 / IMAGE_H),
    ("RShift", 887 / IMAGE_W, 510 / IMAGE_H),
    ("Up",    1067 / IMAGE_W, 510 / IMAGE_H),
    ("KP1",   1217 / IMAGE_W, 510 / IMAGE_H),
    ("KP2",   1277 / IMAGE_W, 510 / IMAGE_H),
    ("KP3",   1337 / IMAGE_W, 510 / IMAGE_H),
    ("KPEnter", 1397 / IMAGE_W, 545 / IMAGE_H),
    ("LCtrl", 117 / IMAGE_W,  590 / IMAGE_H),
    ("Win",   187 / IMAGE_W,  590 / IMAGE_H),
    ("LAlt",  247 / IMAGE_W,  590 / IMAGE_H),
    ("Space", 487 / IMAGE_W,  590 / IMAGE_H),
    ("RAlt",  667 / IMAGE_W,  590 / IMAGE_H),
    ("Fn",    727 / IMAGE_W,  590 / IMAGE_H),
    ("RCtrl", 847 / IMAGE_W,  590 / IMAGE_H),
    ("Left",  1007 / IMAGE_W, 590 / IMAGE_H),
    ("Down",  1067 / IMAGE_W, 590 / IMAGE_H),
    ("Right", 1127 / IMAGE_W, 590 / IMAGE_H),
    ("KP0",   1247 / IMAGE_W, 590 / IMAGE_H),
    ("KPDot", 1337 / IMAGE_W, 590 / IMAGE_H),
]

# Wider keys get a larger highlight radius.
WIDE_KEYS = {
    "Backspace", "Tab", "CapsLk", "Enter", "LShift", "RShift",
    "Space", "LCtrl", "RCtrl", "KP0", "KPPlus", "KPEnter",
}

RADIUS_NORMAL = 22
RADIUS_WIDE = 30
GLOW_EXTRA = 10  # extra pixels for the soft glow ring


def _safe_filename(label: str) -> str:
    """Convert a hotspot label to a safe filename component."""
    return label.replace("/", "_").replace("\\", "_").replace(".", "_dot_")


def _generate_overlay(
    label: str,
    norm_x: float,
    norm_y: float,
    color: tuple[int, int, int, int],
    dst: Path,
) -> None:
    """Generate a single key overlay image."""
    px = int(norm_x * IMAGE_W)
    py = int(norm_y * IMAGE_H)
    r = RADIUS_WIDE if label in WIDE_KEYS else RADIUS_NORMAL
    gr = r + GLOW_EXTRA

    # Create transparent image
    img = Image.new("RGBA", (IMAGE_W, IMAGE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer glow ring (softer, larger)
    glow_color = (color[0], color[1], color[2], color[3] // 3)
    draw.ellipse(
        [px - gr, py - gr, px + gr, py + gr],
        fill=glow_color,
    )

    # Inner highlight circle
    draw.ellipse(
        [px - r, py - r, px + r, py + r],
        fill=color,
        outline=(255, 255, 255, 200),
        width=2,
    )

    # Apply a slight Gaussian blur for the glow effect
    img = img.filter(ImageFilter.GaussianBlur(radius=4))

    # Re-draw the solid inner circle on top of the blurred image
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
    generated = 0

    for theme, color in THEME_COLORS.items():
        out_dir = UI_DIR / "button_overlays" / theme
        out_dir.mkdir(parents=True, exist_ok=True)

        for label, nx, ny in KBD_HOTSPOTS:
            fname = f"kbd_{_safe_filename(label)}.png"
            dst = out_dir / fname
            _generate_overlay(label, nx, ny, color, dst)
            generated += 1

    print(f"[keyboard-overlays] Generated {generated} overlay PNGs across {len(THEME_COLORS)} themes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
