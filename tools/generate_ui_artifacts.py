"""Generate mandatory UI artifacts for this repo.

Goals:
- Keep the local .ui-bundle/ generated (ignored by git) so the helper app can
    load a consistent theme bundle during development.
- All device-on-background PNGs (joycons, m913, incedius, razer) are now
    pre-rendered committed images — the generator does NOT composite overlays
    onto backgrounds.
- Generate button overlays for all devices.

Usage:
        python tools/generate_ui_artifacts.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Directory layout ──
UI_DIR = REPO_ROOT / "docs" / "ui"

# ── Joycon source images (at repo root — used for button overlay rendering) ──
JOYCONS_SRC = REPO_ROOT / "joycons.png"
JOYCONS_GREY_SRC = REPO_ROOT / "joycons-grey.png"
JOYCONS_DARK_SRC = REPO_ROOT / "joycons-dark.png"
JOYCONS_DARK_GREY_SRC = REPO_ROOT / "joycons-dark-grey.png"

GENERATOR_SRC = Path(__file__).resolve()

# ── Background images (committed truth — not regenerated) ──
BG_LIGHT = UI_DIR / "default" / "backgrounds" / "background.png"
BG_DARK = UI_DIR / "dark" / "backgrounds" / "background-dark.png"

UI_BUNDLE_DIR = REPO_ROOT / ".ui-bundle"
UI_BUNDLE_GENERATOR = REPO_ROOT / "tools" / "generate_ui_bundle.py"
BUTTON_OVERLAY_GENERATOR = REPO_ROOT / "tools" / "generate_button_overlays.py"
UI_BUNDLE_INPUTS = [
    UI_BUNDLE_GENERATOR,
    JOYCONS_SRC,
    JOYCONS_GREY_SRC,
    JOYCONS_DARK_SRC,
    JOYCONS_DARK_GREY_SRC,
    BG_LIGHT,
    BG_DARK,
    # Committed device backgrounds (not regenerated).
    UI_DIR / "default" / "backgrounds" / "joycons_both.png",
    UI_DIR / "default" / "backgrounds" / "joycons_left.png",
    UI_DIR / "default" / "backgrounds" / "joycons_right.png",
    UI_DIR / "default" / "backgrounds" / "joycons_none.png",
    UI_DIR / "dark" / "backgrounds" / "joycons_both.png",
    UI_DIR / "dark" / "backgrounds" / "joycons_left.png",
    UI_DIR / "dark" / "backgrounds" / "joycons_right.png",
    UI_DIR / "dark" / "backgrounds" / "joycons_none.png",
    UI_DIR / "default" / "backgrounds" / "m913_connected.png",
    UI_DIR / "default" / "backgrounds" / "m913_none.png",
    UI_DIR / "dark" / "backgrounds" / "m913_connected.png",
    UI_DIR / "dark" / "backgrounds" / "m913_none.png",
    UI_DIR / "default" / "backgrounds" / "incedius_connected.png",
    UI_DIR / "default" / "backgrounds" / "incedius_none.png",
    UI_DIR / "dark" / "backgrounds" / "incedius_connected.png",
    UI_DIR / "dark" / "backgrounds" / "incedius_none.png",
    UI_DIR / "default" / "backgrounds" / "razer_connected.png",
    UI_DIR / "default" / "backgrounds" / "razer_none.png",
    UI_DIR / "dark" / "backgrounds" / "razer_connected.png",
    UI_DIR / "dark" / "backgrounds" / "razer_none.png",
    UI_DIR / "default" / "backgrounds" / "blueprint-texture.png",
    UI_DIR / "dark" / "backgrounds" / "blueprint-texture.png",
    UI_DIR / "misc" / "pinouts.png",
    UI_DIR / "default" / "misc" / "keyboard.png",
    UI_DIR / "dark" / "misc" / "keyboard-dark.png",
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


def _run_ui_bundle_generator() -> bool:
    if not UI_BUNDLE_GENERATOR.exists():
        return False

    # Heuristic: regenerate if missing expected files.
    expected = [
        UI_BUNDLE_DIR / "theme.json",
        UI_BUNDLE_DIR / "layout.json",
        UI_BUNDLE_DIR / "backgrounds" / "joycons_none.png",
        UI_BUNDLE_DIR / "backgrounds" / "joycons_both.png",
        UI_BUNDLE_DIR / "backgrounds" / "m913_connected.png",
        UI_BUNDLE_DIR / "backgrounds" / "m913_none.png",
        UI_BUNDLE_DIR / "backgrounds" / "razer_none.png",
        UI_BUNDLE_DIR / "keyboard.png",
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

    try:
        if _run_ui_bundle_generator():
            changed.append(str(UI_BUNDLE_DIR.relative_to(REPO_ROOT)))
    except Exception as e:
        print(f"[ui-artifacts] bundle generation failed: {e}")
        return 2

    # ── Generate button overlays (all devices) ──
    if BUTTON_OVERLAY_GENERATOR.exists():
        try:
            subprocess.check_call(
                [sys.executable, str(BUTTON_OVERLAY_GENERATOR)],
                cwd=str(REPO_ROOT),
            )
            changed.append("docs/ui/button_overlays/ (all devices)")
        except Exception as e:
            print(f"[ui-artifacts] button overlay generation failed: {e}", file=sys.stderr)
            return 5

    # Copy background PNGs into the bundle so the helper app can find them.
    BG_PNGS = {
        "background.png": BG_LIGHT,
        "background-dark.png": BG_DARK,
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
