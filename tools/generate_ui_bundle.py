"""Generate a small UI bundle for the JoyCon helper app.

A UI bundle is a folder containing:
- theme.json
- background-left.svg
- background-right.svg
- background-both.svg
- background.svg (compat copy)
- layout.json
- icons.svg (optional)
- components.svg (optional)
- README.md

This script is intentionally dependency-free (stdlib only) so it can run anywhere.

Usage:
    python tools/generate_ui_bundle.py --out ./.ui-bundle
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_THEME = {
    "name": "sketchbook-ink",
    "version": 1,
    "colors": {
        "bg": "#f2e4c6",
        "panel": "#fff6e1",
        "panel2": "#f7ebd1",
        "text": "#1b1b1b",
        "muted": "#5b554a",
        "border": "#c6ad7d",
        "accent": "#2f4a9e",
        "accent2": "#2b6a4b",
        "danger": "#b42318",
        "warning": "#a16207",
    },
    "typography": {
        "font_family": "Segoe UI",
        "font_size": 10,
        "mono_family": "Consolas",
        "mono_size": 10,
    },
    "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16},
    "radii": {"sm": 6, "md": 10, "lg": 14},
}


DEFAULT_LAYOUT = {
    "window": {"width": 980, "height": 680},
    "regions": [
        {"id": "topbar", "type": "row", "items": ["port", "baud", "connect", "bt_status"]},
        {"id": "main", "type": "split", "left": "tabs", "right": "actions"},
        {"id": "log", "type": "panel", "title": "Device log / events"},
    ],
    "tabs": ["Profile", "Macros", "Stick", "Share", "Overlay", "Controller"],
}


BUNDLE_README = """# UI bundle

This folder is a generated UI bundle for the JoyCon Bridge helper app.

Files:

- theme.json: semantic tokens (colors/typography/spacing)
- background-left.svg: optional background artwork (Left state)
- background-right.svg: optional background artwork (Right state)
- background-both.svg: optional background artwork (Both state)
- background.svg: compatibility copy (currently the same as background-both.svg)
- layout.json: layout metadata for documentation / future UI refactors
- icons.svg: optional icon set
- components.svg: optional component sheet
- joycons.png: compatibility overlay artwork for older backgrounds/tools
- joycons-both.png: full-color overlay artwork for both connected
- joycons-left.png: left-connected overlay artwork with the right side greyed out
- joycons-right.png: right-connected overlay artwork with the left side greyed out
- joycons-none.png: fully-grey overlay artwork for no controllers connected

This bundle is *not automatically loaded* by the helper app.
"""


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rewrite_bundle_svg(svg_text: str) -> str:
    # Keep docs-friendly relative paths in repo sources, but ensure generated bundle
    # SVGs are self-contained within the output folder.
    return svg_text.replace("../../joycons.png", "joycons.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output folder for the bundle")
    ap.add_argument(
        "--background",
        default=None,
        help=(
            "Legacy: single background SVG to include for all states. "
            "If provided, it will be used as background-left/right/both, and also written as background.svg."
        ),
    )
    ap.add_argument(
        "--background-left",
        default="docs/ui/background-left.svg",
        help="Path to background-left.svg to include (default: docs/ui/background-left.svg)",
    )
    ap.add_argument(
        "--background-right",
        default="docs/ui/background-right.svg",
        help="Path to background-right.svg to include (default: docs/ui/background-right.svg)",
    )
    ap.add_argument(
        "--background-both",
        default="docs/ui/background-both.svg",
        help="Path to background-both.svg to include (default: docs/ui/background-both.svg)",
    )
    ap.add_argument(
        "--icons",
        default="docs/ui/assets/icons.svg",
        help="Path to icons.svg to include when present (default: docs/ui/assets/icons.svg)",
    )
    ap.add_argument(
        "--components",
        default="docs/ui/assets/components.svg",
        help="Path to components.svg to include when present (default: docs/ui/assets/components.svg)",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.background:
        bg_left_path = Path(args.background)
        bg_right_path = Path(args.background)
        bg_both_path = Path(args.background)
    else:
        bg_left_path = Path(args.background_left)
        bg_right_path = Path(args.background_right)
        bg_both_path = Path(args.background_both)

    missing = [p for p in (bg_left_path, bg_right_path, bg_both_path) if not p.exists()]
    if missing:
        legacy = Path("docs/ui/background.svg")
        if legacy.exists() and not args.background:
            bg_left_path = legacy
            bg_right_path = legacy
            bg_both_path = legacy
        else:
            raise SystemExit("background(s) not found: " + ", ".join(str(p) for p in missing))

    (out_dir / "theme.json").write_text(json.dumps(DEFAULT_THEME, indent=2), encoding="utf-8")
    (out_dir / "layout.json").write_text(json.dumps(DEFAULT_LAYOUT, indent=2), encoding="utf-8")
    (out_dir / "background-left.svg").write_text(_rewrite_bundle_svg(_read_text(bg_left_path)), encoding="utf-8")
    (out_dir / "background-right.svg").write_text(_rewrite_bundle_svg(_read_text(bg_right_path)), encoding="utf-8")
    (out_dir / "background-both.svg").write_text(_rewrite_bundle_svg(_read_text(bg_both_path)), encoding="utf-8")
    # Keep a compatibility copy for older docs/tools.
    (out_dir / "background.svg").write_text(_rewrite_bundle_svg(_read_text(bg_both_path)), encoding="utf-8")

    overlays = {
        "joycons.png": Path("joycons.png"),
        "joycons-both.png": Path("docs/ui/assets/joycons-both.png"),
        "joycons-left.png": Path("docs/ui/assets/joycons-left.png"),
        "joycons-right.png": Path("docs/ui/assets/joycons-right.png"),
        "joycons-none.png": Path("docs/ui/assets/joycons-none.png"),
    }
    for name, overlay_path in overlays.items():
        if overlay_path.exists():
            try:
                (out_dir / name).write_bytes(overlay_path.read_bytes())
            except Exception:
                pass

    icons_path = Path(args.icons)
    if icons_path.exists():
        (out_dir / "icons.svg").write_text(_read_text(icons_path), encoding="utf-8")

    components_path = Path(args.components)
    if components_path.exists():
        (out_dir / "components.svg").write_text(_read_text(components_path), encoding="utf-8")

    (out_dir / "README.md").write_text(BUNDLE_README, encoding="utf-8")

    print(f"Wrote UI bundle to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
