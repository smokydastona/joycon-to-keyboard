"""QGraphicsView-based hotspot canvas for controller, keyboard, and mouse overlays.

Renders a device image with interactive hotspot dots representing buttons.
Supports click-to-select, hover tooltips, pulse animation, conflict
indicators, search highlighting, and overlay compositing.
"""
from __future__ import annotations

import math
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import (
    QPointF, QRectF, QSize, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPen, QPixmap, QTransform,
)
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QMenu, QWidget,
)

from ..theme import ThemeEngine, hex_to_rgb

log = logging.getLogger("joycon_helper.ui.widgets.hotspot_canvas")

# Size of hotspot dots at native image resolution
_DOT_RADIUS = 18
_TEXT_OFFSET_Y = -26
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
        self.dot: Optional[QGraphicsEllipseItem] = None
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
                self._dragging.dot.setRect(
                    cx - _DOT_RADIUS, cy - _DOT_RADIUS,
                    _DOT_RADIUS * 2, _DOT_RADIUS * 2,
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
        best_name: Optional[str] = None
        best_dist = float("inf")
        rect = self._scene.sceneRect()
        for hs in self._hotspots:
            hx = hs.norm_x * rect.width()
            hy = hs.norm_y * rect.height()
            dx = scene_pos.x() - hx
            dy = scene_pos.y() - hy
            dist = math.sqrt(dx * dx + dy * dy)
            threshold = _DOT_RADIUS * 2.5
            if dist < threshold and dist < best_dist:
                best_dist = dist
                best_name = hs.name
        return best_name

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

            dot = QGraphicsEllipseItem(
                cx - _DOT_RADIUS, cy - _DOT_RADIUS,
                _DOT_RADIUS * 2, _DOT_RADIUS * 2,
            )
            dot.setZValue(10)
            self._scene.addItem(dot)
            hs.dot = dot

            label = QGraphicsSimpleTextItem(hs.name)
            font = QFont(self._theme.typo("font_family"), 8, QFont.Weight.Bold)
            label.setFont(font)
            lw = label.boundingRect().width()
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
                pulse_r = _DOT_RADIUS + _PULSE_RANGE * math.sin(self._pulse_phase)
                rect = self._scene.sceneRect()
                cx = hs.norm_x * rect.width()
                cy = hs.norm_y * rect.height()
                hs.dot.setRect(cx - pulse_r, cy - pulse_r, pulse_r * 2, pulse_r * 2)

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
