"""Dashboard view — connection status, quick actions, slot overview.

The first view users see.  Shows connection state, BT devices,
battery, latency, and a card grid with quick-action buttons.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..dashboard_summary import (
    build_battery_briefing,
    build_profile_briefing,
)
from ..theme import ThemeEngine
from ..widgets.card import Card
from ..widgets.live_input_visualizer import LiveInputVisualizerWidget

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.dashboard")


class DashboardView(QScrollArea):
    """Dashboard: overview cards, quick actions, connection status."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main
        self._battery_levels: dict[int, int] = {}
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(16)
        self.setWidget(container)

        self._build_header()
        self._build_status_cards()
        self._build_quick_actions()
        self._build_profile_briefing()
        self._build_device_preview()
        self._build_device_log()
        self._layout.addStretch()

    # -----------------------------------------------------------------
    def _build_header(self) -> None:
        header = QLabel("Mission Control")
        header.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        self._layout.addWidget(header)

        subtitle = QLabel("Connection overview and quick actions")
        subtitle.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        self._layout.addWidget(subtitle)

    # -----------------------------------------------------------------
    def _build_status_cards(self) -> None:
        grid = QGridLayout()
        grid.setSpacing(12)

        # Connection card
        self._conn_card = Card(self._main.theme)
        conn_lay = QVBoxLayout(self._conn_card)
        conn_lay.addWidget(QLabel("🔌  Connection"))
        self._conn_status = QLabel("Disconnected")
        self._conn_status.setFont(QFont(self._main.theme.typo("font_family"), 12, QFont.Weight.Bold))
        conn_lay.addWidget(self._conn_status)
        self._conn_port = QLabel("No port selected")
        self._conn_port.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        conn_lay.addWidget(self._conn_port)
        grid.addWidget(self._conn_card, 0, 0)

        # Bluetooth card
        self._bt_card = Card(self._main.theme)
        bt_lay = QVBoxLayout(self._bt_card)
        bt_lay.addWidget(QLabel("📡  Bluetooth"))
        self._bt_status_label = QLabel("—")
        self._bt_status_label.setFont(QFont(self._main.theme.typo("font_family"), 12, QFont.Weight.Bold))
        bt_lay.addWidget(self._bt_status_label)
        self._bt_sides = QLabel("Left: ✗   Right: ✗")
        self._bt_sides.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        bt_lay.addWidget(self._bt_sides)
        grid.addWidget(self._bt_card, 0, 1)

        # Battery card
        self._batt_card = Card(self._main.theme)
        batt_lay = QVBoxLayout(self._batt_card)
        batt_lay.addWidget(QLabel("🔋  Battery"))
        self._batt_level = QLabel("—")
        self._batt_level.setFont(QFont(self._main.theme.typo("font_family"), 12, QFont.Weight.Bold))
        batt_lay.addWidget(self._batt_level)
        self._batt_detail = QLabel("Left — | Right —")
        self._batt_detail.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        batt_lay.addWidget(self._batt_detail)
        grid.addWidget(self._batt_card, 0, 2)

        # Latency card
        self._lat_card = Card(self._main.theme)
        lat_lay = QVBoxLayout(self._lat_card)
        lat_lay.addWidget(QLabel("⏱  Latency"))
        self._lat_value = QLabel("— ms")
        self._lat_value.setFont(QFont(self._main.theme.typo("font_family"), 12, QFont.Weight.Bold))
        lat_lay.addWidget(self._lat_value)
        grid.addWidget(self._lat_card, 0, 3)

        self._layout.addLayout(grid)

    # -----------------------------------------------------------------
    def _build_quick_actions(self) -> None:
        group = QGroupBox("Quick Actions")
        lay = QHBoxLayout(group)
        lay.setSpacing(8)

        actions = [
            ("Ping", self._main._cmd_ping),
            ("Read Profile", self._main._cmd_read_profile),
            ("Upload Profile", self._main._cmd_write_profile),
            ("Toggle Overlay", self._main.toggle_overlay),
        ]
        for label, callback in actions:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(callback)
            lay.addWidget(btn)

        self._scan_btn = QPushButton("🔍 Scan for Joy-Con")
        self._scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_btn.clicked.connect(self._main._cmd_bt_scan)
        self._scan_btn.setEnabled(self._main.bridge.is_connected)
        lay.addWidget(self._scan_btn)

        lay.addStretch()
        self._layout.addWidget(group)

    # -----------------------------------------------------------------
    def _build_device_preview(self) -> None:
        group = QGroupBox("Device Preview")
        lay = QVBoxLayout(group)

        self._visualizer = LiveInputVisualizerWidget(self._main)
        lay.addWidget(self._visualizer)
        self._layout.addWidget(group)

    def _build_profile_briefing(self) -> None:
        group = QGroupBox("Active Loadout")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        top = QGridLayout()
        top.setSpacing(12)

        self._slot_card = Card(self._main.theme)
        slot_lay = QVBoxLayout(self._slot_card)
        slot_lay.addWidget(QLabel("🎯  Active Slot"))
        self._slot_label = QLabel("Slot 0")
        self._slot_label.setFont(QFont(self._main.theme.typo("font_family"), 12, QFont.Weight.Bold))
        slot_lay.addWidget(self._slot_label)
        top.addWidget(self._slot_card, 0, 0)

        self._profile_card = Card(self._main.theme)
        profile_lay = QVBoxLayout(self._profile_card)
        profile_lay.addWidget(QLabel("🗂  Loadout"))
        self._profile_name = QLabel("🎒 General")
        self._profile_name.setFont(QFont(self._main.theme.typo("font_family"), 12, QFont.Weight.Bold))
        profile_lay.addWidget(self._profile_name)
        top.addWidget(self._profile_card, 0, 1)

        self._counts_card = Card(self._main.theme)
        counts_lay = QVBoxLayout(self._counts_card)
        counts_lay.addWidget(QLabel("📦  Composition"))
        self._profile_counts = QLabel("0 mapped | 0 macro(s) | 0 layer(s) | 0 chord(s)")
        self._profile_counts.setWordWrap(True)
        self._profile_counts.setFont(QFont(self._main.theme.typo("font_family"), 11, QFont.Weight.Bold))
        counts_lay.addWidget(self._profile_counts)
        top.addWidget(self._counts_card, 0, 2)

        layout.addLayout(top)

        self._profile_details = QLabel()
        self._profile_details.setWordWrap(True)
        self._profile_details.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        layout.addWidget(self._profile_details)

        self._profile_preview = QLabel()
        self._profile_preview.setWordWrap(True)
        layout.addWidget(self._profile_preview)

        self._layout.addWidget(group)
        self._refresh_profile_briefing(self._main._slot, self._main._profile)

    def _refresh_battery_briefing(self) -> None:
        briefing = build_battery_briefing(self._battery_levels)
        self._batt_level.setText(briefing["headline"])
        self._batt_detail.setText(briefing["details"])

    # -----------------------------------------------------------------
    def _build_device_log(self) -> None:
        group = QGroupBox("Device Log")
        lay = QVBoxLayout(group)
        # Re-parent the log widget owned by MainWindow into this group
        log_widget = self._main._log_text
        log_widget.setMinimumHeight(150)
        lay.addWidget(log_widget)
        self._layout.addWidget(group)

    def _refresh_profile_briefing(self, slot: int, profile: dict) -> None:
        briefing = build_profile_briefing(profile, slot)
        self._slot_label.setText(briefing["slot"])
        self._profile_name.setText(briefing["name"])
        self._profile_counts.setText(briefing["counts"])
        self._profile_details.setText(briefing["details"])
        self._profile_preview.setText(briefing["preview"])

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def device_event(self, obj: dict) -> None:
        evt = obj.get("evt")
        self._visualizer.handle_device_event(obj)

        if evt == "bt_status":
            state = str(obj.get("state", "—"))
            self._bt_status_label.setText(state.capitalize())
            left = "✓" if self._main._bt_connected_left else "✗"
            right = "✓" if self._main._bt_connected_right else "✗"
            self._bt_sides.setText(f"Left: {left}   Right: {right}")

        if evt == "battery":
            device_id = obj.get("device_id")
            level = obj.get("level")
            if isinstance(device_id, int) and isinstance(level, int):
                self._battery_levels[device_id] = level
                self._refresh_battery_briefing()

        if obj.get("rsp") == "pong":
            lat = self._main._latency_ms
            if lat is not None:
                self._lat_value.setText(f"{lat:.1f} ms")

    def profile_loaded(self, slot: int, profile: dict) -> None:
        self._refresh_profile_briefing(slot, profile)

    def profile_updated(self, profile: dict) -> None:
        self._refresh_profile_briefing(self._main._slot, profile)

    def connection_changed(self, connected: bool) -> None:
        c = self._main.theme.theme["colors"]
        self._visualizer.connection_changed(connected)
        if connected:
            self._conn_status.setText("Connected")
            self._conn_status.setStyleSheet(f"color: {c['success']};")
            port = self._main._port_combo.currentData() or ""
            self._conn_port.setText(port)
        else:
            self._conn_status.setText("Disconnected")
            self._conn_status.setStyleSheet(f"color: {c['danger']};")
            self._conn_port.setText("No port selected")
            self._battery_levels.clear()
            self._refresh_battery_briefing()
        self._scan_btn.setEnabled(connected)

    def apply_theme(self, theme: ThemeEngine) -> None:
        c = theme.theme["colors"]
        self._visualizer.apply_theme(theme)
        self._profile_details.setStyleSheet(f"color: {theme.color('text_secondary')};")
        self._batt_detail.setStyleSheet(f"color: {theme.color('text_secondary')};")
        self._conn_status.setStyleSheet("")
        if self._main.bridge.is_connected:
            self._conn_status.setText("Connected")
            self._conn_status.setStyleSheet(f"color: {c['success']};")
        else:
            self._conn_status.setText("Disconnected")
            self._conn_status.setStyleSheet(f"color: {c['danger']};")
