"""Generate pencil-sketch style UI assets for both light and dark themes.

Creates decorative assets that give popup dialogs and toolbars a hand-drawn
notebook/sketchbook aesthetic:

  - popup-frame-{light,dark}.png   : 9-patch style border for popup windows
  - toolbar-bg-{light,dark}.png    : subtle textured strip for toolbar rows
  - divider-{light,dark}.png       : horizontal separator line (hand-drawn)
  - corner-doodle-{light,dark}.png : decorative corner flourish

Output:
    docs/ui/default/misc/sketch-*.png   (light theme)
    docs/ui/dark/misc/sketch-*.png      (dark theme)

Usage:
    python tools/generate_sketch_assets.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter  # type: ignore
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "docs" / "ui"

# Seed for reproducible "hand-drawn" look
RNG = random.Random(42)


def _jitter(x: float, amount: float = 1.5) -> float:
    """Add small random displacement to simulate hand-drawn imprecision."""
    return x + RNG.uniform(-amount, amount)


def _draw_sketchy_line(
    draw: ImageDraw.ImageDraw,
    x0: float, y0: float, x1: float, y1: float,
    fill: tuple, width: int = 2, passes: int = 2,
) -> None:
    """Draw a line with slight waviness to look hand-drawn."""
    import math
    length = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    steps = max(4, int(length / 12))

    for p in range(passes):
        jit = 1.0 + p * 0.5
        points = []
        for i in range(steps + 1):
            t = i / steps
            px = x0 + (x1 - x0) * t
            py = y0 + (y1 - y0) * t
            if 0 < i < steps:
                px = _jitter(px, jit)
                py = _jitter(py, jit)
            points.append((px, py))
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=fill, width=width)


def _draw_sketchy_rect(
    draw: ImageDraw.ImageDraw,
    x0: float, y0: float, x1: float, y1: float,
    fill: tuple, width: int = 2,
) -> None:
    """Draw a rectangle with hand-drawn edges."""
    _draw_sketchy_line(draw, x0, y0, x1, y0, fill, width)  # top
    _draw_sketchy_line(draw, x1, y0, x1, y1, fill, width)  # right
    _draw_sketchy_line(draw, x1, y1, x0, y1, fill, width)  # bottom
    _draw_sketchy_line(draw, x0, y1, x0, y0, fill, width)  # left


def generate_popup_frame(
    out_path: Path,
    size: tuple = (400, 300),
    stroke_color: tuple = (60, 50, 35, 200),
    fill_color: tuple = (242, 232, 208, 240),
    shadow_color: tuple = (40, 30, 20, 60),
) -> None:
    """Generate a popup frame with sketchy borders and soft fill."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Soft shadow offset
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle([6, 6, w - 2, h - 2], radius=8, fill=shadow_color)
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    img = Image.alpha_composite(img, shadow)
    draw = ImageDraw.Draw(img)

    # Fill
    draw.rounded_rectangle([2, 2, w - 6, h - 6], radius=6, fill=fill_color)

    # Sketchy border (double pass for pencil look)
    margin = 4
    _draw_sketchy_rect(draw, margin, margin, w - margin - 4, h - margin - 4, stroke_color, width=2)
    # Second pass slightly offset for pencil doubling
    RNG.seed(99)
    _draw_sketchy_rect(draw, margin + 1, margin + 1, w - margin - 3, h - margin - 3,
                       (*stroke_color[:3], stroke_color[3] // 3), width=1)

    # Corner accents — small cross-hatch marks
    for cx, cy in [(margin + 8, margin + 8), (w - margin - 12, margin + 8),
                   (margin + 8, h - margin - 12), (w - margin - 12, h - margin - 12)]:
        for _ in range(3):
            angle_x = RNG.uniform(-6, 6)
            angle_y = RNG.uniform(-6, 6)
            draw.line(
                [(cx + angle_x, cy + angle_y), (cx - angle_x, cy - angle_y)],
                fill=(*stroke_color[:3], stroke_color[3] // 2), width=1,
            )

    img.save(out_path, "PNG")
    print(f"  -> {out_path.relative_to(REPO_ROOT)}")


def generate_toolbar_bg(
    out_path: Path,
    size: tuple = (800, 36),
    bg_color: tuple = (232, 222, 198, 200),
    line_color: tuple = (150, 130, 100, 80),
) -> None:
    """Generate a subtle toolbar background strip with pencil-line texture."""
    w, h = size
    img = Image.new("RGBA", (w, h), bg_color)
    draw = ImageDraw.Draw(img)

    # Faint horizontal pencil lines (notebook ruled-paper look)
    for y in [h // 3, 2 * h // 3]:
        _draw_sketchy_line(draw, 4, y, w - 4, y, line_color, width=1, passes=1)

    # Bottom border line
    _draw_sketchy_line(draw, 0, h - 2, w, h - 2, (*line_color[:3], line_color[3] + 40), width=1, passes=1)

    img.save(out_path, "PNG")
    print(f"  -> {out_path.relative_to(REPO_ROOT)}")


def generate_divider(
    out_path: Path,
    size: tuple = (600, 8),
    line_color: tuple = (120, 100, 70, 140),
) -> None:
    """Generate a horizontal divider with hand-drawn look."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    mid = h // 2
    _draw_sketchy_line(draw, 8, mid, w - 8, mid, line_color, width=1, passes=2)

    # Small decorative dash in center
    cx = w // 2
    draw.line([(cx - 6, mid - 2), (cx + 6, mid + 2)], fill=line_color, width=1)
    draw.line([(cx - 4, mid + 2), (cx + 4, mid - 2)], fill=line_color, width=1)

    img.save(out_path, "PNG")
    print(f"  -> {out_path.relative_to(REPO_ROOT)}")


def generate_corner_doodle(
    out_path: Path,
    size: tuple = (48, 48),
    stroke_color: tuple = (100, 80, 60, 120),
) -> None:
    """Generate a small corner flourish doodle."""
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Spiral-ish decorative swirl
    import math
    cx, cy = w * 0.3, h * 0.3
    points = []
    for i in range(40):
        t = i / 40
        r = 4 + t * 14
        angle = t * 4 * math.pi
        px = cx + r * math.cos(angle) + RNG.uniform(-0.5, 0.5)
        py = cy + r * math.sin(angle) + RNG.uniform(-0.5, 0.5)
        points.append((px, py))
    for i in range(len(points) - 1):
        alpha = int(stroke_color[3] * (1 - i / len(points) * 0.5))
        draw.line([points[i], points[i + 1]], fill=(*stroke_color[:3], alpha), width=1)

    img.save(out_path, "PNG")
    print(f"  -> {out_path.relative_to(REPO_ROOT)}")


def main() -> None:
    print("Generating pencil-sketch UI assets...")

    # Light theme
    light_dir = UI_DIR / "default" / "misc"
    light_dir.mkdir(parents=True, exist_ok=True)

    RNG.seed(42)
    generate_popup_frame(
        light_dir / "sketch-popup-frame.png",
        size=(400, 300),
        stroke_color=(60, 50, 35, 200),
        fill_color=(242, 232, 208, 240),
        shadow_color=(40, 30, 20, 60),
    )
    RNG.seed(42)
    generate_toolbar_bg(
        light_dir / "sketch-toolbar-bg.png",
        size=(800, 36),
        bg_color=(232, 222, 198, 200),
        line_color=(150, 130, 100, 80),
    )
    RNG.seed(42)
    generate_divider(
        light_dir / "sketch-divider.png",
        size=(600, 8),
        line_color=(120, 100, 70, 140),
    )
    RNG.seed(42)
    generate_corner_doodle(
        light_dir / "sketch-corner.png",
        size=(48, 48),
        stroke_color=(100, 80, 60, 120),
    )

    # Dark theme
    dark_dir = UI_DIR / "dark" / "misc"
    dark_dir.mkdir(parents=True, exist_ok=True)

    RNG.seed(42)
    generate_popup_frame(
        dark_dir / "sketch-popup-frame.png",
        size=(400, 300),
        stroke_color=(140, 160, 190, 180),
        fill_color=(24, 30, 44, 235),
        shadow_color=(0, 0, 0, 80),
    )
    RNG.seed(42)
    generate_toolbar_bg(
        dark_dir / "sketch-toolbar-bg.png",
        size=(800, 36),
        bg_color=(28, 36, 52, 200),
        line_color=(60, 80, 110, 80),
    )
    RNG.seed(42)
    generate_divider(
        dark_dir / "sketch-divider.png",
        size=(600, 8),
        line_color=(80, 100, 140, 120),
    )
    RNG.seed(42)
    generate_corner_doodle(
        dark_dir / "sketch-corner.png",
        size=(48, 48),
        stroke_color=(90, 120, 160, 100),
    )

    print("\nDone! Generated sketch assets for both themes.")


if __name__ == "__main__":
    main()
