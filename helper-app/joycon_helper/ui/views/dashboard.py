"""Dashboard view — ESP32 host status, connected-device list, quick actions.

Replaces the old card-grid dashboard.  Content:

* **ESP32 Host** card — serial connection state, firmware version, latency.
* **Connected Devices** list — one card per connected device showing name,
  type icon, battery level and latency.  An "Add Device" button opens the
  :class:`~joycon_helper.ui.widgets.add_device_dialog.AddDeviceDialog`.
* **Quick Actions** bar — Ping, Toggle Overlay.
* **Device Log** — re-uses the MainWindow log widget (read-only).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import ThemeEngine
from ..widgets.card import Card

if TYPE_CHECKING:
    from ...device_cache import DeviceEntry
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.dashboard")

# ---------------------------------------------------------------------------
# Battery helpers
# ---------------------------------------------------------------------------

_BATTERY_BARS = ["▂___", "▂▂__", "▂▂▂_", "▂▂▂▂", "████"]
_BATTERY_COLORS = ["#ff4444", "#ff8800", "#ffcc00", "#88dd00", "#44cc44"]


def _battery_text(level: int | None) -> tuple[str, str]:
    """Return (text, colour) for a battery level 0-4 or None."""
    if level is None:
        return "—", ""
    level = max(0, min(4, level))
    return _BATTERY_BARS[level], _BATTERY_COLORS[level]


# ---------------------------------------------------------------------------
# Per-device card widget
# ---------------------------------------------------------------------------

class _DeviceCard(Card):
    """Compact card showing one connected device's status."""

    _TYPE_ICONS: ClassVar[dict[str, str]] = {
        "joycon": "🎮",
        "m913":   "🖱",
        "razer":  "🐍",
    }

    def __init__(self, entry: DeviceEntry, main: MainWindow) -> None:
        super().__init__(main.theme)
        self._entry = entry
        self._main = main

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)

        # Icon + name block
        info_col = QVBoxLayout()
        icon = self._TYPE_ICONS.get(entry.type, "📦")
        name_label = QLabel(f"{icon}  {entry.name}")
        name_label.setFont(QFont(main.theme.typo("font_family"), 11, QFont.Weight.Bold))
        info_col.addWidget(name_label)

        src_text = "ESP32 Bluetooth" if entry.source == "esp32-bt" else "PC USB"
        if entry.bda:
            src_text += f"  ·  {entry.bda}"
        detail = QLabel(src_text)
        detail.setStyleSheet(f"color: {main.theme.color('text_secondary')};")
        info_col.addWidget(detail)
        lay.addLayout(info_col, 1)

        # Battery
        batt_col = QVBoxLayout()
        batt_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._batt_label = QLabel("—")
        self._batt_label.setFont(QFont(main.theme.typo("mono_family"), 10))
        self._batt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        batt_col.addWidget(QLabel("Battery"))
        batt_col.addWidget(self._batt_label)
        lay.addLayout(batt_col)

        # Latency (BT devices only)
        if entry.source == "esp32-bt":
            lat_col = QVBoxLayout()
            lat_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._latency_label: QLabel | None = QLabel("— ms")
            self._latency_label.setFont(QFont(main.theme.typo("mono_family"), 10))
            self._latency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lat_col.addWidget(QLabel("Latency"))
            lat_col.addWidget(self._latency_label)
            lay.addLayout(lat_col)
        else:
            self._latency_label = None

        # Configure button
        cfg_btn = QPushButton("Configure")
        cfg_btn.setFixedWidth(90)
        cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cfg_btn.clicked.connect(self._go_configure)
        lay.addWidget(cfg_btn)

        self._refresh_battery()

    def _go_configure(self) -> None:
        from ..main_window import NAV_DEVICES
        dv = self._main._views[NAV_DEVICES]
        if dv is not None and hasattr(dv, "select_device"):
            dv.select_device(self._entry.id)
        self._main._nav_to(NAV_DEVICES)

    def _refresh_battery(self) -> None:
        text, color = _battery_text(self._entry.battery)
        self._batt_label.setText(text)
        if color:
            self._batt_label.setStyleSheet(f"color: {color};")
        else:
            self._batt_label.setStyleSheet("")

    def update_battery(self, level: int) -> None:
        self._entry.battery = level
        self._refresh_battery()

    def update_latency(self, latency_ms: float) -> None:
        self._entry.latency_ms = latency_ms
        if self._latency_label is not None:
            self._latency_label.setText(f"{latency_ms:.1f} ms")


