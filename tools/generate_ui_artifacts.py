"""Generate mandatory UI artifacts for this repo.

Goals:
- Keep three inspection copies of joycons.png available (Left/Right/Both).
    - Left/Right variants gray out the unused side for quick visual inspection.
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
JOYCONS_OUT_DIR = REPO_ROOT / "docs" / "ui" / "assets"
JOYCONS_COPIES = {
    "joycons-left.png": "Inspection copy (left) derived from joycons.png",
    "joycons-right.png": "Inspection copy (right) derived from joycons.png",
    "joycons-both.png": "Inspection copy (both) derived from joycons.png",
}

GENERATOR_SRC = Path(__file__).resolve()

UI_BUNDLE_DIR = REPO_ROOT / ".ui-bundle"
UI_BUNDLE_GENERATOR = REPO_ROOT / "tools" / "generate_ui_bundle.py"


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


def _render_joycons_variant(dst: Path, *, variant: str) -> bool:
    """Render joycons-left/right.png with the unused half greyed out.

    Requires Pillow; if it's missing, fail with a clear message.
    """

    if not _needs_update([JOYCONS_SRC, GENERATOR_SRC], dst):
        return False

    try:
        from PIL import Image, ImageEnhance, ImageOps  # type: ignore
    except Exception:
        print(
            "[ui-artifacts] Pillow is required to render joycons-left/right inspection PNGs.\n"
            "Install with: pip install Pillow",
            file=sys.stderr,
        )
        raise

    img = Image.open(JOYCONS_SRC).convert("RGBA")
    width, height = img.size
    mid = width // 2

    if variant == "left":
        gray_rect = (mid, 0, width, height)
    elif variant == "right":
        gray_rect = (0, 0, mid, height)
    else:
        raise ValueError(f"Unknown variant: {variant}")

    region = img.crop(gray_rect)
    region_gray = ImageOps.grayscale(region).convert("RGBA")
    region_dim = ImageEnhance.Brightness(region_gray).enhance(0.88)
    overlay = Image.new("RGBA", region_dim.size, (180, 180, 180, 140))
    region_out = Image.alpha_composite(region_dim, overlay)

    out = img.copy()
    out.paste(region_out, gray_rect)

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
    ]
    if all(p.exists() for p in expected):
        # Still ensure the overlay image is present when joycons.png exists.
        if JOYCONS_SRC.exists() and not (UI_BUNDLE_DIR / "joycons.png").exists():
            pass
        else:
            return False

    UI_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(UI_BUNDLE_GENERATOR), "--out", str(UI_BUNDLE_DIR)]
    subprocess.check_call(cmd, cwd=str(REPO_ROOT))
    return True


def main() -> int:
    changed: list[str] = []

    if not JOYCONS_SRC.exists():
        print(f"[ui-artifacts] joycons.png not found: {JOYCONS_SRC}")
    else:
        # Render the inspection copies.
        for name in JOYCONS_COPIES:
            dst = JOYCONS_OUT_DIR / name
            try:
                if name == "joycons-left.png":
                    did = _render_joycons_variant(dst, variant="left")
                elif name == "joycons-right.png":
                    did = _render_joycons_variant(dst, variant="right")
                else:
                    did = _copy_if_needed(JOYCONS_SRC, dst)
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

    if changed:
        print("[ui-artifacts] updated:")
        for p in changed:
            print(f"  - {p}")
    else:
        print("[ui-artifacts] up-to-date")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
