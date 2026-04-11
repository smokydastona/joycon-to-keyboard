"""Gyro & Zones view — gyro-to-mouse config, stick zones, and activators.

Provides sub-tabs for:
  1. Gyro Settings — enable/disable, sensitivity, deadzone, acceleration, inversion.
  2. Zones Editor — define stick-region zones that trigger key outputs.
  3. Activators Editor — define trigger-based actions (press/release/double/long/chord).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets.card import Card

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.gyro_zones")

ZONE_SHAPES = ["circle", "ring", "wedge", "rect"]
ACTIVATOR_TRIGGERS = ["press", "release", "double_press", "long_press", "chord"]
ACCEL_TYPES = ["none", "power", "smooth"]
LED_PATTERNS = ["off", "solid", "blink", "pulse", "rainbow"]


class GyroZonesView(QWidget):
    """Combined view for gyro, zones, and activators configuration."""

    def __init__(self, parent: MainWindow) -> None:
        super().__init__(parent)
        self._mw = parent

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._build_gyro_tab(), "Gyro Settings")
        self._tabs.addTab(self._build_zones_tab(), "Zones")
        self._tabs.addTab(self._build_activators_tab(), "Activators")
        self._tabs.addTab(self._build_cal_led_tab(), "Calibration & LED")

        # Calibration poll timer
        self._cal_timer = QTimer(self)
        self._cal_timer.setInterval(250)
        self._cal_timer.timeout.connect(self._poll_cal_status)

    # ------------------------------------------------------------------
    # Gyro Settings Tab
    # ------------------------------------------------------------------
    def _build_gyro_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll.setWidget(container)
        vbox = QVBoxLayout(container)

        # Enable toggle
        enable_card = Card(self._mw.theme)
        enable_lay = QVBoxLayout(enable_card)
        enable_lay.addWidget(QLabel("🎯  Gyro Enable"))
        self._gyro_enabled = QCheckBox("Enable gyro-to-mouse")
        enable_lay.addWidget(self._gyro_enabled)
        vbox.addWidget(enable_card)

        # Sensitivity
        sens_card = Card(self._mw.theme)
        sens_lay = QVBoxLayout(sens_card)
        sens_lay.addWidget(QLabel("📐  Sensitivity"))

        sx_row = QHBoxLayout()
        sx_row.addWidget(QLabel("X (yaw):"))
        self._sens_x = QSlider(Qt.Orientation.Horizontal)
        self._sens_x.setRange(10, 500)
        self._sens_x.setValue(100)
        self._sens_x_label = QLabel("100")
        self._sens_x.valueChanged.connect(lambda v: self._sens_x_label.setText(str(v)))
        sx_row.addWidget(self._sens_x)
        sx_row.addWidget(self._sens_x_label)
        sens_lay.addLayout(sx_row)

        sy_row = QHBoxLayout()
        sy_row.addWidget(QLabel("Y (pitch):"))
        self._sens_y = QSlider(Qt.Orientation.Horizontal)
        self._sens_y.setRange(10, 500)
        self._sens_y.setValue(100)
        self._sens_y_label = QLabel("100")
        self._sens_y.valueChanged.connect(lambda v: self._sens_y_label.setText(str(v)))
        sy_row.addWidget(self._sens_y)
        sy_row.addWidget(self._sens_y_label)
        sens_lay.addLayout(sy_row)
        vbox.addWidget(sens_card)

        # Deadzone
        dz_card = Card(self._mw.theme)
        dz_lay = QVBoxLayout(dz_card)
        dz_lay.addWidget(QLabel("⭕  Deadzone"))
        dz_row = QHBoxLayout()
        dz_row.addWidget(QLabel("Threshold:"))
        self._dz = QSpinBox()
        self._dz.setRange(0, 500)
        self._dz.setValue(50)
        dz_row.addWidget(self._dz)
        dz_lay.addLayout(dz_row)
        vbox.addWidget(dz_card)

        # Acceleration
        accel_card = Card(self._mw.theme)
        accel_lay = QVBoxLayout(accel_card)
        accel_lay.addWidget(QLabel("📈  Acceleration Curve"))

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._accel_type = QComboBox()
        self._accel_type.addItems(ACCEL_TYPES)
        type_row.addWidget(self._accel_type)
        accel_lay.addLayout(type_row)

        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("Parameter:"))
        self._accel_param = QSpinBox()
        self._accel_param.setRange(50, 500)
        self._accel_param.setValue(150)
        param_row.addWidget(self._accel_param)
        accel_lay.addLayout(param_row)
        vbox.addWidget(accel_card)

        # Inversion
        inv_card = Card(self._mw.theme)
        inv_lay = QVBoxLayout(inv_card)
        inv_lay.addWidget(QLabel("🔄  Axis Inversion"))
        inv_row = QHBoxLayout()
        self._invert_x = QCheckBox("Invert X")
        self._invert_y = QCheckBox("Invert Y")
        inv_row.addWidget(self._invert_x)
        inv_row.addWidget(self._invert_y)
        inv_lay.addLayout(inv_row)
        vbox.addWidget(inv_card)

        # Flick Stick
        flick_card = Card(self._mw.theme)
        flick_lay = QVBoxLayout(flick_card)
        flick_lay.addWidget(QLabel("🕹  Flick Stick"))
        self._flick_enabled = QCheckBox("Enable flick stick (right stick)")
        flick_lay.addWidget(self._flick_enabled)

        ft_row = QHBoxLayout()
        ft_row.addWidget(QLabel("Threshold:"))
        self._flick_threshold = QSpinBox()
        self._flick_threshold.setRange(500, 4096)
        self._flick_threshold.setValue(3000)
        ft_row.addWidget(self._flick_threshold)
        flick_lay.addLayout(ft_row)

        fs_row = QHBoxLayout()
        fs_row.addWidget(QLabel("Snap (degrees, 0=off):"))
        self._flick_snap = QSpinBox()
        self._flick_snap.setRange(0, 180)
        self._flick_snap.setValue(0)
        fs_row.addWidget(self._flick_snap)
        flick_lay.addLayout(fs_row)
        vbox.addWidget(flick_card)

        # Stick Acceleration Curve
        sa_card = Card(self._mw.theme)
        sa_lay = QVBoxLayout(sa_card)
        sa_lay.addWidget(QLabel("📊  Stick Acceleration Curve"))

        sat_row = QHBoxLayout()
        sat_row.addWidget(QLabel("Type:"))
        self._stick_accel_type = QComboBox()
        self._stick_accel_type.addItems(["linear", "power", "s-curve"])
        sat_row.addWidget(self._stick_accel_type)
        sa_lay.addLayout(sat_row)

        sap_row = QHBoxLayout()
        sap_row.addWidget(QLabel("Parameter:"))
        self._stick_accel_param = QSpinBox()
        self._stick_accel_param.setRange(50, 500)
        self._stick_accel_param.setValue(200)
        sap_row.addWidget(self._stick_accel_param)
        sa_lay.addLayout(sap_row)
        vbox.addWidget(sa_card)

        # Apply button
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply Gyro Settings")
        apply_btn.clicked.connect(self._apply_gyro)
        btn_row.addStretch()
        btn_row.addWidget(apply_btn)
        vbox.addLayout(btn_row)

        vbox.addStretch()
        return scroll

    # ------------------------------------------------------------------
    # Calibration & LED Tab
    # ------------------------------------------------------------------
    def _build_cal_led_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll.setWidget(container)
        vbox = QVBoxLayout(container)

        # --- Gyro Calibration ---
        cal_card = Card(self._mw.theme)
        cal_lay = QVBoxLayout(cal_card)
        cal_lay.addWidget(QLabel("🧭  Gyro Calibration"))
        cal_lay.addWidget(QLabel(
            "Place the controller flat and still, then click Calibrate.\n"
            "128 gyro samples will be averaged to compute bias offsets."
        ))

        self._cal_btn = QPushButton("Calibrate Gyro")
        self._cal_btn.clicked.connect(self._start_calibration)
        cal_lay.addWidget(self._cal_btn)

        self._cal_progress = QProgressBar()
        self._cal_progress.setRange(0, 0)  # indeterminate
        self._cal_progress.setVisible(False)
        cal_lay.addWidget(self._cal_progress)

        self._cal_status_label = QLabel("Status: idle")
        cal_lay.addWidget(self._cal_status_label)

        # Current bias display
        bias_group = QGroupBox("Current Gyro Bias")
        bias_lay = QHBoxLayout(bias_group)
        bias_lay.addWidget(QLabel("X:"))
        self._bias_x = QSpinBox()
        self._bias_x.setRange(-32768, 32767)
        bias_lay.addWidget(self._bias_x)
        bias_lay.addWidget(QLabel("Y:"))
        self._bias_y = QSpinBox()
        self._bias_y.setRange(-32768, 32767)
        bias_lay.addWidget(self._bias_y)
        bias_lay.addWidget(QLabel("Z:"))
        self._bias_z = QSpinBox()
        self._bias_z.setRange(-32768, 32767)
        bias_lay.addWidget(self._bias_z)
        cal_lay.addWidget(bias_group)

        bias_btn_row = QHBoxLayout()
        read_bias_btn = QPushButton("Read Bias from Device")
        read_bias_btn.clicked.connect(self._read_bias)
        set_bias_btn = QPushButton("Set Bias Manually")
        set_bias_btn.clicked.connect(self._set_bias)
        bias_btn_row.addWidget(read_bias_btn)
        bias_btn_row.addWidget(set_bias_btn)
        bias_btn_row.addStretch()
        cal_lay.addLayout(bias_btn_row)

        vbox.addWidget(cal_card)

        # --- LED Control ---
        led_card = Card(self._mw.theme)
        led_lay = QVBoxLayout(led_card)
        led_lay.addWidget(QLabel("💡  LED Control"))

        pat_row = QHBoxLayout()
        pat_row.addWidget(QLabel("Pattern:"))
        self._led_pattern = QComboBox()
        self._led_pattern.addItems(LED_PATTERNS)
        pat_row.addWidget(self._led_pattern)
        led_lay.addLayout(pat_row)

        rgb_row = QHBoxLayout()
        rgb_row.addWidget(QLabel("R:"))
        self._led_r = QSpinBox()
        self._led_r.setRange(0, 255)
        self._led_r.setValue(0)
        rgb_row.addWidget(self._led_r)
        rgb_row.addWidget(QLabel("G:"))
        self._led_g = QSpinBox()
        self._led_g.setRange(0, 255)
        self._led_g.setValue(0)
        rgb_row.addWidget(self._led_g)
        rgb_row.addWidget(QLabel("B:"))
        self._led_b = QSpinBox()
        self._led_b.setRange(0, 255)
        self._led_b.setValue(255)
        rgb_row.addWidget(self._led_b)
        led_lay.addLayout(rgb_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed (ms):"))
        self._led_speed = QSpinBox()
        self._led_speed.setRange(50, 10000)
        self._led_speed.setValue(500)
        speed_row.addWidget(self._led_speed)
        led_lay.addLayout(speed_row)

        led_btn = QPushButton("Apply LED")
        led_btn.clicked.connect(self._apply_led)
        led_lay.addWidget(led_btn)

        vbox.addWidget(led_card)

        vbox.addStretch()
        return scroll

    # --- Calibration actions ---
    def _start_calibration(self) -> None:
        if not self._mw.bridge.is_connected:
            self._cal_status_label.setText("Status: not connected")
            return
        self._mw.bridge.send_cmd({"cmd": "gyro_cal_start"})
        self._cal_btn.setEnabled(False)
        self._cal_progress.setVisible(True)
        self._cal_status_label.setText("Status: calibrating…")
        self._cal_timer.start()

    def _poll_cal_status(self) -> None:
        if not self._mw.bridge.is_connected:
            self._cal_timer.stop()
            self._cal_btn.setEnabled(True)
            self._cal_progress.setVisible(False)
            self._cal_status_label.setText("Status: disconnected during cal")
            return
        self._mw.bridge.send_cmd({"cmd": "gyro_cal_status"})
        # Response will arrive asynchronously; we check via a callback
        # registered in serial_client or via the general message handler.
        # For simplicity, poll the bridge's last_reply if available.
        reply = getattr(self._mw.bridge, "last_reply", None)
        if reply and reply.get("cmd") == "gyro_cal_status":
            active = reply.get("active", False)
            if not active:
                self._cal_timer.stop()
                self._cal_btn.setEnabled(True)
                self._cal_progress.setVisible(False)
                bx = reply.get("bias_x", 0)
                by = reply.get("bias_y", 0)
                bz = reply.get("bias_z", 0)
                self._bias_x.setValue(bx)
                self._bias_y.setValue(by)
                self._bias_z.setValue(bz)
                self._cal_status_label.setText(
                    f"Status: done — bias=({bx}, {by}, {bz})"
                )
                log.info("Gyro calibration done: bias=(%d, %d, %d)", bx, by, bz)

    def _read_bias(self) -> None:
        if not self._mw.bridge.is_connected:
            return
        self._mw.bridge.send_cmd({"cmd": "gyro_cal_status"})
        reply = getattr(self._mw.bridge, "last_reply", None)
        if reply and reply.get("cmd") == "gyro_cal_status":
            self._bias_x.setValue(reply.get("bias_x", 0))
            self._bias_y.setValue(reply.get("bias_y", 0))
            self._bias_z.setValue(reply.get("bias_z", 0))

    def _set_bias(self) -> None:
        if not self._mw.bridge.is_connected:
            return
        self._mw.bridge.send_cmd({
            "cmd": "gyro_cal_set",
            "bias_x": self._bias_x.value(),
            "bias_y": self._bias_y.value(),
            "bias_z": self._bias_z.value(),
        })
        self._cal_status_label.setText(
            f"Status: bias set to ({self._bias_x.value()}, "
            f"{self._bias_y.value()}, {self._bias_z.value()})"
        )
        log.info("Manually set gyro bias: (%d, %d, %d)",
                 self._bias_x.value(), self._bias_y.value(), self._bias_z.value())

    # --- LED actions ---
    def _apply_led(self) -> None:
        if not self._mw.bridge.is_connected:
            return
        self._mw.bridge.send_cmd({
            "cmd": "set_led",
            "pattern": self._led_pattern.currentIndex(),
            "r": self._led_r.value(),
            "g": self._led_g.value(),
            "b": self._led_b.value(),
            "speed": self._led_speed.value(),
        })
        log.info("Sent LED config: pattern=%s r=%d g=%d b=%d speed=%d",
                 self._led_pattern.currentText(), self._led_r.value(),
                 self._led_g.value(), self._led_b.value(), self._led_speed.value())

    # ------------------------------------------------------------------
    # Gyro apply
    # ------------------------------------------------------------------
    def _apply_gyro(self) -> None:
        """Send gyro + flick stick + stick accel config."""
        gyro = {
            "enabled": self._gyro_enabled.isChecked(),
            "sensitivity_x": self._sens_x.value(),
            "sensitivity_y": self._sens_y.value(),
            "deadzone": self._dz.value(),
            "accel_type": self._accel_type.currentIndex(),
            "accel_param": self._accel_param.value(),
            "invert_x": self._invert_x.isChecked(),
            "invert_y": self._invert_y.isChecked(),
        }
        flick_stick = {
            "enabled": self._flick_enabled.isChecked(),
            "threshold": self._flick_threshold.value(),
            "snap_degrees": self._flick_snap.value(),
        }
        stick_accel = {
            "type": self._stick_accel_type.currentIndex(),
            "param": self._stick_accel_param.value(),
        }
        if self._mw.bridge.is_connected:
            self._mw.bridge.send_cmd({
                "cmd": "set_gyro",
                "gyro": gyro,
                "flick_stick": flick_stick,
                "stick_accel": stick_accel,
            })
            log.info("Sent gyro/flick/accel config")

    # ------------------------------------------------------------------
    # Zones Tab
    # ------------------------------------------------------------------
    def _build_zones_tab(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)

        self._zone_table = QTableWidget(0, 7)
        self._zone_table.setHorizontalHeaderLabels([
            "Shape", "CX", "CY", "Param1", "Param2", "Output Key", "Actions",
        ])
        header = self._zone_table.horizontalHeader()
        if header:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        vbox.addWidget(self._zone_table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Zone")
        add_btn.clicked.connect(self._add_zone_row)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_zone_row)
        apply_btn = QPushButton("Apply Zones")
        apply_btn.clicked.connect(self._apply_zones)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(apply_btn)
        vbox.addLayout(btn_row)

        return w

    def _add_zone_row(self) -> None:
        row = self._zone_table.rowCount()
        self._zone_table.insertRow(row)

        shape_combo = QComboBox()
        shape_combo.addItems(ZONE_SHAPES)
        self._zone_table.setCellWidget(row, 0, shape_combo)

        for col in range(1, 5):
            spin = QSpinBox()
            spin.setRange(-4096, 65535)
            spin.setValue(0)
            self._zone_table.setCellWidget(row, col, spin)

        key_spin = QSpinBox()
        key_spin.setRange(0, 255)
        self._zone_table.setCellWidget(row, 5, key_spin)

        # Action column - just a placeholder
        self._zone_table.setItem(row, 6, QTableWidgetItem(""))

    def _remove_zone_row(self) -> None:
        row = self._zone_table.currentRow()
        if row >= 0:
            self._zone_table.removeRow(row)

    def _apply_zones(self) -> None:
        zones = []
        for row in range(self._zone_table.rowCount()):
            shape_w = self._zone_table.cellWidget(row, 0)
            shape = shape_w.currentText() if shape_w else "circle"

            def _spin_val(r: int, c: int) -> int:
                w = self._zone_table.cellWidget(r, c)
                return w.value() if w else 0

            zones.append({
                "shape": shape,
                "cx": _spin_val(row, 1),
                "cy": _spin_val(row, 2),
                "param1": _spin_val(row, 3),
                "param2": _spin_val(row, 4),
                "output_key": _spin_val(row, 5),
            })

        if self._mw.bridge.is_connected:
            self._mw.bridge.send_cmd({"cmd": "set_zones", "zones": zones})
            log.info("Sent %d zones", len(zones))

    # ------------------------------------------------------------------
    # Activators Tab
    # ------------------------------------------------------------------
    def _build_activators_tab(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)

        self._act_table = QTableWidget(0, 6)
        self._act_table.setHorizontalHeaderLabels([
            "Trigger", "Source Key", "Output Key", "Threshold (ms)", "Flags", "Actions",
        ])
        header = self._act_table.horizontalHeader()
        if header:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        vbox.addWidget(self._act_table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Activator")
        add_btn.clicked.connect(self._add_act_row)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_act_row)
        apply_btn = QPushButton("Apply Activators")
        apply_btn.clicked.connect(self._apply_activators)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(apply_btn)
        vbox.addLayout(btn_row)

        return w

    def _add_act_row(self) -> None:
        row = self._act_table.rowCount()
        self._act_table.insertRow(row)

        trig_combo = QComboBox()
        trig_combo.addItems(ACTIVATOR_TRIGGERS)
        self._act_table.setCellWidget(row, 0, trig_combo)

        for col in range(1, 5):
            spin = QSpinBox()
            spin.setRange(0, 65535)
            spin.setValue(0)
            self._act_table.setCellWidget(row, col, spin)

        self._act_table.setItem(row, 5, QTableWidgetItem(""))

    def _remove_act_row(self) -> None:
        row = self._act_table.currentRow()
        if row >= 0:
            self._act_table.removeRow(row)

    def _apply_activators(self) -> None:
        acts = []
        for row in range(self._act_table.rowCount()):
            trig_w = self._act_table.cellWidget(row, 0)
            trigger = trig_w.currentText() if trig_w else "press"

            def _spin_val(r: int, c: int) -> int:
                w = self._act_table.cellWidget(r, c)
                return w.value() if w else 0

            acts.append({
                "trigger": trigger,
                "source_key": _spin_val(row, 1),
                "output_key": _spin_val(row, 2),
                "threshold_ms": _spin_val(row, 3),
                "flags": _spin_val(row, 4),
            })

        if self._mw.bridge.is_connected:
            self._mw.bridge.send_cmd({"cmd": "set_activators", "activators": acts})
            log.info("Sent %d activators", len(acts))

    # ------------------------------------------------------------------
    # Profile data helpers
    # ------------------------------------------------------------------
    def get_gyro_data(self) -> dict:
        """Return current gyro settings as a dict for profile serialization."""
        return {
            "enabled": self._gyro_enabled.isChecked(),
            "sensitivity_x": self._sens_x.value(),
            "sensitivity_y": self._sens_y.value(),
            "deadzone": self._dz.value(),
            "accel_type": self._accel_type.currentIndex(),
            "accel_param": self._accel_param.value(),
            "invert_x": self._invert_x.isChecked(),
            "invert_y": self._invert_y.isChecked(),
        }

    def get_flick_stick_data(self) -> dict:
        """Return flick stick settings for profile serialization."""
        return {
            "enabled": self._flick_enabled.isChecked(),
            "threshold": self._flick_threshold.value(),
            "snap_degrees": self._flick_snap.value(),
        }

    def get_stick_accel_data(self) -> dict:
        """Return stick acceleration curve settings for profile serialization."""
        return {
            "type": self._stick_accel_type.currentIndex(),
            "param": self._stick_accel_param.value(),
        }

    def get_zones_data(self) -> list:
        """Return current zone definitions for profile serialization."""
        zones = []
        for row in range(self._zone_table.rowCount()):
            shape_w = self._zone_table.cellWidget(row, 0)
            shape = shape_w.currentText() if shape_w else "circle"

            def _spin_val(r: int, c: int) -> int:
                w = self._zone_table.cellWidget(r, c)
                return w.value() if w else 0

            zones.append({
                "shape": shape,
                "cx": _spin_val(row, 1),
                "cy": _spin_val(row, 2),
                "param1": _spin_val(row, 3),
                "param2": _spin_val(row, 4),
                "output_key": _spin_val(row, 5),
            })
        return zones

    def get_activators_data(self) -> list:
        """Return current activator definitions for profile serialization."""
        acts = []
        for row in range(self._act_table.rowCount()):
            trig_w = self._act_table.cellWidget(row, 0)
            trigger = trig_w.currentText() if trig_w else "press"

            def _spin_val(r: int, c: int) -> int:
                w = self._act_table.cellWidget(r, c)
                return w.value() if w else 0

            acts.append({
                "trigger": trigger,
                "source_key": _spin_val(row, 1),
                "output_key": _spin_val(row, 2),
                "threshold_ms": _spin_val(row, 3),
                "flags": _spin_val(row, 4),
            })
        return acts

    def get_led_data(self) -> dict:
        """Return current LED settings for profile serialization."""
        return {
            "pattern": self._led_pattern.currentIndex(),
            "r": self._led_r.value(),
            "g": self._led_g.value(),
            "b": self._led_b.value(),
            "speed": self._led_speed.value(),
        }

    def load_from_profile(self, profile: dict) -> None:
        """Populate UI from a loaded profile dict."""
        gyro = profile.get("gyro", {})
        self._gyro_enabled.setChecked(gyro.get("enabled", False))
        self._sens_x.setValue(gyro.get("sensitivity_x", 100))
        self._sens_y.setValue(gyro.get("sensitivity_y", 100))
        self._dz.setValue(gyro.get("deadzone", 50))
        self._accel_type.setCurrentIndex(gyro.get("accel_type", 0))
        self._accel_param.setValue(gyro.get("accel_param", 150))
        self._invert_x.setChecked(gyro.get("invert_x", False))
        self._invert_y.setChecked(gyro.get("invert_y", False))

        # Load flick stick
        flick = profile.get("flick_stick", {})
        self._flick_enabled.setChecked(flick.get("enabled", False))
        self._flick_threshold.setValue(flick.get("threshold", 3000))
        self._flick_snap.setValue(flick.get("snap_degrees", 0))

        # Load stick accel
        saccel = profile.get("stick_accel", {})
        self._stick_accel_type.setCurrentIndex(saccel.get("type", 0))
        self._stick_accel_param.setValue(saccel.get("param", 200))

        # Load zones
        self._zone_table.setRowCount(0)
        for z in profile.get("zones", []):
            self._add_zone_row()
            row = self._zone_table.rowCount() - 1
            shape_w = self._zone_table.cellWidget(row, 0)
            if shape_w:
                idx = ZONE_SHAPES.index(z.get("shape", "circle")) if z.get("shape") in ZONE_SHAPES else 0
                shape_w.setCurrentIndex(idx)
            for col, key in enumerate(["cx", "cy", "param1", "param2"], start=1):
                w = self._zone_table.cellWidget(row, col)
                if w:
                    w.setValue(z.get(key, 0))
            key_w = self._zone_table.cellWidget(row, 5)
            if key_w:
                key_w.setValue(z.get("output_key", 0))

        # Load activators
        self._act_table.setRowCount(0)
        for a in profile.get("activators", []):
            self._add_act_row()
            row = self._act_table.rowCount() - 1
            trig_w = self._act_table.cellWidget(row, 0)
            if trig_w:
                t = a.get("trigger", "press")
                idx = ACTIVATOR_TRIGGERS.index(t) if t in ACTIVATOR_TRIGGERS else 0
                trig_w.setCurrentIndex(idx)
            for col, key in enumerate(["source_key", "output_key", "threshold_ms", "flags"], start=1):
                w = self._act_table.cellWidget(row, col)
                if w:
                    w.setValue(a.get(key, 0))

        # Load LED settings
        led = profile.get("led", {})
        pat = led.get("pattern", 0)
        if 0 <= pat < len(LED_PATTERNS):
            self._led_pattern.setCurrentIndex(pat)
        self._led_r.setValue(led.get("r", 0))
        self._led_g.setValue(led.get("g", 0))
        self._led_b.setValue(led.get("b", 255))
        self._led_speed.setValue(led.get("speed", 500))
