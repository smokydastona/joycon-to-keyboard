"""Settings view — dedicated full-panel settings with categorised cards.

Provides five sections: General, Serial, Input (Key Pops), Profiles, and
Developer Tools.  All settings persist via QSettings.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..theme import ThemeEngine
from ..widgets.card import Card

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.settings")


class SettingsView(QScrollArea):
    """Full-page settings panel with themed card sections."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main
        self._settings = QSettings()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(20)

        # Title
        title = QLabel("Settings")
        title.setFont(QFont(
            main.theme.typo("font_family_decorative"),
            main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        self._layout.addWidget(title)

        self._build_general_card()
        self._build_serial_card()
        self._build_input_card()
        self._build_profiles_card()
        self._build_developer_card()

        self._layout.addStretch()
        self.setWidget(container)

    # -----------------------------------------------------------------
    # General
    # -----------------------------------------------------------------
    def _build_general_card(self) -> None:
        card = Card(self._main.theme, padding=16)
        card_layout = QVBoxLayout(card)

        header = QLabel("General")
        header.setFont(QFont(
            self._main.theme.typo("font_family"),
            12, QFont.Weight.Bold,
        ))
        card_layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)

        # Theme selector
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Dark", "Light", "Heist"])
        _mode_to_idx = {"dark": 0, "light": 1, "heist": 2}
        self._theme_combo.setCurrentIndex(
            _mode_to_idx.get(self._main.theme.mode_name, 0))
        self._theme_combo.setToolTip(
            "Application colour scheme\n"
            "Heist: blueprint-navy tactical board aesthetic")
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        form.addRow("Theme:", self._theme_combo)

        # Minimise to tray
        self._cb_tray = QCheckBox("Minimize to system tray on close")
        self._cb_tray.setChecked(self._settings.value("minimize_to_tray", False, type=bool))
        self._cb_tray.setToolTip("Keep the app running in the system tray when you close the window")
        self._cb_tray.toggled.connect(lambda v: self._settings.setValue("minimize_to_tray", v))
        form.addRow(self._cb_tray)

        # Start minimised
        self._cb_start_min = QCheckBox("Start minimized to tray")
        self._cb_start_min.setChecked(self._settings.value("start_minimized", False, type=bool))
        self._cb_start_min.setToolTip("Launch the app hidden in the system tray")
        self._cb_start_min.toggled.connect(lambda v: self._settings.setValue("start_minimized", v))
        form.addRow(self._cb_start_min)

        # Auto-start with Windows
        self._cb_autostart = QCheckBox("Start with Windows")
        self._cb_autostart.setChecked(self._main._is_autostart_enabled())
        self._cb_autostart.setToolTip("Automatically launch the app when you log in")
        self._cb_autostart.toggled.connect(lambda v: self._main._set_autostart(v))
        form.addRow(self._cb_autostart)

        # Auto-connect
        self._cb_auto_conn = QCheckBox("Auto-connect to last serial port")
        self._cb_auto_conn.setChecked(self._settings.value("auto_connect", True, type=bool))
        self._cb_auto_conn.setToolTip("Automatically reconnect to the last used COM port on startup")
        self._cb_auto_conn.toggled.connect(lambda v: self._settings.setValue("auto_connect", v))
        form.addRow(self._cb_auto_conn)

        card_layout.addLayout(form)
        self._layout.addWidget(card)

    # -----------------------------------------------------------------
    # Serial
    # -----------------------------------------------------------------
    def _build_serial_card(self) -> None:
        card = Card(self._main.theme, padding=16)
        card_layout = QVBoxLayout(card)

        header = QLabel("Serial Connection")
        header.setFont(QFont(
            self._main.theme.typo("font_family"),
            12, QFont.Weight.Bold,
        ))
        card_layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)

        # Baud rate
        self._baud_combo = QComboBox()
        self._baud_combo.addItems(["115200", "230400", "460800", "921600"])
        current_baud = str(self._settings.value("baud_rate", "115200"))
        idx = self._baud_combo.findText(current_baud)
        if idx >= 0:
            self._baud_combo.setCurrentIndex(idx)
        self._baud_combo.setToolTip("Serial baud rate — must match the ESP32-S3 firmware setting")
        self._baud_combo.currentTextChanged.connect(
            lambda v: self._settings.setValue("baud_rate", v))
        form.addRow("Baud rate:", self._baud_combo)

        # Reconnect interval
        self._reconnect_spin = QSpinBox()
        self._reconnect_spin.setRange(0, 60)
        self._reconnect_spin.setSuffix(" sec")
        self._reconnect_spin.setSpecialValueText("Disabled")
        self._reconnect_spin.setValue(self._settings.value("reconnect_interval", 5, type=int))
        self._reconnect_spin.setToolTip(
            "Seconds between automatic reconnect attempts (0 = disabled)")
        self._reconnect_spin.valueChanged.connect(
            lambda v: self._settings.setValue("reconnect_interval", v))
        form.addRow("Auto-reconnect interval:", self._reconnect_spin)

        # Serial timeout
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 30)
        self._timeout_spin.setSuffix(" sec")
        self._timeout_spin.setValue(self._settings.value("serial_timeout", 5, type=int))
        self._timeout_spin.setToolTip("How long to wait for a serial response before timing out")
        self._timeout_spin.valueChanged.connect(
            lambda v: self._settings.setValue("serial_timeout", v))
        form.addRow("Read timeout:", self._timeout_spin)

        card_layout.addLayout(form)
        self._layout.addWidget(card)

    # -----------------------------------------------------------------
    # Input / Key Pops
    # -----------------------------------------------------------------
    def _build_input_card(self) -> None:
        card = Card(self._main.theme, padding=16)
        card_layout = QVBoxLayout(card)

        header = QLabel("Input & Key Pops")
        header.setFont(QFont(
            self._main.theme.typo("font_family"),
            12, QFont.Weight.Bold,
        ))
        card_layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)

        # Key pop enable
        self._cb_keypop = QCheckBox("Enable Key Pop overlay")
        self._cb_keypop.setChecked(self._settings.value("keypop_enabled", True, type=bool))
        self._cb_keypop.setToolTip("Show a floating key-press indicator on screen")
        self._cb_keypop.toggled.connect(lambda v: self._settings.setValue("keypop_enabled", v))
        form.addRow(self._cb_keypop)

        # Key pop style
        self._keypop_style = QComboBox()
        self._keypop_style.addItems(["Classic", "Bubble", "Minimal"])
        style_idx = {"classic": 0, "bubble": 1, "minimal": 2}.get(
            str(self._settings.value("keypop_style", "bubble")).lower(), 1)
        self._keypop_style.setCurrentIndex(style_idx)
        self._keypop_style.setToolTip("Visual appearance of key pop notifications")
        self._keypop_style.currentTextChanged.connect(
            lambda v: self._settings.setValue("keypop_style", v.lower()))
        form.addRow("Style:", self._keypop_style)

        # Opacity
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 100)
        ov = int(self._settings.value("overlay_opacity", 0.85, type=float) * 100)
        self._opacity_slider.setValue(ov)
        self._opacity_slider.setToolTip("Overlay transparency (20–100%)")
        self._opacity_label = QLabel(f"{ov}%")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        row = QHBoxLayout()
        row.addWidget(self._opacity_slider)
        row.addWidget(self._opacity_label)
        form.addRow("Opacity:", row)

        # Auto-hide
        self._autohide_spin = QSpinBox()
        self._autohide_spin.setRange(0, 300)
        self._autohide_spin.setSuffix(" sec")
        self._autohide_spin.setSpecialValueText("Disabled")
        self._autohide_spin.setValue(self._settings.value("overlay_auto_hide", 0, type=int))
        self._autohide_spin.setToolTip("Hide overlay after N seconds of no input (0 = never)")
        self._autohide_spin.valueChanged.connect(
            lambda v: self._settings.setValue("overlay_auto_hide", v))
        form.addRow("Auto-hide after:", self._autohide_spin)

        # Key pop size
        self._keypop_size = QComboBox()
        self._keypop_size.addItems(["Small", "Medium", "Large"])
        size_idx = {"small": 0, "medium": 1, "large": 2}.get(
            str(self._settings.value("keypop_size", "medium")).lower(), 1)
        self._keypop_size.setCurrentIndex(size_idx)
        self._keypop_size.setToolTip("Size of the key pop indicator")
        self._keypop_size.currentTextChanged.connect(
            lambda v: self._settings.setValue("keypop_size", v.lower()))
        form.addRow("Pop size:", self._keypop_size)

        # Fade speed
        self._fade_slider = QSlider(Qt.Orientation.Horizontal)
        self._fade_slider.setRange(500, 3000)
        self._fade_slider.setValue(self._settings.value("keypop_fade_ms", 1500, type=int))
        self._fade_slider.setToolTip("How long the key pop stays visible (500–3000 ms)")
        self._fade_label = QLabel(f"{self._fade_slider.value()} ms")
        self._fade_slider.valueChanged.connect(self._on_fade_changed)
        fade_row = QHBoxLayout()
        fade_row.addWidget(self._fade_slider)
        fade_row.addWidget(self._fade_label)
        form.addRow("Fade speed:", fade_row)

        # Placement
        self._placement_combo = QComboBox()
        self._placement_combo.addItems([
            "Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right", "Custom",
        ])
        placement_idx = {
            "top-left": 0, "top-right": 1, "bottom-left": 2,
            "bottom-right": 3, "custom": 4,
        }.get(str(self._settings.value("keypop_placement", "top-right")).lower(), 1)
        self._placement_combo.setCurrentIndex(placement_idx)
        self._placement_combo.setToolTip("Where the key pop appears on screen")
        self._placement_combo.currentTextChanged.connect(
            lambda v: self._settings.setValue("keypop_placement", v.lower()))
        form.addRow("Placement:", self._placement_combo)

        # Show input / output / both
        self._keypop_show = QComboBox()
        self._keypop_show.addItems(["Input Only", "Output Only", "Both"])
        show_idx = {"input": 0, "output": 1, "both": 2}.get(
            str(self._settings.value("keypop_show", "both")).lower(), 2)
        self._keypop_show.setCurrentIndex(show_idx)
        self._keypop_show.setToolTip("What to display in the key pop")
        self._keypop_show.currentTextChanged.connect(
            lambda v: self._settings.setValue("keypop_show", v.split()[0].lower()))
        form.addRow("Display:", self._keypop_show)

        card_layout.addLayout(form)
        self._layout.addWidget(card)

    # -----------------------------------------------------------------
    # Profiles
    # -----------------------------------------------------------------
    def _build_profiles_card(self) -> None:
        card = Card(self._main.theme, padding=16)
        card_layout = QVBoxLayout(card)

        header = QLabel("Profiles")
        header.setFont(QFont(
            self._main.theme.typo("font_family"),
            12, QFont.Weight.Bold,
        ))
        card_layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)

        # Auto-save
        self._cb_autosave = QCheckBox("Auto-save profile after changes")
        self._cb_autosave.setChecked(self._settings.value("profile_autosave", True, type=bool))
        self._cb_autosave.setToolTip("Automatically upload the profile to the device after editing")
        self._cb_autosave.toggled.connect(
            lambda v: self._settings.setValue("profile_autosave", v))
        form.addRow(self._cb_autosave)

        # Default slot
        self._default_slot = QComboBox()
        self._default_slot.addItems(["Slot 0", "Slot 1", "Slot 2", "Slot 3"])
        self._default_slot.setCurrentIndex(
            self._settings.value("default_slot", 0, type=int))
        self._default_slot.setToolTip("Profile slot to load on startup")
        self._default_slot.currentIndexChanged.connect(
            lambda v: self._settings.setValue("default_slot", v))
        form.addRow("Default slot:", self._default_slot)

        # Export / Import all
        btn_row = QHBoxLayout()
        export_btn = QPushButton("Export All Profiles")
        export_btn.setToolTip("Save all 4 profile slots to a JSON file")
        export_btn.clicked.connect(self._export_all_profiles)
        btn_row.addWidget(export_btn)

        import_btn = QPushButton("Import All Profiles")
        import_btn.setToolTip("Load all 4 profile slots from a JSON file")
        import_btn.clicked.connect(self._import_all_profiles)
        btn_row.addWidget(import_btn)
        form.addRow(btn_row)

        card_layout.addLayout(form)
        self._layout.addWidget(card)

    # -----------------------------------------------------------------
    # Developer Tools
    # -----------------------------------------------------------------
    def _build_developer_card(self) -> None:
        card = Card(self._main.theme, padding=16)
        card_layout = QVBoxLayout(card)

        header = QLabel("Developer Tools")
        header.setFont(QFont(
            self._main.theme.typo("font_family"),
            12, QFont.Weight.Bold,
        ))
        card_layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(10)

        # Log level
        self._log_combo = QComboBox()
        self._log_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        current_level = str(self._settings.value("log_level", "INFO"))
        idx = self._log_combo.findText(current_level)
        if idx >= 0:
            self._log_combo.setCurrentIndex(idx)
        self._log_combo.setToolTip("Console and file log verbosity")
        self._log_combo.currentTextChanged.connect(self._on_log_level_changed)
        form.addRow("Log level:", self._log_combo)

        # Verbose logging
        self._cb_verbose = QCheckBox("Verbose serial logging")
        self._cb_verbose.setChecked(self._settings.value("verbose_serial", False, type=bool))
        self._cb_verbose.setToolTip("Log every raw serial byte for debugging")
        self._cb_verbose.toggled.connect(
            lambda v: self._settings.setValue("verbose_serial", v))
        form.addRow(self._cb_verbose)

        # Raw HID log
        self._cb_raw_hid = QCheckBox("Show raw HID reports in log")
        self._cb_raw_hid.setChecked(self._settings.value("raw_hid_log", False, type=bool))
        self._cb_raw_hid.setToolTip("Display raw HID keyboard report bytes in the device log")
        self._cb_raw_hid.toggled.connect(
            lambda v: self._settings.setValue("raw_hid_log", v))
        form.addRow(self._cb_raw_hid)

        # Latency graph
        self._cb_latency = QCheckBox("Show latency graph on Dashboard")
        self._cb_latency.setChecked(self._settings.value("show_latency_graph", False, type=bool))
        self._cb_latency.setToolTip("Display a real-time latency graph on the Dashboard view")
        self._cb_latency.toggled.connect(
            lambda v: self._settings.setValue("show_latency_graph", v))
        form.addRow(self._cb_latency)

        # Debug bundle export
        debug_btn = QPushButton("Export Debug Bundle")
        debug_btn.setToolTip("Save logs, settings, and profile data to a ZIP file for support")
        debug_btn.clicked.connect(self._export_debug_bundle)
        form.addRow(debug_btn)

        # Onboarding reset
        onboard_btn = QPushButton("Show Onboarding Wizard")
        onboard_btn.setToolTip("Re-run the first-time setup wizard on next launch")
        onboard_btn.clicked.connect(self._reset_onboarding)
        form.addRow(onboard_btn)

        card_layout.addLayout(form)
        self._layout.addWidget(card)

    # -----------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------

    def _on_theme_changed(self, value: str | int) -> None:
        # Accept both text (new) and legacy index (belt-and-suspenders).
        if isinstance(value, int):
            value = ["dark", "light", "heist"][value] if value < 3 else "dark"
        mode = value.lower()
        if mode != self._main.theme.mode_name:
            self._main._set_theme_mode(mode)

    def _on_opacity_changed(self, value: int) -> None:
        self._opacity_label.setText(f"{value}%")
        self._settings.setValue("overlay_opacity", value / 100.0)
        if self._main._overlay and not self._main._overlay.is_closed:
            self._main._overlay._set_opacity(value / 100.0)

    def _on_fade_changed(self, value: int) -> None:
        self._fade_label.setText(f"{value} ms")
        self._settings.setValue("keypop_fade_ms", value)

    def _on_log_level_changed(self, level: str) -> None:
        self._settings.setValue("log_level", level)
        logging.getLogger().setLevel(getattr(logging, level, logging.INFO))

    def _export_all_profiles(self) -> None:
        import json

        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export All Profiles", "bind_bandit_profiles.json",
            "JSON (*.json)")
        if not path:
            return
        try:
            data = {"slot_count": 4, "profiles": {}}
            # Gather profiles from the main window's state
            data["profiles"][str(self._main._slot)] = self._main.get_profile()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            from ..widgets.toast import Toast
            Toast.success(self, f"Profiles exported to {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _import_all_profiles(self) -> None:
        import json

        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import All Profiles", "",
            "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles", {})
            if profiles:
                # Load the first available profile
                for _slot_str, profile in profiles.items():
                    self._main.set_profile(profile)
                    break
            from ..widgets.toast import Toast
            Toast.success(self, "Profiles imported successfully")
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))

    def _export_debug_bundle(self) -> None:
        import json
        import zipfile

        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Debug Bundle", "bind_bandit_debug.zip",
            "ZIP (*.zip)")
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                # Settings
                settings_data = {}
                for key in self._settings.allKeys():
                    settings_data[key] = str(self._settings.value(key))
                zf.writestr("settings.json",
                            json.dumps(settings_data, indent=2, ensure_ascii=False))

                # Current profile
                profile = self._main.get_profile()
                zf.writestr("current_profile.json",
                            json.dumps(profile, indent=2, ensure_ascii=False))

                # Log file
                log_dir = os.path.join(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))), "logs")
                if os.path.isdir(log_dir):
                    for fname in os.listdir(log_dir):
                        fpath = os.path.join(log_dir, fname)
                        if os.path.isfile(fpath):
                            zf.write(fpath, f"logs/{fname}")

            from ..widgets.toast import Toast
            Toast.success(self, f"Debug bundle saved to {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _reset_onboarding(self) -> None:
        self._settings.setValue("onboarding_done", False)
        QMessageBox.information(
            self, "Onboarding",
            "The onboarding wizard will show on next launch.")

    # -----------------------------------------------------------------
    # View protocol
    # -----------------------------------------------------------------

    def apply_theme(self, theme: ThemeEngine) -> None:
        # Re-apply card themes
        for child in self.widget().findChildren(Card):
            child.apply_theme(theme)

    def device_event(self, obj: dict) -> None:
        pass

    def profile_loaded(self, slot: int, profile: dict) -> None:
        pass

    def profile_updated(self, profile: dict) -> None:
        pass

    def slot_changed(self, slot: int) -> None:
        pass

    def connection_changed(self, connected: bool) -> None:
        pass
