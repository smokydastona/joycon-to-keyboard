"""Devices view — M913 keypad and Razer mouse configuration.

Merges the old Mouse + Razer tabs into a device management view with
sub-tabs for each peripheral type.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QScrollArea, QSlider,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
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
        self._m913_dev: Any = None
        self._razer_dev: Any = None
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

    # -----------------------------------------------------------------
    # M913 Keypad
    # -----------------------------------------------------------------

    def _build_m913_tab(self) -> None:
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # Header
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

        # Connection status
        status_card = Card(self._main.theme)
        status_lay = QHBoxLayout(status_card)
        status_lay.addWidget(QLabel("Status:"))
        self._m913_status = QLabel("Not connected (connect via USB)")
        self._m913_status.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        status_lay.addWidget(self._m913_status, 1)

        detect_btn = QPushButton("Detect Device")
        detect_btn.setProperty("accent", True)
        detect_btn.clicked.connect(self._detect_m913)
        status_lay.addWidget(detect_btn)
        lay.addWidget(status_card)

        # DPI settings
        dpi_group = QGroupBox("DPI Settings")
        dpi_lay = QVBoxLayout(dpi_group)

        for i in range(4):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"DPI Stage {i + 1}:"))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(200, 12000)
            slider.setSingleStep(100)
            slider.setValue(800 + i * 400)
            row.addWidget(slider)
            val_label = QLabel(f"{800 + i * 400}")
            slider.valueChanged.connect(lambda v, lbl=val_label: lbl.setText(str(v)))
            row.addWidget(val_label)
            dpi_lay.addLayout(row)

        apply_dpi = QPushButton("Apply DPI")
        apply_dpi.setProperty("accent", True)
        apply_dpi.clicked.connect(self._apply_m913_dpi)
        dpi_lay.addWidget(apply_dpi)
        lay.addWidget(dpi_group)

        # Button remapping
        btn_group = QGroupBox("Button Remapping")
        btn_lay = QVBoxLayout(btn_group)
        btn_lay.addWidget(QLabel("Configure side buttons and scroll functions."))

        self._m913_btn_list = QListWidget()
        self._m913_btn_list.setMaximumHeight(150)
        btn_lay.addWidget(self._m913_btn_list)

        lay.addWidget(btn_group)

        # LED settings
        led_group = QGroupBox("LED / Lighting")
        led_lay = QVBoxLayout(led_group)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self._m913_led_mode = QComboBox()
        self._m913_led_mode.addItems(["Steady", "Breathing", "Rainbow", "Off"])
        mode_row.addWidget(self._m913_led_mode)
        led_lay.addLayout(mode_row)

        bright_row = QHBoxLayout()
        bright_row.addWidget(QLabel("Brightness:"))
        self._m913_led_brightness = QSlider(Qt.Orientation.Horizontal)
        self._m913_led_brightness.setRange(0, 100)
        self._m913_led_brightness.setValue(80)
        bright_row.addWidget(self._m913_led_brightness)
        led_lay.addLayout(bright_row)

        apply_led = QPushButton("Apply LED")
        apply_led.clicked.connect(self._apply_m913_led)
        led_lay.addWidget(apply_led)
        lay.addWidget(led_group)

        lay.addStretch()
        self._m913_tab.setWidget(container)

    # -----------------------------------------------------------------
    # Razer Mouse
    # -----------------------------------------------------------------

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

        # Device image
        self._razer_image = QLabel()
        self._razer_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = self._main.assets.load_pixmap("razer_none.png", QSize(400, 300))
        if pm:
            self._razer_image.setPixmap(pm)
        lay.addWidget(self._razer_image)

        # Connection
        status_card = Card(self._main.theme)
        status_lay = QHBoxLayout(status_card)
        status_lay.addWidget(QLabel("Status:"))
        self._razer_status = QLabel("Not connected")
        self._razer_status.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        status_lay.addWidget(self._razer_status, 1)

        detect_btn = QPushButton("Detect Device")
        detect_btn.setProperty("accent", True)
        detect_btn.clicked.connect(self._detect_razer)
        status_lay.addWidget(detect_btn)
        lay.addWidget(status_card)

        # DPI
        dpi_group = QGroupBox("DPI Settings")
        dpi_lay = QVBoxLayout(dpi_group)

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(QLabel("DPI:"))
        self._razer_dpi = QSpinBox()
        self._razer_dpi.setRange(100, 30000)
        self._razer_dpi.setSingleStep(100)
        self._razer_dpi.setValue(800)
        dpi_row.addWidget(self._razer_dpi)

        apply_dpi = QPushButton("Apply")
        apply_dpi.setProperty("accent", True)
        apply_dpi.clicked.connect(self._apply_razer_dpi)
        dpi_row.addWidget(apply_dpi)
        dpi_lay.addLayout(dpi_row)
        lay.addWidget(dpi_group)

        # Polling rate
        poll_group = QGroupBox("Polling Rate")
        poll_lay = QHBoxLayout(poll_group)
        poll_lay.addWidget(QLabel("Rate:"))
        self._razer_polling = QComboBox()
        self._razer_polling.addItems(["125 Hz", "250 Hz", "500 Hz", "1000 Hz"])
        self._razer_polling.setCurrentIndex(3)
        poll_lay.addWidget(self._razer_polling)

        apply_poll = QPushButton("Apply")
        apply_poll.clicked.connect(self._apply_razer_polling)
        poll_lay.addWidget(apply_poll)
        lay.addWidget(poll_group)

        # Hypershift
        hyper_group = QGroupBox("Hypershift")
        hyper_lay = QVBoxLayout(hyper_group)
        self._razer_hypershift = QCheckBox("Enable Hypershift layer")
        hyper_lay.addWidget(self._razer_hypershift)
        hyper_lay.addWidget(QLabel(
            "When enabled, holding the designated button activates "
            "an alternate button mapping layer."
        ))
        lay.addWidget(hyper_group)

        # Button config
        btn_group = QGroupBox("Button Configuration")
        btn_lay = QVBoxLayout(btn_group)
        self._razer_btn_list = QListWidget()
        self._razer_btn_list.setMaximumHeight(150)
        btn_lay.addWidget(self._razer_btn_list)
        lay.addWidget(btn_group)

        lay.addStretch()
        self._razer_tab.setWidget(container)

    # -----------------------------------------------------------------
    # M913 operations
    # -----------------------------------------------------------------

    def _detect_m913(self) -> None:
        try:
            mod = _get_m913_mod()
            dev = mod.M913Device()
            if dev.connect():
                self._m913_dev = dev
                self._m913_status.setText("Connected")
                self._m913_status.setStyleSheet(
                    f"color: {self._main.theme.color('success')};"
                )
                pm = self._main.assets.load_pixmap("m913_connected.png", QSize(400, 300))
                if pm:
                    self._m913_image.setPixmap(pm)
            else:
                self._m913_status.setText("Device not found")
                self._m913_status.setStyleSheet(
                    f"color: {self._main.theme.color('danger')};"
                )
        except Exception as e:
            self._m913_status.setText(f"Error: {e}")
            log.error("M913 detect failed: %s", e, exc_info=True)

    def _apply_m913_dpi(self) -> None:
        log.info("Applying M913 DPI settings")

    def _apply_m913_led(self) -> None:
        log.info("Applying M913 LED settings")

    # -----------------------------------------------------------------
    # Razer operations
    # -----------------------------------------------------------------

    def _detect_razer(self) -> None:
        try:
            mod = _get_razer_mod()
            dev = mod.RazerDevice()
            if dev.connect():
                self._razer_dev = dev
                self._razer_status.setText("Connected")
                self._razer_status.setStyleSheet(
                    f"color: {self._main.theme.color('success')};"
                )
                pm = self._main.assets.load_pixmap("razer_connected.png", QSize(400, 300))
                if pm:
                    self._razer_image.setPixmap(pm)
            else:
                self._razer_status.setText("Device not found")
                self._razer_status.setStyleSheet(
                    f"color: {self._main.theme.color('danger')};"
                )
        except Exception as e:
            self._razer_status.setText(f"Error: {e}")
            log.error("Razer detect failed: %s", e, exc_info=True)
            log.error("Razer detect failed: %s", e, exc_info=True)

    def _apply_razer_dpi(self) -> None:
        log.info("Applying Razer DPI: %d", self._razer_dpi.value())

    def _apply_razer_polling(self) -> None:
        log.info("Applying Razer polling rate: %s", self._razer_polling.currentText())

    # -----------------------------------------------------------------
    # Slot changed — auto-apply linked M913 / Razer profiles
    # -----------------------------------------------------------------

    def slot_changed(self, slot: int) -> None:
        """Called when the active Joy-Con slot changes (manual or app-switch).

        Scans saved M913 and Razer profiles for any whose ``sister_slot``
        matches *slot* and applies the first match to the connected device.
        """
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
                log.info("M913 auto-switch: loaded '%s' (sister_slot=%d)", name, slot)
                if self._m913_dev and self._m913_dev.is_open:
                    try:
                        self._m913_dev.apply_profile(profile)
                        self._m913_status.setText(f"Linked: {name}")
                        self._m913_status.setStyleSheet(
                            f"color: {self._main.theme.color('success')};"
                        )
                        self._main._log_line(f"[m913] Auto-applied profile '{name}' for slot {slot}")
                    except Exception as e:
                        log.warning("M913 auto-apply failed: %s", e)
                else:
                    self._main._log_line(f"[m913] Linked profile '{name}' ready (device not connected)")
                return
        # No linked profile for this slot
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
                log.info("Razer auto-switch: loaded '%s' (sister_slot=%d)", name, slot)
                if self._razer_dev and self._razer_dev.is_open:
                    try:
                        self._razer_dev.apply_profile(profile)
                        self._razer_status.setText(f"Linked: {name}")
                        self._razer_status.setStyleSheet(
                            f"color: {self._main.theme.color('success')};"
                        )
                        self._main._log_line(f"[razer] Auto-applied profile '{name}' for slot {slot}")
                    except Exception as e:
                        log.warning("Razer auto-apply failed: %s", e)
                else:
                    self._main._log_line(f"[razer] Linked profile '{name}' ready (device not connected)")
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
