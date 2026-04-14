"""Devices view — M913 keypad and Razer mouse configuration.

Merges the old Mouse + Razer tabs into a device management view with
sub-tabs for each peripheral type.  Full feature parity with the
Tkinter app.py M913 and Razer tabs.
"""
from __future__ import annotations

import copy
import json
import logging
import zipfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import M913_HOTSPOTS
from ..theme import ThemeEngine
from ..widgets.card import Card
from ..widgets.hotspot_canvas import HotspotCanvas

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.devices")

# ---------------------------------------------------------------------------
# M913 button mapping constants (mirrors m913_device.py to avoid hard
# dependency on hidapi being installed at import time)
# ---------------------------------------------------------------------------
_M913_BUTTON_ORDER = [
    "left", "right", "middle", "fire",
    "side1", "side2", "side3", "side4", "side5", "side6",
    "side7", "side8", "side9", "side10", "side11", "side12",
]
_M913_BUTTON_LABELS: dict[str, str] = {
    "left": "Left Click",    "right": "Right Click",
    "middle": "Middle Click", "fire": "Fire",
    "side1": "Side 1",       "side2": "Side 2",
    "side3": "Side 3",       "side4": "Side 4",
    "side5": "Side 5",       "side6": "Side 6",
    "side7": "Side 7",       "side8": "Side 8",
    "side9": "Side 9",       "side10": "Side 10",
    "side11": "Side 11",     "side12": "Side 12",
}
_M913_ACTION_CHOICES: list[str] = [
    # Mouse buttons
    "left", "right", "middle", "backward", "forward",
    # Special mouse
    "dpi-", "dpi+", "dpi-cycle", "snipe", "led_toggle",
    "fire", "three_click", "polling_switch", "none",
    # Media
    "media_play", "media_next", "media_prev", "media_stop",
    "media_vol_up", "media_vol_down", "media_mute",
    "media_email", "media_calc", "media_home", "media_search",
    # Letters
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
    "k", "l", "m", "n", "o", "p", "q", "r", "s", "t",
    "u", "v", "w", "x", "y", "z",
    # Numbers
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    # Function keys
    "f1", "f2", "f3", "f4", "f5", "f6",
    "f7", "f8", "f9", "f10", "f11", "f12",
    # Navigation / common
    "enter", "escape", "backspace", "tab", "space",
    "up_arrow", "down_arrow", "left_arrow", "right_arrow",
    "insert", "delete", "home", "end", "pageup", "pagedown",
    # Modifiers
    "shift_l", "ctrl_l", "alt_l", "super_l",
    "shift_r", "ctrl_r", "alt_r",
    # Hardware macros
    *[f"macro{i}" for i in range(1, 16)],
]
# Key names used in the hardware macro event editor
_M913_MACRO_KEY_NAMES: list[str] = [
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
    "k", "l", "m", "n", "o", "p", "q", "r", "s", "t",
    "u", "v", "w", "x", "y", "z",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "f1", "f2", "f3", "f4", "f5", "f6",
    "f7", "f8", "f9", "f10", "f11", "f12",
    "enter", "escape", "backspace", "tab", "space",
    "up_arrow", "down_arrow", "left_arrow", "right_arrow",
    "delete", "home", "end", "pageup", "pagedown",
]

# ---------------------------------------------------------------------------
# Background worker for HID operations (keeps UI responsive)
# ---------------------------------------------------------------------------
class _HidWorker(QObject):
    """Runs a callable in a QThread and emits finished/error signals."""

    finished = pyqtSignal(object)  # result of the callable
    error = pyqtSignal(str)        # error message

    def __init__(self, func: Callable[[], Any]) -> None:
        super().__init__()
        self._func = func

    def run(self) -> None:
        try:
            result = self._func()
            self.finished.emit(result)
        except Exception as exc:
            log.error("HID worker error: %s", exc, exc_info=True)
            self.error.emit(str(exc))


def _run_hid_task(
    parent: QWidget,
    func: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[str], None],
) -> None:
    """Execute *func* on a background QThread. Calls on_done/on_error on the GUI thread."""
    from PyQt6.QtCore import QThread

    thread = QThread(parent)
    worker = _HidWorker(func)
    worker.moveToThread(thread)

    def _cleanup() -> None:
        thread.quit()
        thread.wait()
        thread.deleteLater()
        worker.deleteLater()

    worker.finished.connect(lambda result: (on_done(result), _cleanup()))
    worker.error.connect(lambda msg: (on_error(msg), _cleanup()))
    thread.started.connect(worker.run)
    thread.start()


# Lazy-imported device modules (avoid import errors when hidapi missing)
_m913_mod: Any = None
_razer_mod: Any = None


def _get_m913_mod() -> Any:
    global _m913_mod
    if _m913_mod is None:
        from ... import m913_device as _mod
        _m913_mod = _mod
    return _m913_mod


def _get_razer_mod() -> Any:
    global _razer_mod
    if _razer_mod is None:
        from ... import razer_device as _mod
        _razer_mod = _mod
    return _razer_mod


