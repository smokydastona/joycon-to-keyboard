"""Always-on-top overlay window (Key Pops).

Shows a minimal, semi-transparent display of current key state, macro activity,
slot information, active layer, and turbo state over other applications.
Enhanced with bubble-style glow effects and customisable placement.
"""
from __future__ import annotations

from typing import ClassVar

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QMenu, QWidget

from ..theme import ThemeEngine

# Placement presets: (x_fraction, y_fraction) of screen
PLACEMENT_PRESETS = {
    "Top Left": (0.02, 0.02),
    "Top Center": (0.4, 0.02),
    "Top Right": (0.75, 0.02),
    "Center Left": (0.02, 0.4),
    "Center Right": (0.75, 0.4),
    "Bottom Left": (0.02, 0.85),
    "Bottom Center": (0.4, 0.85),
    "Bottom Right": (0.75, 0.85),
}


class OverlayWindow(QWidget):
    """Semi-transparent always-on-top key-state overlay."""

    # Opacity presets available from the context menu
    _OPACITY_PRESETS: ClassVar[list[float]] = [0.3, 0.5, 0.7, 1.0]

    def __init__(self, theme: ThemeEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._active_keys: set[str] = set()
        self._slot_text = "Slot: —"
        self._profile_name = ""
        self._layer_text = ""
        self._turbo_active = False
        self._macro_text = ""
        self._last_key_text = ""
        self._compact = False
        self.is_closed = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._full_size = (280, 170)
        self._compact_size = (180, 60)
        self.setFixedSize(*self._full_size)

        # Load saved opacity or default
        settings = QSettings()
        self._opacity = settings.value("overlay_opacity", 0.85, type=float)

        # Restore saved position (clamped to visible screen area)
        saved_pos = settings.value("overlay_pos", None)
        if saved_pos is not None and isinstance(saved_pos, QPoint):
            self.move(self._clamp_to_screen(saved_pos))

        # Drag support
        self._drag_pos: QPoint | None = None

        # Glow/bubble shadow effect
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setBlurRadius(24)
        self._glow.setOffset(0, 0)
        self._glow.setColor(QColor(theme.theme["colors"]["accent"]))
        self.setGraphicsEffect(self._glow)

        # Glow pulse animation for key presses
        self._glow_anim = QPropertyAnimation(self._glow, b"blurRadius")
        self._glow_anim.setDuration(400)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Bubble style from settings
        self._bubble_style = settings.value("overlay_style", "bubble", type=str)

        # Fade timer for last-key flash
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.setInterval(1500)
        self._fade_timer.timeout.connect(self._clear_last_key)

        # Auto-hide timer (0 = disabled)
        self._auto_hide_secs = settings.value("overlay_auto_hide", 0, type=int)
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._auto_hide)

    def set_slot(self, slot: int) -> None:
        self._slot_text = f"Slot: {slot}"
        self.update()

    def set_profile_name(self, name: str) -> None:
        self._profile_name = name
        self.update()

    def set_layer(self, layer_name: str) -> None:
        self._layer_text = f"Layer: {layer_name}" if layer_name else ""
        self.update()

    def set_turbo(self, active: bool) -> None:
        self._turbo_active = active
        self.update()

    def set_last_key(self, pressed: bool, key_name: str) -> None:
        action = "▼" if pressed else "▲"
        self._last_key_text = f"{action} {key_name}"
        if pressed:
            self._active_keys.add(key_name)
            # Pulse glow on key press
            self._glow_anim.stop()
            self._glow_anim.setStartValue(24)
            self._glow_anim.setEndValue(40)
            self._glow_anim.start()
        else:
            self._active_keys.discard(key_name)
            # Settle glow back
            self._glow_anim.stop()
            self._glow_anim.setStartValue(40)
            self._glow_anim.setEndValue(24)
            self._glow_anim.start()
        self._fade_timer.start()
        self._restart_auto_hide()
        self.update()

    def set_macro(self, macro_id: str, state: str) -> None:
        self._macro_text = f"Macro: {macro_id} ({state})" if state else ""
        self.update()

    def _clear_last_key(self) -> None:
        self._last_key_text = ""
        self.update()

    def _restart_auto_hide(self) -> None:
        if self._auto_hide_secs > 0:
            self.show()
            self._auto_hide_timer.start(self._auto_hide_secs * 1000)

    def _auto_hide(self) -> None:
        self.hide()

    def paintEvent(self, event: object) -> None:
        c = self._theme.theme["colors"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        bg = QColor(0, 0, 0)
        bg.setAlphaF(self._opacity * 0.7)
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 12, 12)

        # Border
        border = QColor(c["accent"])
        border.setAlphaF(0.4)
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

        # Text
        text_color = QColor("#ffffff")
        text_color.setAlphaF(0.9)
        painter.setPen(text_color)

        font = QFont(self._theme.typo("font_family"), 10)
        painter.setFont(font)

        y = 16

        # Slot + profile name
        slot_line = self._slot_text
        if self._profile_name:
            slot_line += f"  —  {self._profile_name}"
        painter.drawText(12, y + 12, slot_line)
        y += 22

        if self._compact:
            # Compact mode: just show last key
            if self._last_key_text:
                font_key = QFont(self._theme.typo("font_family"), 12, QFont.Weight.Bold)
                painter.setFont(font_key)
                key_color = QColor(c["accent"])
                key_color.setAlphaF(0.95)
                painter.setPen(key_color)
                painter.drawText(12, y + 12, self._last_key_text)
            painter.end()
            return

        # Layer + turbo indicators
        indicators: list[str] = []
        if self._layer_text:
            indicators.append(self._layer_text)
        if self._turbo_active:
            indicators.append("⚡ Turbo")
        if indicators:
            muted = QColor(c.get("warning", "#c09840"))
            muted.setAlphaF(0.85)
            painter.setPen(muted)
            painter.drawText(12, y + 12, "  |  ".join(indicators))
            y += 20
            painter.setPen(text_color)

        if self._last_key_text:
            font_key = QFont(self._theme.typo("font_family"), 14, QFont.Weight.Bold)
            painter.setFont(font_key)
            key_color = QColor(c["accent"])
            key_color.setAlphaF(0.95)
            painter.setPen(key_color)
            painter.drawText(12, y + 16, self._last_key_text)
            y += 28
            painter.setFont(font)
            painter.setPen(text_color)

        if self._active_keys:
            active_str = ", ".join(sorted(self._active_keys))
            muted = QColor(c["muted"])
            muted.setAlphaF(0.8)
            painter.setPen(muted)
            painter.drawText(12, y + 12, f"Active: {active_str}")
            y += 20

        if self._macro_text:
            painter.setPen(text_color)
            painter.drawText(12, y + 12, self._macro_text)

        painter.end()

    # -----------------------------------------------------------------
    # Context menu (right-click)
    # -----------------------------------------------------------------

    def contextMenuEvent(self, event: object) -> None:
        menu = QMenu(self)

        # Opacity presets
        opacity_menu = menu.addMenu("Opacity")
        for level in self._OPACITY_PRESETS:
            pct = int(level * 100)
            act = QAction(f"{pct}%", self)
            act.setCheckable(True)
            act.setChecked(abs(self._opacity - level) < 0.05)
            act.triggered.connect(lambda checked, o=level: self._set_opacity(o))
            opacity_menu.addAction(act)

        # Placement presets
        place_menu = menu.addMenu("Placement")
        for name, (fx, fy) in PLACEMENT_PRESETS.items():
            act = QAction(name, self)
            act.triggered.connect(lambda checked, x=fx, y=fy: self._move_to_preset(x, y))
            place_menu.addAction(act)

        # Compact mode toggle
        compact_act = QAction("Compact Mode", self)
        compact_act.setCheckable(True)
        compact_act.setChecked(self._compact)
        compact_act.triggered.connect(self._toggle_compact)
        menu.addAction(compact_act)

        menu.addSeparator()
        close_act = menu.addAction("Close Overlay")
        close_act.triggered.connect(self.close)

        if hasattr(event, 'globalPos'):
            menu.exec(event.globalPos())

    def _move_to_preset(self, fx: float, fy: float) -> None:
        """Move the overlay to a fractional screen position."""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = int(geo.x() + geo.width() * fx)
            y = int(geo.y() + geo.height() * fy)
            pos = self._clamp_to_screen(QPoint(x, y))
            self.move(pos)
            QSettings().setValue("overlay_pos", pos)

    def _set_opacity(self, opacity: float) -> None:
        self._opacity = opacity
        settings = QSettings()
        settings.setValue("overlay_opacity", opacity)
        self.update()

    def _toggle_compact(self, checked: bool) -> None:
        self._compact = checked
        if checked:
            self.setFixedSize(*self._compact_size)
        else:
            self.setFixedSize(*self._full_size)
        self.update()

    # -----------------------------------------------------------------
    # Double-click toggles compact
    # -----------------------------------------------------------------

    def mouseDoubleClickEvent(self, event: object) -> None:
        self._toggle_compact(not self._compact)

    def mousePressEvent(self, event: object) -> None:
        if hasattr(event, 'position') and hasattr(event, 'globalPosition'):
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: object) -> None:
        if self._drag_pos is not None and hasattr(event, 'globalPosition'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: object) -> None:
        if self._drag_pos is not None:
            # Persist position for next launch
            pos = self._clamp_to_screen(self.pos())
            self.move(pos)
            QSettings().setValue("overlay_pos", pos)
        self._drag_pos = None

    def closeEvent(self, event: object) -> None:
        self.is_closed = True
        super().closeEvent(event)

    @staticmethod
    def _clamp_to_screen(pos: QPoint) -> QPoint:
        """Clamp *pos* so the overlay stays within a visible screen."""
        combined = QRect()
        for screen in QApplication.screens():
            combined = combined.united(screen.availableGeometry())
        if combined.isNull():
            return pos
        x = max(combined.left(), min(pos.x(), combined.right() - 100))
        y = max(combined.top(), min(pos.y(), combined.bottom() - 40))
        return QPoint(x, y)

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self.update()
