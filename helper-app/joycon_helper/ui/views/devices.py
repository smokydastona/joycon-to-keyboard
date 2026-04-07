"""Devices view — M913 keypad and Razer mouse configuration.

Merges the old Mouse + Razer tabs into a device management view with
sub-tabs for each peripheral type.  Full feature parity with the
Tkinter app.py M913 and Razer tabs.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea,
    QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..theme import ThemeEngine
from ..widgets.card import Card

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.devices")

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # M913 tab
        self._m913_tab = QScrollArea()
        self._m913_tab.setWidgetResizable(True)
        self._m913_tab.setFrameShape(QScrollArea.Shape.NoFrame)
        self._build_m913_tab()
        self._tabs.addTab(self._m913_tab, "🖱 M913 Keypad")

        # Razer tab
        self._razer_tab = QScrollArea()
        self._razer_tab.setWidgetResizable(True)
        self._razer_tab.setFrameShape(QScrollArea.Shape.NoFrame)
        self._build_razer_tab()
        self._tabs.addTab(self._razer_tab, "🐍 Razer Mouse")

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

        # Device image
        self._m913_image = QLabel()
        self._m913_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = self._main.assets.load_pixmap("m913_none.png", QSize(400, 300))
        if pm:
            self._m913_image.setPixmap(pm)
        lay.addWidget(self._m913_image)

        # Connection bar
        conn_card = Card(self._main.theme)
        conn_lay = QHBoxLayout(conn_card)
        conn_lay.addWidget(QLabel("Device:"))
        self._m913_dev_combo = QComboBox()
        self._m913_dev_combo.setMinimumWidth(200)
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

        # Profile name + sister slot + layout
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile name:"))
        self._m913_prof_name = QLineEdit("Default")
        self._m913_prof_name.setFixedWidth(200)
        profile_row.addWidget(self._m913_prof_name)
        profile_row.addSpacing(16)
        profile_row.addWidget(QLabel("Sister slot:"))
        self._m913_sister_combo = QComboBox()
        self._m913_sister_combo.addItems(
            ["None", "Slot 0", "Slot 1", "Slot 2", "Slot 3"])
        profile_row.addWidget(self._m913_sister_combo)
        profile_row.addSpacing(16)
        profile_row.addWidget(QLabel("Layout:"))
        self._m913_layout_combo = QComboBox()
        self._m913_layout_combo.addItems(["Stock M913", "IncediusMod"])
        self._m913_layout_combo.currentTextChanged.connect(
            self._m913_on_layout_changed)
        profile_row.addWidget(self._m913_layout_combo)
        self._m913_edit_layout_btn = QPushButton("Edit Map…")
        self._m913_edit_layout_btn.setEnabled(False)
        self._m913_edit_layout_btn.clicked.connect(self._m913_edit_incedius)
        profile_row.addWidget(self._m913_edit_layout_btn)
        profile_row.addStretch()
        lay.addLayout(profile_row)

        # Button remapping (16 buttons)
        btn_group = QGroupBox("Button Remapping")
        btn_lay = QGridLayout(btn_group)
        self._m913_button_combos: Dict[str, QComboBox] = {}
        self._m913_button_labels: Dict[str, QLabel] = {}
        try:
            mod = _get_m913_mod()
            actions = list(mod.MOUSE_ACTIONS.keys()) + ["macro"]
            btn_order = mod.BUTTON_ORDER
            display_names = mod.BUTTON_DISPLAY_NAMES
        except Exception:
            actions = ["left", "right", "middle", "none"]
            btn_order = []
            display_names = {}

        for i, btn_name in enumerate(btn_order):
            label = QLabel(f"{display_names.get(btn_name, btn_name)}:")
            self._m913_button_labels[btn_name] = label
            btn_lay.addWidget(label, i // 4, (i % 4) * 2)
            combo = QComboBox()
            combo.addItems(actions)
            btn_lay.addWidget(combo, i // 4, (i % 4) * 2 + 1)
            self._m913_button_combos[btn_name] = combo
        lay.addWidget(btn_group)

        # DPI settings (5 stages with enable checkboxes)
        dpi_group = QGroupBox("DPI Settings (5 stages)")
        dpi_lay = QVBoxLayout(dpi_group)
        self._m913_dpi_spins: List[QSpinBox] = []
        self._m913_dpi_checks: List[QCheckBox] = []
        defaults = [800, 1600, 3200, 6400, 16000]
        for i in range(5):
            row = QHBoxLayout()
            chk = QCheckBox(f"Stage {i + 1}:")
            chk.setChecked(True)
            self._m913_dpi_checks.append(chk)
            row.addWidget(chk)
            spin = QSpinBox()
            spin.setRange(100, 16000)
            spin.setSingleStep(100)
            spin.setValue(defaults[i])
            self._m913_dpi_spins.append(spin)
            row.addWidget(spin)
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
        self._m913_led_mode.addItems([
            "off", "steady", "respiration", "rainbow",
            "wave", "reactive", "ripple", "starlight", "breath_single",
        ])
        self._m913_led_mode.setCurrentText("steady")
        led_row1.addWidget(self._m913_led_mode)
        led_row1.addSpacing(16)
        led_row1.addWidget(QLabel("Speed (1-5):"))
        self._m913_led_speed = QSpinBox()
        self._m913_led_speed.setRange(1, 5)
        self._m913_led_speed.setValue(3)
        led_row1.addWidget(self._m913_led_speed)
        led_row1.addStretch()
        led_lay.addLayout(led_row1)

        led_row2 = QHBoxLayout()
        led_row2.addWidget(QLabel("Color:"))
        self._m913_led_color_edit = QLineEdit("00ff00")
        self._m913_led_color_edit.setFixedWidth(80)
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
            self._m913_poll_group.addButton(rb, hz)
            poll_lay.addWidget(rb)
        poll_lay.addStretch()
        lay.addWidget(poll_group)

        # Action buttons
        actions_group = QGroupBox("Actions")
        actions_lay = QHBoxLayout(actions_group)
        apply_btn = QPushButton("Apply Config")
        apply_btn.setProperty("accent", True)
        apply_btn.clicked.connect(self._m913_apply_config)
        actions_lay.addWidget(apply_btn)
        save_btn = QPushButton("Save Profile")
        save_btn.clicked.connect(self._m913_save_profile)
        actions_lay.addWidget(save_btn)
        load_btn = QPushButton("Load Profile")
        load_btn.clicked.connect(self._m913_load_profile)
        actions_lay.addWidget(load_btn)
        del_btn = QPushButton("Delete Profile")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(self._m913_delete_profile)
        actions_lay.addWidget(del_btn)
        actions_lay.addSpacing(16)
        ini_export_btn = QPushButton("Export INI")
        ini_export_btn.clicked.connect(self._m913_export_ini)
        actions_lay.addWidget(ini_export_btn)
        ini_import_btn = QPushButton("Import INI")
        ini_import_btn.clicked.connect(self._m913_import_ini)
        actions_lay.addWidget(ini_import_btn)
        actions_lay.addSpacing(16)
        macro_btn = QPushButton("Macro Builder…")
        macro_btn.clicked.connect(self._m913_macro_popup)
        actions_lay.addWidget(macro_btn)
        diag_btn = QPushButton("Diagnostics…")
        diag_btn.clicked.connect(self._m913_diag_popup)
        actions_lay.addWidget(diag_btn)
        actions_lay.addStretch()
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
        self._razer_sister_combo.addItems(
            ["None", "Slot 0", "Slot 1", "Slot 2", "Slot 3"])
        profile_row.addWidget(self._razer_sister_combo)
        profile_row.addStretch()
        lay.addLayout(profile_row)

        # DPI stages (5, X/Y independent)
        dpi_group = QGroupBox("DPI Stages (5 levels)")
        dpi_lay = QVBoxLayout(dpi_group)
        self._razer_dpi_x_spins: List[QSpinBox] = []
        self._razer_dpi_y_spins: List[QSpinBox] = []
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

        # Button remapping
        try:
            r_mod = _get_razer_mod()
            razer_actions = r_mod.REMAP_ACTIONS
            razer_btn_order = r_mod.BUTTON_ORDER
            razer_display = r_mod.BUTTON_DISPLAY_NAMES
        except Exception:
            razer_actions = ["default"]
            razer_btn_order = []
            razer_display = {}

        btn_group = QGroupBox("Button Remapping")
        btn_lay = QGridLayout(btn_group)
        self._razer_button_combos: Dict[str, QComboBox] = {}
        for i, btn_name in enumerate(razer_btn_order):
            display = razer_display.get(btn_name, btn_name)
            btn_lay.addWidget(QLabel(f"{display}:"), i // 3, (i % 3) * 2)
            combo = QComboBox()
            combo.addItems(razer_actions)
            btn_lay.addWidget(combo, i // 3, (i % 3) * 2 + 1)
            self._razer_button_combos[btn_name] = combo
        lay.addWidget(btn_group)

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
        idle_lay.addWidget(self._razer_idle_spin)
        idle_lay.addStretch()
        lay.addWidget(idle_group)

        # Hypershift
        hyper_group = QGroupBox("Hypershift")
        hyper_lay = QVBoxLayout(hyper_group)
        self._razer_hypershift = QCheckBox("Enable Hypershift layer")
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

    def _detect_m913(self) -> None:
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
                if pm:
                    self._m913_image.setPixmap(pm)
            else:
                self._m913_status.setText("No M913 devices found")
                self._m913_status.setStyleSheet(
                    f"color: {self._main.theme.color('danger')};")
        except Exception as e:
            self._m913_status.setText(f"Error: {e}")
            log.error("M913 detect failed: %s", e, exc_info=True)

    def _m913_on_device_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._m913_devices):
            return
        dev_info = self._m913_devices[index]
        reg = self._m913_registry.get(dev_info.device_id, {})
        linked = reg.get("profile")
        if linked:
            try:
                mod = _get_m913_mod()
                self._m913_profile = mod.load_profile(linked)
                self._m913_ui_from_profile()
                self._m913_status.setText(f"Loaded profile '{linked}'")
                return
            except Exception:
                pass
        self._m913_status.setText(
            f"Selected {dev_info.display_name} (no saved profile)")

    def _m913_on_layout_changed(self, text: str) -> None:
        is_incedius = text == "IncediusMod"
        self._m913_edit_layout_btn.setEnabled(is_incedius)
        try:
            mod = _get_m913_mod()
            mode = "incedius" if is_incedius else "stock"
            names = mod.LAYOUT_DISPLAY_NAMES.get(
                mode, mod.BUTTON_DISPLAY_NAMES)
            for btn_name, lbl in self._m913_button_labels.items():
                lbl.setText(f"{names.get(btn_name, btn_name)}:")
        except Exception:
            pass

    def _m913_edit_incedius(self) -> None:
        try:
            mod = _get_m913_mod()
        except Exception:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit IncediusMod Button Map")
        dlg.setFixedSize(400, 480)
        d_lay = QVBoxLayout(dlg)
        d_lay.addWidget(QLabel(
            "Assign each M913 side button to the matching\n"
            "physical position on your IncediusMod mouse."))
        combos: Dict[str, QComboBox] = {}
        current_map = dict(
            self._m913_profile.incedius_map) if self._m913_profile else {}
        for key in mod.INCEDIUS_SIDE_KEYS:
            row = QHBoxLayout()
            row.addWidget(QLabel(
                f"{mod.BUTTON_DISPLAY_NAMES.get(key, key)} →"))
            cb = QComboBox()
            cb.addItems(mod.INCEDIUS_LABEL_CHOICES)
            cur = current_map.get(key,
                                  mod.DEFAULT_INCEDIUS_MAP.get(key, ""))
            idx = cb.findText(cur)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            combos[key] = cb
            row.addWidget(cb)
            d_lay.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        d_lay.addWidget(buttons)
        if dlg.exec() == QDialog.DialogCode.Accepted and self._m913_profile:
            new_map: Dict[str, str] = {}
            used: Dict[str, str] = {}
            for key in mod.INCEDIUS_SIDE_KEYS:
                label = combos[key].currentText()
                if label in used:
                    QMessageBox.warning(
                        self, "Duplicate",
                        f"'{label}' assigned to both "
                        f"{mod.BUTTON_DISPLAY_NAMES[used[label]]} and "
                        f"{mod.BUTTON_DISPLAY_NAMES[key]}")
                    return
                used[label] = key
                new_map[key] = label
            self._m913_profile.incedius_map = new_map
            self._m913_on_layout_changed(
                self._m913_layout_combo.currentText())

    def _m913_ui_to_profile(self) -> None:
        if not self._m913_profile:
            return
        p = self._m913_profile
        p.name = self._m913_prof_name.text().strip() or "Default"
        p.layout = ("incedius"
                     if self._m913_layout_combo.currentText() == "IncediusMod"
                     else "stock")
        for btn_name, combo in self._m913_button_combos.items():
            p.buttons[btn_name] = combo.currentText().strip().lower() or "none"
        p.dpi_values = [s.value() for s in self._m913_dpi_spins]
        p.dpi_enabled = [c.isChecked() for c in self._m913_dpi_checks]
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

    def _m913_ui_from_profile(self) -> None:
        if not self._m913_profile:
            return
        p = self._m913_profile
        self._m913_prof_name.setText(p.name)
        for btn_name, combo in self._m913_button_combos.items():
            idx = combo.findText(p.buttons.get(btn_name, "none"))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        for i in range(min(5, len(p.dpi_values))):
            self._m913_dpi_spins[i].setValue(p.dpi_values[i])
        for i in range(min(5, len(p.dpi_enabled))):
            self._m913_dpi_checks[i].setChecked(p.dpi_enabled[i])
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
        layout_text = ("IncediusMod" if p.layout == "incedius"
                       else "Stock M913")
        self._m913_layout_combo.setCurrentText(layout_text)

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
        try:
            mod = _get_m913_mod()
            dev = mod.M913Device()
            dev.open(dev_info)
            sent, errors = dev.apply_profile(self._m913_profile)
            dev.close()
            if errors:
                self._m913_status.setText(
                    f"Applied with {errors} error(s) — {sent} packets")
            else:
                self._m913_status.setText(
                    f"Applied — {sent} packets to {dev_info.display_name}")
            self._main._log_line(
                f"[M913] Config applied: {sent} packets, {errors} errors")
        except Exception as e:
            self._m913_status.setText(f"Error: {e}")
            log.error("M913 apply failed: %s", e, exc_info=True)

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

    def _m913_macro_popup(self) -> None:
        try:
            mod = _get_m913_mod()
        except Exception:
            QMessageBox.warning(self, "Error", "M913 module not available")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("M913 Macro Builder")
        dlg.setMinimumSize(540, 480)
        main_lay = QVBoxLayout(dlg)
        top = QHBoxLayout()
        top.addWidget(QLabel("Macro Slot:"))
        slot_spin = QSpinBox()
        slot_spin.setRange(1, mod.MACRO_SLOT_COUNT)
        slot_spin.setValue(1)
        top.addWidget(slot_spin)
        top.addStretch()
        main_lay.addLayout(top)

        event_list = QListWidget()
        event_list.setFont(QFont("Consolas", 10))
        event_list.setMinimumHeight(200)
        main_lay.addWidget(event_list)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Key:"))
        key_combo = QComboBox()
        key_combo.addItems(mod.ALL_KEY_NAMES)
        ctrl.addWidget(key_combo)

        def _add(kind: str) -> None:
            k = key_combo.currentText()
            if k not in mod.KEY_CODES:
                return
            sc = mod.KEY_CODES[k]
            if kind in ("both", "press"):
                event_list.addItem(f"Press   {k}  (0x{sc:02X})")
            if kind in ("both", "release"):
                event_list.addItem(f"Release {k}  (0x{sc:02X})")

        pr_btn = QPushButton("Press+Release")
        pr_btn.clicked.connect(lambda: _add("both"))
        ctrl.addWidget(pr_btn)
        p_btn = QPushButton("Press")
        p_btn.clicked.connect(lambda: _add("press"))
        ctrl.addWidget(p_btn)
        r_btn = QPushButton("Release")
        r_btn.clicked.connect(lambda: _add("release"))
        ctrl.addWidget(r_btn)
        rm_btn = QPushButton("Remove")
        rm_btn.clicked.connect(
            lambda: event_list.takeItem(event_list.currentRow())
            if event_list.currentRow() >= 0 else None)
        ctrl.addWidget(rm_btn)
        clr_btn = QPushButton("Clear")
        clr_btn.clicked.connect(event_list.clear)
        ctrl.addWidget(clr_btn)
        main_lay.addLayout(ctrl)

        status_lbl = QLabel("")
        main_lay.addWidget(status_lbl)

        def _parse_events():
            events = []
            for i in range(event_list.count()):
                parts = event_list.item(i).text().split()
                if len(parts) < 3:
                    continue
                evt = (mod.MACRO_EVENT_DOWN if parts[0] == "Press"
                       else mod.MACRO_EVENT_UP)
                try:
                    sc = int(parts[-1].strip("()"), 16)
                    events.append((evt, sc))
                except ValueError:
                    pass
            return events

        def _load_slot():
            slot = slot_spin.value()
            event_list.clear()
            if not self._m913_profile:
                return
            macro = self._m913_profile.macros.get(slot)
            if macro and not macro.is_empty():
                sc_to_name = {v: k for k, v in mod.KEY_CODES.items()}
                for evt_type, sc in macro.events:
                    kind = ("Press" if evt_type == mod.MACRO_EVENT_DOWN
                            else "Release")
                    name = sc_to_name.get(sc, f"?{sc:02X}")
                    event_list.addItem(
                        f"{kind:7s} {name}  (0x{sc:02X})")
                status_lbl.setText(
                    f"Loaded slot {slot}: {len(macro.events)} events")
            else:
                status_lbl.setText(f"Slot {slot} is empty")

        def _save_slot():
            slot = slot_spin.value()
            events = _parse_events()
            if not self._m913_profile:
                return
            if not events:
                self._m913_profile.macros.pop(slot, None)
                status_lbl.setText(f"Slot {slot} cleared")
            elif len(events) > mod.MACRO_MAX_ACTIONS:
                status_lbl.setText(
                    f"Too many events "
                    f"({len(events)}/{mod.MACRO_MAX_ACTIONS})")
            else:
                self._m913_profile.macros[slot] = mod.MacroSlot(
                    events=events)
                status_lbl.setText(
                    f"Saved slot {slot}: {len(events)} events")

        bot = QHBoxLayout()
        load_s = QPushButton("Load Slot")
        load_s.clicked.connect(_load_slot)
        bot.addWidget(load_s)
        save_s = QPushButton("Save Slot")
        save_s.clicked.connect(_save_slot)
        bot.addWidget(save_s)
        bot.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        bot.addWidget(close_btn)
        main_lay.addLayout(bot)
        _load_slot()
        dlg.exec()

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
        try:
            mod = _get_razer_mod()
            dev = mod.RazerDevice()
            dev.open(dev_info)
            state = dev.read_full_state()
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
            if state.button_bindings:
                for name, action in state.button_bindings.items():
                    self._razer_profile.button_bindings[name] = action
            self._razer_ui_from_profile()
            self._razer_status.setText(
                f"Read state from {dev_info.display_name}")
            self._main._log_line(
                f"[Razer] State: FW={state.firmware_version}, "
                f"DPI={state.dpi_x}x{state.dpi_y}, "
                f"Poll={state.poll_rate}Hz")
            dev.close()
        except Exception as e:
            self._razer_status.setText(f"Read error: {e}")
            log.error("Razer read failed: %s", e, exc_info=True)

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
        for name, combo in self._razer_button_combos.items():
            p.button_bindings[name] = combo.currentText()
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
        for name, combo in self._razer_button_combos.items():
            action = p.button_bindings.get(name, "default")
            idx = combo.findText(action)
            if idx >= 0:
                combo.setCurrentIndex(idx)
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
        try:
            mod = _get_razer_mod()
            dev = mod.RazerDevice()
            dev.open(dev_info)
            ok, errors = dev.apply_profile(self._razer_profile)
            dev.close()
            if errors:
                self._razer_status.setText(
                    f"Applied with {errors} error(s) — {ok} ok")
            else:
                self._razer_status.setText(
                    f"Applied — {ok} commands to {dev_info.display_name}")
            self._main._log_line(
                f"[Razer] Config applied: {ok} ok, {errors} errors")
        except Exception as e:
            self._razer_status.setText(f"Error: {e}")
            log.error("Razer apply failed: %s", e, exc_info=True)

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
        pass

    def profile_loaded(self, slot: int, profile: dict) -> None:
        pass

    def profile_updated(self, profile: dict) -> None:
        pass

    def apply_theme(self, theme: ThemeEngine) -> None:
        pass
