"""Diagnostics view — input test and controller info."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import ThemeEngine
from ..widgets.card import Card
from ..widgets.timeline import TimelineWidget

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.diagnostics")


class DiagnosticsView(QWidget):
    """Input testing and controller diagnostics."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll)

        container = QWidget()
        main_lay = QVBoxLayout(container)
        main_lay.setContentsMargins(16, 16, 16, 16)
        main_lay.setSpacing(16)

        self._build_input_test(main_lay)
        self._build_controller_info(main_lay)

        main_lay.addStretch()
        scroll.setWidget(container)

    # -----------------------------------------------------------------
    # Input Test
    # -----------------------------------------------------------------

    def _build_input_test(self, parent: QVBoxLayout) -> None:
        group = QGroupBox("Input Test")
        lay = QVBoxLayout(group)

        # Active keys row
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Active keys:"))
        self._active_keys_label = QLabel("—")
        self._active_keys_label.setStyleSheet("font-weight: bold;")
        top_row.addWidget(self._active_keys_label, 1)

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self._clear_input_log)
        top_row.addWidget(clear_btn)
        lay.addLayout(top_row)

        # Performance stats
        perf_row = QHBoxLayout()
        self._perf_check = QCheckBox("Show performance stats")
        self._perf_check.setToolTip("Display input latency and throughput statistics")
        self._perf_check.stateChanged.connect(self._toggle_perf)
        perf_row.addWidget(self._perf_check)
        self._perf_label = QLabel("")
        self._perf_label.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        perf_row.addWidget(self._perf_label, 1)
        lay.addLayout(perf_row)

        # Timeline
        self._timeline = TimelineWidget(self._main.theme)
        self._timeline.setMinimumHeight(70)
        self._timeline.setMaximumHeight(90)
        lay.addWidget(self._timeline)

        # Event log
        self._input_log = QPlainTextEdit()
        self._input_log.setReadOnly(True)
        self._input_log.setMaximumBlockCount(500)
        self._input_log.setFont(QFont("Consolas", 9))
        self._input_log.setMinimumHeight(180)
        lay.addWidget(self._input_log)

        parent.addWidget(group)

    # -----------------------------------------------------------------
    # Controller Info
    # -----------------------------------------------------------------

    def _build_controller_info(self, parent: QVBoxLayout) -> None:
        group = QGroupBox("Controller Information")
        lay = QVBoxLayout(group)

        grid = QHBoxLayout()

        # Type card
        type_card = Card(self._main.theme)
        tc_lay = QVBoxLayout(type_card)
        tc_lay.addWidget(QLabel("Controller"))
        self._ctrl_type = QLabel("—")
        self._ctrl_type.setFont(QFont(
            self._main.theme.typo("font_family"), 14, QFont.Weight.Bold,
        ))
        tc_lay.addWidget(self._ctrl_type)
        grid.addWidget(type_card)

        # Serial card
        serial_card = Card(self._main.theme)
        sc_lay = QVBoxLayout(serial_card)
        sc_lay.addWidget(QLabel("Serial"))
        self._ctrl_serial = QLabel("—")
        self._ctrl_serial.setFont(QFont("Consolas", 11))
        sc_lay.addWidget(self._ctrl_serial)
        grid.addWidget(serial_card)

        lay.addLayout(grid)

        # Stick calibration
        stick_row = QHBoxLayout()
        stick_row.addWidget(QLabel("Deadzone:"))
        self._ctrl_deadzone = QLabel("—")
        stick_row.addWidget(self._ctrl_deadzone)
        stick_row.addSpacing(24)
        stick_row.addWidget(QLabel("Range ratio:"))
        self._ctrl_range = QLabel("—")
        stick_row.addWidget(self._ctrl_range)
        stick_row.addStretch()
        lay.addLayout(stick_row)

        # Color swatches
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Body color:"))
        self._body_swatch = QLabel("  ")
        self._body_swatch.setFixedSize(24, 24)
        self._body_swatch.setStyleSheet(
            "background: #808080; border: 1px solid #555; border-radius: 4px;"
        )
        color_row.addWidget(self._body_swatch)
        color_row.addSpacing(16)
        color_row.addWidget(QLabel("Button color:"))
        self._btn_swatch = QLabel("  ")
        self._btn_swatch.setFixedSize(24, 24)
        self._btn_swatch.setStyleSheet(
            "background: #808080; border: 1px solid #555; border-radius: 4px;"
        )
        color_row.addWidget(self._btn_swatch)
        color_row.addStretch()
        lay.addLayout(color_row)

        # Controls
        ctrl_row = QHBoxLayout()
        rumble_btn = QPushButton("Rumble Test")
        rumble_btn.clicked.connect(self._do_rumble_test)
        ctrl_row.addWidget(rumble_btn)

        home_led_btn = QPushButton("Home LED Toggle")
        home_led_btn.clicked.connect(lambda: self._main.send_cmd({"cmd": "home_led_toggle"}))
        ctrl_row.addWidget(home_led_btn)

        bt_reconnect = QPushButton("BT Reconnect")
        bt_reconnect.clicked.connect(lambda: self._main.send_cmd({"cmd": "bt_reconnect"}))
        ctrl_row.addWidget(bt_reconnect)

        ctrl_row.addStretch()
        lay.addLayout(ctrl_row)

        parent.addWidget(group)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _clear_input_log(self) -> None:
        self._input_log.clear()
        self._active_keys_label.setText("—")

    def _toggle_perf(self, state: int) -> None:
        if state:
            self._perf_label.setText("Collecting…")
        else:
            self._perf_label.setText("")

    # -----------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------

    def _do_rumble_test(self) -> None:
        """Send a 300 ms rumble pulse, then stop."""
        self._main.send_cmd({"cmd": "rumble", "freq": 160, "amp": 50})
        QTimer.singleShot(300, lambda: self._main.send_cmd({"cmd": "rumble", "freq": 160, "amp": 0}))

    def device_event(self, obj: dict) -> None:
        evt = obj.get("event")

        if evt == "mapped_key":
            key_id = obj.get("key_id", "?")
            action = obj.get("action", "?")
            line = f"[{action}] key_id={key_id}"
            self._input_log.appendPlainText(line)
            color = "#4caf50" if action == "press" else "#f44336"
            self._timeline.add_event(str(key_id), color)

            # Update active keys display
            if action == "press":
                cur = self._active_keys_label.text()
                if cur == "—":
                    cur = ""
                keys = [k.strip() for k in cur.split(",") if k.strip()]
                if str(key_id) not in keys:
                    keys.append(str(key_id))
                self._active_keys_label.setText(", ".join(keys))
            elif action == "release":
                cur = self._active_keys_label.text()
                keys = [k.strip() for k in cur.split(",") if k.strip()]
                kid = str(key_id)
                if kid in keys:
                    keys.remove(kid)
                self._active_keys_label.setText(", ".join(keys) if keys else "—")

        elif evt == "controller_info":
            type_labels = {
                "joycon_l": "Joy-Con (L)",
                "joycon_r": "Joy-Con (R)",
                "pro": "Pro Controller",
            }
            self._ctrl_type.setText(
                type_labels.get(obj.get("type", ""), obj.get("type", "unknown"))
            )
            self._ctrl_serial.setText(obj.get("serial", "—") or "—")

            dz = obj.get("stick_deadzone")
            self._ctrl_deadzone.setText(f"{dz:.3f}" if dz is not None else "—")
            rr = obj.get("stick_range_ratio")
            self._ctrl_range.setText(f"{rr:.3f}" if rr is not None else "—")

            body = obj.get("body_color")
            if body:
                self._body_swatch.setStyleSheet(
                    f"background: {body}; border: 1px solid #555; border-radius: 4px;"
                )
            btn_c = obj.get("button_color")
            if btn_c:
                self._btn_swatch.setStyleSheet(
                    f"background: {btn_c}; border: 1px solid #555; border-radius: 4px;"
                )

    def profile_loaded(self, slot: int, profile: dict) -> None:
        pass

    def profile_updated(self, profile: dict) -> None:
        pass

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._perf_label.setStyleSheet(f"color: {theme.color('text_secondary')};")
