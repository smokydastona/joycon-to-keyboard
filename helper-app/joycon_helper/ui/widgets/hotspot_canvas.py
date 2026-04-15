"""QGraphicsView-based hotspot canvas for controller, keyboard, and mouse overlays.

Renders a device image with interactive hotspot dots representing buttons.
Supports click-to-select, hover tooltips, pulse animation, conflict
indicators, search highlighting, and overlay compositing.
"""
from __future__ import annotations

import logging
import math
import random
import zlib
from typing import Any

from PyQt6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QWidget,
)

from ..theme import ThemeEngine

log = logging.getLogger("joycon_helper.ui.widgets.hotspot_canvas")

# Size of hotspot dots at native image resolution
_DOT_RADIUS = 24
_TEXT_OFFSET_Y = -36
_HOVER_GROW = 8
_PULSE_RANGE = 4

# Thumbstick group patterns — hotspots whose names match the same prefix
# are always moved together during drag-edit.  The centre button may be
# named differently per device ("LStick" on Joy-Con, "LS" on Gamepad), so
# we normalise everything to two canonical groups.
_STICK_PREFIXES: dict[str, str] = {
    # Joy-Con naming
    "LStick": "L", "LSUp": "L", "LSDown": "L", "LSLeft": "L", "LSRight": "L",
    # Joy-Con right
    "RStick": "R", "RSUp": "R", "RSDown": "R", "RSLeft": "R", "RSRight": "R",
    # Gamepad naming (centre is "LS" / "RS")
    "LS": "L", "RS": "R",
}


class HotspotItem:
    """Holds QGraphicsItems for a single hotspot."""

    def __init__(self, name: str, norm_x: float, norm_y: float) -> None:
        self.name = name
        self.norm_x = norm_x
        self.norm_y = norm_y
        self.key_id: int | None = None
        self.mapped = False
        self.conflict = False
        self.search_match = False
        self.disabled = False
        self.locked = False
        self.dot: QGraphicsPathItem | None = None
        self.label: QGraphicsSimpleTextItem | None = None