class DevicesView(QWidget):
    """Device configuration for M913 keypad and Razer mice."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main

        # Active device handles (set after detect)
        self._m913_devices: list = []
        self._m913_registry: dict = {}
        self._razer_devices: list = []
        self._razer_registry: dict = {}

        # Currently loaded device profiles
        self._m913_profile: Any = None
        self._razer_profile: Any = None

        # M913 UI widgets populated in _build_m913_tab
        self._m913_canvas: HotspotCanvas | None = None
        self._m913_hw_group: QButtonGroup | None = None
        self._m913_dpi_indicator_frames: list[QFrame] = []
        self._m913_dpi_name_edits: list[QLineEdit] = []
        self._m913_dpi_color_btns: list[QPushButton] = []
        self._m913_live_apply_chk: QCheckBox | None = None
        self._m913_live_timer: QTimer | None = None
        self._m913_reader_dev: Any = None

        # Joy-Con battery label registry (populated in _build_joycon_tab)
        self._joycon_battery_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Empty state shown when no devices are connected
        self._empty_label = QLabel(
            "No devices connected.\n\n"
            "Open Mission Control and click ＋ Add Device to connect a device."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(
            f"color: {self._main.theme.color('text_secondary')}; font-size: 13pt;")
        layout.addWidget(self._empty_label)

        # Dynamic tab widget — tabs are added/removed as devices connect/disconnect
        self._tabs = QTabWidget()
        self._tabs.hide()
        layout.addWidget(self._tabs)

        # device_id → tab QWidget (tracks what is visible in self._tabs)
        self._device_tabs: dict[str, QWidget] = {}

        # Pre-build M913 and Razer tab widgets (added to _tabs on demand)
        self._m913_tab = QScrollArea()
        self._m913_tab.setWidgetResizable(True)
        self._m913_tab.setFrameShape(QScrollArea.Shape.NoFrame)
        self._build_m913_tab()

        self._razer_tab = QScrollArea()
        self._razer_tab.setWidgetResizable(True)
        self._razer_tab.setFrameShape(QScrollArea.Shape.NoFrame)
        self._build_razer_tab()

        self._init_default_profiles()

    def _init_default_profiles(self) -> None:
        try:
            mod = _get_m913_mod()
            self._m913_profile = mod.M913Profile()
            self._m913_registry = mod.load_device_registry()
        except Exception:
            pass
        try:
            mod = _get_razer_mod()
            self._razer_profile = mod.RazerProfile()
            self._razer_registry = mod.load_device_registry()
        except Exception:
            pass

    # =================================================================
    # M913 Keypad Tab
    # =================================================================

    def _build_m913_tab(self) -> None:
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        header = QLabel("M913 Gaming Keypad")
        header.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        lay.addWidget(header)

        # Interactive canvas (replaces static image)
        theme_key = "dark" if self._main.theme.is_dark else "default"
        self._m913_canvas = HotspotCanvas(self._main.theme, self)
        pm = self._main.assets.load_pixmap("m913_none.png", QSize(400, 300))
        if pm:
            self._m913_canvas.set_background(pm)
        self._m913_canvas.set_hotspots(
            M913_HOTSPOTS.get(theme_key, M913_HOTSPOTS["default"]))
        self._m913_canvas.hotspot_clicked.connect(self._m913_canvas_hotspot_clicked)
        self._m913_canvas.hotspot_hovered.connect(self._m913_canvas_hotspot_hovered)
        lay.addWidget(self._m913_canvas)

        # Connection bar
        conn_card = Card(self._main.theme)
        conn_lay = QHBoxLayout(conn_card)
        conn_lay.addWidget(QLabel("Device:"))
        self._m913_dev_combo = QComboBox()
        self._m913_dev_combo.setMinimumWidth(200)
        self._m913_dev_combo.setToolTip("Select a detected M913 keypad from the list")
        self._m913_dev_combo.currentIndexChanged.connect(self._m913_on_device_selected)
        conn_lay.addWidget(self._m913_dev_combo, 1)
        scan_btn = QPushButton("Scan")
        scan_btn.setProperty("accent", True)
        scan_btn.clicked.connect(self._detect_m913)
        conn_lay.addWidget(scan_btn)
        self._m913_status = QLabel("Not connected")
        self._m913_status.setStyleSheet(
            f"color: {self._main.theme.color('text_secondary')};")
        conn_lay.addWidget(self._m913_status)
        lay.addWidget(conn_card)

        # Profile name + hardware slot (P1/P2) + sister slot
        profile_card = Card(self._main.theme)
        profile_row = QHBoxLayout(profile_card)
        profile_row.addWidget(QLabel("Profile name:"))
        self._m913_prof_name = QLineEdit("Default")
        self._m913_prof_name.setFixedWidth(200)
        profile_row.addWidget(self._m913_prof_name)
        profile_row.addSpacing(16)
        profile_row.addWidget(QLabel("Hardware slot:"))
        self._m913_hw_group = QButtonGroup(self)
        p1_rb = QRadioButton("P1")
        p1_rb.setChecked(True)
        p1_rb.setToolTip("Save to onboard profile slot 1 (hold DPI button to switch)")
        self._m913_hw_group.addButton(p1_rb, 1)
        profile_row.addWidget(p1_rb)
        p2_rb = QRadioButton("P2")
        p2_rb.setToolTip("Save to onboard profile slot 2 (hold DPI button to switch)")
        self._m913_hw_group.addButton(p2_rb, 2)
        profile_row.addWidget(p2_rb)
        profile_row.addSpacing(16)
        profile_row.addWidget(QLabel("Sister slot:"))
        self._m913_sister_combo = QComboBox()
        self._m913_sister_combo.setToolTip(
            "Link this M913 to a Joy-Con profile slot so they switch together")
        self._m913_sister_combo.addItems(
            ["None", "Slot 0", "Slot 1", "Slot 2", "Slot 3"])
        profile_row.addWidget(self._m913_sister_combo)
        profile_row.addStretch()
        lay.addWidget(profile_card)

        # DPI settings (5 stages with indicator, name, color, enable, spin, slider)
        dpi_group = QGroupBox("DPI Settings (5 stages)")
        dpi_lay = QVBoxLayout(dpi_group)
        self._m913_dpi_spins = []
        self._m913_dpi_checks = []
        self._m913_dpi_indicator_frames = []
        self._m913_dpi_name_edits = []
        self._m913_dpi_color_btns = []
        defaults = [800, 1600, 3200, 6400, 16000]
        stage_default_colors = ["#00ff00", "#0088ff", "#8800ff", "#ff8800", "#ff0000"]
        for i in range(5):
            row = QHBoxLayout()

            # Active-stage indicator (colored bar on the left)
            indicator = QFrame()
            indicator.setFixedSize(4, 22)
            indicator.setStyleSheet("background: transparent; border-radius: 2px;")
            self._m913_dpi_indicator_frames.append(indicator)
            row.addWidget(indicator)

            # Enable checkbox
            chk = QCheckBox(f"Stage {i + 1}:")
            chk.setChecked(True)
            chk.toggled.connect(self._m913_live_apply_trigger)
            self._m913_dpi_checks.append(chk)
            row.addWidget(chk)

            # Stage name (editable label)
            name_edit = QLineEdit(f"Stage {i + 1}")
            name_edit.setFixedWidth(70)
            name_edit.setPlaceholderText("Name…")
            name_edit.setToolTip("Stage label shown in the canvas and UI")
            name_edit.textChanged.connect(self._m913_live_apply_trigger)
            self._m913_dpi_name_edits.append(name_edit)
            row.addWidget(name_edit)

            # Stage color button
            color_btn = QPushButton()
            color_btn.setFixedSize(22, 22)
            c = stage_default_colors[i]
            color_btn.setStyleSheet(
                f"background: {c}; border: 1px solid #555; border-radius: 4px;")
            color_btn.setToolTip("Pick DPI stage indicator color")
            color_btn.clicked.connect(
                lambda _checked, idx=i: self._m913_pick_stage_color(idx))
            self._m913_dpi_color_btns.append(color_btn)
            row.addWidget(color_btn)

            # DPI spinbox
            spin = QSpinBox()
            spin.setRange(100, 16000)
            spin.setSingleStep(100)
            spin.setValue(defaults[i])
            spin.valueChanged.connect(self._m913_live_apply_trigger)
            self._m913_dpi_spins.append(spin)
            row.addWidget(spin)

            # DPI slider
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(100, 16000)
            slider.setSingleStep(100)
            slider.setValue(defaults[i])
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            row.addWidget(slider)

            dpi_lay.addLayout(row)
        lay.addWidget(dpi_group)

        # LED settings
        led_group = QGroupBox("LED / Lighting")
        led_lay = QVBoxLayout(led_group)
        led_row1 = QHBoxLayout()
        led_row1.addWidget(QLabel("Mode:"))
        self._m913_led_mode = QComboBox()
        self._m913_led_mode.setToolTip("LED lighting effect pattern")
        self._m913_led_mode.addItems([
            "off", "steady", "respiration", "rainbow",
            "wave", "reactive", "ripple", "starlight", "breath_single",
        ])
        self._m913_led_mode.setCurrentText("steady")
        self._m913_led_mode.currentIndexChanged.connect(self._m913_live_apply_trigger)
        led_row1.addWidget(self._m913_led_mode)
        led_row1.addSpacing(16)
        led_row1.addWidget(QLabel("Speed (1-5):"))
        self._m913_led_speed = QSpinBox()
        self._m913_led_speed.setRange(1, 5)
        self._m913_led_speed.setValue(3)
        self._m913_led_speed.setToolTip("Animation speed for the selected LED effect")
        self._m913_led_speed.valueChanged.connect(self._m913_live_apply_trigger)
        led_row1.addWidget(self._m913_led_speed)
        led_row1.addStretch()
        led_lay.addLayout(led_row1)

        led_row2 = QHBoxLayout()
        led_row2.addWidget(QLabel("Color:"))
        self._m913_led_color_edit = QLineEdit("00ff00")
        self._m913_led_color_edit.setFixedWidth(80)
        self._m913_led_color_edit.textChanged.connect(self._m913_live_apply_trigger)
        led_row2.addWidget(self._m913_led_color_edit)
        self._m913_led_color_swatch = QLabel("  ")
        self._m913_led_color_swatch.setFixedSize(24, 24)
        self._m913_led_color_swatch.setStyleSheet(
            "background: #00ff00; border: 1px solid #555; border-radius: 4px;")
        led_row2.addWidget(self._m913_led_color_swatch)
        pick_btn = QPushButton("Pick…")
        pick_btn.clicked.connect(self._m913_pick_led_color)
        led_row2.addWidget(pick_btn)
        led_row2.addSpacing(16)
        led_row2.addWidget(QLabel("Brightness (0-255):"))
        self._m913_led_brightness = QSpinBox()
        self._m913_led_brightness.setRange(0, 255)
        self._m913_led_brightness.setValue(255)
        self._m913_led_brightness.setToolTip("LED brightness level (0=off, 255=max)")
        self._m913_led_brightness.valueChanged.connect(self._m913_live_apply_trigger)
        led_row2.addWidget(self._m913_led_brightness)
        led_row2.addStretch()
        led_lay.addLayout(led_row2)
        lay.addWidget(led_group)

        # Polling rate
        poll_group = QGroupBox("Polling Rate")
        poll_lay = QHBoxLayout(poll_group)
        self._m913_poll_group = QButtonGroup(self)
        for hz in [125, 250, 500, 1000]:
            rb = QRadioButton(f"{hz} Hz")
            if hz == 1000:
                rb.setChecked(True)
            rb.toggled.connect(self._m913_live_apply_trigger)
            self._m913_poll_group.addButton(rb, hz)
            poll_lay.addWidget(rb)
        poll_lay.addStretch()
        lay.addWidget(poll_group)

        # Button Mapping (16 buttons × action combobox)
        btn_map_group = QGroupBox("Button Mapping")
        btn_map_lay = QVBoxLayout(btn_map_group)
        btn_scroll = QScrollArea()
        btn_scroll.setWidgetResizable(True)
        btn_scroll.setMaximumHeight(340)
        btn_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        btn_container = QWidget()
        btn_container_lay = QVBoxLayout(btn_container)
        btn_container_lay.setSpacing(3)
        btn_container_lay.setContentsMargins(4, 4, 4, 4)
        self._btn_action_widgets: dict[str, QComboBox] = {}
        _btn_defaults = {
            "left": "left", "right": "right",
            "middle": "middle", "fire": "fire",
        }
        for _bname in _M913_BUTTON_ORDER:
            _brow = QHBoxLayout()
            _blbl = QLabel(_M913_BUTTON_LABELS.get(_bname, _bname))
            _blbl.setFixedWidth(110)
            _brow.addWidget(_blbl)
            _bcombo = QComboBox()
            _bcombo.setEditable(True)
            _bcombo.addItems(_M913_ACTION_CHOICES)
            _bcombo.setCurrentText(_btn_defaults.get(_bname, "none"))
            _bcombo.setToolTip(
                f"Action for {_M913_BUTTON_LABELS.get(_bname, _bname)}. "
                "Select from list or type a combo like 'ctrl+c'."
            )
            _bcombo.currentTextChanged.connect(self._m913_live_apply_trigger)
            self._btn_action_widgets[_bname] = _bcombo
            _brow.addWidget(_bcombo, 1)
            btn_container_lay.addLayout(_brow)
        btn_container_lay.addStretch()
        btn_scroll.setWidget(btn_container)
        btn_map_lay.addWidget(btn_scroll)
        lay.addWidget(btn_map_group)

        # Action buttons — 3 rows
        actions_group = QGroupBox("Actions")
        actions_vlay = QVBoxLayout(actions_group)

        # Row 1: core config buttons
        row1 = QHBoxLayout()
        apply_btn = QPushButton("Apply Config")
        apply_btn.setProperty("accent", True)
        apply_btn.clicked.connect(self._m913_apply_config)
        row1.addWidget(apply_btn)
        save_btn = QPushButton("Save Profile")
        save_btn.clicked.connect(self._m913_save_profile)
        row1.addWidget(save_btn)
        load_btn = QPushButton("Load Profile")
        load_btn.clicked.connect(self._m913_load_profile)
        row1.addWidget(load_btn)
        del_btn = QPushButton("Delete Profile")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(self._m913_delete_profile)
        row1.addWidget(del_btn)
        row1.addSpacing(16)
        ini_export_btn = QPushButton("Export INI")
        ini_export_btn.clicked.connect(self._m913_export_ini)
        row1.addWidget(ini_export_btn)
        ini_import_btn = QPushButton("Import INI")
        ini_import_btn.clicked.connect(self._m913_import_ini)
        row1.addWidget(ini_import_btn)
        row1.addSpacing(16)
        diag_btn = QPushButton("Diagnostics…")
        diag_btn.clicked.connect(self._m913_diag_popup)
        row1.addWidget(diag_btn)
        macros_btn = QPushButton("Manage Macros…")
        macros_btn.clicked.connect(self._m913_macros_popup)
        row1.addWidget(macros_btn)
        row1.addStretch()
        actions_vlay.addLayout(row1)

        # Row 2: live-apply + factory reset
        row2 = QHBoxLayout()
        self._m913_live_apply_chk = QCheckBox("Live Apply")
        self._m913_live_apply_chk.setToolTip(
            "Automatically send config to connected device 1.5 s after any change")
        _prefs = QSettings("BindBandit", "m913_prefs")
        self._m913_live_apply_chk.setChecked(
            _prefs.value("live_apply", False, bool))
        self._m913_live_apply_chk.toggled.connect(self._m913_live_apply_toggled)
        row2.addWidget(self._m913_live_apply_chk)

        self._m913_live_timer = QTimer(self)
        self._m913_live_timer.setSingleShot(True)
        self._m913_live_timer.setInterval(1500)
        self._m913_live_timer.timeout.connect(self._m913_apply_config)

        row2.addSpacing(24)
        factory_btn = QPushButton("Factory Reset…")
        factory_btn.setProperty("danger", True)
        factory_btn.setToolTip("Restore all settings to M913 factory defaults")
        factory_btn.clicked.connect(self._m913_factory_reset)
        row2.addWidget(factory_btn)
        row2.addStretch()
        actions_vlay.addLayout(row2)

        # Row 3: profile bundle export/import
        row3 = QHBoxLayout()
        export_bundle_btn = QPushButton("Export Bundle…")
        export_bundle_btn.setToolTip(
            "Save all saved M913 profiles to a single .bindbandit archive")
        export_bundle_btn.clicked.connect(self._m913_export_bundle)
        row3.addWidget(export_bundle_btn)
        import_bundle_btn = QPushButton("Import Bundle…")
        import_bundle_btn.setToolTip(
            "Load M913 profiles from a .bindbandit archive")
        import_bundle_btn.clicked.connect(self._m913_import_bundle)
        row3.addWidget(import_bundle_btn)
        row3.addStretch()
        actions_vlay.addLayout(row3)

        lay.addWidget(actions_group)

        lay.addStretch()
        self._m913_tab.setWidget(container)

    # =================================================================
    # Razer Mouse Tab
    # =================================================================

    def _build_razer_tab(self) -> None:
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        header = QLabel("Razer Mouse")
        header.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        lay.addWidget(header)

        self._razer_image = QLabel()
        self._razer_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = self._main.assets.load_pixmap("razer_none.png", QSize(400, 300))
        if pm:
            self._razer_image.setPixmap(pm)
        lay.addWidget(self._razer_image)

        # Connection bar
        conn_card = Card(self._main.theme)
        conn_lay = QHBoxLayout(conn_card)
        conn_lay.addWidget(QLabel("Device:"))
        self._razer_dev_combo = QComboBox()
        self._razer_dev_combo.setMinimumWidth(200)
        self._razer_dev_combo.setToolTip("Select a detected Razer mouse from the list")
        self._razer_dev_combo.currentIndexChanged.connect(
            self._razer_on_device_selected)
        conn_lay.addWidget(self._razer_dev_combo, 1)
        scan_btn = QPushButton("Scan")
        scan_btn.setProperty("accent", True)
        scan_btn.clicked.connect(self._detect_razer)
        conn_lay.addWidget(scan_btn)
        read_btn = QPushButton("Read State")
        read_btn.clicked.connect(self._razer_read_state)
        conn_lay.addWidget(read_btn)
        self._razer_status = QLabel("Not connected")
        self._razer_status.setStyleSheet(
            f"color: {self._main.theme.color('text_secondary')};")
        conn_lay.addWidget(self._razer_status)
        lay.addWidget(conn_card)

        # Info bar
        info_card = Card(self._main.theme)
        info_lay = QHBoxLayout(info_card)
        info_lay.addWidget(QLabel("FW:"))
        self._razer_fw_label = QLabel("—")
        info_lay.addWidget(self._razer_fw_label)
        info_lay.addSpacing(16)
        info_lay.addWidget(QLabel("Serial:"))
        self._razer_serial_label = QLabel("—")
        info_lay.addWidget(self._razer_serial_label)
        info_lay.addSpacing(16)
        info_lay.addWidget(QLabel("Battery:"))
        self._razer_battery_label = QLabel("—")
        info_lay.addWidget(self._razer_battery_label)
        info_lay.addStretch()
        lay.addWidget(info_card)

        # Profile name + sister slot
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile name:"))
        self._razer_prof_name = QLineEdit("Default")
        self._razer_prof_name.setFixedWidth(200)
        profile_row.addWidget(self._razer_prof_name)
        profile_row.addSpacing(16)
        profile_row.addWidget(QLabel("Sister slot:"))
        self._razer_sister_combo = QComboBox()
        self._razer_sister_combo.setToolTip("Link this Razer mouse to a Joy-Con profile slot so they switch together")
        self._razer_sister_combo.addItems(
            ["None", "Slot 0", "Slot 1", "Slot 2", "Slot 3"])
        profile_row.addWidget(self._razer_sister_combo)
        profile_row.addStretch()
        lay.addLayout(profile_row)

        # DPI stages (5, X/Y independent)
        dpi_group = QGroupBox("DPI Stages (5 levels)")
        dpi_lay = QVBoxLayout(dpi_group)
        self._razer_dpi_x_spins: list[QSpinBox] = []
        self._razer_dpi_y_spins: list[QSpinBox] = []
        self._razer_dpi_active_group = QButtonGroup(self)
        for i in range(5):
            row = QHBoxLayout()
            rb = QRadioButton(f"Stage {i + 1}:")
            if i == 0:
                rb.setChecked(True)
            self._razer_dpi_active_group.addButton(rb, i + 1)
            row.addWidget(rb)
            row.addWidget(QLabel("X:"))
            x_spin = QSpinBox()
            x_spin.setRange(100, 26000)
            x_spin.setSingleStep(100)
            x_spin.setValue(800)
            self._razer_dpi_x_spins.append(x_spin)
            row.addWidget(x_spin)
            row.addWidget(QLabel("Y:"))
            y_spin = QSpinBox()
            y_spin.setRange(100, 26000)
            y_spin.setSingleStep(100)
            y_spin.setValue(800)
            self._razer_dpi_y_spins.append(y_spin)
            row.addWidget(y_spin)
            row.addStretch()
            dpi_lay.addLayout(row)
        lay.addWidget(dpi_group)

        # Polling rate
        poll_group = QGroupBox("Polling Rate")
        poll_lay = QHBoxLayout(poll_group)
        self._razer_poll_group = QButtonGroup(self)
        for hz in [125, 500, 1000]:
            rb = QRadioButton(f"{hz} Hz")
            if hz == 1000:
                rb.setChecked(True)
            self._razer_poll_group.addButton(rb, hz)
            poll_lay.addWidget(rb)
        poll_lay.addStretch()
        lay.addWidget(poll_group)

        # Idle timeout
        idle_group = QGroupBox("Idle Timeout")
        idle_lay = QHBoxLayout(idle_group)
        idle_lay.addWidget(QLabel("Timeout (60-900 sec):"))
        self._razer_idle_spin = QSpinBox()
        self._razer_idle_spin.setRange(60, 900)
        self._razer_idle_spin.setSingleStep(30)
        self._razer_idle_spin.setValue(300)
        self._razer_idle_spin.setToolTip("Seconds of inactivity before the mouse enters sleep mode")
        idle_lay.addWidget(self._razer_idle_spin)
        idle_lay.addStretch()
        lay.addWidget(idle_group)

        # Hypershift
        hyper_group = QGroupBox("Hypershift")
        hyper_lay = QVBoxLayout(hyper_group)
        self._razer_hypershift = QCheckBox("Enable Hypershift layer")
        self._razer_hypershift.setToolTip("Activate an alternate button layer while holding the designated key")
        hyper_lay.addWidget(self._razer_hypershift)
        hyper_lay.addWidget(QLabel(
            "When enabled, holding the designated button activates "
            "an alternate button mapping layer."))
        lay.addWidget(hyper_group)

        # Action buttons
        actions_group = QGroupBox("Actions")
        actions_lay = QHBoxLayout(actions_group)
        apply_btn = QPushButton("Apply Config")
        apply_btn.setProperty("accent", True)
        apply_btn.clicked.connect(self._razer_apply_config)
        actions_lay.addWidget(apply_btn)
        save_btn = QPushButton("Save Profile")
        save_btn.clicked.connect(self._razer_save_profile)
        actions_lay.addWidget(save_btn)
        load_btn = QPushButton("Load Profile")
        load_btn.clicked.connect(self._razer_load_profile)
        actions_lay.addWidget(load_btn)
        del_btn = QPushButton("Delete Profile")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(self._razer_delete_profile)
        actions_lay.addWidget(del_btn)
        actions_lay.addStretch()
        lay.addWidget(actions_group)

        lay.addStretch()
        self._razer_tab.setWidget(container)

    # =================================================================
    # M913 Operations
    # =================================================================

    # -----------------------------------------------------------------
    # DPI stage input reader lifecycle
    # -----------------------------------------------------------------

    def _m913_stop_input_reader(self) -> None:
        """Stop and release the background DPI-stage input reader."""
        if self._m913_reader_dev is not None:
            try:
                self._m913_reader_dev.stop_input_reader()
                self._m913_reader_dev.close()
            except Exception:
                pass
            self._m913_reader_dev = None

    def _m913_start_input_reader(self, device_index: int) -> None:
        """Open the selected device and start polling for DPI-cycle presses."""
        self._m913_stop_input_reader()
        if device_index < 0 or device_index >= len(self._m913_devices):
            return
        try:
            mod = _get_m913_mod()
            enabled = (
                list(self._m913_profile.dpi_enabled)
                if self._m913_profile
                else [True] * 5
            )
            rdev = mod.M913Device()
            rdev.start_input_reader(self._m913_set_active_stage, enabled)
            self._m913_reader_dev = rdev
        except Exception as ex:
            log.debug("M913 input reader could not start: %s", ex)

    def cleanup(self) -> None:
        """Release all held HID device handles. Called by MainWindow on quit."""
        self._m913_stop_input_reader()

    # -----------------------------------------------------------------
    # Device detection / selection
    # -----------------------------------------------------------------

    def _detect_m913(self) -> None:
        self._m913_stop_input_reader()
        try:
            mod = _get_m913_mod()
            self._m913_devices = mod.M913Device.enumerate()
            self._m913_dev_combo.clear()
            for d in self._m913_devices:
                self._m913_dev_combo.addItem(d.display_name)
            if self._m913_devices:
                self._m913_status.setText(
                    f"Found {len(self._m913_devices)} device(s)")
                self._m913_status.setStyleSheet(
                    f"color: {self._main.theme.color('success')};")
                pm = self._main.assets.load_pixmap(
                    "m913_connected.png", QSize(400, 300))
                if pm and self._m913_canvas:
                    self._m913_canvas.set_background(pm)
            else:
                self._m913_status.setText("No M913 devices found")
                self._m913_status.setStyleSheet(
                    f"color: {self._main.theme.color('danger')};")
                pm = self._main.assets.load_pixmap(
                    "m913_none.png", QSize(400, 300))
                if pm and self._m913_canvas:
                    self._m913_canvas.set_background(pm)
        except Exception as e:
            self._m913_status.setText(f"Error: {e}")
            log.error("M913 detect failed: %s", e, exc_info=True)

    def _m913_on_device_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._m913_devices):
            return
        dev_info = self._m913_devices[index]
        reg = self._m913_registry.get(dev_info.device_id, {})
        linked = reg.get("profile")
        loaded = False
        if linked:
            try:
                mod = _get_m913_mod()
                self._m913_profile = mod.load_profile(linked)
                self._m913_ui_from_profile()
                self._m913_status.setText(f"Loaded profile '{linked}'")
                loaded = True
            except Exception:
                pass
        if not loaded:
            self._m913_status.setText(
                f"Selected {dev_info.display_name} (no saved profile)")
        self._m913_start_input_reader(index)

    def _m913_ui_to_profile(self) -> None:
        if not self._m913_profile:
            return
        p = self._m913_profile
        p.name = self._m913_prof_name.text().strip() or "Default"

        # Hardware profile slot (P1 / P2)
        if self._m913_hw_group:
            hw_id = self._m913_hw_group.checkedId()
            if hw_id > 0:
                p.hardware_profile = hw_id

        p.dpi_values = [s.value() for s in self._m913_dpi_spins]
        p.dpi_enabled = [c.isChecked() for c in self._m913_dpi_checks]

        # Stage names
        p.stage_names = [e.text() or f"Stage {i + 1}"
                         for i, e in enumerate(self._m913_dpi_name_edits)]

        # Stage colors (extracted from button stylesheets)
        colors = []
        for btn in self._m913_dpi_color_btns:
            ss = btn.styleSheet()
            c = "#00ff00"
            for part in ss.split(";"):
                part = part.strip()
                if part.startswith("background:"):
                    c = part.split(":", 1)[-1].strip()
                    break
            colors.append(c)
        p.stage_colors = colors

        p.led_mode = self._m913_led_mode.currentText()
        try:
            p.led_color = int(
                self._m913_led_color_edit.text().strip().lstrip("#"), 16)
        except ValueError:
            p.led_color = 0x00FF00
        p.led_brightness = self._m913_led_brightness.value()
        p.led_speed = self._m913_led_speed.value()
        checked = self._m913_poll_group.checkedId()
        p.polling_rate = checked if checked > 0 else 1000
        sister = self._m913_sister_combo.currentText()
        if sister.startswith("Slot "):
            try:
                p.sister_slot = int(sister.split()[-1])
            except ValueError:
                p.sister_slot = None
        else:
            p.sister_slot = None
        # Button mappings
        for btn_name, combo in self._btn_action_widgets.items():
            action = combo.currentText().strip()
            if action:
                p.buttons[btn_name] = action

    def _m913_ui_from_profile(self) -> None:
        if not self._m913_profile:
            return
        p = self._m913_profile

        self._m913_prof_name.setText(p.name)

        # Hardware slot (P1 / P2)
        if self._m913_hw_group:
            hw_btn = self._m913_hw_group.button(p.hardware_profile)
            if hw_btn:
                hw_btn.setChecked(True)

        for i in range(min(5, len(p.dpi_values))):
            self._m913_dpi_spins[i].setValue(p.dpi_values[i])
        for i in range(min(5, len(p.dpi_enabled))):
            self._m913_dpi_checks[i].setChecked(p.dpi_enabled[i])

        # Stage names
        for i, name_edit in enumerate(self._m913_dpi_name_edits):
            if i < len(p.stage_names):
                name_edit.setText(p.stage_names[i])

        # Stage colors
        for i, color_btn in enumerate(self._m913_dpi_color_btns):
            if i < len(p.stage_colors):
                c = p.stage_colors[i]
                color_btn.setStyleSheet(
                    f"background: {c}; border: 1px solid #555; border-radius: 4px;")

        self._m913_led_mode.setCurrentText(p.led_mode)
        self._m913_led_color_edit.setText(f"{p.led_color:06x}")
        self._m913_led_color_swatch.setStyleSheet(
            f"background: #{p.led_color:06x}; "
            f"border: 1px solid #555; border-radius: 4px;")
        self._m913_led_brightness.setValue(p.led_brightness)
        self._m913_led_speed.setValue(p.led_speed)
        btn = self._m913_poll_group.button(p.polling_rate)
        if btn:
            btn.setChecked(True)
        if p.sister_slot is not None:
            self._m913_sister_combo.setCurrentText(f"Slot {p.sister_slot}")
        else:
            self._m913_sister_combo.setCurrentIndex(0)

        # Button mappings
        for btn_name, combo in self._btn_action_widgets.items():
            action = p.buttons.get(btn_name, "none")
            idx = combo.findText(action)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(action)

        # Refresh canvas labels
        self._m913_canvas_refresh_labels()

    def _m913_pick_led_color(self) -> None:
        cur = self._m913_led_color_edit.text().strip().lstrip("#")
        try:
            initial = QColor(f"#{cur}" if len(cur) == 6 else "#00ff00")
        except Exception:
            initial = QColor("#00ff00")
        color = QColorDialog.getColor(initial, self, "Pick LED Color")
        if color.isValid():
            hx = color.name().lstrip("#")
            self._m913_led_color_edit.setText(hx)
            self._m913_led_color_swatch.setStyleSheet(
                f"background: #{hx}; "
                f"border: 1px solid #555; border-radius: 4px;")

    def _m913_apply_config(self) -> None:
        if not self._m913_devices:
            self._m913_status.setText("No device selected")
            return
        idx = self._m913_dev_combo.currentIndex()
        if idx < 0 or idx >= len(self._m913_devices):
            return
        dev_info = self._m913_devices[idx]
        self._m913_ui_to_profile()
        profile = self._m913_profile
        self._m913_status.setText("Applying...")

        def _work() -> tuple:
            mod = _get_m913_mod()
            dev = mod.M913Device()
            dev.open(dev_info)
            sent, errors = dev.apply_profile(profile)
            dev.close()
            return sent, errors, dev_info.display_name

        def _done(result: tuple) -> None:
            sent, errors, name = result
            if errors:
                self._m913_status.setText(
                    f"Applied with {errors} error(s) — {sent} packets")
            else:
                self._m913_status.setText(
                    f"Applied — {sent} packets to {name}")
            self._main._log_line(
                f"[M913] Config applied: {sent} packets, {errors} errors")

        def _err(msg: str) -> None:
            self._m913_status.setText(f"Error: {msg}")

        _run_hid_task(self, _work, _done, _err)

    def _m913_save_profile(self) -> None:
        self._m913_ui_to_profile()
        if not self._m913_profile:
            return
        if not self._m913_profile.name.strip():
            self._m913_profile.name = "Default"
        try:
            mod = _get_m913_mod()
            mod.save_profile(self._m913_profile)
            idx = self._m913_dev_combo.currentIndex()
            if 0 <= idx < len(self._m913_devices):
                did = self._m913_devices[idx].device_id
                self._m913_registry[did] = {
                    "profile": self._m913_profile.name}
                mod.save_device_registry(self._m913_registry)
            self._m913_status.setText(
                f"Saved profile '{self._m913_profile.name}'")
            self._main._log_line(
                f"[M913] Profile saved: {self._m913_profile.name}")
        except Exception as e:
            self._m913_status.setText(f"Save error: {e}")

    def _m913_load_profile(self) -> None:
        try:
            mod = _get_m913_mod()
            saved = mod.list_saved_profiles()
        except Exception:
            self._m913_status.setText("Could not list profiles")
            return
        if not saved:
            self._m913_status.setText("No saved M913 profiles")
            return
        name, ok = QInputDialog.getItem(
            self, "Load M913 Profile", "Select profile:", saved, 0, False)
        if not ok or not name:
            return
        try:
            self._m913_profile = mod.load_profile(name)
            self._m913_ui_from_profile()
            self._m913_status.setText(f"Loaded profile '{name}'")
        except Exception as e:
            self._m913_status.setText(f"Load error: {e}")

    def _m913_delete_profile(self) -> None:
        try:
            mod = _get_m913_mod()
            saved = mod.list_saved_profiles()
        except Exception:
            return
        if not saved:
            self._m913_status.setText("No profiles to delete")
            return
        name, ok = QInputDialog.getItem(
            self, "Delete M913 Profile",
            "Select profile to delete:", saved, 0, False)
        if not ok or not name:
            return
        if QMessageBox.question(
            self, "Confirm", f"Delete M913 profile '{name}'?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            mod.delete_profile(name)
            self._m913_status.setText(f"Deleted profile '{name}'")

    def _m913_export_ini(self) -> None:
        self._m913_ui_to_profile()
        if not self._m913_profile:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export M913 INI",
            f"{self._m913_profile.name}.ini",
            "INI files (*.ini);;All files (*)")
        if not path:
            return
        try:
            mod = _get_m913_mod()
            mod.export_ini(self._m913_profile, path)
            self._m913_status.setText(f"Exported INI → {path}")
            self._main._log_line(f"[M913] Exported INI: {path}")
        except Exception as e:
            self._m913_status.setText(f"Export error: {e}")

    def _m913_import_ini(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import M913 INI", "",
            "INI files (*.ini);;All files (*)")
        if not path:
            return
        try:
            mod = _get_m913_mod()
            self._m913_profile = mod.import_ini(path)
            self._m913_ui_from_profile()
            self._m913_status.setText(f"Imported INI ← {path}")
            self._main._log_line(f"[M913] Imported INI: {path}")
        except Exception as e:
            self._m913_status.setText(f"Import error: {e}")

    def _m913_canvas_hotspot_clicked(self, name: str) -> None:
        """Handle a click on a hotspot in the M913 canvas — open an action picker."""
        # scroll_up / scroll_down are non-configurable display-only hotspots
        if name in ("scroll_up", "scroll_down"):
            return
        combo = self._btn_action_widgets.get(name)
        if combo is None:
            return
        current = combo.currentText()

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Assign action — {_M913_BUTTON_LABELS.get(name, name)}")
        dlg_lay = QVBoxLayout(dlg)
        dlg_lay.addWidget(QLabel(f"Choose action for <b>{_M913_BUTTON_LABELS.get(name, name)}</b>:"))
        action_combo = QComboBox()
        action_combo.setEditable(True)
        action_combo.addItems(_M913_ACTION_CHOICES)
        action_combo.setCurrentText(current)
        dlg_lay.addWidget(action_combo)
        btns = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setProperty("accent", True)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dlg.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        dlg_lay.addLayout(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_action = action_combo.currentText().strip()
            if new_action:
                idx = combo.findText(new_action)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setEditText(new_action)
                self._m913_canvas_refresh_labels()

    def _m913_canvas_hotspot_hovered(self, name: str) -> None:
        """Handle hover event from canvas — no additional action needed (canvas handles tooltip)."""
        pass

    def _m913_canvas_refresh_labels(self) -> None:
        """Push current button-action mapping to the canvas as overlay labels."""
        if self._m913_canvas is None:
            return
        labels: dict[str, str] = {}
        for btn_name, combo in self._btn_action_widgets.items():
            labels[btn_name] = combo.currentText()
        self._m913_canvas.set_mapping_labels(labels)

    def _m913_set_active_stage(self, idx: int) -> None:
        """Visually highlight the active DPI stage indicator frame."""
        for i, frame in enumerate(self._m913_dpi_indicator_frames):
            if i == idx and i < len(self._m913_dpi_color_btns):
                # Extract color from the stage color button's stylesheet
                ss = self._m913_dpi_color_btns[i].styleSheet()
                c = "#00ff00"
                for part in ss.split(";"):
                    part = part.strip()
                    if part.startswith("background:"):
                        c = part.split(":", 1)[-1].strip()
                        break
                frame.setStyleSheet(
                    f"background: {c}; border-radius: 2px;")
            else:
                frame.setStyleSheet("background: transparent; border-radius: 2px;")

    def _m913_pick_stage_color(self, idx: int) -> None:
        """Open a color dialog and update the DPI stage color button."""
        if idx >= len(self._m913_dpi_color_btns):
            return
        btn = self._m913_dpi_color_btns[idx]
        ss = btn.styleSheet()
        cur_color = "#00ff00"
        for part in ss.split(";"):
            part = part.strip()
            if part.startswith("background:"):
                cur_color = part.split(":", 1)[-1].strip()
                break
        try:
            initial = QColor(cur_color)
        except Exception:
            initial = QColor("#00ff00")
        color = QColorDialog.getColor(initial, self, f"Stage {idx + 1} Color")
        if color.isValid():
            c = color.name()
            btn.setStyleSheet(
                f"background: {c}; border: 1px solid #555; border-radius: 4px;")

    def _m913_live_apply_toggled(self, checked: bool) -> None:
        """Save live-apply preference and stop timer when disabled."""
        prefs = QSettings("BindBandit", "m913_prefs")
        prefs.setValue("live_apply", checked)
        if not checked and self._m913_live_timer:
            self._m913_live_timer.stop()

    def _m913_live_apply_trigger(self) -> None:
        """Restart the live-apply debounce timer if live apply is on and device is connected."""
        if (self._m913_live_apply_chk
                and self._m913_live_apply_chk.isChecked()
                and self._m913_devices
                and self._m913_live_timer):
            self._m913_live_timer.start()

    def _m913_factory_reset(self) -> None:
        """Restore all M913 profile settings to factory defaults."""
        if QMessageBox.question(
            self, "Factory Reset",
            "Reset all M913 settings to factory defaults?\n"
            "This will not affect saved profile files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            mod = _get_m913_mod()
            self._m913_profile = copy.deepcopy(mod.FACTORY_DEFAULTS)
            self._m913_profile.name = self._m913_prof_name.text().strip() or "Default"
            self._m913_ui_from_profile()
            self._m913_status.setText("Settings reset to factory defaults")
        except Exception as e:
            self._m913_status.setText(f"Reset error: {e}")

    def _m913_export_bundle(self) -> None:
        """Export all saved M913 profiles to a single .bindbandit archive."""
        try:
            mod = _get_m913_mod()
            saved = mod.list_saved_profiles()
        except Exception as e:
            self._m913_status.setText(f"Export error: {e}")
            return
        if not saved:
            self._m913_status.setText("No saved M913 profiles to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export M913 Bundle",
            "m913_profiles.bindbandit",
            "BindBandit Bundle (*.bindbandit);;All files (*)")
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for name in saved:
                    profile = mod.load_profile(name)
                    data = json.dumps(profile.to_dict(), indent=2)
                    safe_name = name.replace("/", "_").replace("\\", "_")
                    zf.writestr(f"m913/{safe_name}.json", data)
            self._m913_status.setText(
                f"Exported {len(saved)} profile(s) → {path}")
            self._main._log_line(f"[M913] Bundle exported: {path}")
        except Exception as e:
            self._m913_status.setText(f"Export error: {e}")
            log.error("M913 bundle export failed: %s", e, exc_info=True)

    def _m913_import_bundle(self) -> None:
        """Load M913 profiles from a .bindbandit archive."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import M913 Bundle", "",
            "BindBandit Bundle (*.bindbandit);;All files (*)")
        if not path:
            return
        try:
            mod = _get_m913_mod()
            count = 0
            with zipfile.ZipFile(path, "r") as zf:
                for entry in zf.namelist():
                    if not entry.startswith("m913/") or not entry.endswith(".json"):
                        continue
                    data = json.loads(zf.read(entry).decode("utf-8"))
                    profile = mod.M913Profile.from_dict(data)
                    mod.save_profile(profile)
                    count += 1
            self._m913_status.setText(
                f"Imported {count} profile(s) from bundle")
            self._main._log_line(f"[M913] Bundle imported: {path}")
        except Exception as e:
            self._m913_status.setText(f"Import error: {e}")
            log.error("M913 bundle import failed: %s", e, exc_info=True)

    def _m913_diag_popup(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("M913 Diagnostics")
        dlg.setMinimumSize(580, 420)
        main_lay = QVBoxLayout(dlg)
        main_lay.addWidget(QLabel("Raw HID Feature Report Viewer"))
        log_box = QPlainTextEdit()
        log_box.setReadOnly(True)
        log_box.setFont(QFont("Consolas", 9))
        log_box.setMinimumHeight(250)
        main_lay.addWidget(log_box)

        def _append(text: str):
            log_box.appendPlainText(text)

        ctrl = QHBoxLayout()

        def _device_info():
            idx = self._m913_dev_combo.currentIndex()
            if idx < 0 or idx >= len(self._m913_devices):
                _append("[INFO] No device selected")
                return
            d = self._m913_devices[idx]
            _append(f"[INFO] Product: {d.product_string}")
            _append(f"[INFO] Serial:  {d.serial_number}")
            _append(f"[INFO] Mfr:     {d.manufacturer_string}")
            _append(f"[INFO] Iface:   {d.interface_number}")

        info_btn = QPushButton("Device Info")
        info_btn.clicked.connect(_device_info)
        ctrl.addWidget(info_btn)
        ctrl.addWidget(QLabel("Raw hex:"))
        raw_edit = QLineEdit()
        raw_edit.setFont(QFont("Consolas", 9))
        raw_edit.setMinimumWidth(250)
        ctrl.addWidget(raw_edit)

        def _send_raw():
            raw = raw_edit.text().strip()
            if not raw:
                return
            try:
                mod = _get_m913_mod()
            except Exception:
                _append("[ERROR] M913 module not available")
                return
            idx = self._m913_dev_combo.currentIndex()
            if idx < 0 or idx >= len(self._m913_devices):
                _append("[ERROR] No device selected")
                return
            try:
                data = bytes.fromhex(raw.replace(" ", ""))
                if len(data) != mod.PACKET_SIZE:
                    _append(
                        f"[ERROR] Expected {mod.PACKET_SIZE} bytes, "
                        f"got {len(data)}")
                    return
                pkt = bytearray(data)
                _append("[SEND] " + " ".join(f"{b:02X}" for b in pkt))
                dev = mod.M913Device()
                dev.open(self._m913_devices[idx])
                resp = dev.send_recv(pkt)
                if resp:
                    _append(
                        f"[RECV] ({len(resp)} bytes) "
                        + " ".join(f"{b:02X}" for b in resp))
                else:
                    _append("[RECV] No response")
                dev.close()
            except ValueError:
                _append("[ERROR] Invalid hex string")
            except Exception as e:
                _append(f"[ERROR] {e}")

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(_send_raw)
        ctrl.addWidget(send_btn)
        main_lay.addLayout(ctrl)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        main_lay.addWidget(close_btn)
        dlg.exec()

    def _m913_macros_popup(self) -> None:
        """Open hardware macro editor for M913 slots 1–15."""
        if not self._m913_profile:
            try:
                mod = _get_m913_mod()
                self._m913_profile = mod.M913Profile()
            except Exception as e:
                QMessageBox.warning(
                    self, "M913 Error",
                    f"Could not initialise M913 module: {e}",
                )
                return
        dlg = QDialog(self)
        dlg.setWindowTitle("M913 Hardware Macros")
        dlg.setMinimumSize(640, 500)
        dlg_lay = QVBoxLayout(dlg)
        info = QLabel(
            "Hardware macros are stored in the M913's onboard memory. "
            "Up to 15 slots, 67 key events each. "
            "Assign a slot to a button via action 'macro1'–'macro15'."
        )
        info.setWordWrap(True)
        dlg_lay.addWidget(info)

        # Slot selector
        slot_row = QHBoxLayout()
        slot_row.addWidget(QLabel("Slot:"))
        slot_combo = QComboBox()
        for _si in range(1, 16):
            slot_combo.addItem(f"Macro {_si}", _si)
        slot_row.addWidget(slot_combo)
        slot_row.addStretch()
        dlg_lay.addLayout(slot_row)

        # Event list
        event_list = QListWidget()
        event_list.setFont(QFont("Consolas", 9))
        event_list.setMinimumHeight(220)
        event_list.setToolTip(
            "Sequence of key press/release events in this macro slot")
        dlg_lay.addWidget(event_list)

        # Key input row
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Key:"))
        key_combo = QComboBox()
        key_combo.addItems(_M913_MACRO_KEY_NAMES)
        key_row.addWidget(key_combo)
        add_down_btn = QPushButton("▼ Add Press")
        add_up_btn = QPushButton("▲ Add Release")
        del_evt_btn = QPushButton("Delete Event")
        del_evt_btn.setProperty("danger", True)
        clear_slot_btn = QPushButton("Clear Slot")
        key_row.addWidget(add_down_btn)
        key_row.addWidget(add_up_btn)
        key_row.addWidget(del_evt_btn)
        key_row.addWidget(clear_slot_btn)
        key_row.addStretch()
        dlg_lay.addLayout(key_row)

        macro_status = QLabel("")
        macro_status.setStyleSheet(
            f"color: {self._main.theme.color('text_secondary')};")
        dlg_lay.addWidget(macro_status)

        # Action buttons
        action_row = QHBoxLayout()
        apply_btn = QPushButton("Apply to Device")
        apply_btn.setProperty("accent", True)
        save_btn = QPushButton("Save to Profile")
        m_close = QPushButton("Close")
        action_row.addWidget(apply_btn)
        action_row.addWidget(save_btn)
        action_row.addStretch()
        action_row.addWidget(m_close)
        dlg_lay.addLayout(action_row)
        m_close.clicked.connect(dlg.accept)

        # Per-slot event storage: slot_num → list of (evt_type, scancode)
        slot_events: dict[int, list[tuple[int, int]]] = {}
        for _k, _ms in self._m913_profile.macros.items():
            slot_events[_k] = list(_ms.events)

        def _refresh_events() -> None:
            sn: int = slot_combo.currentData()
            evts = slot_events.get(sn, [])
            event_list.clear()
            try:
                _rev = {v: k for k, v in _get_m913_mod().KEY_CODES.items()}
            except Exception:
                _rev = {}
            for _et, _sc in evts:
                _kn = _rev.get(_sc, f"0x{_sc:02X}")
                _icon = "\u25bc" if _et == 0x81 else "\u25b2"
                event_list.addItem(f"{_icon} {_kn}  (0x{_sc:02X})")

        def _add_event(is_press: bool) -> None:
            sn: int = slot_combo.currentData()
            try:
                _sc = _get_m913_mod().KEY_CODES.get(key_combo.currentText(), 0x04)
            except Exception:
                _sc = 0x04
            _et = 0x81 if is_press else 0x41
            _evts = slot_events.setdefault(sn, [])
            if len(_evts) < 67:
                _evts.append((_et, _sc))
                _refresh_events()
            else:
                macro_status.setText("Slot full (max 67 events)")

        def _delete_event() -> None:
            sn: int = slot_combo.currentData()
            _row = event_list.currentRow()
            _evts = slot_events.get(sn, [])
            if 0 <= _row < len(_evts):
                _evts.pop(_row)
                _refresh_events()

        def _clear_slot() -> None:
            sn: int = slot_combo.currentData()
            slot_events[sn] = []
            _refresh_events()

        def _save_to_profile() -> None:
            try:
                _mod = _get_m913_mod()
                for _sn, _evts in slot_events.items():
                    _ms2 = _mod.MacroSlot(events=list(_evts))
                    self._m913_profile.macros[_sn] = _ms2
                _empty = [
                    _k for _k, _ms2 in self._m913_profile.macros.items()
                    if _ms2.is_empty()
                ]
                for _k in _empty:
                    del self._m913_profile.macros[_k]
                macro_status.setText(
                    "Macros saved to profile (click Apply to flash to device)")
                self._m913_status.setText("Macros saved to profile")
            except Exception as _e:
                macro_status.setText(f"Save error: {_e}")

        def _apply_to_device() -> None:
            _save_to_profile()
            if not self._m913_devices:
                macro_status.setText(
                    "No device connected — macros saved to profile only")
                return
            _didx = self._m913_dev_combo.currentIndex()
            if _didx < 0 or _didx >= len(self._m913_devices):
                return
            _dev_info = self._m913_devices[_didx]
            _macros_snap = dict(self._m913_profile.macros)
            self._m913_status.setText("Applying macros\u2026")
            macro_status.setText("Applying macros to device\u2026")

            def _work() -> tuple:
                _mod2 = _get_m913_mod()
                _dev = _mod2.M913Device()
                _dev.open(_dev_info)
                _sent, _errors = _dev.apply_macros(_macros_snap)
                _dev.close()
                return _sent, _errors

            def _done(result: tuple) -> None:
                _sent, _errors = result
                _msg = f"Macros applied — {_sent} packet(s), {_errors} error(s)"
                self._m913_status.setText(_msg)
                macro_status.setText(_msg)
                self._main._log_line(f"[M913] {_msg}")

            def _err(msg: str) -> None:
                self._m913_status.setText(f"Macro apply error: {msg}")
                macro_status.setText(f"Error: {msg}")

            _run_hid_task(self, _work, _done, _err)

        slot_combo.currentIndexChanged.connect(_refresh_events)
        add_down_btn.clicked.connect(lambda: _add_event(True))
        add_up_btn.clicked.connect(lambda: _add_event(False))
        del_evt_btn.clicked.connect(_delete_event)
        clear_slot_btn.clicked.connect(_clear_slot)
        save_btn.clicked.connect(_save_to_profile)
        apply_btn.clicked.connect(_apply_to_device)
        _refresh_events()
        dlg.exec()

    # =================================================================
    # Razer Operations
    # =================================================================

    def _detect_razer(self) -> None:
        try:
            mod = _get_razer_mod()
            self._razer_devices = mod.RazerDevice.enumerate()
            self._razer_dev_combo.clear()
            for d in self._razer_devices:
                self._razer_dev_combo.addItem(d.display_name)
            if self._razer_devices:
                self._razer_status.setText(
                    f"Found {len(self._razer_devices)} device(s)")
                self._razer_status.setStyleSheet(
                    f"color: {self._main.theme.color('success')};")
                pm = self._main.assets.load_pixmap(
                    "razer_connected.png", QSize(400, 300))
                if pm:
                    self._razer_image.setPixmap(pm)
            else:
                self._razer_status.setText("No supported Razer devices found")
                self._razer_status.setStyleSheet(
                    f"color: {self._main.theme.color('danger')};")
        except Exception as e:
            self._razer_status.setText(f"Error: {e}")
            log.error("Razer detect failed: %s", e, exc_info=True)

    def _razer_on_device_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._razer_devices):
            return
        dev_info = self._razer_devices[index]
        reg = self._razer_registry.get(dev_info.device_id, {})
        linked = reg.get("profile")
        if linked:
            try:
                mod = _get_razer_mod()
                self._razer_profile = mod.load_profile(linked)
                self._razer_ui_from_profile()
                self._razer_status.setText(f"Loaded profile '{linked}'")
                return
            except Exception:
                pass
        self._razer_status.setText(
            f"Selected {dev_info.display_name} (no saved profile)")

    def _razer_read_state(self) -> None:
        idx = self._razer_dev_combo.currentIndex()
        if idx < 0 or idx >= len(self._razer_devices):
            self._razer_status.setText("No device selected")
            return
        dev_info = self._razer_devices[idx]
        self._razer_status.setText("Reading...")

        def _work() -> Any:
            mod = _get_razer_mod()
            dev = mod.RazerDevice()
            dev.open(dev_info)
            state = dev.read_full_state()
            dev.close()
            return state

        def _done(state: Any) -> None:
            self._razer_fw_label.setText(state.firmware_version or "—")
            self._razer_serial_label.setText(state.serial or "—")
            if state.battery_level >= 0:
                charge = " ⚡" if state.battery_charging else ""
                self._razer_battery_label.setText(
                    f"{state.battery_level}%{charge}")
            else:
                self._razer_battery_label.setText("N/A")
            if state.dpi_stages:
                self._razer_profile.dpi_stages = list(state.dpi_stages)
                self._razer_profile.active_dpi_stage = state.active_dpi_stage
            if state.poll_rate:
                self._razer_profile.poll_rate = state.poll_rate
            if state.idle_time:
                self._razer_profile.idle_time = state.idle_time
            self._razer_ui_from_profile()
            self._razer_status.setText(
                f"Read state from {dev_info.display_name}")
            self._main._log_line(
                f"[Razer] State: FW={state.firmware_version}, "
                f"DPI={state.dpi_x}x{state.dpi_y}, "
                f"Poll={state.poll_rate}Hz")

        def _err(msg: str) -> None:
            self._razer_status.setText(f"Read error: {msg}")

        _run_hid_task(self, _work, _done, _err)

    def _razer_ui_to_profile(self) -> None:
        if not self._razer_profile:
            return
        p = self._razer_profile
        p.name = self._razer_prof_name.text().strip() or "Default"
        p.active_dpi_stage = self._razer_dpi_active_group.checkedId()
        stages = []
        for i in range(5):
            stages.append((self._razer_dpi_x_spins[i].value(),
                           self._razer_dpi_y_spins[i].value()))
        p.dpi_stages = stages
        p.poll_rate = self._razer_poll_group.checkedId()
        p.idle_time = self._razer_idle_spin.value()
        sister = self._razer_sister_combo.currentText()
        if sister.startswith("Slot "):
            try:
                p.sister_slot = int(sister.split()[-1])
            except ValueError:
                p.sister_slot = None
        else:
            p.sister_slot = None

    def _razer_ui_from_profile(self) -> None:
        if not self._razer_profile:
            return
        p = self._razer_profile
        self._razer_prof_name.setText(p.name)
        btn = self._razer_dpi_active_group.button(p.active_dpi_stage)
        if btn:
            btn.setChecked(True)
        for i in range(5):
            if i < len(p.dpi_stages):
                dx, dy = p.dpi_stages[i]
            else:
                dx, dy = 800, 800
            self._razer_dpi_x_spins[i].setValue(dx)
            self._razer_dpi_y_spins[i].setValue(dy)
        poll_btn = self._razer_poll_group.button(p.poll_rate)
        if poll_btn:
            poll_btn.setChecked(True)
        self._razer_idle_spin.setValue(getattr(p, "idle_time", 300))
        if p.sister_slot is not None:
            self._razer_sister_combo.setCurrentText(f"Slot {p.sister_slot}")
        else:
            self._razer_sister_combo.setCurrentIndex(0)

    def _razer_apply_config(self) -> None:
        idx = self._razer_dev_combo.currentIndex()
        if idx < 0 or idx >= len(self._razer_devices):
            self._razer_status.setText("No device selected")
            return
        dev_info = self._razer_devices[idx]
        self._razer_ui_to_profile()
        profile = self._razer_profile
        self._razer_status.setText("Applying...")

        def _work() -> tuple:
            mod = _get_razer_mod()
            dev = mod.RazerDevice()
            dev.open(dev_info)
            ok, errors = dev.apply_profile(profile)
            dev.close()
            return ok, errors, dev_info.display_name

        def _done(result: tuple) -> None:
            ok, errors, name = result
            if errors:
                self._razer_status.setText(
                    f"Applied with {errors} error(s) — {ok} ok")
            else:
                self._razer_status.setText(
                    f"Applied — {ok} commands to {name}")
            self._main._log_line(
                f"[Razer] Config applied: {ok} ok, {errors} errors")

        def _err(msg: str) -> None:
            self._razer_status.setText(f"Error: {msg}")

        _run_hid_task(self, _work, _done, _err)

    def _razer_save_profile(self) -> None:
        self._razer_ui_to_profile()
        if not self._razer_profile:
            return
        if not self._razer_profile.name.strip():
            self._razer_profile.name = "Default"
        try:
            mod = _get_razer_mod()
            mod.save_profile(self._razer_profile)
            idx = self._razer_dev_combo.currentIndex()
            if 0 <= idx < len(self._razer_devices):
                did = self._razer_devices[idx].device_id
                self._razer_registry[did] = {
                    "profile": self._razer_profile.name}
                mod.save_device_registry(self._razer_registry)
            self._razer_status.setText(
                f"Saved profile '{self._razer_profile.name}'")
            self._main._log_line(
                f"[Razer] Profile saved: {self._razer_profile.name}")
        except Exception as e:
            self._razer_status.setText(f"Save error: {e}")

    def _razer_load_profile(self) -> None:
        try:
            mod = _get_razer_mod()
            saved = mod.list_saved_profiles()
        except Exception:
            self._razer_status.setText("Could not list profiles")
            return
        if not saved:
            self._razer_status.setText("No saved Razer profiles")
            return
        name, ok = QInputDialog.getItem(
            self, "Load Razer Profile", "Select profile:", saved, 0, False)
        if not ok or not name:
            return
        try:
            self._razer_profile = mod.load_profile(name)
            self._razer_ui_from_profile()
            self._razer_status.setText(f"Loaded profile '{name}'")
        except Exception as e:
            self._razer_status.setText(f"Load error: {e}")

    def _razer_delete_profile(self) -> None:
        try:
            mod = _get_razer_mod()
            saved = mod.list_saved_profiles()
        except Exception:
            return
        if not saved:
            self._razer_status.setText("No profiles to delete")
            return
        name, ok = QInputDialog.getItem(
            self, "Delete Razer Profile",
            "Select profile to delete:", saved, 0, False)
        if not ok or not name:
            return
        if QMessageBox.question(
            self, "Confirm", f"Delete Razer profile '{name}'?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            mod.delete_profile(name)
            self._razer_status.setText(f"Deleted profile '{name}'")

    # =================================================================
    # Slot changed — auto-apply linked M913 / Razer profiles
    # =================================================================

    def slot_changed(self, slot: int) -> None:
        self._apply_linked_m913(slot)
        self._apply_linked_razer(slot)

    def _apply_linked_m913(self, slot: int) -> None:
        try:
            mod = _get_m913_mod()
        except Exception:
            return
        try:
            names = mod.list_saved_profiles()
        except Exception:
            return
        for name in names:
            try:
                profile = mod.load_profile(name)
            except Exception:
                continue
            if getattr(profile, "sister_slot", None) == slot:
                self._m913_profile = profile
                self._m913_ui_from_profile()
                log.info("M913 auto-switch: '%s' (sister_slot=%d)", name, slot)
                self._m913_status.setText(f"Linked: {name}")
                self._m913_status.setStyleSheet(
                    f"color: {self._main.theme.color('success')};")
                self._main._log_line(
                    f"[m913] Auto-applied '{name}' for slot {slot}")
                return
        log.debug("No M913 profile linked to slot %d", slot)

    def _apply_linked_razer(self, slot: int) -> None:
        try:
            mod = _get_razer_mod()
        except Exception:
            return
        try:
            names = mod.list_saved_profiles()
        except Exception:
            return
        for name in names:
            try:
                profile = mod.load_profile(name)
            except Exception:
                continue
            if getattr(profile, "sister_slot", None) == slot:
                self._razer_profile = profile
                self._razer_ui_from_profile()
                log.info("Razer auto-switch: '%s' (sister_slot=%d)", name, slot)
                self._razer_status.setText(f"Linked: {name}")
                self._razer_status.setStyleSheet(
                    f"color: {self._main.theme.color('success')};")
                self._main._log_line(
                    f"[razer] Auto-applied '{name}' for slot {slot}")
                return
        log.debug("No Razer profile linked to slot %d", slot)

    # -----------------------------------------------------------------
    def device_event(self, obj: dict) -> None:
        evt = obj.get("evt")
        if evt == "battery":
            try:
                raw_id = int(obj.get("device_id", 0))
                level = int(obj.get("level", -1))
            except (TypeError, ValueError):
                return
            if 0 <= level <= 4:
                jc_id = f"joycon-{'L' if raw_id == 0 else 'R'}"
                lbl = self._joycon_battery_labels.get(jc_id)
                if lbl:
                    bars = "▂▄▆█"[:level] + "░" * (4 - level)
                    lbl.setText(f"{bars}  {level}/4")

    def profile_loaded(self, slot: int, profile: dict) -> None:
        pass

    def profile_updated(self, profile: dict) -> None:
        pass

    def apply_theme(self, theme: ThemeEngine) -> None:
        pass

    # =================================================================
    # Dynamic device tab management
    # =================================================================

    def _update_empty_state(self) -> None:
        has_tabs = self._tabs.count() > 0
        self._tabs.setVisible(has_tabs)
        self._empty_label.setVisible(not has_tabs)

    def _build_joycon_tab(self, entry: Any) -> QScrollArea:
        """Build a Joy-Con info tab widget for *entry*."""
        widget = QWidget()
        lay = QVBoxLayout(widget)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        title = QLabel(entry.name)
        title.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        lay.addWidget(title)

        from ..widgets.card import Card
        info_card = Card(self._main.theme)
        info_lay = QFormLayout(info_card)
        info_lay.addRow("Device ID:", QLabel(entry.id))
        info_lay.addRow("BT Address:", QLabel(entry.bda or "—"))
        bat_lbl = QLabel("—")
        info_lay.addRow("Battery:", bat_lbl)
        lay.addWidget(info_card)

        note = QLabel(
            "Joy-Con key mapping is configured in Blueprint Layout.\n"
            "Battery and latency are shown on the Mission Control dashboard."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {self._main.theme.color('text_secondary')};")
        lay.addWidget(note)
        lay.addStretch()

        self._joycon_battery_labels[entry.id] = bat_lbl

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def select_device(self, device_id: str) -> None:
        """Switch to the tab for *device_id* (called from Dashboard Configure button)."""
        tab = self._device_tabs.get(device_id)
        if tab is not None and self._tabs.indexOf(tab) >= 0:
            self._tabs.setCurrentWidget(tab)

    def device_connected(self, entry: Any) -> None:
        """Add a tab for the newly connected device."""
        did = entry.id
        if did in self._device_tabs:
            return  # already shown
        if entry.type == "joycon":
            tab_widget = self._build_joycon_tab(entry)
            tab_title = f"🎮 {entry.name}"
        elif entry.type == "m913":
            tab_widget = self._m913_tab
            tab_title = "🖱 M913 Keypad"
        elif entry.type == "razer":
            tab_widget = self._razer_tab
            tab_title = "🐍 Razer Mouse"
        else:
            return
        self._device_tabs[did] = tab_widget
        self._tabs.addTab(tab_widget, tab_title)
        self._update_empty_state()

    def device_disconnected(self, device_id: str) -> None:
        """Remove the tab for *device_id*."""
        tab = self._device_tabs.pop(device_id, None)
        if tab is not None:
            idx = self._tabs.indexOf(tab)
            if idx >= 0:
                self._tabs.removeTab(idx)
            self._joycon_battery_labels.pop(device_id, None)
        self._update_empty_state()

    def connection_changed(self, connected: bool) -> None:
        """Remove ESP32-BT Joy-Con tabs when serial disconnects."""
        if not connected:
            for did in [k for k in list(self._device_tabs) if k.startswith("joycon-")]:
                self.device_disconnected(did)
