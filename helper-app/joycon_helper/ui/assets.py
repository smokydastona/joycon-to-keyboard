"""Asset loading and image cache for the PyQt6 UI.

Locates device images, backgrounds, overlays, and icons using the same
search-path logic as the original Tkinter app, then caches them as QPixmaps.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap

log = logging.getLogger("joycon_helper.ui.assets")


# ---------------------------------------------------------------------------
# Search path construction (mirrors app.py logic)
# ---------------------------------------------------------------------------

def _frozen_bundle_root() -> Optional[Path]:
    base = getattr(sys, "_MEIPASS", None)
    if not isinstance(base, str) or not base:
        return None
    try:
        return Path(base).resolve()
    except Exception:
        return None


def _executable_dir() -> Optional[Path]:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except Exception:
        return None


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: set[str] = set()
    unique: List[Path] = []
    for p in paths:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def ui_bundle_search_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        roots.append(Path.cwd() / ".ui-bundle")
    except Exception:
        pass
    exe_dir = _executable_dir()
    if exe_dir is not None:
        roots.append(exe_dir / ".ui-bundle")
    bundle_root = _frozen_bundle_root()
    if bundle_root is not None:
        roots.append(bundle_root / ".ui-bundle")
    here = Path(__file__).resolve()
    roots.extend([
        here.parents[1] / ".ui-bundle",      # helper-app/.ui-bundle
        here.parents[3] / ".ui-bundle",       # repo root/.ui-bundle
    ])
    return _dedupe_paths(roots)


def device_image_search_roots(theme: str = "default") -> List[Path]:
    bundle_name = ".ui-bundle-dark" if theme == "dark" else ".ui-bundle"
    roots: List[Path] = []
    try:
        cwd = Path.cwd()
        roots.append(cwd / "docs" / "ui" / theme / "backgrounds")
        roots.extend([
            cwd,
            cwd / bundle_name / "backgrounds",
            cwd / bundle_name,
            cwd / ".ui-bundle" / "backgrounds",
            cwd / ".ui-bundle",
        ])
    except Exception:
        pass
    exe_dir = _executable_dir()
    if exe_dir is not None:
        roots.extend([
            exe_dir, exe_dir / bundle_name / "backgrounds", exe_dir / bundle_name,
            exe_dir / ".ui-bundle" / "backgrounds", exe_dir / ".ui-bundle",
        ])
    bundle_root = _frozen_bundle_root()
    if bundle_root is not None:
        roots.extend([
            bundle_root, bundle_root / bundle_name / "backgrounds", bundle_root / bundle_name,
            bundle_root / ".ui-bundle" / "backgrounds", bundle_root / ".ui-bundle",
        ])
    here = Path(__file__).resolve()
    repo = here.parents[3]
    roots.extend([
        repo / "docs" / "ui" / theme / "backgrounds",
        here.parents[1],
        here.parents[1] / bundle_name / "backgrounds",
        here.parents[1] / bundle_name,
        here.parents[1] / ".ui-bundle" / "backgrounds",
        here.parents[1] / ".ui-bundle",
        repo,
        repo / bundle_name / "backgrounds",
        repo / bundle_name,
        repo / ".ui-bundle" / "backgrounds",
        repo / ".ui-bundle",
    ])
    return _dedupe_paths(roots)


# ---------------------------------------------------------------------------
# AssetManager
# ---------------------------------------------------------------------------

class AssetManager:
    """Loads and caches image assets as QPixmaps."""

    def __init__(self, theme_name: str = "default") -> None:
        self._theme = theme_name
        self._cache: Dict[str, QPixmap] = {}
        self._search_roots = device_image_search_roots(theme_name)
        self._bundle_roots = ui_bundle_search_roots()

    def set_theme(self, theme_name: str) -> None:
        self._theme = theme_name
        self._search_roots = device_image_search_roots(theme_name)
        self._cache.clear()

    def find_file(self, filename: str, extra_roots: Optional[List[Path]] = None) -> Optional[Path]:
        roots = list(extra_roots or []) + self._search_roots + self._bundle_roots
        for root in roots:
            candidate = root / filename
            if candidate.is_file():
                return candidate
        return None

    def load_pixmap(self, filename: str, size: Optional[QSize] = None,
                    extra_roots: Optional[List[Path]] = None) -> Optional[QPixmap]:
        cache_key = f"{filename}|{size.width() if size else 0}x{size.height() if size else 0}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        path = self.find_file(filename, extra_roots)
        if path is None:
            log.debug("Asset not found: %s", filename)
            return None

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            log.warning("Failed to load pixmap: %s", path)
            return None

        if size is not None and not size.isEmpty():
            pixmap = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)

        self._cache[cache_key] = pixmap
        return pixmap

    def load_image(self, filename: str, extra_roots: Optional[List[Path]] = None) -> Optional[QImage]:
        path = self.find_file(filename, extra_roots)
        if path is None:
            return None
        img = QImage(str(path))
        return img if not img.isNull() else None

    def composite(self, base: QPixmap, overlay: QPixmap,
                  x: int = 0, y: int = 0) -> QPixmap:
        result = base.copy()
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(x, y, overlay)
        painter.end()
        return result

    def tinted_pixmap(self, pixmap: QPixmap, color: str, opacity: float = 0.5) -> QPixmap:
        result = pixmap.copy()
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        c = QColor(color)
        c.setAlphaF(opacity)
        painter.fillRect(result.rect(), c)
        painter.end()
        return result

    # ----- Device image variants -----

    def find_joycons_variants(self) -> Dict[str, Optional[Path]]:
        variants: Dict[str, Optional[Path]] = {}
        for state in ("none", "left", "right", "both"):
            variants[state] = self.find_file(f"joycons_{state}.png")
        return variants

    def find_m913_variants(self, layout: str = "stock") -> Dict[str, Optional[Path]]:
        prefix = "incedius" if layout == "incedius" else "m913"
        variants: Dict[str, Optional[Path]] = {}
        for state in ("none", "connected"):
            variants[state] = self.find_file(f"{prefix}_{state}.png")
        return variants

    def find_razer_variants(self) -> Dict[str, Optional[Path]]:
        variants: Dict[str, Optional[Path]] = {}
        for state in ("none", "connected"):
            variants[state] = self.find_file(f"razer_{state}.png")
        return variants

    def load_icon(self) -> Optional[QPixmap]:
        here = Path(__file__).resolve()
        repo = here.parents[3]
        icon_roots = [
            repo / "docs" / "ui" / "misc",
            here.parents[2],              # helper-app/
            repo,
        ]
        path = self.find_file("icon.ico", extra_roots=icon_roots)
        if path is None:
            path = self.find_file("icon.png", extra_roots=icon_roots)
        if path is None:
            return None
        return QPixmap(str(path))

    def find_background(self) -> Optional[Path]:
        names = ["background.png", "bg.png"]
        for name in names:
            p = self.find_file(name)
            if p is not None:
                return p
        return None

    def find_keyboard_image(self) -> Optional[Path]:
        for name in ("keyboard.png", "keyboard_preview.png"):
            p = self.find_file(name)
            if p is not None:
                return p
        return None

    def find_overlay_image(self, device: str, button: str, color: str) -> Optional[Path]:
        filename = f"{button}.png"
        extra_roots: List[Path] = []
        try:
            cwd = Path.cwd()
            extra_roots.append(cwd / "docs" / "ui" / "button_overlays" / color / device)
        except Exception:
            pass
        here = Path(__file__).resolve()
        repo = here.parents[3]
        extra_roots.append(repo / "docs" / "ui" / "button_overlays" / color / device)
        return self.find_file(filename, extra_roots)

    def find_pale_overlay(self, device: str, color: str) -> Optional[Path]:
        """Return path to the pale composite PNG for *device* and *color*."""
        filename = f"pale_{device}.png"
        extra_roots: List[Path] = []
        try:
            cwd = Path.cwd()
            extra_roots.append(cwd / "docs" / "ui" / "button_overlays" / color / device)
        except Exception:
            pass
        here = Path(__file__).resolve()
        repo = here.parents[3]
        extra_roots.append(repo / "docs" / "ui" / "button_overlays" / color / device)
        return self.find_file(filename, extra_roots)

    def clear_cache(self) -> None:
        self._cache.clear()
