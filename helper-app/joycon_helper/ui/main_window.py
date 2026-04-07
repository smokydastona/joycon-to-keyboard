"""Main application window for Bind Bandit (PyQt6 UI).

Provides sidebar navigation, stacked views, connection toolbar, serial log
dock, status bar, and device event dispatch.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtGui import QAction, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDockWidget, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
)

from .._version import __version__
from ..serial_client import SerialClient
from .assets import AssetManager
from .constants import KEYMAP_HOTSPOTS, KBD_HOTSPOTS
from .serial_bridge import SerialBridge
from .theme import ThemeEngine
from .widgets.overlay_window import OverlayWindow
from .widgets.sidebar import SidebarWidget
from .widgets.status_bar import AppStatusBar

log = logging.getLogger("joycon_helper.ui.main_window")

# Navigation section indices
NAV_DASHBOARD = 0
NAV_MAPPING = 1
NAV_MACROS = 2
NAV_PROFILES = 3
NAV_DEVICES = 4
NAV_DIAGNOSTICS = 5
NAV_HELP = 6

# Navigation item definitions: (icon_char, label)
NAV_ITEMS = [
    ("🏠", "Dashboard"),
    ("🎮", "Mapping"),
    ("⚡", "Macros & Stick"),
    ("💾", "Profiles"),
    ("🖱", "Devices"),
    ("🔧", "Diagnostics"),
    ("❓", "Help"),
]


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self) -> None:
        super().__init__()

        # Core services
        self.theme = ThemeEngine()
        self.assets = AssetManager("dark" if self.theme.is_dark else "default")
        self.bridge = SerialBridge(self)

        # Application state
        self._profile: Dict[str, Any] = {}
        self._slot = 0
        self._bt_status = ""
        self._battery_level: Optional[int] = None
        self._latency_ms: Optional[float] = None
        self._ping_sent_time: Optional[float] = None
        self._overlay: Optional[OverlayWindow] = None
        self._active_key_ids: set = set()
        self._bt_connected_left = False
        self._bt_connected_right = False

        self._setup_window()
        self._build_toolbar()
        self._build_sidebar()
        self._build_views()
        self._build_log_dock()
        self._build_status_bar()
        self._connect_signals()
        self._apply_theme()

        # Refresh ports on startup
        QTimer.singleShot(200, self._refresh_ports)

        # Auto-update check
        try:
            from ..updater import check_for_update_async
            check_for_update_async(self._on_update_result)
        except Exception:
            pass

        log.info("MainWindow initialized (v%s)", __version__)

    # -----------------------------------------------------------------
    # Window setup
    # -----------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle(f"Bind Bandit v{__version__}")
        self.setMinimumSize(1200, 800)
        self.resize(1440, 900)

        icon_pm = self.assets.load_icon()
        if icon_pm:
            self.setWindowIcon(QIcon(icon_pm))

    # -----------------------------------------------------------------
    # Connection toolbar
    # -----------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Connection", self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setObjectName("ConnectionToolbar")
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # Port
        port_label = QLabel("  Port: ")
        tb.addWidget(port_label)
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(200)
        self._port_combo.setEditable(False)
        tb.addWidget(self._port_combo)

        # Refresh
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh_ports)
        tb.addWidget(self._refresh_btn)

        tb.addSeparator()

        # Baud
        baud_label = QLabel(" Baud: ")
        tb.addWidget(baud_label)
        self._baud_edit = QLineEdit("115200")
        self._baud_edit.setFixedWidth(80)
        tb.addWidget(self._baud_edit)

        tb.addSeparator()

        # Connect/Disconnect
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setProperty("accent", True)
        self._connect_btn.clicked.connect(self._toggle_connect)
        tb.addWidget(self._connect_btn)

        tb.addSeparator()

        # Slot selector
        slot_label = QLabel(" Slot: ")
        tb.addWidget(slot_label)
        self._slot_combo = QComboBox()
        self._slot_combo.addItems(["0", "1", "2", "3"])
        self._slot_combo.setFixedWidth(60)
        self._slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        tb.addWidget(self._slot_combo)

        # Quick actions
        tb.addSeparator()
        self._ping_btn = QPushButton("Ping")
        self._ping_btn.clicked.connect(self._cmd_ping)
        tb.addWidget(self._ping_btn)

        self._upload_btn = QPushButton("Upload")
        self._upload_btn.clicked.connect(self._cmd_write_profile)
        tb.addWidget(self._upload_btn)

        self._read_btn = QPushButton("Read")
        self._read_btn.clicked.connect(self._cmd_read_profile)
        tb.addWidget(self._read_btn)

        # Theme toggle
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._theme_btn = QPushButton("🌙" if self.theme.is_dark else "☀")
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.setToolTip("Toggle light/dark theme")
        self._theme_btn.clicked.connect(self._toggle_theme)
        tb.addWidget(self._theme_btn)

        # Update button (hidden until update available)
        self._update_btn = QPushButton(" ↑ Update ")
        self._update_btn.setProperty("accent", True)
        self._update_btn.setVisible(False)
        self._update_btn.clicked.connect(self._open_update_dialog)
        tb.addWidget(self._update_btn)

    # -----------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------

    def _build_sidebar(self) -> None:
        self._sidebar = SidebarWidget(self.theme, self)
        for icon, label in NAV_ITEMS:
            self._sidebar.add_nav_item(icon, label)
        self._sidebar.set_version(__version__)
        self._sidebar.nav_clicked.connect(self._on_nav_changed)

    # -----------------------------------------------------------------
    # Stacked views
    # -----------------------------------------------------------------

    def _build_views(self) -> None:
        # Central widget: sidebar + stacked views
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._sidebar)

        self._view_stack = QStackedWidget()
        layout.addWidget(self._view_stack)

        # Lazy-load views
        self._views: List[Optional[QWidget]] = [None] * len(NAV_ITEMS)
        self._views_built: List[bool] = [False] * len(NAV_ITEMS)

        # Build dashboard eagerly
        self._ensure_view(NAV_DASHBOARD)
        self._sidebar.set_active(NAV_DASHBOARD)

    def _ensure_view(self, index: int) -> QWidget:
        if self._views[index] is not None:
            return self._views[index]

        view: QWidget
        if index == NAV_DASHBOARD:
            from .views.dashboard import DashboardView
            view = DashboardView(self)
        elif index == NAV_MAPPING:
            from .views.mapping import MappingView
            view = MappingView(self)
        elif index == NAV_MACROS:
            from .views.macros import MacrosView
            view = MacrosView(self)
        elif index == NAV_PROFILES:
            from .views.profiles import ProfilesView
            view = ProfilesView(self)
        elif index == NAV_DEVICES:
            from .views.devices import DevicesView
            view = DevicesView(self)
        elif index == NAV_DIAGNOSTICS:
            from .views.diagnostics import DiagnosticsView
            view = DiagnosticsView(self)
        elif index == NAV_HELP:
            from .views.help_view import HelpView
            view = HelpView(self)
        else:
            view = QWidget()

        self._views[index] = view
        self._view_stack.addWidget(view)
        return view

    # -----------------------------------------------------------------
    # Log dock
    # -----------------------------------------------------------------

    def _build_log_dock(self) -> None:
        dock = QDockWidget("Device Log", self)
        dock.setObjectName("LogDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(2000)
        self._log_text.setFont(QFont(
            self.theme.typo("mono_family"), self.theme.typo("mono_size")
        ))
        dock.setWidget(self._log_text)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    # -----------------------------------------------------------------
    # Status bar
    # -----------------------------------------------------------------

    def _build_status_bar(self) -> None:
        self._status_bar = AppStatusBar(self.theme, self)
        self.setStatusBar(self._status_bar)

    # -----------------------------------------------------------------
    # Signal wiring
    # -----------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.bridge.connected.connect(self._on_serial_connected)
        self.bridge.disconnected.connect(self._on_serial_disconnected)
        self.bridge.raw_line.connect(self._on_raw_line)
        self.bridge.device_event.connect(self._handle_dev_obj)
        self.bridge.connection_error.connect(self._on_connection_error)

    # -----------------------------------------------------------------
    # Serial connection
    # -----------------------------------------------------------------

    def _refresh_ports(self) -> None:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        self._port_combo.clear()
        for p in ports:
            self._port_combo.addItem(f"{p.device} — {p.description}", p.device)

    def _toggle_connect(self) -> None:
        if self.bridge.is_connected:
            self.bridge.disconnect_serial()
        else:
            port = self._port_combo.currentData()
            if not port:
                QMessageBox.warning(self, "No Port", "Select a serial port first.")
                return
            try:
                baud = int(self._baud_edit.text())
            except ValueError:
                baud = 115200
            self.bridge.connect_serial(port, baud)

    def _on_serial_connected(self) -> None:
        self._connect_btn.setText("Disconnect")
        self._connect_btn.setProperty("danger", True)
        self._connect_btn.setProperty("accent", False)
        self._connect_btn.style().unpolish(self._connect_btn)
        self._connect_btn.style().polish(self._connect_btn)
        self._status_bar.set_connected(self._port_combo.currentData() or "")
        self._log_line("[connected]")

    def _on_serial_disconnected(self) -> None:
        self._connect_btn.setText("Connect")
        self._connect_btn.setProperty("danger", False)
        self._connect_btn.setProperty("accent", True)
        self._connect_btn.style().unpolish(self._connect_btn)
        self._connect_btn.style().polish(self._connect_btn)
        self._status_bar.set_disconnected()
        self._log_line("[disconnected]")

    def _on_connection_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Connection Error", msg)

    def _on_raw_line(self, line: str) -> None:
        self._log_line(f"[rx] {line}")

    # -----------------------------------------------------------------
    # Device event dispatch
    # -----------------------------------------------------------------

    def _handle_dev_obj(self, obj: dict) -> None:
        """Central device event dispatcher — mirrors app.py _handle_dev_obj."""
        evt = obj.get("evt")
        rsp = obj.get("rsp")

        # Pong → latency
        if rsp == "pong":
            if self._ping_sent_time is not None:
                rtt = (time.monotonic() - self._ping_sent_time) * 1000
                self._latency_ms = rtt
                self._ping_sent_time = None
                self._status_bar.set_latency(rtt)

        # Read profile response
        if rsp == "read_profile":
            slot = obj.get("slot")
            profile = obj.get("profile")
            if isinstance(slot, int) and isinstance(profile, dict):
                self._profile = profile
                self._notify_views("profile_loaded", slot=slot, profile=profile)

        # Battery
        if evt == "battery":
            try:
                level = int(obj.get("level", -1))
                if 0 <= level <= 4:
                    self._battery_level = level
                    self._status_bar.set_battery(level)
            except (ValueError, TypeError):
                pass

        # BT status
        if evt == "bt_status":
            state = str(obj.get("state", "-"))
            name = obj.get("name")
            bda = obj.get("bda")
            self._bt_status = state
            if state == "connected":
                side = None
                if isinstance(name, str):
                    if "(L)" in name:
                        side = "L"
                    elif "(R)" in name:
                        side = "R"
                if side == "L":
                    self._bt_connected_left = True
                elif side == "R":
                    self._bt_connected_right = True
            elif state == "disconnected":
                self._bt_connected_left = False
                self._bt_connected_right = False
                self._battery_level = None

        # Mapped key events
        if evt == "mapped_key":
            try:
                pressed = bool(obj.get("pressed"))
                key_id = int(obj.get("key_id"))
            except Exception:
                return
            if pressed:
                self._active_key_ids.add(key_id)
            else:
                self._active_key_ids.discard(key_id)

            if self._overlay and not self._overlay.is_closed:
                name = self._get_hotspot_name(key_id)
                self._overlay.set_last_key(pressed, name)

        # Macro
        if evt == "macro":
            macro_id = str(obj.get("id", ""))
            state = str(obj.get("state", ""))
            if self._overlay and not self._overlay.is_closed:
                self._overlay.set_macro(macro_id, state)

        # Forward to all active views
        self._notify_views("device_event", obj=obj)

    def _notify_views(self, method: str, **kwargs: Any) -> None:
        for view in self._views:
            if view is not None and hasattr(view, method):
                try:
                    getattr(view, method)(**kwargs)
                except Exception:
                    log.debug("View notification failed: %s", method, exc_info=True)

    def _get_hotspot_name(self, key_id: int) -> str:
        for name, _, _ in KEYMAP_HOTSPOTS:
            from .constants import KBD_LABEL_TO_KEYCODE
            for lbl, code in KBD_LABEL_TO_KEYCODE.items():
                if code == key_id:
                    return lbl
        return f"key_{key_id}"

    # -----------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------

    def send_cmd(self, obj: dict) -> None:
        self.bridge.send_cmd(obj)
        self._log_line(f"[tx] {json.dumps(obj, ensure_ascii=False)}")

    def _cmd_ping(self) -> None:
        self._ping_sent_time = time.monotonic()
        self.send_cmd({"cmd": "ping"})

    def _cmd_write_profile(self) -> None:
        if not self._profile:
            QMessageBox.warning(self, "No Profile", "Load or create a profile first.")
            return
        slot = int(self._slot_combo.currentText())
        self.send_cmd({"cmd": "write_profile", "slot": slot, "profile": self._profile})

    def _cmd_read_profile(self) -> None:
        slot = int(self._slot_combo.currentText())
        self.send_cmd({"cmd": "read_profile", "slot": slot})

    def _on_slot_changed(self, index: int) -> None:
        self._slot = index
        self._status_bar.set_slot(index)

    # -----------------------------------------------------------------
    # Profile access (for views)
    # -----------------------------------------------------------------

    def get_profile(self) -> Dict[str, Any]:
        return self._profile

    def set_profile(self, profile: Dict[str, Any]) -> None:
        self._profile = profile
        self._notify_views("profile_updated", profile=profile)

    # -----------------------------------------------------------------
    # Theme
    # -----------------------------------------------------------------

    def _toggle_theme(self) -> None:
        self.theme.toggle()
        theme_name = "dark" if self.theme.is_dark else "default"
        self.assets.set_theme(theme_name)
        self._theme_btn.setText("🌙" if self.theme.is_dark else "☀")
        self._apply_theme()

    def _apply_theme(self) -> None:
        qss = self.theme.generate_qss()
        self.setStyleSheet(qss)
        self._sidebar.apply_theme(self.theme)
        self._status_bar.apply_theme(self.theme)

        # Update log font
        self._log_text.setFont(QFont(
            self.theme.typo("mono_family"), self.theme.typo("mono_size")
        ))

        # Notify views
        for view in self._views:
            if view is not None and hasattr(view, "apply_theme"):
                view.apply_theme(self.theme)

    # -----------------------------------------------------------------
    # Overlay
    # -----------------------------------------------------------------

    def toggle_overlay(self) -> None:
        if self._overlay and not self._overlay.is_closed:
            self._overlay.close()
            self._overlay = None
        else:
            self._overlay = OverlayWindow(self.theme)
            self._overlay.set_slot(self._slot)
            self._overlay.show()

    # -----------------------------------------------------------------
    # Navigation
    # -----------------------------------------------------------------

    def _on_nav_changed(self, index: int) -> None:
        view = self._ensure_view(index)
        self._view_stack.setCurrentWidget(view)

    # -----------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------

    def _log_line(self, text: str) -> None:
        self._log_text.appendPlainText(text)

    # -----------------------------------------------------------------
    # Update
    # -----------------------------------------------------------------

    def _on_update_result(self, has_update: bool, info: dict) -> None:
        if has_update:
            self._update_btn.setVisible(True)
            self._update_info = info

    def _open_update_dialog(self) -> None:
        info = getattr(self, "_update_info", {})
        version = info.get("version", "?")
        url = info.get("url", "")
        QMessageBox.information(
            self, "Update Available",
            f"Version {version} is available.\n\n"
            f"Download: {url}" if url else f"Version {version} is available."
        )

    # -----------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------

    def closeEvent(self, event: Any) -> None:
        if self.bridge.is_connected:
            self.bridge.disconnect_serial()
        if self._overlay and not self._overlay.is_closed:
            self._overlay.close()
        super().closeEvent(event)
