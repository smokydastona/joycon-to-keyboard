"""Always-on-top overlay window.

Shows a minimal, semi-transparent display of current key state, macro activity,
and slot information over other applications.
"""
from __future__ import annotations

from typing import Dict, Optional, Set

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import ThemeEngine


class OverlayWindow(QWidget):
    """Semi-transparent always-on-top key-state overlay."""

    def __init__(self, theme: ThemeEngine, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._active_keys: Set[str] = set()
        self._slot_text = "Slot: —"
        self._macro_text = ""
        self._last_key_text = ""
        self.is_closed = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.setFixedSize(260, 140)
        self._opacity = 0.85

        # Drag support
        self._drag_pos: Optional[QPoint] = None

        # Fade timer for last-key flash
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.setInterval(1500)
        self._fade_timer.timeout.connect(self._clear_last_key)

    def set_slot(self, slot: int) -> None:
        self._slot_text = f"Slot: {slot}"
        self.update()

    def set_last_key(self, pressed: bool, key_name: str) -> None:
        action = "▼" if pressed else "▲"
        self._last_key_text = f"{action} {key_name}"
        if pressed:
            self._active_keys.add(key_name)
        else:
            self._active_keys.discard(key_name)
        self._fade_timer.start()
        self.update()

    def set_macro(self, macro_id: str, state: str) -> None:
        self._macro_text = f"Macro: {macro_id} ({state})" if state else ""
        self.update()

    def _clear_last_key(self) -> None:
        self._last_key_text = ""
        self.update()

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
        painter.drawText(12, y + 12, self._slot_text)
        y += 24

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

    def mousePressEvent(self, event: object) -> None:
        if hasattr(event, 'position') and hasattr(event, 'globalPosition'):
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: object) -> None:
        if self._drag_pos is not None and hasattr(event, 'globalPosition'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: object) -> None:
        self._drag_pos = None

    def closeEvent(self, event: object) -> None:
        self.is_closed = True
        super().closeEvent(event)

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self.update()
