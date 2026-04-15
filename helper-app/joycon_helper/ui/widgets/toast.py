"""Non-blocking slide-in toast notifications.

Usage:
    from .widgets.toast import Toast
    Toast.info(parent_widget, "Profile saved.")
    Toast.warning(parent_widget, "Low battery!")
    Toast.error(parent_widget, "Connection lost.")
    Toast.success(parent_widget, "Firmware updated.")
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

from PyQt6.QtCore import QPoint, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)

# Maximum visible toasts stacked at once
_MAX_VISIBLE = 3
# Global list of active toasts (most recent last)
_active_toasts: list[Toast] = []

# Type presets: (icon, bg_color)
_PRESETS = {
    "info":    ("ℹ️", "#3b82f6"),
    "success": ("✅", "#22c55e"),
    "warning": ("⚠️", "#eab308"),
    "error":   ("❌", "#ef4444"),
}


class Toast(QWidget):
    """Self-dismissing slide-in notification widget."""

    DURATION_MS = 3500
    HEIGHT = 40
    WIDTH = 320
    MARGIN = 8

    def __init__(
        self,
        parent: QWidget,
        message: str,
        kind: str = "info",
        duration_ms: int = DURATION_MS,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)

        icon, bg = _PRESETS.get(kind, _PRESETS["info"])
        self._bg_color = QColor(bg)
        self._text = f"{icon}  {message}"
        self._opacity = 1.0
        self._on_click = on_click

        if self._on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Accessibility
        self.setAccessibleName(message)
        self.setAccessibleDescription(f"{kind}: {message}")

        # Position: stack from bottom-right of parent
        _active_toasts.append(self)
        if len(_active_toasts) > _MAX_VISIBLE:
            _active_toasts[0]._dismiss()

        self._reposition_all()
        self.show()
        self.raise_()

        # Slide-in animation
        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setDuration(250)
        start = self.pos()
        self._anim.setStartValue(QPoint(start.x() + self.WIDTH, start.y()))
        self._anim.setEndValue(start)
        self._anim.start()

        # Auto-dismiss timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(duration_ms)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start()

    # -- class-level convenience methods --
    @classmethod
    def info(cls, parent: QWidget, msg: str, **kw: object) -> Toast:
        return cls(parent, msg, "info", **kw)

    @classmethod
    def success(cls, parent: QWidget, msg: str, **kw: object) -> Toast:
        return cls(parent, msg, "success", **kw)

    @classmethod
    def warning(cls, parent: QWidget, msg: str, **kw: object) -> Toast:
        return cls(parent, msg, "warning", **kw)

    @classmethod
    def error(cls, parent: QWidget, msg: str, **kw: object) -> Toast:
        return cls(parent, msg, "error", **kw)

    # -- internals --
    def _dismiss(self) -> None:
        if self in _active_toasts:
            _active_toasts.remove(self)
        self._reposition_all()
        self.close()
        self.deleteLater()

    @staticmethod
    def _reposition_all() -> None:
        for i, t in enumerate(reversed(_active_toasts)):
            if t.parent() is None:
                continue
            p = t.parent()
            x = p.width() - t.WIDTH - t.MARGIN
            y = p.height() - (i + 1) * (t.HEIGHT + t.MARGIN)
            t.move(x, y)

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(self._bg_color)
        bg.setAlphaF(0.92)
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)

        painter.setPen(QColor("#ffffff"))
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(12, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, self._text)
        painter.end()

    def mousePressEvent(self, event: object) -> None:
        if self._on_click is not None:
            with contextlib.suppress(Exception):
                self._on_click()
        self._dismiss()
