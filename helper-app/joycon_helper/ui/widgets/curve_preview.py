"""Stick response curve preview widget.

Draws a small graph showing the response curve (linear, exponential, S-curve,
etc.) with configurable deadzone, sensitivity, and max output.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..theme import ThemeEngine


class CurvePreviewWidget(QWidget):
    """Small widget drawing a response curve graph."""

    def __init__(self, theme: ThemeEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._deadzone = 0.05
        self._sensitivity = 1.0
        self._max_output = 1.0
        self._curve_type = "linear"  # linear | exponential | s_curve
        self._custom_fn: Callable[[float], float] | None = None
        self.setMinimumSize(120, 100)

    def set_curve(self, curve_type: str = "linear",
                  deadzone: float = 0.05,
                  sensitivity: float = 1.0,
                  max_output: float = 1.0) -> None:
        self._curve_type = curve_type
        self._deadzone = max(0.0, min(0.5, deadzone))
        self._sensitivity = max(0.1, min(5.0, sensitivity))
        self._max_output = max(0.0, min(1.0, max_output))
        self.update()

    def set_custom_function(self, fn: Callable[[float], float] | None) -> None:
        self._custom_fn = fn
        self.update()

    def _evaluate(self, x: float) -> float:
        if self._custom_fn:
            return max(0.0, min(1.0, self._custom_fn(x)))

        if x < self._deadzone:
            return 0.0

        norm = (x - self._deadzone) / (1.0 - self._deadzone)

        if self._curve_type == "exponential":
            out = norm ** self._sensitivity
        elif self._curve_type == "s_curve":
            # Sigmoid-like
            mid = 0.5
            k = self._sensitivity * 4
            out = 1.0 / (1.0 + math.exp(-k * (norm - mid)))
            out_min = 1.0 / (1.0 + math.exp(-k * (0 - mid)))
            out_max = 1.0 / (1.0 + math.exp(-k * (1 - mid)))
            out = (out - out_min) / (out_max - out_min) if out_max > out_min else norm
        else:
            out = norm * self._sensitivity

        return max(0.0, min(self._max_output, out))

    def paintEvent(self, event: object) -> None:
        c = self._theme.theme["colors"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 10
        gw = w - 2 * margin
        gh = h - 2 * margin

        # Background
        bg = QColor(c["surface"])
        painter.fillRect(self.rect(), bg)

        # Grid
        grid_pen = QPen(QColor(c["border_light"]), 1, Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        for i in range(1, 4):
            frac = i / 4.0
            x = margin + frac * gw
            y = margin + (1 - frac) * gh
            painter.drawLine(int(x), margin, int(x), margin + gh)
            painter.drawLine(margin, int(y), margin + gw, int(y))

        # Axes
        axis_pen = QPen(QColor(c["border"]), 1)
        painter.setPen(axis_pen)
        painter.drawLine(margin, margin + gh, margin + gw, margin + gh)
        painter.drawLine(margin, margin, margin, margin + gh)

        # Deadzone indicator
        if self._deadzone > 0:
            dz_x = margin + self._deadzone * gw
            dz_pen = QPen(QColor(c["warning"]), 1, Qt.PenStyle.DashLine)
            painter.setPen(dz_pen)
            painter.drawLine(int(dz_x), margin, int(dz_x), margin + gh)

        # Curve path
        path = QPainterPath()
        steps = max(50, gw)
        for i in range(steps + 1):
            x_norm = i / steps
            y_norm = self._evaluate(x_norm)
            px = margin + x_norm * gw
            py = margin + (1 - y_norm) * gh
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)

        curve_pen = QPen(QColor(c["accent"]), 2)
        painter.setPen(curve_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # Linear reference line
        ref_pen = QPen(QColor(c["muted"]), 1, Qt.PenStyle.DashLine)
        painter.setPen(ref_pen)
        painter.drawLine(margin, margin + gh, margin + gw, margin)

        painter.end()

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self.update()
