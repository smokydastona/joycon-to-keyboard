"""Status bar widget with connection state, slot info, and mode indicators."""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QStatusBar, QWidget

from ..theme import ThemeEngine


class AppStatusBar(QStatusBar):
    """Application status bar showing connection, slot, battery, and mode info."""

    def __init__(self, theme: ThemeEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

        # Left: connection status
        self._conn_label = QLabel("Disconnected")
        self.addWidget(self._conn_label)

        # Left: separator
        sep = QLabel("│")
        sep.setStyleSheet("color: rgba(128,128,128,0.5);")
        self.addWidget(sep)

        # Left: slot
        self._slot_label = QLabel("Slot: —")
        self.addWidget(self._slot_label)

        sep2 = QLabel("│")
        sep2.setStyleSheet("color: rgba(128,128,128,0.5);")
        self.addWidget(sep2)

        # Left: mode
        self._mode_label = QLabel("")
        self.addWidget(self._mode_label)

        # Right side: battery, latency, undo depth
        self._battery_label = QLabel("")
        self.addPermanentWidget(self._battery_label)

        self._latency_label = QLabel("")
        self.addPermanentWidget(self._latency_label)

        self._undo_label = QLabel("")
        self.addPermanentWidget(self._undo_label)

    def set_connected(self, port: str) -> None:
        c = self._theme.color("success")
        self._conn_label.setText(f"Connected: {port}")
        self._conn_label.setStyleSheet(f"color: {c}; font-weight: 600;")

    def set_disconnected(self) -> None:
        c = self._theme.color("danger")
        self._conn_label.setText("Disconnected")
        self._conn_label.setStyleSheet(f"color: {c};")

    def set_slot(self, slot: int, name: str = "") -> None:
        text = f"Slot {slot}"
        if name:
            text += f" — {name}"
        self._slot_label.setText(text)

    def set_mode(self, text: str) -> None:
        self._mode_label.setText(text)

    def set_battery(self, level: int) -> None:
        bars = "█" * level + "░" * (4 - level) if level >= 0 else ""
        self._battery_label.setText(f"🔋 {bars}" if bars else "")

    def set_latency(self, ms: float) -> None:
        self._latency_label.setText(f"⚡ {ms:.0f}ms" if ms > 0 else "")

    def set_undo_depth(self, depth: int) -> None:
        self._undo_label.setText(f"↩ {depth}" if depth > 0 else "")

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
