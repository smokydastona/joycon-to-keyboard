"""Diagnostics view — input test, controller telemetry, and forensics export."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
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
from ..widgets.live_input_visualizer import LiveInputVisualizerWidget
from ..widgets.timeline import TimelineWidget
from ...diagnostics_metrics import (
    CalibrationAssessment,
    DiagnosticsTelemetry,
    assess_controller_calibration,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.diagnostics")


class DiagnosticsView(QWidget):
    """Input testing and controller diagnostics."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main
        self._telemetry = DiagnosticsTelemetry()
        self._last_controller_info: dict = {}
        self._calibration = CalibrationAssessment(
            status="Unknown",
            summary="Waiting for controller calibration data.",
            deadzone_status="Unknown",
            range_status="Unknown",
        )

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
        self._build_visualizer(main_lay)
        self._build_controller_info(main_lay)

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._refresh_metrics_display)
        self._stats_timer.start()

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

        reset_btn = QPushButton("Reset Metrics")
        reset_btn.clicked.connect(self._reset_metrics)
        top_row.addWidget(reset_btn)

        copy_btn = QPushButton("Copy Summary")
        copy_btn.clicked.connect(self._copy_summary)
        top_row.addWidget(copy_btn)

        export_btn = QPushButton("Export Report")
        export_btn.setProperty("accent", True)
        export_btn.clicked.connect(self._export_report)
        top_row.addWidget(export_btn)
        lay.addLayout(top_row)

        metrics_row = QHBoxLayout()
        self._session_card = self._make_metric_card("Session", "0.0 s")
        self._event_card = self._make_metric_card("Events", "0")
        self._rate_card = self._make_metric_card("Rate", "0.0 eps")
        self._active_card = self._make_metric_card("Active / Peak", "0 / 0")
        self._hold_card = self._make_metric_card("Avg Hold", "—")
        self._latency_card = self._make_metric_card("Latency", "—")
        for card in (
            self._session_card,
            self._event_card,
            self._rate_card,
            self._active_card,
            self._hold_card,
            self._latency_card,
        ):
            metrics_row.addWidget(card)
        lay.addLayout(metrics_row)

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

    def _make_metric_card(self, title: str, value: str) -> Card:
        card = Card(self._main.theme)
        card.setMinimumWidth(130)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        layout.addWidget(title_label)
        value_label = QLabel(value)
        value_label.setProperty("metricValue", True)
        value_label.setFont(QFont(
            self._main.theme.typo("font_family"), 13, QFont.Weight.Bold,
        ))
        layout.addWidget(value_label)
        card._metric_value_label = value_label  # type: ignore[attr-defined]
        return card

    @staticmethod
    def _set_metric_card_value(card: Card, value: str) -> None:
        card._metric_value_label.setText(value)  # type: ignore[attr-defined]

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

        calibration_group = QGroupBox("Calibration Assessment")
        calibration_lay = QVBoxLayout(calibration_group)
        self._calibration_status = QLabel("Unknown")
        self._calibration_status.setFont(QFont(
            self._main.theme.typo("font_family"), 12, QFont.Weight.Bold,
        ))
        calibration_lay.addWidget(self._calibration_status)
        self._calibration_detail = QLabel("Waiting for controller calibration data.")
        self._calibration_detail.setWordWrap(True)
        calibration_lay.addWidget(self._calibration_detail)
        lay.addWidget(calibration_group)

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

    def _build_visualizer(self, parent: QVBoxLayout) -> None:
        group = QGroupBox("Live Visualizer")
        layout = QVBoxLayout(group)
        self._visualizer = LiveInputVisualizerWidget(self._main, compact=True)
        layout.addWidget(self._visualizer)
        parent.addWidget(group)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _clear_input_log(self) -> None:
        self._input_log.clear()
        self._active_keys_label.setText("—")
        self._timeline.clear()

    def _toggle_perf(self, state: int) -> None:
        if state:
            self._refresh_metrics_display()
        else:
            self._perf_label.setText("")

    def _reset_metrics(self) -> None:
        self._telemetry.reset()
        self._active_keys_label.setText("—")
        self._timeline.clear()
        self._refresh_metrics_display()

    def _copy_summary(self) -> None:
        QApplication.clipboard().setText(self._build_summary_text())

    def _export_report(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"bind-bandit-forensics-{timestamp}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Forensics Report",
            default_name,
            "JSON Files (*.json)",
        )
        if not file_path:
            return

        recent_lines = [
            self._input_log.document().findBlockByNumber(index).text()
            for index in range(max(0, self._input_log.blockCount() - 50), self._input_log.blockCount())
        ]
        report = self._telemetry.build_report(
            profile_slot=self._main._slot,
            controller_info=self._last_controller_info,
            calibration=self._calibration,
            recent_log_lines=[line for line in recent_lines if line],
        )
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)

    def _build_summary_text(self) -> str:
        snapshot = self._telemetry.snapshot()
        last_latency = "—" if snapshot.last_latency_ms is None else f"{snapshot.last_latency_ms:.1f} ms"
        avg_hold = "—" if snapshot.average_hold_ms is None else f"{snapshot.average_hold_ms:.1f} ms"
        return (
            f"Session: {snapshot.session_seconds:.1f}s\n"
            f"Events: {snapshot.total_events} ({snapshot.total_presses} presses / {snapshot.total_releases} releases)\n"
            f"Recent rate: {snapshot.recent_events_per_second:.2f} eps\n"
            f"Average rate: {snapshot.average_events_per_second:.2f} eps\n"
            f"Active/Peak: {snapshot.active_keys}/{snapshot.peak_active_keys}\n"
            f"Average hold: {avg_hold}\n"
            f"Last latency: {last_latency}\n"
            f"Calibration: {self._calibration.status} — {self._calibration.summary}"
        )

    def _refresh_metrics_display(self) -> None:
        snapshot = self._telemetry.snapshot()
        self._set_metric_card_value(self._session_card, f"{snapshot.session_seconds:.1f} s")
        self._set_metric_card_value(self._event_card, str(snapshot.total_events))
        self._set_metric_card_value(self._rate_card, f"{snapshot.recent_events_per_second:.1f} eps")
        self._set_metric_card_value(
            self._active_card,
            f"{snapshot.active_keys} / {snapshot.peak_active_keys}",
        )
        self._set_metric_card_value(
            self._hold_card,
            "—" if snapshot.average_hold_ms is None else f"{snapshot.average_hold_ms:.1f} ms",
        )
        latency_text = "—"
        if snapshot.last_latency_ms is not None:
            latency_text = f"{snapshot.last_latency_ms:.1f} ms"
            if snapshot.average_latency_ms is not None:
                latency_text += f" avg {snapshot.average_latency_ms:.1f}"
        self._set_metric_card_value(self._latency_card, latency_text)

        if self._perf_check.isChecked():
            hold_text = "—" if snapshot.average_hold_ms is None else f"{snapshot.average_hold_ms:.1f} ms"
            avg_latency_text = "—"
            if snapshot.average_latency_ms is not None:
                avg_latency_text = f"{snapshot.average_latency_ms:.1f} ms"
            self._perf_label.setText(
                f"rate {snapshot.recent_events_per_second:.2f} eps | "
                f"avg {snapshot.average_events_per_second:.2f} eps | "
                f"hold {hold_text} | latency {avg_latency_text}"
            )

    def _derive_pressed(self, obj: dict) -> bool | None:
        if isinstance(obj.get("pressed"), bool):
            return bool(obj["pressed"])
        action = obj.get("action")
        if action == "press":
            return True
        if action == "release":
            return False
        return None

    def _append_input_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._input_log.appendPlainText(f"[{timestamp}] {message}")

    def _update_calibration_labels(self) -> None:
        self._calibration_status.setText(self._calibration.status)
        palette = {
            "Excellent": self._main.theme.color("success"),
            "Good": self._main.theme.color("success"),
            "Fair": self._main.theme.color("warning"),
            "Poor": self._main.theme.color("danger"),
            "Unknown": self._main.theme.color("text_secondary"),
        }
        self._calibration_status.setStyleSheet(f"color: {palette[self._calibration.status]};")
        self._calibration_detail.setText(self._calibration.summary)

    # -----------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------

    def _do_rumble_test(self) -> None:
        """Send a 300 ms rumble pulse, then stop."""
        self._main.send_cmd({"cmd": "rumble", "freq": 160, "amp": 50})
        QTimer.singleShot(300, lambda: self._main.send_cmd({"cmd": "rumble", "freq": 160, "amp": 0}))

    def device_event(self, obj: dict) -> None:
        evt = obj.get("event")
        self._visualizer.handle_device_event(obj)

        if evt == "mapped_key":
            key_id = obj.get("key_id", "?")
            pressed = self._derive_pressed(obj)
            action = "press" if pressed else "release"
            if pressed is None:
                action = str(obj.get("action", "?"))
            self._append_input_log(f"[{action}] key_id={key_id}")
            color = "#4caf50" if pressed is not False else "#f44336"
            self._timeline.add_event(str(key_id), color)

            if isinstance(key_id, int) and pressed is not None:
                self._telemetry.record_mapped_key(key_id, pressed)
                snapshot = self._telemetry.snapshot()
                self._active_keys_label.setText(
                    ", ".join(sorted(str(item) for item in self._telemetry._active_keys)) or "—"
                )
                if self._perf_check.isChecked() and snapshot.active_keys == 0 and snapshot.total_events == 0:
                    self._perf_label.setText("Collecting…")
                self._refresh_metrics_display()

        elif obj.get("rsp") == "pong":
            self._telemetry.record_latency(self._main._latency_ms)
            self._refresh_metrics_display()

        elif evt == "controller_info":
            self._last_controller_info = dict(obj)
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
            self._calibration = assess_controller_calibration(dz, rr)
            self._update_calibration_labels()

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
        self._refresh_metrics_display()

    def profile_updated(self, profile: dict) -> None:
        self._refresh_metrics_display()

    def connection_changed(self, connected: bool) -> None:
        self._visualizer.connection_changed(connected)
        if connected:
            self._telemetry.reset()
            self._refresh_metrics_display()

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._perf_label.setStyleSheet(f"color: {theme.color('text_secondary')};")
        self._update_calibration_labels()
        self._timeline.apply_theme(theme)
        self._visualizer.apply_theme(theme)

