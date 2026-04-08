"""QGraphicsView-based hotspot canvas for controller, keyboard, and mouse overlays.

Renders a device image with interactive hotspot dots representing buttons.
Supports click-to-select, hover tooltips, pulse animation, conflict
indicators, search highlighting, and overlay compositing.
"""
from __future__ import annotations

import math
import logging
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    QRectF, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QWidget,
)

from ..theme import ThemeEngine

log = logging.getLogger("joycon_helper.ui.widgets.hotspot_canvas")

# Size of hotspot dots at native image resolution
_DOT_RADIUS = 18
_TEXT_OFFSET_Y = -32
_HOVER_GROW = 6
_PULSE_RANGE = 4


class HotspotItem:
    """Holds QGraphicsItems for a single hotspot."""

    def __init__(self, name: str, norm_x: float, norm_y: float) -> None:
        self.name = name
        self.norm_x = norm_x
        self.norm_y = norm_y
        self.key_id: Optional[int] = None
        self.mapped = False
        self.conflict = False
        self.search_match = False
        self.disabled = False
        self.locked = False
        self.dot: Optional[QGraphicsPathItem] = None
        self.label: Optional[QGraphicsSimpleTextItem] = None


class HotspotCanvas(QGraphicsView):
    """Interactive canvas for device-image + clickable hotspot dots."""

    hotspot_clicked = pyqtSignal(str)            # name
    hotspot_right_clicked = pyqtSignal(str, object)  # name, QPoint (screen pos)
    hotspot_hovered = pyqtSignal(str)            # name (empty string = no hover)

    def __init__(self, theme: ThemeEngine, parent: Optional[QWidget] = None) -> None:
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
        self._bg_item: Optional[QGraphicsPixmapItem] = None
        self._hotspots: List[HotspotItem] = []
        self._selected: Optional[str] = None
        self._hovered: Optional[str] = None
        self._overlay_color = "#a03cc8"  # violet default
        self._mapping_labels: Dict[str, str] = {}
        self._shapes: Dict[str, Any] = {}

        # Drag-edit mode (temporary position tweaking)
        self._edit_mode = False
        self._dragging: Optional[HotspotItem] = None

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
        self._scene.clear()
        self._bg_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._rebuild_hotspot_items()
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_hotspots(self, hotspots: List[Tuple[str, float, float]]) -> None:
        self._hotspots = [HotspotItem(name, nx, ny) for name, nx, ny in hotspots]
        self._rebuild_hotspot_items()

    def set_hotspot_shapes(self, shapes: Dict[str, Any]) -> None:
        """Set per-button shape specs (only affects Joy-Con canvas)."""
        self._shapes = shapes
        self._rebuild_hotspot_items()

    def set_selected(self, name: Optional[str]) -> None:
        self._selected = name
        self._update_hotspot_visuals()

    def set_overlay_color(self, hex_color: str) -> None:
        self._overlay_color = hex_color
        self._update_hotspot_visuals()

    def update_hotspot_state(self, name: str, *,
                             key_id: Optional[int] = None,
                             mapped: Optional[bool] = None,
                             conflict: Optional[bool] = None,
                             search_match: Optional[bool] = None,
                             disabled: Optional[bool] = None,
                             locked: Optional[bool] = None) -> None:
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

    def set_mapping_labels(self, labels: Dict[str, str]) -> None:
        self._mapping_labels = labels
        self._update_hotspot_visuals()

    def clear_search(self) -> None:
        for hs in self._hotspots:
            hs.search_match = False
        self._update_hotspot_visuals()

    def get_hotspot_names(self) -> List[str]:
        return [hs.name for hs in self._hotspots]

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        self._dragging = None
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if enabled
            else Qt.CursorShape.ArrowCursor
        )

    def export_positions(self) -> List[Tuple[str, float, float]]:
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
                self._dragging.norm_x = nx
                self._dragging.norm_y = ny
                cx = nx * rect.width()
                cy = ny * rect.height()
                self._dragging.dot.setPath(
                    self._make_shape_path(cx, cy, self._dragging.name)
                )
                if self._dragging.label:
                    lw = self._dragging.label.boundingRect().width()
                    self._dragging.label.setPos(cx - lw / 2, cy + _TEXT_OFFSET_Y)
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

    def _pick_hotspot(self, view_pos: Any) -> Optional[str]:
        scene_pos = self.mapToScene(int(view_pos.x()), int(view_pos.y()))
        rect = self._scene.sceneRect()
        if rect.width() <= 0:
            return None
        # Pass 1: exact shape containment
        best_name: Optional[str] = None
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
            if self._make_shape_path(hx, hy, hs.name, grow=6).contains(scene_pos):
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
        path = QPainterPath()
        spec = self._shapes.get(name)
        if not spec:
            r = _DOT_RADIUS + grow
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

        self._update_hotspot_visuals()

    def _update_hotspot_visuals(self) -> None:
        c = self._theme.theme["colors"]
        for hs in self._hotspots:
            if not hs.dot:
                continue

            # Determine color
            if hs.disabled:
                fill_color = c["muted"]
                border_color = c["border"]
            elif hs.name == self._selected:
                fill_color = c["accent"]
                border_color = c["accent"]
            elif hs.conflict:
                fill_color = c["conflict"]
                border_color = c["conflict"]
            elif hs.search_match:
                fill_color = c["success"]
                border_color = c["success"]
            elif hs.mapped:
                fill_color = self._overlay_color
                border_color = self._overlay_color
            else:
                fill_color = c["muted"]
                border_color = c["border"]

            # Hover effect
            is_hovered = hs.name == self._hovered
            opacity = 0.95 if is_hovered or hs.name == self._selected else 0.75

            fc = QColor(fill_color)
            fc.setAlphaF(opacity)
            hs.dot.setBrush(QBrush(fc))

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
