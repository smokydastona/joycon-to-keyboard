"""Generate mandatory UI artifacts for this repo.

Goals:
- Keep four inspection copies of joycons.png available (None/Left/Right/Both).
    - Left/Right variants use joycons-grey.png on the unused side.
    - None is a fully-grey disconnected view used by the helper app when no controllers are connected.
- Pre-bake composited backgrounds: each device overlay is fused onto the app
    background image so every tab shows a seamless background with the device
    baked in.
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

# ── Directory layout ──
UI_DIR = REPO_ROOT / "docs" / "ui"

# Intermediate overlays go to a gitignored build dir (not committed).
BUILD_DIR = REPO_ROOT / ".ui-build" / "overlays"

# ── Joycon source images (at repo root — used for overlay rendering) ──
JOYCONS_SRC = REPO_ROOT / "joycons.png"
JOYCONS_GREY_SRC = REPO_ROOT / "joycons-grey.png"
JOYCONS_DARK_SRC = REPO_ROOT / "joycons-dark.png"
JOYCONS_DARK_GREY_SRC = REPO_ROOT / "joycons-dark-grey.png"
JOYCONS_OUT_DIR = BUILD_DIR
JOYCONS_COPIES = {
    "joycons-none.png": "Overlay variant (none) derived from joycons-grey.png",
    "joycons-left.png": "Overlay variant (left connected) composited from joycons.png + joycons-grey.png",
    "joycons-right.png": "Overlay variant (right connected) composited from joycons.png + joycons-grey.png",
    "joycons-both.png": "Overlay variant (both connected) derived from joycons.png",
}
JOYCONS_DARK_COPIES = {
    "joycons-dark-none.png": "Dark overlay variant (none) derived from joycons-dark-grey.png",
    "joycons-dark-left.png": "Dark overlay variant (left connected) composited from joycons-dark.png + joycons-dark-grey.png",
    "joycons-dark-right.png": "Dark overlay variant (right connected) composited from joycons-dark.png + joycons-dark-grey.png",
    "joycons-dark-both.png": "Dark overlay variant (both connected) derived from joycons-dark.png",
}

GENERATOR_SRC = Path(__file__).resolve()

# ── Background + overlay compositing ──
# Backgrounds now live inside theme folders (the composited PNGs are THE truth).
BG_LIGHT = UI_DIR / "default" / "backgrounds" / "background.png"
BG_DARK = UI_DIR / "dark" / "backgrounds" / "background-dark.png"

# Map: output path (relative to UI_DIR) → (background path, overlay path)
# Only Joy-Con composites are regenerated (overlays built from source art).
# M913 stock + Incedius composites are committed truth and NOT regenerated.
COMPOSITES: dict[str, tuple[Path, Path]] = {
    # default (light) — Joy-Con
    "default/backgrounds/joycons-none.png":  (BG_LIGHT, BUILD_DIR / "joycons-none.png"),
    "default/backgrounds/joycons-left.png":  (BG_LIGHT, BUILD_DIR / "joycons-left.png"),
    "default/backgrounds/joycons-right.png": (BG_LIGHT, BUILD_DIR / "joycons-right.png"),
    "default/backgrounds/joycons-both.png":  (BG_LIGHT, BUILD_DIR / "joycons-both.png"),
    # dark — Joy-Con
    "dark/backgrounds/joycons-none.png":  (BG_DARK, BUILD_DIR / "joycons-dark-none.png"),
    "dark/backgrounds/joycons-left.png":  (BG_DARK, BUILD_DIR / "joycons-dark-left.png"),
    "dark/backgrounds/joycons-right.png": (BG_DARK, BUILD_DIR / "joycons-dark-right.png"),
    "dark/backgrounds/joycons-both.png":  (BG_DARK, BUILD_DIR / "joycons-dark-both.png"),
}

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
    # Composited backgrounds are the truth — they are bundle inputs.
    UI_DIR / "default" / "backgrounds" / "m913.png",
    UI_DIR / "default" / "backgrounds" / "m913-none.png",
    UI_DIR / "dark" / "backgrounds" / "m913.png",
    UI_DIR / "dark" / "backgrounds" / "m913-none.png",
    UI_DIR / "default" / "backgrounds" / "m913-incedius.png",
    UI_DIR / "default" / "backgrounds" / "m913-incedius-none.png",
    UI_DIR / "dark" / "backgrounds" / "m913-incedius.png",
    UI_DIR / "dark" / "backgrounds" / "m913-incedius-none.png",
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


def _composite_overlay_on_bg(
    dst: Path,
    bg_path: Path,
    overlay_path: Path,
) -> bool:
    """Fuse *overlay_path* centred onto *bg_path* and write to *dst*.

    The background is scaled to cover the overlay's dimensions (so the
    composite is the same size as the overlay — it IS the tab background).
    """
    if not bg_path.exists() or not overlay_path.exists():
        return False

    if not _needs_update([bg_path, overlay_path, GENERATOR_SRC], dst):
        return False

    try:
        from PIL import Image  # type: ignore
    except Exception:
        print(
            "[ui-artifacts] Pillow is required to render composited backgrounds.\n"
            "Install with: pip install Pillow",
            file=sys.stderr,
        )
        raise

    overlay = Image.open(overlay_path).convert("RGBA")
    bg = Image.open(bg_path).convert("RGBA")

    ov_w, ov_h = overlay.size

    # Scale the background to cover the overlay dimensions.
    bg_w, bg_h = bg.size
    scale = max(ov_w / bg_w, ov_h / bg_h)
    new_bg_w = int(bg_w * scale)
    new_bg_h = int(bg_h * scale)
    bg_resized = bg.resize((new_bg_w, new_bg_h), Image.LANCZOS)

    # Centre-crop to overlay dimensions.
    left = (new_bg_w - ov_w) // 2
    top = (new_bg_h - ov_h) // 2
    composite = bg_resized.crop((left, top, left + ov_w, top + ov_h))

    # Alpha-composite the overlay onto the background.
    composite = Image.alpha_composite(composite.convert("RGBA"), overlay)

    dst.parent.mkdir(parents=True, exist_ok=True)
    composite.save(dst, format="PNG", optimize=True)
    return True


def _run_ui_bundle_generator() -> bool:
    if not UI_BUNDLE_GENERATOR.exists():
        return False

    # Heuristic: regenerate if missing expected files.
    expected = [
        UI_BUNDLE_DIR / "theme.json",
        UI_BUNDLE_DIR / "layout.json",
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

    # ── Pre-bake composited backgrounds (overlay fused onto background) ──
    for name, (bg, overlay) in COMPOSITES.items():
        dst = UI_DIR / name
        try:
            did = _composite_overlay_on_bg(dst, bg, overlay)
        except Exception as e:
            print(f"[ui-artifacts] composite failed for {name}: {e}", file=sys.stderr)
            return 4
        if did:
            changed.append(str(dst.relative_to(REPO_ROOT)))

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