class HotspotCanvas(QGraphicsView):
    """Interactive canvas for device-image + clickable hotspot dots."""

    hotspot_clicked = pyqtSignal(str)            # name
    hotspot_right_clicked = pyqtSignal(str, object)  # name, QPoint (screen pos)
    hotspot_hovered = pyqtSignal(str)            # name (empty string = no hover)

    def __init__(self, theme: ThemeEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        # Rendering
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("background: transparent;")

        # State
        self._bg_item: QGraphicsPixmapItem | None = None
        self._hotspots: list[HotspotItem] = []
        self._stick_groups: dict[str, list[HotspotItem]] = {}
        self._selected: str | None = None
        self._hovered: str | None = None
        self._overlay_color = "#a03cc8"  # violet default
        self._mapping_labels: dict[str, str] = {}
        self._shapes: dict[str, Any] = {}
        self._wide_set: set = set()

        # Pale composite (all buttons dimmed) and bright individual overlay
        self._pale_pixmap: QPixmap | None = None
        self._pale_item: QGraphicsPixmapItem | None = None
        self._bright_pixmap: QPixmap | None = None
        self._bright_item: QGraphicsPixmapItem | None = None

        # Per-button overlay textures (sketch-style brush fills)
        self._overlay_paths: dict[str, str] = {}
        self._overlay_full_pixmaps: dict[str, QPixmap] = {}
        self._overlay_brushes: dict[str, QBrush] = {}

        # Drag-edit mode (temporary position tweaking)
        self._edit_mode = False
        self._dragging: HotspotItem | None = None

        # Pulse animation
        self._pulse_phase = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(80)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_timer.start()

        self.setMinimumSize(200, 150)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def set_background(self, pixmap: QPixmap) -> None:
        # Null out refs before clear(); clear() deletes the C++ objects,
        # so any leftover hs.dot / hs.label would become dangling pointers.
        for hs in self._hotspots:
            hs.dot = None
            hs.label = None
        self._pale_item = None
        self._bright_item = None
        self._scene.clear()
        self._bg_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        # Re-add pale/bright overlay layers after clear
        if self._pale_pixmap and not self._pale_pixmap.isNull():
            self._pale_item = self._scene.addPixmap(self._pale_pixmap)
            self._pale_item.setZValue(5)
        if self._bright_pixmap and not self._bright_pixmap.isNull():
            self._bright_item = self._scene.addPixmap(self._bright_pixmap)
            self._bright_item.setZValue(8)
        self._rebuild_hotspot_items()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_hotspots(self, hotspots: list[tuple[str, float, float]]) -> None:
        self._hotspots = [HotspotItem(name, nx, ny) for name, nx, ny in hotspots]
        self._rebuild_stick_groups()
        self._rebuild_hotspot_items()

    def set_hotspot_shapes(self, shapes: dict[str, Any]) -> None:
        """Set per-button shape specs (only affects Joy-Con canvas)."""
        self._shapes = shapes
        self._rebuild_hotspot_items()

    def set_wide_set(self, wide: set) -> None:
        """Set the names of buttons that should use a larger hit area."""
        self._wide_set = wide
        self._rebuild_hotspot_items()

    def set_overlay_paths(self, paths: dict[str, str]) -> None:
        """Set file paths for per-button overlay PNGs used as texture fills."""
        self._overlay_paths = paths
        self._overlay_full_pixmaps.clear()
        for name, path in paths.items():
            pm = QPixmap(path)
            if not pm.isNull():
                self._overlay_full_pixmaps[name] = pm
        self._build_overlay_brushes()
        self._update_hotspot_visuals()

    def set_selected(self, name: str | None) -> None:
        self._selected = name
        self._update_hotspot_visuals()

    def set_overlay_color(self, hex_color: str) -> None:
        self._overlay_color = hex_color
        self._build_overlay_brushes()
        self._update_hotspot_visuals()

    def set_pale_overlay(self, pixmap: QPixmap | None) -> None:
        """Set (or clear) the pale composite overlay showing all buttons dimmed."""
        self._pale_pixmap = pixmap
        if self._pale_item and self._pale_item.scene():
            self._scene.removeItem(self._pale_item)
            self._pale_item = None
        if pixmap and not pixmap.isNull():
            self._pale_item = self._scene.addPixmap(pixmap)
            self._pale_item.setZValue(5)

    def set_bright_overlay(self, pixmap: QPixmap | None) -> None:
        """Set (or clear) the bright overlay for the currently selected button."""
        self._bright_pixmap = pixmap
        if self._bright_item and self._bright_item.scene():
            self._scene.removeItem(self._bright_item)
            self._bright_item = None
        if pixmap and not pixmap.isNull():
            self._bright_item = self._scene.addPixmap(pixmap)
            self._bright_item.setZValue(8)

    def update_hotspot_state(self, name: str, *,
                             key_id: int | None = None,
                             mapped: bool | None = None,
                             conflict: bool | None = None,
                             search_match: bool | None = None,
                             disabled: bool | None = None,
                             locked: bool | None = None) -> None:
        for hs in self._hotspots:
            if hs.name == name:
                if key_id is not None:
                    hs.key_id = key_id
                if mapped is not None:
                    hs.mapped = mapped
                if conflict is not None:
                    hs.conflict = conflict
                if search_match is not None:
                    hs.search_match = search_match
                if disabled is not None:
                    hs.disabled = disabled
                if locked is not None:
                    hs.locked = locked
                break
        self._update_hotspot_visuals()

    def set_mapping_labels(self, labels: dict[str, str]) -> None:
        self._mapping_labels = labels
        self._update_hotspot_visuals()

    def clear_search(self) -> None:
        for hs in self._hotspots:
            hs.search_match = False
        self._update_hotspot_visuals()

    def get_hotspot_names(self) -> list[str]:
        return [hs.name for hs in self._hotspots]

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self._dragging = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if enabled
            else Qt.CursorShape.ArrowCursor
        )

    def export_positions(self) -> list[tuple[str, float, float]]:
        return [(hs.name, round(hs.norm_x, 6), round(hs.norm_y, 6))
                for hs in self._hotspots]

    # -----------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if self._scene.sceneRect().width() > 0:
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event: Any) -> None:
        if self._edit_mode and event.button() == Qt.MouseButton.LeftButton:
            name = self._pick_hotspot(event.position())
            if name:
                for hs in self._hotspots:
                    if hs.name == name:
                        self._dragging = hs
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
                        break
            return
        if event.button() == Qt.MouseButton.LeftButton:
            name = self._pick_hotspot(event.position())
            if name:
                self.hotspot_clicked.emit(name)
        elif event.button() == Qt.MouseButton.RightButton:
            name = self._pick_hotspot(event.position())
            if name:
                self.hotspot_right_clicked.emit(name, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:
        if self._edit_mode and self._dragging:
            scene_pos = self.mapToScene(int(event.position().x()),
                                        int(event.position().y()))
            rect = self._scene.sceneRect()
            if rect.width() > 0 and rect.height() > 0:
                nx = max(0.0, min(1.0, scene_pos.x() / rect.width()))
                ny = max(0.0, min(1.0, scene_pos.y() / rect.height()))
                # Move entire stick group together
                siblings = self._stick_groups.get(self._dragging.name)
                targets = siblings if siblings else [self._dragging]
                for hs in targets:
                    hs.norm_x = nx
                    hs.norm_y = ny
                    cx = nx * rect.width()
                    cy = ny * rect.height()
                    if hs.dot:
                        hs.dot.setPath(
                            self._make_shape_path(cx, cy, hs.name)
                        )
                    if hs.label:
                        lw = hs.label.boundingRect().width()
                        spec = self._shapes.get(hs.name)
                        if spec and spec[0].startswith("arc_"):
                            d = spec[0][4:]
                            outer_r = spec[2]
                            if d == "top":
                                hs.label.setPos(cx - lw / 2, cy - outer_r - 20)
                            elif d == "bottom":
                                hs.label.setPos(cx - lw / 2, cy + outer_r + 4)
                            elif d == "left":
                                hs.label.setPos(cx - outer_r - lw - 4, cy - 8)
                            else:
                                hs.label.setPos(cx + outer_r + 4, cy - 8)
                        else:
                            hs.label.setPos(cx - lw / 2, cy + _TEXT_OFFSET_Y)
                self._build_overlay_brushes()
                self._update_hotspot_visuals()
            return
        name = self._pick_hotspot(event.position())
        if name != self._hovered:
            self._hovered = name
            self.hotspot_hovered.emit(name or "")
            self._update_hotspot_visuals()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if self._edit_mode and self._dragging:
            self._dragging = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        super().mouseReleaseEvent(event)

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _rebuild_stick_groups(self) -> None:
        """Build a map from hotspot name → list of co-located stick siblings."""
        groups: dict[str, list[HotspotItem]] = {}  # "L"/"R" → items
        for hs in self._hotspots:
            key = _STICK_PREFIXES.get(hs.name)
            if key:
                groups.setdefault(key, []).append(hs)
        # Flatten: every member maps to the full sibling list
        self._stick_groups: dict[str, list[HotspotItem]] = {}
        for members in groups.values():
            if len(members) > 1:
                for hs in members:
                    self._stick_groups[hs.name] = members

    def _pick_hotspot(self, view_pos: Any) -> str | None:
        scene_pos = self.mapToScene(int(view_pos.x()), int(view_pos.y()))
        rect = self._scene.sceneRect()
        if rect.width() <= 0:
            return None
        # Pass 1: exact shape containment
        best_name: str | None = None
        best_dist = float("inf")
        for hs in self._hotspots:
            hx = hs.norm_x * rect.width()
            hy = hs.norm_y * rect.height()
            if self._make_shape_path(hx, hy, hs.name).contains(scene_pos):
                dx = scene_pos.x() - hx
                dy = scene_pos.y() - hy
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < best_dist:
                    best_dist = dist
                    best_name = hs.name
        if best_name:
            return best_name
        # Pass 2: sloppy (grown) containment for near-miss clicks
        for hs in self._hotspots:
            hx = hs.norm_x * rect.width()
            hy = hs.norm_y * rect.height()
            if self._make_shape_path(hx, hy, hs.name, grow=12).contains(scene_pos):
                dx = scene_pos.x() - hx
                dy = scene_pos.y() - hy
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < best_dist:
                    best_dist = dist
                    best_name = hs.name
        return best_name

    def _make_shape_path(self, cx: float, cy: float, name: str,
                         grow: float = 0.0) -> QPainterPath:
        """Build a QPainterPath for the hotspot shape centred at (cx, cy)."""
        _WIDE_RADIUS = 36
        path = QPainterPath()
        spec = self._shapes.get(name)
        if not spec:
            base_r = _WIDE_RADIUS if name in self._wide_set else _DOT_RADIUS
            r = base_r + grow
            path.addEllipse(cx - r, cy - r, r * 2, r * 2)
        elif spec[0] == "circle":
            r = spec[1] + grow
            path.addEllipse(cx - r, cy - r, r * 2, r * 2)
        elif spec[0] == "rrect":
            w, h, cr = spec[1], spec[2], spec[3]
            path.addRoundedRect(
                cx - w / 2 - grow, cy - h / 2 - grow,
                w + grow * 2, h + grow * 2, cr, cr,
            )
        elif spec[0] == "plus":
            arm = spec[1] + grow
            t = spec[2] + grow * 0.4
            path.setFillRule(Qt.FillRule.WindingFill)
            path.addRect(cx - arm, cy - t, arm * 2, t * 2)
            path.addRect(cx - t, cy - arm, t * 2, arm * 2)
        elif spec[0] == "home":
            s = spec[1] + grow
            path.setFillRule(Qt.FillRule.WindingFill)
            path.moveTo(cx, cy - s * 1.2)
            path.lineTo(cx + s, cy - s * 0.1)
            path.lineTo(cx - s, cy - s * 0.1)
            path.closeSubpath()
            path.addRect(cx - s * 0.7, cy - s * 0.1, s * 1.4, s * 1.1)
        elif spec[0] == "camera":
            s = spec[1] + grow
            path.setFillRule(Qt.FillRule.WindingFill)
            path.addRoundedRect(
                cx - s * 1.2, cy - s * 0.5,
                s * 2.4, s * 1.3, s * 0.2, s * 0.2,
            )
            path.addRect(cx - s * 0.35, cy - s * 0.9, s * 0.7, s * 0.4)
        elif spec[0].startswith("arrow_"):
            s = spec[1] + grow
            d = spec[0][6:]  # "up", "down", "left", "right"
            if d == "up":
                path.moveTo(cx, cy - s)
                path.lineTo(cx + s * 0.7, cy + s * 0.1)
                path.lineTo(cx + s * 0.25, cy + s * 0.1)
                path.lineTo(cx + s * 0.25, cy + s)
                path.lineTo(cx - s * 0.25, cy + s)
                path.lineTo(cx - s * 0.25, cy + s * 0.1)
                path.lineTo(cx - s * 0.7, cy + s * 0.1)
                path.closeSubpath()
            elif d == "down":
                path.moveTo(cx, cy + s)
                path.lineTo(cx + s * 0.7, cy - s * 0.1)
                path.lineTo(cx + s * 0.25, cy - s * 0.1)
                path.lineTo(cx + s * 0.25, cy - s)
                path.lineTo(cx - s * 0.25, cy - s)
                path.lineTo(cx - s * 0.25, cy - s * 0.1)
                path.lineTo(cx - s * 0.7, cy - s * 0.1)
                path.closeSubpath()
            elif d == "left":
                path.moveTo(cx - s, cy)
                path.lineTo(cx + s * 0.1, cy - s * 0.7)
                path.lineTo(cx + s * 0.1, cy - s * 0.25)
                path.lineTo(cx + s, cy - s * 0.25)
                path.lineTo(cx + s, cy + s * 0.25)
                path.lineTo(cx + s * 0.1, cy + s * 0.25)
                path.lineTo(cx + s * 0.1, cy + s * 0.7)
                path.closeSubpath()
            else:  # right
                path.moveTo(cx + s, cy)
                path.lineTo(cx - s * 0.1, cy - s * 0.7)
                path.lineTo(cx - s * 0.1, cy - s * 0.25)
                path.lineTo(cx - s, cy - s * 0.25)
                path.lineTo(cx - s, cy + s * 0.25)
                path.lineTo(cx - s * 0.1, cy + s * 0.25)
                path.lineTo(cx - s * 0.1, cy + s * 0.7)
                path.closeSubpath()
        elif spec[0].startswith("arc_"):
            inner_r = max(1, spec[1] - grow * 0.5)
            outer_r = spec[2] + grow
            d = spec[0][4:]  # "top", "bottom", "left", "right"
            gap = 8  # degrees between arc segments
            if d == "top":
                start, sweep = 45 + gap / 2, 90 - gap
            elif d == "right":
                start, sweep = -45 + gap / 2, 90 - gap
            elif d == "bottom":
                start, sweep = 225 + gap / 2, 90 - gap
            else:  # left
                start, sweep = 135 + gap / 2, 90 - gap
            o = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
            i = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
            path.arcMoveTo(o, start)
            path.arcTo(o, start, sweep)
            path.arcTo(i, start + sweep, -sweep)
            path.closeSubpath()
        else:
            r = _DOT_RADIUS + grow
            path.addEllipse(cx - r, cy - r, r * 2, r * 2)
        return path

    def _rebuild_hotspot_items(self) -> None:
        # Remove old hotspot items (keep bg)
        for hs in self._hotspots:
            if hs.dot and hs.dot.scene():
                self._scene.removeItem(hs.dot)
            if hs.label and hs.label.scene():
                self._scene.removeItem(hs.label)
            hs.dot = None
            hs.label = None

        rect = self._scene.sceneRect()
        if rect.width() <= 0:
            return

        for hs in self._hotspots:
            cx = hs.norm_x * rect.width()
            cy = hs.norm_y * rect.height()

            dot = QGraphicsPathItem(self._make_shape_path(cx, cy, hs.name))
            dot.setZValue(10)
            self._scene.addItem(dot)
            hs.dot = dot

            label = QGraphicsSimpleTextItem(hs.name)
            font = QFont(self._theme.typo("font_family"), 11, QFont.Weight.Bold)
            label.setFont(font)
            lw = label.boundingRect().width()
            spec = self._shapes.get(hs.name)
            if spec and spec[0].startswith("arc_"):
                d = spec[0][4:]
                outer_r = spec[2]
                if d == "top":
                    label.setPos(cx - lw / 2, cy - outer_r - 20)
                elif d == "bottom":
                    label.setPos(cx - lw / 2, cy + outer_r + 4)
                elif d == "left":
                    label.setPos(cx - outer_r - lw - 4, cy - 8)
                else:
                    label.setPos(cx + outer_r + 4, cy - 8)
            else:
                label.setPos(cx - lw / 2, cy + _TEXT_OFFSET_Y)
            label.setZValue(11)
            self._scene.addItem(label)
            hs.label = label

        self._build_overlay_brushes()
        self._update_hotspot_visuals()

    def _build_overlay_brushes(self) -> None:
        """Build overlay brushes directly from the live hotspot geometry."""
        self._overlay_brushes.clear()
        rect = self._scene.sceneRect()
        if rect.width() <= 0:
            return

        for hs in self._hotspots:
            brush = self._build_overlay_brush(hs, rect)
            if brush is not None:
                self._overlay_brushes[hs.name] = brush

    def _build_overlay_brush(self, hs: HotspotItem, rect: QRectF) -> QBrush | None:
        cx = hs.norm_x * rect.width()
        cy = hs.norm_y * rect.height()
        shape_path = self._make_shape_path(cx, cy, hs.name, grow=_PULSE_RANGE + 8)
        bounds = shape_path.boundingRect().toAlignedRect()
        if bounds.isEmpty():
            return None

        pixmap = QPixmap(bounds.size())
        pixmap.fill(Qt.GlobalColor.transparent)

        local_path = QPainterPath(shape_path)
        local_path.translate(-bounds.x(), -bounds.y())

        painter = QPainter(pixmap)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self._paint_overlay_texture(painter, local_path, hs.name)
        painter.end()

        brush = QBrush(pixmap)
        transform = QTransform()
        transform.translate(bounds.x(), bounds.y())
        brush.setTransform(transform)
        return brush

    def _paint_overlay_texture(self, painter: QPainter, path: QPainterPath, seed_name: str) -> None:
        seed = zlib.crc32(seed_name.encode("utf-8")) & 0xFFFF_FFFF
        rng = random.Random(seed)
        bounds = path.boundingRect()
        base = QColor(self._overlay_color)

        tint = QColor(base)
        tint.setAlpha(26)
        painter.fillPath(path, tint)

        painter.save()
        painter.setClipPath(path)

        hatch = QColor(base)
        hatch.setAlpha(86)
        hatch_pen = QPen(hatch, 1.2)
        hatch_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(hatch_pen)

        primary_step = max(6, int(min(bounds.width(), bounds.height()) / 5))
        start = int(bounds.left() - bounds.height())
        stop = int(bounds.right() + bounds.height())
        for offset in range(start, stop, primary_step):
            painter.drawLine(
                QPointF(offset + rng.uniform(-1.5, 1.5), bounds.top() + rng.uniform(-1.5, 1.5)),
                QPointF(offset - bounds.height() + rng.uniform(-1.5, 1.5), bounds.bottom() + rng.uniform(-1.5, 1.5)),
            )

        secondary = QColor(base)
        secondary.setAlpha(52)
        secondary_pen = QPen(secondary, 1.0)
        secondary_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(secondary_pen)
        secondary_step = primary_step + 3
        for offset in range(start, stop, secondary_step):
            painter.drawLine(
                QPointF(offset + rng.uniform(-1.2, 1.2), bounds.bottom() + rng.uniform(-1.2, 1.2)),
                QPointF(offset - bounds.height() + rng.uniform(-1.2, 1.2), bounds.top() + rng.uniform(-1.2, 1.2)),
            )

        painter.restore()

        glow = QColor(base)
        glow.setAlpha(70)
        glow_pen = QPen(glow, 5.0)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.strokePath(path, glow_pen)

        for width, alpha, jitter in ((2.2, 220, 1.1), (1.7, 165, 1.9), (1.0, 115, 2.4)):
            outline = QColor(base)
            outline.setAlpha(alpha)
            pen = QPen(outline, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            dx = rng.uniform(-jitter, jitter)
            dy = rng.uniform(-jitter, jitter)
            painter.strokePath(QTransform.fromTranslate(dx, dy).map(path), pen)

    def _update_hotspot_visuals(self) -> None:
        c = self._theme.theme["colors"]
        for hs in self._hotspots:
            if not hs.dot:
                continue

            # Determine color
            if hs.disabled:
                border_color = c["border"]
            elif hs.name == self._selected:
                border_color = c["accent"]
            elif hs.conflict:
                border_color = c["conflict"]
            elif hs.search_match:
                border_color = c["success"]
            elif hs.mapped:
                border_color = self._overlay_color
            else:
                border_color = c["border"]

            # Hover effect — determine opacity based on state
            is_hovered = hs.name == self._hovered
            overlay_brush = self._overlay_brushes.get(hs.name)

            if hs.disabled:
                opacity = 0.18
            elif hs.name == self._selected or is_hovered:
                opacity = 0.92
            elif hs.mapped:
                opacity = 0.72
            else:
                opacity = 0.34

            # Hotspots always render through the overlay texture brush.
            if overlay_brush:
                hs.dot.setBrush(overlay_brush)
                hs.dot.setOpacity(opacity)
            else:
                hs.dot.setBrush(Qt.BrushStyle.NoBrush)
                hs.dot.setOpacity(1.0)

            pen_width = 3 if is_hovered or hs.name == self._selected else 2
            pen = QPen(QColor(border_color), pen_width)
            hs.dot.setPen(pen)

            # Label color
            if hs.label:
                label_color = QColor("#ffffff" if hs.mapped or hs.name == self._selected else c["text"])
                hs.label.setBrush(QBrush(label_color))

                # Show mapping output below hotspot name
                mapping_text = self._mapping_labels.get(hs.name, "")
                if mapping_text and hs.name != self._selected:
                    hs.label.setText(f"{hs.name}\n{mapping_text}")
                else:
                    hs.label.setText(hs.name)

            # Pulse for selected
            if hs.name == self._selected:
                grow = _PULSE_RANGE * math.sin(self._pulse_phase)
                rect = self._scene.sceneRect()
                cx = hs.norm_x * rect.width()
                cy = hs.norm_y * rect.height()
                hs.dot.setPath(self._make_shape_path(cx, cy, hs.name, grow))

            # Lock indicator
            if hs.locked and hs.label:
                current = hs.label.text()
                if "🔒" not in current:
                    hs.label.setText(f"🔒 {current}")

    def _pulse_tick(self) -> None:
        self._pulse_phase += 0.15
        if self._pulse_phase > math.pi * 2:
            self._pulse_phase -= math.pi * 2
        if self._selected:
            self._update_hotspot_visuals()

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self._update_hotspot_visuals()
