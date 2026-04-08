"""Input event timeline widget for diagnostics.

Displays a scrolling horizontal timeline of input events with colored bars
showing press/release timing.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Optional, Tuple

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..theme import ThemeEngine


class TimelineEvent:
    __slots__ = ("name", "color", "time")

    def __init__(self, name: str, color: str, t: float) -> None:
        self.name = name
        self.color = color
        self.time = t


class TimelineWidget(QWidget):
    """Scrolling horizontal timeline showing recent input events."""

    MAX_EVENTS = 200
    WINDOW_SECONDS = 10.0

    def __init__(self, theme: ThemeEngine, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._events: Deque[TimelineEvent] = deque(maxlen=self.MAX_EVENTS)
        self._start_time = time.monotonic()
        self.setMinimumHeight(60)
        self.setMaximumHeight(120)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def add_event(self, name: str, color: str) -> None:
        self._events.append(TimelineEvent(name, color, time.monotonic()))
        self.update()

    def clear(self) -> None:
        self._events.clear()
        self._start_time = time.monotonic()
        self.update()

    def paintEvent(self, event: object) -> None:
        c = self._theme.theme["colors"]
        t_now = time.monotonic()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(self.rect(), QColor(c["surface"]))

        # Border
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawRect(0, 0, w - 1, h - 1)

        if not self._events:
            painter.setPen(QColor(c["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No events yet")
            painter.end()
            return

        margin_l = 8
        margin_r = 8
        margin_t = 6
        margin_b = 16
        gw = w - margin_l - margin_r
        gh = h - margin_t - margin_b

        t_end = t_now
        t_start = t_end - self.WINDOW_SECONDS

        # Time axis markers
        painter.setPen(QPen(QColor(c["border_light"]), 1, Qt.PenStyle.DotLine))
        font = QFont(self._theme.typo("font_family"), 7)
        painter.setFont(font)
        for sec in range(int(self.WINDOW_SECONDS) + 1):
            frac = sec / self.WINDOW_SECONDS
            x = margin_l + frac * gw
            painter.drawLine(int(x), margin_t, int(x), margin_t + gh)
            painter.setPen(QColor(c["muted"]))
            painter.drawText(int(x) - 10, h - 2, f"-{int(self.WINDOW_SECONDS) - sec}s")
            painter.setPen(QPen(QColor(c["border_light"]), 1, Qt.PenStyle.DotLine))

        # Draw event markers
        bar_h = max(4, min(12, gh // 3))
        for ev in self._events:
            if ev.time < t_start:
                continue
            frac = (ev.time - t_start) / self.WINDOW_SECONDS
            x = margin_l + frac * gw
            y_center = margin_t + gh / 2

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ev.color))
            painter.drawRoundedRect(
                QRectF(x - 2, y_center - bar_h / 2, 4, bar_h), 2, 2
            )

        painter.end()

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme

    def showEvent(self, event: object) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event: object) -> None:  # type: ignore[override]
        super().hideEvent(event)  # type: ignore[arg-type]
        self._timer.stop()
        self.update()
