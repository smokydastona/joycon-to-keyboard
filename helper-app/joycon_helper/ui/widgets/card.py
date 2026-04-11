"""Reusable Card widget — a rounded, elevated QFrame container."""
from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QWidget

from ..theme import ThemeEngine


class Card(QFrame):
    """A themed rounded-corner container with a subtle drop shadow."""

    def __init__(self, theme: ThemeEngine, parent: QWidget | None = None,
                 padding: int = 16, radius: int = 10) -> None:
        super().__init__(parent)
        self._theme = theme
        self._padding = padding
        self._radius = radius

        self.setObjectName("Card")

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(16)
        self._shadow.setOffset(0, 2)
        self.setGraphicsEffect(self._shadow)

        self._apply_theme()

    def _apply_theme(self) -> None:
        c = self._theme.theme["colors"]
        self.setStyleSheet(f"""
            #Card {{
                background: {c['surface']};
                border: 1px solid {c['border_light']};
                border-radius: {self._radius}px;
            }}
        """)
        shadow_color = QColor(0, 0, 0, 20 if not self._theme.is_dark else 60)
        self._shadow.setColor(shadow_color)

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self._apply_theme()
