"""Main application window for Bind Bandit (PyQt6 UI).

Provides sidebar navigation, stacked views, connection toolbar, serial log
dock, status bar, and device event dispatch.
"""
from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
from typing import Any

from PyQt6.QtCore import QSettings, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .._version import __version__
from ..app_switcher import AppSwitcher, load_rules
from ..default_profiles import get_default_profile
from .assets import AssetManager
from .constants import KEYMAP_HOTSPOTS
from .serial_bridge import SerialBridge
from .theme import ThemeEngine
from .widgets.onboarding import OnboardingWizard, should_show_onboarding
from .widgets.overlay_window import OverlayWindow
from .widgets.sidebar import SidebarWidget
from .widgets.status_bar import AppStatusBar
from .widgets.toast import Toast

log = logging.getLogger("joycon_helper.ui.main_window")

# Navigation section indices
NAV_DASHBOARD = 0
NAV_MAPPING = 1
NAV_MACROS = 2
NAV_PROFILES = 3
NAV_DEVICES = 4
NAV_DIAGNOSTICS = 5
NAV_HELP = 6
NAV_SETTINGS = 7
NAV_GYRO_ZONES = 8

# Navigation item definitions: (icon_char, label)
NAV_ITEMS = [
    ("🏠", "Mission Control"),
    ("🎮", "Blueprint Layout"),
    ("⚡", "Operation Scripts"),
    ("💾", "Crew Loadouts"),
    ("🖱", "Target Assets"),
    ("🔧", "Forensics"),
    ("❓", "Help"),
    ("⚙", "Safehouse Config"),
    ("🎯", "Motion Grid"),
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
        self._profile: dict[str, Any] = get_default_profile(0)
        self._slot = 0
        self._bt_status = ""
        self._battery_level: int | None = None
        self._latency_ms: float | None = None
        self._ping_sent_time: float | None = None
        self._overlay: OverlayWindow | None = None
        self._active_key_ids: set = set()
        self._bt_connected_left = False
        self._bt_connected_right = False

        # Undo / redo (centralized for all profile changes)
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []
        self._undo_max = 50
        self._skip_undo = False  # prevents recursion during undo/redo

        # Debounced auto-save: uploads profile to device after 2 s of inactivity
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(2000)
        self._autosave_timer.timeout.connect(self._auto_upload_profile)

        # App switcher (foreground-window → profile slot)
        self._app_switcher = AppSwitcher(on_switch=self._on_app_switch_slot)
        rules = load_rules()
        self._app_switcher.set_rules(rules)

        # Persistent settings
        self._settings = QSettings()

        self._setup_window()
        self._build_toolbar()
        self._build_sidebar()
        self._build_log_widget()
        self._build_views()
        self._build_status_bar()
        self._build_shortcuts()
        self._build_tray_icon()
        self._connect_signals()
        self._apply_theme()

        # Refresh ports on startup
        QTimer.singleShot(200, self._refresh_ports)

        # First-run onboarding wizard
        if should_show_onboarding():
            QTimer.singleShot(500, self._show_onboarding)

        # Auto-update check
        try:
            from ..updater import check_for_update_async
            check_for_update_async(self._on_update_result)
        except Exception:
            pass

        # Pending firmware (downloaded during last app update)
        QTimer.singleShot(1500, self._check_pending_firmware)

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
        self._port_combo.setToolTip("Select the COM port for your ESP32-S3 USB bridge")
        tb.addWidget(self._port_combo)

        # Refresh
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip("Rescan available serial ports")
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
        self._connect_btn.setToolTip("Connect or disconnect the serial link to the ESP32-S3")
        self._connect_btn.clicked.connect(self._toggle_connect)
        tb.addWidget(self._connect_btn)

        tb.addSeparator()

        # Slot selector
        slot_label = QLabel(" Slot: ")
        tb.addWidget(slot_label)
        self._slot_combo = QComboBox()
        self._slot_combo.addItems(["0", "1", "2", "3"])
        self._slot_combo.setFixedWidth(60)
        self._slot_combo.setToolTip("Active profile slot (0–3) — each slot stores an independent key mapping")
        self._slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        tb.addWidget(self._slot_combo)

        # Quick actions
        tb.addSeparator()
        self._ping_btn = QPushButton("Ping")
        self._ping_btn.setToolTip("Send a ping to the device and measure round-trip latency")
        self._ping_btn.clicked.connect(self._cmd_ping)
        tb.addWidget(self._ping_btn)

        self._upload_btn = QPushButton("Upload")
        self._upload_btn.setToolTip("Write the current profile to the selected slot on the device")
        self._upload_btn.clicked.connect(self._cmd_write_profile)
        tb.addWidget(self._upload_btn)

        self._read_btn = QPushButton("Read")
        self._read_btn.setToolTip("Read the profile stored in the selected slot from the device")
        self._read_btn.clicked.connect(self._cmd_read_profile)
        tb.addWidget(self._read_btn)

        # Right-side spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # Settings
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setToolTip("Settings (Ctrl+8)")
        settings_btn.clicked.connect(lambda: self._nav_to(NAV_SETTINGS))
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
        self._update_btn.setToolTip("A new version of Bind Bandit is available — click for details")
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
        self._sidebar.update_clicked.connect(self._do_full_update)

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
        self._views: list[QWidget | None] = [None] * len(NAV_ITEMS)
        self._views_built: list[bool] = [False] * len(NAV_ITEMS)

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
        elif index == NAV_SETTINGS:
            from .views.settings import SettingsView
            view = SettingsView(self)
        elif index == NAV_GYRO_ZONES:
            from .views.gyro_zones import GyroZonesView
            view = GyroZonesView(self)
        else:
            view = QWidget()

        self._views[index] = view
        self._view_stack.addWidget(view)
        return view

    # -----------------------------------------------------------------
    # Device log widget (embedded in Dashboard)
    # -----------------------------------------------------------------

    def _build_log_widget(self) -> None:
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(2000)
        self._log_text.setFont(QFont(
            self.theme.typo("mono_family"), self.theme.typo("mono_size")
        ))

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
                Toast.warning(self, "Select a serial port first.")
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
        Toast.success(self, f"Connected to {self._port_combo.currentData() or 'device'}")
        self._notify_views("connection_changed", connected=True)

    def _on_serial_disconnected(self) -> None:
        self._connect_btn.setText("Connect")
        self._connect_btn.setProperty("danger", False)
        self._connect_btn.setProperty("accent", True)
        self._connect_btn.style().unpolish(self._connect_btn)
        self._connect_btn.style().polish(self._connect_btn)
        self._status_bar.set_disconnected()
        self._log_line("[disconnected]")
        Toast.info(self, "Serial disconnected")
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
        if rsp == "pong" and self._ping_sent_time is not None:
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
        for _name, _, _ in KEYMAP_HOTSPOTS["dark"]:
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
            Toast.warning(self, "Load or create a profile first.")
            return
        slot = int(self._slot_combo.currentText())
        self.send_cmd({"cmd": "write_profile", "slot": slot, "profile": self._profile})

    def _auto_upload_profile(self) -> None:
        """Debounced auto-upload: sends the current profile to the device."""
        if self._profile and self.bridge.is_connected:
            slot = int(self._slot_combo.currentText())
            log.debug("Auto-saving profile to slot %d", slot)
            self.send_cmd({"cmd": "write_profile", "slot": slot,
                           "profile": self._profile})

    def _cmd_read_profile(self) -> None:
        slot = int(self._slot_combo.currentText())
        self.send_cmd({"cmd": "read_profile", "slot": slot})

    def _cmd_bt_scan(self) -> None:
        """Tell ESP32-S3 to command the ESP32 BT host to start Joy-Con discovery."""
        self.send_cmd({"cmd": "bt_connect"})

    def _on_slot_changed(self, index: int) -> None:
        self._slot = index
        self._status_bar.set_slot(index)
        # When no device is connected, load the built-in default for this slot
        if not self.bridge.is_connected:
            self.set_profile(get_default_profile(index))
        self._notify_views("slot_changed", slot=index)
        self._update_tray_slot_checks()

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

    def get_profile(self) -> dict[str, Any]:
        return self._profile

    def set_profile(self, profile: dict[str, Any]) -> None:
        if not self._skip_undo and self._profile:
            self._push_undo()
        self._profile = profile
        self._notify_views("profile_updated", profile=profile)
        self._update_undo_ui()
        # Restart auto-save timer (debounced — waits for 2 s of inactivity)
        if self.bridge.is_connected:
            self._autosave_timer.start()

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

        # Navigation: Ctrl+1..8
        for i in range(min(8, len(NAV_ITEMS))):
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

    def _set_theme_mode(self, mode: str) -> None:
        """Switch to a named theme ("light" or "dark") and refresh the UI."""
        self.theme.set_mode(mode)
        asset_variant = "dark" if self.theme.is_dark else "default"
        self.assets.set_theme(asset_variant)
        self._theme_btn.setText("🌙" if self.theme.is_dark else "☀")
        self._apply_theme()

    def _toggle_theme(self) -> None:
        self.theme.toggle()
        self._set_theme_mode(self.theme.mode_name)

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
            self._overlay.set_profile_name(self._profile.get("name", ""))
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
            self._update_info = info
            version = info.get("version", "?")
            # Toolbar button (legacy)
            self._update_btn.setVisible(True)
            # Sidebar button
            self._sidebar.show_update_button(version)

    def _do_full_update(self) -> None:
        """Download firmware assets + new exe, then relaunch.

        Phase 1 (this call): download everything + swap exe, then relaunch.
        Phase 2 (next launch): ``_check_pending_firmware`` flashes the boards.
        """
        from ..updater import is_frozen
        info = getattr(self, "_update_info", {})
        version = info.get("version", "?")

        if not is_frozen():
            import webbrowser
            url = info.get("html_url", "https://github.com/smokydastona/joycon-to-keyboard/releases")
            QMessageBox.information(
                self, "Update Available",
                f"Version {version} is available.\n\n"
                "Auto-update only works in the packaged .exe build.\n"
                f"Download it from:\n{url}"
            )
            webbrowser.open(url)
            return

        fw_count = len(info.get("fw_assets", {}))
        fw_note = (
            f"\n\nFirmware for {fw_count} board(s) will also be downloaded and "
            "flashed automatically after the app restarts."
            if fw_count else ""
        )
        reply = QMessageBox.question(
            self, "Install Update",
            f"Install Bind Bandit v{version}?"
            f"{fw_note}\n\n"
            "The app will close and relaunch automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._sidebar.hide_update_button()
        self._update_btn.setVisible(False)

        # Progress dialog
        from PyQt6.QtWidgets import QProgressDialog
        progress_dlg = QProgressDialog("Preparing update…", None, 0, 100, self)
        progress_dlg.setWindowTitle("Updating Bind Bandit")
        progress_dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dlg.setMinimumDuration(0)
        progress_dlg.setValue(0)
        progress_dlg.show()

        import threading as _threading

        def _update_worker() -> None:
            try:
                from ..updater import download_update_bundle, relaunch

                total_size = 0
                downloaded_so_far = 0

                # Calculate total download size for progress
                for fa in info.get("fw_assets", {}).values():
                    total_size += fa.get("size", 0)
                # Exe size unknown upfront; treat each asset as equal weight
                asset_count = len(info.get("fw_assets", {})) + 1
                current_step = [0]

                def _progress(label: str, done: int, total: int) -> None:
                    if total > 0:
                        step_pct = int(done * 100 / total)
                        # Map to overall: each step gets equal share
                        overall = int(
                            (current_step[0] * 100 + step_pct) / asset_count
                        )
                        QTimer.singleShot(0, lambda p=overall, lbl=label: (
                            progress_dlg.setValue(p),
                            progress_dlg.setLabelText(lbl),
                        ))

                    # Detect step boundaries by label change
                    _progress._last = getattr(_progress, "_last", "")
                    if label != _progress._last:
                        current_step[0] += 1
                        _progress._last = label

                download_update_bundle(info, progress_cb=_progress)
                QTimer.singleShot(0, lambda: (
                    progress_dlg.setLabelText("Relaunching…"),
                    progress_dlg.setValue(100),
                ))
                QTimer.singleShot(600, relaunch)
            except Exception as exc:
                QTimer.singleShot(0, lambda e=str(exc): (
                    progress_dlg.close(),
                    QMessageBox.critical(
                        self, "Update Failed",
                        f"The update could not be installed:\n\n{e}"
                    ),
                    self._sidebar.show_update_button(version),
                ))

        _threading.Thread(target=_update_worker, daemon=True).start()

    def _check_pending_firmware(self) -> None:
        """After an app update, flash any firmware that was downloaded alongside it."""
        try:
            from ..updater import load_pending_firmware, clear_pending_firmware
        except Exception:
            return

        pending = load_pending_firmware()
        if not pending:
            return

        names = ", ".join(sorted(pending))
        reply = QMessageBox.question(
            self, "Firmware Update Ready",
            f"Firmware downloaded with the app update ({names}) is ready to flash.\n\n"
            "Connect the ESP32-S3 and click Yes to flash now, or No to skip.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            clear_pending_firmware()
            return

        if not self.bridge.is_connected:
            Toast.warning(self, "Connect to the device first, then update firmware from Diagnostics.")
            clear_pending_firmware()
            return

        # Use the existing DiagnosticsView firmware flash machinery
        diag = self._ensure_view(NAV_DIAGNOSTICS)
        self._nav_to(NAV_DIAGNOSTICS)

        import threading as _threading
        from PyQt6.QtWidgets import QProgressDialog

        progress_dlg = QProgressDialog("Flashing firmware…", None, 0, 100, self)
        progress_dlg.setWindowTitle("Firmware Update")
        progress_dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dlg.setMinimumDuration(0)
        progress_dlg.setValue(0)
        progress_dlg.show()

        results: list[str] = []

        def _flash_worker() -> None:
            try:
                from ..fw_updater import FirmwareFlasher, extract_app_from_merged
                flasher = FirmwareFlasher(self.bridge.client)
                for name, path in sorted(pending.items()):
                    board = "esp32s3" if "esp32s3" in name else "esp32"
                    QTimer.singleShot(0, lambda n=name: progress_dlg.setLabelText(f"Flashing {n}…"))
                    data = path.read_bytes()
                    try:
                        app = extract_app_from_merged(data)
                    except Exception:
                        app = data

                    def _cb(done: int, total: int, _n: str = name) -> None:
                        pct = int(done * 100 / total) if total else 0
                        QTimer.singleShot(0, lambda p=pct: progress_dlg.setValue(p))

                    flasher.flash(board, app, progress_cb=_cb)
                    results.append(name)

                clear_pending_firmware()
                QTimer.singleShot(0, lambda: (
                    progress_dlg.close(),
                    Toast.success(self, f"Firmware updated: {', '.join(results)}"),
                ))
            except Exception as exc:
                clear_pending_firmware()
                QTimer.singleShot(0, lambda e=str(exc): (
                    progress_dlg.close(),
                    QMessageBox.warning(self, "Firmware Flash Error", str(e)),
                ))

        _threading.Thread(target=_flash_worker, daemon=True).start()

    def _open_update_dialog(self) -> None:
        """Toolbar update button — delegates to the full update flow."""
        self._do_full_update()

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

        self._tray_menu = QMenu()
        show_action = self._tray_menu.addAction("Show / Hide")
        show_action.triggered.connect(self._toggle_visibility)
        self._tray_menu.addSeparator()

        # Profiles submenu
        self._tray_profiles_menu = QMenu("Profiles")
        self._tray_slot_actions: list[QAction] = []
        for i in range(4):
            act = QAction(f"Slot {i}", self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, s=i: self._tray_switch_slot(s))
            self._tray_profiles_menu.addAction(act)
            self._tray_slot_actions.append(act)
        self._tray_slot_actions[0].setChecked(True)
        self._tray_menu.addMenu(self._tray_profiles_menu)

        # Overlay toggle
        self._tray_overlay_action = self._tray_menu.addAction("Toggle Overlay")
        self._tray_overlay_action.triggered.connect(self.toggle_overlay)

        # Auto-switch toggle
        self._tray_autoswitch_action = QAction("Auto-Switch", self)
        self._tray_autoswitch_action.setCheckable(True)
        self._tray_autoswitch_action.setChecked(self._app_switcher.enabled)
        self._tray_autoswitch_action.triggered.connect(self._tray_toggle_autoswitch)
        self._tray_menu.addAction(self._tray_autoswitch_action)

        self._tray_menu.addSeparator()
        settings_action = self._tray_menu.addAction("⚙ Settings")
        settings_action.triggered.connect(lambda: (self._toggle_visibility() if not self.isVisible() else None, self._nav_to(NAV_SETTINGS)))
        self._tray_menu.addSeparator()
        quit_action = self._tray_menu.addAction("Quit")
        quit_action.triggered.connect(self._real_quit)
        self._tray_icon.setContextMenu(self._tray_menu)

        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _tray_switch_slot(self, slot: int) -> None:
        """Switch profile slot from the tray menu."""
        self._slot_combo.setCurrentIndex(slot)
        self._cmd_read_profile()
        self._update_tray_slot_checks()

    def _tray_toggle_autoswitch(self, checked: bool) -> None:
        self._app_switcher.enabled = checked

    def _update_tray_slot_checks(self) -> None:
        """Keep tray profile radio marks in sync with the active slot."""
        for i, act in enumerate(self._tray_slot_actions):
            act.setChecked(i == self._slot)

    def _update_tray_profile_names(self) -> None:
        """Update tray slot labels with profile names."""
        for i, act in enumerate(self._tray_slot_actions):
            name = ""
            if i == self._slot:
                name = self._profile.get("name", "")
            label = f"Slot {i}"
            if name:
                label += f": {name}"
            act.setText(label)

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
    # Onboarding wizard
    # -----------------------------------------------------------------

    def _show_onboarding(self) -> None:
        wizard = OnboardingWizard(self)
        wizard.exec()

    # -----------------------------------------------------------------
    # Settings dialog
    # -----------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Safehouse Config")
        dlg.setMinimumWidth(460)
        layout = QVBoxLayout(dlg)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # --- General tab ---
        general = QWidget()
        g_layout = QFormLayout(general)

        cb_tray = QCheckBox("Minimize to system tray on close")
        cb_tray.setChecked(self._settings.value("minimize_to_tray", False, type=bool))
        cb_tray.setToolTip("Keep the app running in the system tray when you close the window")
        g_layout.addRow(cb_tray)

        cb_start_minimized = QCheckBox("Start minimized to tray")
        cb_start_minimized.setChecked(self._settings.value("start_minimized", False, type=bool))
        cb_start_minimized.setToolTip("Launch the app hidden in the system tray")
        g_layout.addRow(cb_start_minimized)

        cb_autostart = QCheckBox("Start with Windows")
        cb_autostart.setChecked(self._is_autostart_enabled())
        cb_autostart.setToolTip("Automatically launch the app when you log in")
        g_layout.addRow(cb_autostart)

        cb_auto_connect = QCheckBox("Auto-connect to last serial port")
        cb_auto_connect.setChecked(self._settings.value("auto_connect", True, type=bool))
        cb_auto_connect.setToolTip("Automatically reconnect to the last used COM port on startup")
        g_layout.addRow(cb_auto_connect)

        tabs.addTab(general, "General")

        # --- Overlay tab ---
        overlay = QWidget()
        o_layout = QFormLayout(overlay)

        opacity_slider = QSlider(Qt.Orientation.Horizontal)
        opacity_slider.setRange(20, 100)
        opacity_slider.setValue(int(self._settings.value("overlay_opacity", 0.85, type=float) * 100))
        opacity_slider.setToolTip("Set the overlay window transparency (20–100%)")
        opacity_label = QLabel(f"{opacity_slider.value()}%")
        opacity_slider.valueChanged.connect(lambda v: opacity_label.setText(f"{v}%"))
        o_row = QHBoxLayout()
        o_row.addWidget(opacity_slider)
        o_row.addWidget(opacity_label)
        o_layout.addRow("Default opacity:", o_row)

        auto_hide_spin = QSpinBox()
        auto_hide_spin.setRange(0, 300)
        auto_hide_spin.setSuffix(" sec")
        auto_hide_spin.setSpecialValueText("Disabled")
        auto_hide_spin.setValue(self._settings.value("overlay_auto_hide", 0, type=int))
        auto_hide_spin.setToolTip("Hide the overlay after this many seconds of no input (0 = never)")
        o_layout.addRow("Auto-hide after:", auto_hide_spin)

        tabs.addTab(overlay, "Overlay")

        # --- Theme tab ---
        theme_tab = QWidget()
        t_layout = QFormLayout(theme_tab)

        theme_combo = QComboBox()
        theme_combo.addItems(["Dark", "Light"])
        theme_combo.setCurrentIndex(0 if self.theme.is_dark else 1)
        theme_combo.setToolTip("Choose the application color scheme")
        t_layout.addRow("Theme:", theme_combo)

        tabs.addTab(theme_tab, "Theme")

        # --- Developer tab ---
        dev_tab = QWidget()
        d_layout = QFormLayout(dev_tab)

        baud_combo = QComboBox()
        baud_combo.addItems(["115200", "230400", "460800", "921600"])
        current_baud = str(self._settings.value("baud_rate", "115200"))
        idx = baud_combo.findText(current_baud)
        if idx >= 0:
            baud_combo.setCurrentIndex(idx)
        baud_combo.setToolTip("Serial baud rate — must match the ESP32-S3 firmware setting")
        d_layout.addRow("Baud rate:", baud_combo)

        log_combo = QComboBox()
        log_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        current_level = str(self._settings.value("log_level", "INFO"))
        idx2 = log_combo.findText(current_level)
        if idx2 >= 0:
            log_combo.setCurrentIndex(idx2)
        log_combo.setToolTip("Console and file log verbosity")
        d_layout.addRow("Log level:", log_combo)

        btn_onboarding = QPushButton("Show Onboarding Wizard")
        btn_onboarding.setToolTip("Re-run the first-time setup wizard")
        btn_onboarding.clicked.connect(lambda: (
            self._settings.setValue("onboarding_done", False),
            QMessageBox.information(dlg, "Onboarding", "The onboarding wizard will show on next launch."),
        ))
        d_layout.addRow(btn_onboarding)

        tabs.addTab(dev_tab, "Developer")

        # --- Buttons ---
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings.setValue("minimize_to_tray", cb_tray.isChecked())
            self._settings.setValue("start_minimized", cb_start_minimized.isChecked())
            self._set_autostart(cb_autostart.isChecked())
            self._settings.setValue("auto_connect", cb_auto_connect.isChecked())

            new_opacity = opacity_slider.value() / 100.0
            self._settings.setValue("overlay_opacity", new_opacity)
            self._settings.setValue("overlay_auto_hide", auto_hide_spin.value())
            if self._overlay and not self._overlay.is_closed:
                self._overlay._set_opacity(new_opacity)

            self._settings.setValue("baud_rate", baud_combo.currentText())
            self._settings.setValue("log_level", log_combo.currentText())
            logging.getLogger().setLevel(getattr(logging, log_combo.currentText(), logging.INFO))

            # Legacy inline settings dialog — keep in sync with new Settings view.
            # This branch may still exist in older code paths; forward to set_mode.
            pass  # theme is now handled by the Settings view via _set_theme_mode()

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
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE) as key, contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, self._AUTOSTART_VALUE_NAME)
        except OSError:
            log.warning("Failed to update auto-start registry", exc_info=True)
