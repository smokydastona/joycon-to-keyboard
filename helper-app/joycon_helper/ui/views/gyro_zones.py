"""Gyro & Zones view — gyro-to-mouse config, stick zones, and activators.

Provides sub-tabs for:
  1. Gyro Settings — enable/disable, sensitivity, deadzone, acceleration, inversion.
  2. Zones Editor — define stick-region zones that trigger key outputs.
  3. Activators Editor — define trigger-based actions (press/release/double/long/chord).
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QScrollArea, QSlider, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..widgets.card import Card

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.gyro_zones")

ZONE_SHAPES = ["circle", "ring", "wedge", "rect"]
ACTIVATOR_TRIGGERS = ["press", "release", "double_press", "long_press", "chord"]
ACCEL_TYPES = ["none", "power", "smooth"]


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
        enable_card = Card("Gyro Enable")
        enable_layout = QHBoxLayout()
        self._gyro_enabled = QCheckBox("Enable gyro-to-mouse")
        enable_layout.addWidget(self._gyro_enabled)
        enable_card.body_layout.addLayout(enable_layout)
        vbox.addWidget(enable_card)

        # Sensitivity
        sens_card = Card("Sensitivity")
        sens_layout = QVBoxLayout()

        sx_row = QHBoxLayout()
        sx_row.addWidget(QLabel("X (yaw):"))
        self._sens_x = QSlider(Qt.Orientation.Horizontal)
        self._sens_x.setRange(10, 500)
        self._sens_x.setValue(100)
        self._sens_x_label = QLabel("100")
        self._sens_x.valueChanged.connect(lambda v: self._sens_x_label.setText(str(v)))
        sx_row.addWidget(self._sens_x)
        sx_row.addWidget(self._sens_x_label)
        sens_layout.addLayout(sx_row)

        sy_row = QHBoxLayout()
        sy_row.addWidget(QLabel("Y (pitch):"))
        self._sens_y = QSlider(Qt.Orientation.Horizontal)
        self._sens_y.setRange(10, 500)
        self._sens_y.setValue(100)
        self._sens_y_label = QLabel("100")
        self._sens_y.valueChanged.connect(lambda v: self._sens_y_label.setText(str(v)))
        sy_row.addWidget(self._sens_y)
        sy_row.addWidget(self._sens_y_label)
        sens_layout.addLayout(sy_row)

        sens_card.body_layout.addLayout(sens_layout)
        vbox.addWidget(sens_card)

        # Deadzone
        dz_card = Card("Deadzone")
        dz_layout = QHBoxLayout()
        dz_layout.addWidget(QLabel("Threshold:"))
        self._dz = QSpinBox()
        self._dz.setRange(0, 500)
        self._dz.setValue(50)
        dz_layout.addWidget(self._dz)
        dz_card.body_layout.addLayout(dz_layout)
        vbox.addWidget(dz_card)

        # Acceleration
        accel_card = Card("Acceleration Curve")
        accel_layout = QVBoxLayout()

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._accel_type = QComboBox()
        self._accel_type.addItems(ACCEL_TYPES)
        type_row.addWidget(self._accel_type)
        accel_layout.addLayout(type_row)

        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("Parameter:"))
        self._accel_param = QSpinBox()
        self._accel_param.setRange(50, 500)
        self._accel_param.setValue(150)
        param_row.addWidget(self._accel_param)
        accel_layout.addLayout(param_row)

        accel_card.body_layout.addLayout(accel_layout)
        vbox.addWidget(accel_card)

        # Inversion
        inv_card = Card("Axis Inversion")
        inv_layout = QHBoxLayout()
        self._invert_x = QCheckBox("Invert X")
        self._invert_y = QCheckBox("Invert Y")
        inv_layout.addWidget(self._invert_x)
        inv_layout.addWidget(self._invert_y)
        inv_card.body_layout.addLayout(inv_layout)
        vbox.addWidget(inv_card)

        # Apply button
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply Gyro Settings")
        apply_btn.clicked.connect(self._apply_gyro)
        btn_row.addStretch()
        btn_row.addWidget(apply_btn)
        vbox.addLayout(btn_row)

        vbox.addStretch()
        return scroll

    def _apply_gyro(self) -> None:
        """Send gyro config as part of current profile update."""
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
        if self._mw.is_connected:
            self._mw.serial.send_obj({"cmd": "set_gyro", "gyro": gyro})
            log.info("Sent gyro config: %s", gyro)

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

        if self._mw.is_connected:
            self._mw.serial.send_obj({"cmd": "set_zones", "zones": zones})
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

        if self._mw.is_connected:
            self._mw.serial.send_obj({"cmd": "set_activators", "activators": acts})
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
