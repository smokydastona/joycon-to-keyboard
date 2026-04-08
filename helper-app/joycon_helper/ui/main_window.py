"""Main application window for Bind Bandit (PyQt6 UI).

Provides sidebar navigation, stacked views, connection toolbar, serial log
dock, status bar, and device event dispatch.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import os
import sys

from PyQt6.QtCore import QSettings, QSize, QTimer, Qt
from PyQt6.QtGui import QAction, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDockWidget, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QSizePolicy, QSplitter, QStackedWidget, QSystemTrayIcon,
    QToolBar, QVBoxLayout, QWidget,
)

from .._version import __version__
from ..app_switcher import AppSwitcher, load_rules, save_rules
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

        # Undo / redo (centralized for all profile changes)
        self._undo_stack: List[str] = []
        self._redo_stack: List[str] = []
        self._undo_max = 50
        self._skip_undo = False  # prevents recursion during undo/redo

        # App switcher (foreground-window → profile slot)
        self._app_switcher = AppSwitcher(on_switch=self._on_app_switch_slot)
        rules = load_rules()
        self._app_switcher.set_rules(rules)

        # Persistent settings
        self._settings = QSettings()

        self._setup_window()
        self._build_toolbar()
        self._build_sidebar()
        self._build_views()
        self._build_log_dock()
        self._build_status_bar()
        self._build_shortcuts()
        self._build_tray_icon()
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

        # Right-side spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # Settings
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._open_settings)
        tb.addWidget(settings_btn)

        # Theme toggle
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
        self._notify_views("connection_changed", connected=True)

    def _on_serial_disconnected(self) -> None:
        self._connect_btn.setText("Connect")
        self._connect_btn.setProperty("danger", False)
        self._connect_btn.setProperty("accent", True)
        self._connect_btn.style().unpolish(self._connect_btn)
        self._connect_btn.style().polish(self._connect_btn)
        self._status_bar.set_disconnected()
        self._log_line("[disconnected]")
        # Clear stale key state so overlay/views don't show phantom presses.
        self._active_key_ids.clear()
        self._notify_views("connection_changed", connected=False)

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
                    log.warning("View notification failed: %s on %s",
                                method, type(view).__name__, exc_info=True)

    def _get_hotspot_name(self, key_id: int) -> str:
        for name, _, _ in KEYMAP_HOTSPOTS["dark"]:
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
        self._notify_views("slot_changed", slot=index)

    def _on_app_switch_slot(self, slot: int) -> None:
        """Called from AppSwitcher background thread — marshal to main thread."""
        QTimer.singleShot(0, lambda s=slot: self._apply_app_switch(s))

    def _apply_app_switch(self, slot: int) -> None:
        """Apply profile-slot change triggered by the app switcher."""
        if slot == self._slot:
            return
        self._slot_combo.setCurrentIndex(slot)
        self.send_cmd({"cmd": "set_active_profile", "slot": slot})
        self._cmd_read_profile()
        self._notify_views("slot_changed", slot=slot)
        self._log_line(f"[app-switch] → slot {slot}")

    # -----------------------------------------------------------------
    # Profile access (for views)
    # -----------------------------------------------------------------

    def get_profile(self) -> Dict[str, Any]:
        return self._profile

    def set_profile(self, profile: Dict[str, Any]) -> None:
        if not self._skip_undo and self._profile:
            self._push_undo()
        self._profile = profile
        self._notify_views("profile_updated", profile=profile)
        self._update_undo_ui()

    # -----------------------------------------------------------------
    # Undo / Redo (centralized)
    # -----------------------------------------------------------------

    def _push_undo(self) -> None:
        snapshot = json.dumps(self._profile, ensure_ascii=False)
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self._undo_max:
            self._undo_stack = self._undo_stack[-self._undo_max:]
        self._redo_stack.clear()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        current = json.dumps(self._profile, ensure_ascii=False)
        self._redo_stack.append(current)
        snapshot = self._undo_stack.pop()
        self._skip_undo = True
        self._profile = json.loads(snapshot)
        self._notify_views("profile_updated", profile=self._profile)
        self._skip_undo = False
        self._update_undo_ui()
        # Refresh profiles editor if visible
        pv = self._views[NAV_PROFILES]
        if pv is not None and hasattr(pv, "_refresh_editor"):
            pv._refresh_editor()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        current = json.dumps(self._profile, ensure_ascii=False)
        self._undo_stack.append(current)
        snapshot = self._redo_stack.pop()
        self._skip_undo = True
        self._profile = json.loads(snapshot)
        self._notify_views("profile_updated", profile=self._profile)
        self._skip_undo = False
        self._update_undo_ui()
        pv = self._views[NAV_PROFILES]
        if pv is not None and hasattr(pv, "_refresh_editor"):
            pv._refresh_editor()

    def _update_undo_ui(self) -> None:
        self._status_bar.set_undo_depth(len(self._undo_stack))
        # Update ProfilesView undo/redo buttons if built
        pv = self._views[NAV_PROFILES]
        if pv is not None and hasattr(pv, "_undo_btn"):
            pv._undo_btn.setEnabled(bool(self._undo_stack))
            pv._redo_btn.setEnabled(bool(self._redo_stack))

    # -----------------------------------------------------------------
    # Keyboard shortcuts
    # -----------------------------------------------------------------

    def _build_shortcuts(self) -> None:
        # Undo / Redo
        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self).activated.connect(self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self.redo)

        # Save / Load (device)
        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(
            self._cmd_write_profile
        )
        QShortcut(QKeySequence.StandardKey.Open, self).activated.connect(
            self._cmd_read_profile
        )

        # Save to file
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(
            self._shortcut_save_to_file
        )

        # New profile
        QShortcut(QKeySequence.StandardKey.New, self).activated.connect(
            self._shortcut_new_profile
        )

        # Find (focus search in current view)
        QShortcut(QKeySequence.StandardKey.Find, self).activated.connect(
            self._shortcut_focus_search
        )

        # Ping
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._cmd_ping)

        # Refresh ports
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self._refresh_ports)

        # Navigation: Ctrl+1..7
        for i in range(min(7, len(NAV_ITEMS))):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self).activated.connect(
                lambda idx=i: self._nav_to(idx)
            )

        # Toggle theme
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(self._toggle_theme)

        # Toggle overlay
        QShortcut(QKeySequence("Ctrl+Shift+O"), self).activated.connect(
            self.toggle_overlay
        )

        # Quit
        QShortcut(QKeySequence.StandardKey.Quit, self).activated.connect(
            self._real_quit
        )

    def _nav_to(self, index: int) -> None:
        self._sidebar.set_active(index)
        self._on_nav_changed(index)

    def _shortcut_save_to_file(self) -> None:
        pv = self._views[NAV_PROFILES]
        if pv is None:
            pv = self._ensure_view(NAV_PROFILES)
        if hasattr(pv, "_save_to_file"):
            pv._save_to_file()

    def _shortcut_new_profile(self) -> None:
        from .views.profiles import _default_profile
        self.set_profile(_default_profile())
        pv = self._views[NAV_PROFILES]
        if pv is not None and hasattr(pv, "_refresh_editor"):
            pv._refresh_editor()

    def _shortcut_focus_search(self) -> None:
        view = self._view_stack.currentWidget()
        if view is None:
            return
        # MappingView has _search_input, HelpView has _search
        for attr in ("_search_input", "_search"):
            widget = getattr(view, attr, None)
            if widget is not None:
                widget.setFocus()
                widget.selectAll()
                return

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
        # Called from background thread — marshal to main thread
        QTimer.singleShot(0, lambda: self._apply_update_result(has_update, info))

    def _apply_update_result(self, has_update: bool, info: dict) -> None:
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
        if self._settings.value("minimize_to_tray", False, type=bool) and self._tray_icon.isVisible():
            event.ignore()
            self.hide()
            self._tray_icon.showMessage(
                "Bind Bandit",
                "Running in the background. Right-click the tray icon to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            return
        self._real_quit()
        super().closeEvent(event)

    def _real_quit(self) -> None:
        """Perform full cleanup and quit the application."""
        self._app_switcher.stop()
        # Disconnect bridge signals to avoid callbacks during teardown.
        try:
            self.bridge.connected.disconnect(self._on_serial_connected)
            self.bridge.disconnected.disconnect(self._on_serial_disconnected)
            self.bridge.raw_line.disconnect(self._on_raw_line)
            self.bridge.device_event.disconnect(self._handle_dev_obj)
            self.bridge.connection_error.disconnect(self._on_connection_error)
        except (TypeError, RuntimeError):
            pass  # already disconnected
        if self.bridge.is_connected:
            self.bridge.disconnect_serial()
        if self._overlay and not self._overlay.is_closed:
            self._overlay.close()
        self._tray_icon.hide()
        QApplication.quit()

    # -----------------------------------------------------------------
    # System tray
    # -----------------------------------------------------------------

    def _build_tray_icon(self) -> None:
        self._tray_icon = QSystemTrayIcon(self)
        icon_pm = self.assets.load_icon()
        if icon_pm:
            self._tray_icon.setIcon(QIcon(icon_pm))
        else:
            self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip(f"Bind Bandit v{__version__}")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show / Hide")
        show_action.triggered.connect(self._toggle_visibility)
        tray_menu.addSeparator()
        settings_action = tray_menu.addAction("⚙ Settings")
        settings_action.triggered.connect(self._open_settings)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self._real_quit)
        self._tray_icon.setContextMenu(tray_menu)

        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visibility()

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    # -----------------------------------------------------------------
    # Settings dialog
    # -----------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setMinimumWidth(380)
        layout = QVBoxLayout(dlg)

        form = QFormLayout()
        layout.addLayout(form)

        cb_tray = QCheckBox("Minimize to system tray on close")
        cb_tray.setChecked(self._settings.value("minimize_to_tray", False, type=bool))
        form.addRow(cb_tray)

        cb_start_minimized = QCheckBox("Start minimized to tray")
        cb_start_minimized.setChecked(self._settings.value("start_minimized", False, type=bool))
        form.addRow(cb_start_minimized)

        cb_autostart = QCheckBox("Start with Windows")
        cb_autostart.setChecked(self._is_autostart_enabled())
        form.addRow(cb_autostart)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings.setValue("minimize_to_tray", cb_tray.isChecked())
            self._settings.setValue("start_minimized", cb_start_minimized.isChecked())
            self._set_autostart(cb_autostart.isChecked())

    # -----------------------------------------------------------------
    # Windows auto-start helpers
    # -----------------------------------------------------------------

    _AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _AUTOSTART_VALUE_NAME = "BindBandit"

    def _get_app_executable(self) -> str:
        if getattr(sys, "frozen", False):
            return sys.executable
        # Running from source — use pythonw with module invocation
        return f'"{sys.executable}" -m joycon_helper'

    def _is_autostart_enabled(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._AUTOSTART_REG_KEY, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, self._AUTOSTART_VALUE_NAME)
                return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def _set_autostart(self, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            import winreg
            if enabled:
                exe = self._get_app_executable()
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, self._AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, exe)
            else:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    try:
                        winreg.DeleteValue(key, self._AUTOSTART_VALUE_NAME)
                    except FileNotFoundError:
                        pass
        except OSError:
            log.warning("Failed to update auto-start registry", exc_info=True)
