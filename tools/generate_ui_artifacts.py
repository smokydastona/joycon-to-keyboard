"""Generate mandatory UI artifacts for this repo.

Goals:
- Keep four inspection copies of joycons.png available (None/Left/Right/Both).
    - Left/Right variants use joycons-grey.png on the unused side.
    - None is a fully-grey disconnected view used by the helper app when no controllers are connected.
- Keep the local .ui-bundle/ generated (ignored by git) so the helper app can
    load a consistent theme bundle during development.

Usage:
        python tools/generate_ui_artifacts.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

JOYCONS_SRC = REPO_ROOT / "joycons.png"
JOYCONS_GREY_SRC = REPO_ROOT / "joycons-grey.png"
JOYCONS_DARK_SRC = REPO_ROOT / "joycons-dark.png"
JOYCONS_DARK_GREY_SRC = REPO_ROOT / "joycons-dark-grey.png"
JOYCONS_OUT_DIR = REPO_ROOT / "docs" / "ui" / "assets"
JOYCONS_COPIES = {
    "joycons-none.png": "Inspection copy (none disconnected) derived from joycons-grey.png",
    "joycons-left.png": "Inspection copy (left connected) composited from joycons.png + joycons-grey.png",
    "joycons-right.png": "Inspection copy (right connected) composited from joycons.png + joycons-grey.png",
    "joycons-both.png": "Inspection copy (both connected) derived from joycons.png",
}
JOYCONS_DARK_COPIES = {
    "joycons-dark-none.png": "Dark inspection copy (none) derived from joycons-dark-grey.png",
    "joycons-dark-left.png": "Dark inspection copy (left connected) composited from joycons-dark.png + joycons-dark-grey.png",
    "joycons-dark-right.png": "Dark inspection copy (right connected) composited from joycons-dark.png + joycons-dark-grey.png",
    "joycons-dark-both.png": "Dark inspection copy (both connected) derived from joycons-dark.png",
}

# M913 mouse overlays — pre-rendered, no compositing needed.  Just copy.
M913_SRC_DIR = REPO_ROOT / "docs" / "ui" / "assets"
M913_LIGHT_COPIES = {
    "m913.png": "M913 mouse overlay (light theme, connected)",
    "m913-none.png": "M913 mouse overlay (light theme, disconnected)",
}
M913_DARK_COPIES = {
    "m913-dark.png": "M913 mouse overlay (dark theme, connected)",
    "m913-dark-none.png": "M913 mouse overlay (dark theme, disconnected)",
}

# Misc static assets — just copy.
MISC_COPIES = {
    "pinouts.png": "ESP32 / ESP32-S3 board pinout reference diagram",
}

GENERATOR_SRC = Path(__file__).resolve()

UI_BUNDLE_DIR = REPO_ROOT / ".ui-bundle"
UI_BUNDLE_GENERATOR = REPO_ROOT / "tools" / "generate_ui_bundle.py"
UI_BUNDLE_INPUTS = [
    UI_BUNDLE_GENERATOR,
    JOYCONS_SRC,
    JOYCONS_GREY_SRC,
    JOYCONS_DARK_SRC,
    JOYCONS_DARK_GREY_SRC,
    REPO_ROOT / "docs" / "ui" / "background.svg",
    REPO_ROOT / "docs" / "ui" / "background-left.svg",
    REPO_ROOT / "docs" / "ui" / "background-right.svg",
    REPO_ROOT / "docs" / "ui" / "background-both.svg",
    REPO_ROOT / "docs" / "ui" / "background-dark.svg",
    REPO_ROOT / "docs" / "ui" / "background.png",
    REPO_ROOT / "docs" / "ui" / "background-dark.png",
    REPO_ROOT / "docs" / "ui" / "assets" / "components.svg",
    REPO_ROOT / "docs" / "ui" / "assets" / "icons.svg",
    REPO_ROOT / "docs" / "ui" / "assets" / "components-dark.svg",
    REPO_ROOT / "docs" / "ui" / "assets" / "icons-dark.svg",
    REPO_ROOT / "docs" / "ui" / "assets" / "m913.png",
    REPO_ROOT / "docs" / "ui" / "assets" / "m913-none.png",
    REPO_ROOT / "docs" / "ui" / "assets" / "m913-dark.png",
    REPO_ROOT / "docs" / "ui" / "assets" / "m913-dark-none.png",
    REPO_ROOT / "docs" / "ui" / "assets" / "pinouts.png",
]


def _needs_update(inputs: list[Path], dst: Path) -> bool:
    if not dst.exists():
        return True
    try:
        newest = max(p.stat().st_mtime for p in inputs if p.exists())
        return newest > dst.stat().st_mtime
    except Exception:
        return True


def _copy_if_needed(src: Path, dst: Path) -> bool:
    if not _needs_update([src, GENERATOR_SRC], dst):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def _render_joycons_variant(
    dst: Path,
    *,
    variant: str,
    color_src: Path | None = None,
    grey_src: Path | None = None,
) -> bool:
    """Render joycons-none/left/right/both from a color + grey source pair."""
    color_src = color_src or JOYCONS_SRC
    grey_src = grey_src or JOYCONS_GREY_SRC

    if not _needs_update([color_src, grey_src, GENERATOR_SRC], dst):
        return False

    try:
        from PIL import Image  # type: ignore
    except Exception:
        print(
            "[ui-artifacts] Pillow is required to render joycons inspection PNGs.\n"
            "Install with: pip install Pillow",
            file=sys.stderr,
        )
        raise

    img = Image.open(color_src).convert("RGBA")
    grey = Image.open(grey_src).convert("RGBA")
    if img.size != grey.size:
        raise ValueError(
            f"{color_src.name} and {grey_src.name} must have the same size, got {img.size} vs {grey.size}"
        )

    width, height = img.size
    mid = width // 2
    out = img.copy()

    if variant == "none":
        out = grey
    elif variant == "left":
        out.paste(grey.crop((mid, 0, width, height)), (mid, 0))
    elif variant == "right":
        out.paste(grey.crop((0, 0, mid, height)), (0, 0))
    elif variant == "both":
        out = img
    else:
        raise ValueError(f"Unknown variant: {variant}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, format="PNG", optimize=True)
    return True


def _run_ui_bundle_generator() -> bool:
    if not UI_BUNDLE_GENERATOR.exists():
        return False

    # Heuristic: regenerate if missing expected files.
    expected = [
        UI_BUNDLE_DIR / "theme.json",
        UI_BUNDLE_DIR / "layout.json",
        UI_BUNDLE_DIR / "background.svg",
        UI_BUNDLE_DIR / "joycons-none.png",
        UI_BUNDLE_DIR / "joycons-left.png",
        UI_BUNDLE_DIR / "joycons-right.png",
        UI_BUNDLE_DIR / "joycons-both.png",
        UI_BUNDLE_DIR / "m913.png",
        UI_BUNDLE_DIR / "m913-none.png",
        UI_BUNDLE_DIR / "background.png",
    ]
    if all(p.exists() for p in expected) and not any(_needs_update(UI_BUNDLE_INPUTS, p) for p in expected):
        return False

    UI_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(UI_BUNDLE_GENERATOR), "--out", str(UI_BUNDLE_DIR)]
    subprocess.check_call(cmd, cwd=str(REPO_ROOT))
    return True


def main() -> int:
    changed: list[str] = []

    if not JOYCONS_SRC.exists():
        print(f"[ui-artifacts] joycons.png not found: {JOYCONS_SRC}")
    elif not JOYCONS_GREY_SRC.exists():
        print(f"[ui-artifacts] joycons-grey.png not found: {JOYCONS_GREY_SRC}")
    else:
        # Render the light inspection copies.
        for name in JOYCONS_COPIES:
            dst = JOYCONS_OUT_DIR / name
            try:
                did = _render_joycons_variant(dst, variant=name.removeprefix("joycons-").removesuffix(".png"))
            except Exception:
                return 3

            if did:
                changed.append(str(dst.relative_to(REPO_ROOT)))

    # Render dark inspection copies.
    if not JOYCONS_DARK_SRC.exists():
        print(f"[ui-artifacts] joycons-dark.png not found: {JOYCONS_DARK_SRC}")
    elif not JOYCONS_DARK_GREY_SRC.exists():
        print(f"[ui-artifacts] joycons-dark-grey.png not found: {JOYCONS_DARK_GREY_SRC}")
    else:
        for name in JOYCONS_DARK_COPIES:
            dst = JOYCONS_OUT_DIR / name
            try:
                did = _render_joycons_variant(
                    dst,
                    variant=name.removeprefix("joycons-dark-").removesuffix(".png"),
                    color_src=JOYCONS_DARK_SRC,
                    grey_src=JOYCONS_DARK_GREY_SRC,
                )
            except Exception:
                return 3

            if did:
                changed.append(str(dst.relative_to(REPO_ROOT)))

    try:
        if _run_ui_bundle_generator():
            changed.append(str(UI_BUNDLE_DIR.relative_to(REPO_ROOT)))
    except Exception as e:
        print(f"[ui-artifacts] bundle generation failed: {e}")
        return 2

    # Copy background PNGs into the bundle so the helper app can find them.
    BG_PNGS = {
        "background.png": REPO_ROOT / "docs" / "ui" / "background.png",
        "background-dark.png": REPO_ROOT / "docs" / "ui" / "background-dark.png",
    }
    for dst_name, src in BG_PNGS.items():
        if src.exists():
            dst = UI_BUNDLE_DIR / dst_name
            if _copy_if_needed(src, dst):
                changed.append(str(dst.relative_to(REPO_ROOT)))

    if changed:
        print("[ui-artifacts] updated:")
        for p in changed:
            print(f"  - {p}")
    else:
        print("[ui-artifacts] up-to-date")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
