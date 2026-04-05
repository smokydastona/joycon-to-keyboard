"""Generate a small UI bundle for the JoyCon helper app.

A UI bundle is a folder containing:
- theme.json
- background.svg
- layout.json
- README.md

This script is intentionally dependency-free (stdlib only) so it can run anywhere.

Usage:
  python tools/generate_ui_bundle.py --out docs/ui/bundle-example
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_THEME = {
    "name": "midnight-grid",
    "version": 1,
    "colors": {
        "bg": "#0b1220",
        "panel": "#0f1a2e",
        "panel2": "#111f37",
        "text": "#e5e7eb",
        "muted": "#94a3b8",
        "border": "#22314f",
        "accent": "#2b63ff",
        "accent2": "#22c55e",
        "danger": "#ef4444",
        "warning": "#f59e0b",
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
- background.svg: optional background artwork (no trademarks/logos)
- layout.json: layout metadata for documentation / future UI refactors

This bundle is *not automatically loaded* by the helper app.
"""


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output folder for the bundle")
    ap.add_argument(
        "--background",
        default="docs/ui/background.svg",
        help="Path to background.svg to include (default: docs/ui/background.svg)",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    bg_path = Path(args.background)
    if not bg_path.exists():
        raise SystemExit(f"background not found: {bg_path}")

    (out_dir / "theme.json").write_text(json.dumps(DEFAULT_THEME, indent=2), encoding="utf-8")
    (out_dir / "layout.json").write_text(json.dumps(DEFAULT_LAYOUT, indent=2), encoding="utf-8")
    (out_dir / "background.svg").write_text(_read_text(bg_path), encoding="utf-8")
    (out_dir / "README.md").write_text(BUNDLE_README, encoding="utf-8")

    print(f"Wrote UI bundle to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