# ---------------------------------------------------------------------------
# DashboardView
# ---------------------------------------------------------------------------

class DashboardView(QScrollArea):
    """Dashboard: ESP32 status, connected devices, quick actions, device log."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main
        self._device_cards: dict[str, _DeviceCard] = {}  # device_id → card

        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(16)
        self.setWidget(container)

        self._build_header()
        self._build_esp32_status()
        self._build_connected_devices()
        self._build_quick_actions()
        self._build_device_log()
        self._layout.addStretch()

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = QLabel("Mission Control")
        header.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        self._layout.addWidget(header)
        subtitle = QLabel("Device status and connections")
        subtitle.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        self._layout.addWidget(subtitle)

    def _build_esp32_status(self) -> None:
        group = QGroupBox("ESP32 Host")
        row = QHBoxLayout(group)
        row.setSpacing(24)

        # Connection indicator
        conn_col = QVBoxLayout()
        conn_col.addWidget(QLabel("🔌  Serial"))
        self._conn_status = QLabel("Disconnected")
        self._conn_status.setFont(QFont(
            self._main.theme.typo("font_family"), 11, QFont.Weight.Bold))
        conn_col.addWidget(self._conn_status)
        self._conn_port = QLabel("No port selected")
        self._conn_port.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        conn_col.addWidget(self._conn_port)
        row.addLayout(conn_col)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        row.addWidget(sep)

        # Firmware version
        fw_col = QVBoxLayout()
        fw_col.addWidget(QLabel("💾  Firmware"))
        self._fw_version = QLabel("—")
        self._fw_version.setFont(QFont(
            self._main.theme.typo("font_family"), 11, QFont.Weight.Bold))
        fw_col.addWidget(self._fw_version)
        row.addLayout(fw_col)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        row.addWidget(sep2)

        # Latency
        lat_col = QVBoxLayout()
        lat_col.addWidget(QLabel("⏱  Latency"))
        self._lat_value = QLabel("— ms")
        self._lat_value.setFont(QFont(
            self._main.theme.typo("font_family"), 11, QFont.Weight.Bold))
        lat_col.addWidget(self._lat_value)
        row.addLayout(lat_col)

        row.addStretch()
        self._layout.addWidget(group)

    def _build_connected_devices(self) -> None:
        header_row = QHBoxLayout()
        grp_label = QLabel("Connected Devices")
        grp_label.setFont(QFont(
            self._main.theme.typo("font_family"), 12, QFont.Weight.Bold))
        header_row.addWidget(grp_label)
        header_row.addStretch()
        add_btn = QPushButton("＋  Add Device")
        add_btn.setProperty("accent", True)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._open_add_device)
        header_row.addWidget(add_btn)
        self._layout.addLayout(header_row)

        # Container for device cards (populated dynamically)
        self._devices_container = QWidget()
        self._devices_layout = QVBoxLayout(self._devices_container)
        self._devices_layout.setContentsMargins(0, 0, 0, 0)
        self._devices_layout.setSpacing(8)

        self._empty_label = QLabel("No devices connected.  Press  ＋ Add Device  to connect.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {self._main.theme.color('text_secondary')}; "
            "padding: 24px;"
        )
        self._devices_layout.addWidget(self._empty_label)
        self._layout.addWidget(self._devices_container)

    def _build_quick_actions(self) -> None:
        group = QGroupBox("Quick Actions")
        lay = QHBoxLayout(group)
        lay.setSpacing(8)

        for label, cb in [
            ("Ping", self._main._cmd_ping),
            ("Toggle Overlay", self._main.toggle_overlay),
        ]:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(cb)
            lay.addWidget(btn)

        lay.addStretch()
        self._layout.addWidget(group)

    def _build_device_log(self) -> None:
        group = QGroupBox("Device Log")
        lay = QVBoxLayout(group)
        log_widget = self._main._log_text
        log_widget.setMinimumHeight(150)
        lay.addWidget(log_widget)
        self._layout.addWidget(group)

    # ------------------------------------------------------------------
    # Add Device dialog
    # ------------------------------------------------------------------

    def _open_add_device(self) -> None:
        from ..widgets.add_device_dialog import AddDeviceDialog
        dlg = AddDeviceDialog(self._main, self._main._device_cache)
        dlg.device_added.connect(self._on_device_added_via_dialog)
        self._main._add_device_dialog = dlg
        dlg.exec()
        self._main._add_device_dialog = None

    def _on_device_added_via_dialog(self, entry: DeviceEntry) -> None:
        entry.connected = True
        self._main._device_cache.mark_connected(entry.id, True)
        self._main._connected_devices[entry.id] = entry
        self._add_or_update_card(entry)
        self._main._notify_views("device_connected", entry=entry)

    # ------------------------------------------------------------------
    # Device card management
    # ------------------------------------------------------------------

    def _add_or_update_card(self, entry: DeviceEntry) -> None:
        if entry.id in self._device_cards:
            return
        self._empty_label.setVisible(False)
        card = _DeviceCard(entry, self._main)
        self._device_cards[entry.id] = card
        self._devices_layout.addWidget(card)

    def _remove_card(self, device_id: str) -> None:
        card = self._device_cards.pop(device_id, None)
        if card is not None:
            self._devices_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        if not self._device_cards:
            self._empty_label.setVisible(True)

    # ------------------------------------------------------------------
    # View protocol (called by MainWindow._notify_views)
    # ------------------------------------------------------------------

    def device_connected(self, entry: DeviceEntry) -> None:
        self._add_or_update_card(entry)

    def device_disconnected(self, device_id: str) -> None:
        self._remove_card(device_id)

    def device_event(self, obj: dict) -> None:
        evt = obj.get("evt")

        if evt == "battery":
            device_id_int = obj.get("device_id")
            level = obj.get("level")
            if not isinstance(device_id_int, int) or not isinstance(level, int):
                return
            side = "R" if device_id_int == 1 else "L"
            cache_id = f"joycon-{side}"
            card = self._device_cards.get(cache_id)
            if card:
                card.update_battery(level)

        elif obj.get("rsp") == "pong":
            lat = self._main._latency_ms
            if lat is not None:
                self._lat_value.setText(f"{lat:.1f} ms")
                for card in self._device_cards.values():
                    if card._entry.source == "esp32-bt":
                        card.update_latency(lat)

        if obj.get("rsp") == "fw_version" and obj.get("ok") and obj.get("board") == "esp32s3":
                self._fw_version.setText(obj.get("version", "—"))

    def connection_changed(self, connected: bool) -> None:
        c = self._main.theme.theme["colors"]
        if connected:
            self._conn_status.setText("Connected")
            self._conn_status.setStyleSheet(f"color: {c['success']};")
            port = self._main._port_combo.currentData() or ""
            self._conn_port.setText(port)
            self._main.send_cmd({"cmd": "fw_version"})
        else:
            self._conn_status.setText("Disconnected")
            self._conn_status.setStyleSheet(f"color: {c['danger']};")
            self._conn_port.setText("No port selected")
            self._fw_version.setText("—")
            self._lat_value.setText("— ms")
            for did in list(self._device_cards):
                self._remove_card(did)

    def apply_theme(self, theme: ThemeEngine) -> None:
        c = theme.theme["colors"]
        self._conn_port.setStyleSheet(f"color: {theme.color('text_secondary')};")
        self._empty_label.setStyleSheet(
            f"color: {theme.color('text_secondary')}; padding: 24px;"
        )
        if self._main.bridge.is_connected:
            self._conn_status.setStyleSheet(f"color: {c['success']};")
        else:
            self._conn_status.setStyleSheet(f"color: {c['danger']};")
