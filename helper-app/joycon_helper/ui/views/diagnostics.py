"""Diagnostics view — input test, firmware update, initial flash, controller info.

Merges the old Input Test tab with firmware management and controller
diagnostics into a single view.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..theme import ThemeEngine
from ..widgets.card import Card
from ..widgets.timeline import TimelineWidget

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.diagnostics")


class DiagnosticsView(QWidget):
    """Input testing, firmware management, and controller diagnostics."""

    _flash_progress = pyqtSignal(str, int)
    _flash_done = pyqtSignal(bool, str)

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main

        self._flash_progress.connect(self._on_flash_progress)
        self._flash_done.connect(self._on_flash_done)

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
        self._build_firmware_section(main_lay)
        self._build_initial_flash(main_lay)

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
        rumble_btn.clicked.connect(lambda: self._main.send_cmd({"cmd": "rumble"}))
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
    # Firmware Update
    # -----------------------------------------------------------------

    def _build_firmware_section(self, parent: QVBoxLayout) -> None:
        group = QGroupBox("Firmware Update (OTA)")
        lay = QVBoxLayout(group)

        ver_row = QHBoxLayout()
        ver_row.addWidget(QLabel("ESP32-S3:"))
        self._fw_s3_ver = QLabel("—")
        ver_row.addWidget(self._fw_s3_ver)
        ver_row.addSpacing(24)
        ver_row.addWidget(QLabel("ESP32 host:"))
        self._fw_esp32_ver = QLabel("—")
        ver_row.addWidget(self._fw_esp32_ver)
        ver_row.addStretch()
        lay.addLayout(ver_row)

        self._fw_status = QLabel("")
        self._fw_status.setWordWrap(True)
        lay.addWidget(self._fw_status)

        self._fw_progress = QProgressBar()
        self._fw_progress.setRange(0, 100)
        self._fw_progress.setVisible(False)
        lay.addWidget(self._fw_progress)

        btn_row = QHBoxLayout()
        self._fw_check_btn = QPushButton("Check Versions")
        self._fw_check_btn.setProperty("accent", True)
        self._fw_check_btn.setToolTip("Query the device and GitHub for available firmware versions")
        self._fw_check_btn.clicked.connect(self._fw_check_versions)
        btn_row.addWidget(self._fw_check_btn)

        self._fw_update_btn = QPushButton("Update Firmware")
        self._fw_update_btn.setEnabled(False)
        self._fw_update_btn.setToolTip("Download and flash the latest firmware via OTA")
        self._fw_update_btn.clicked.connect(self._fw_do_update)
        btn_row.addWidget(self._fw_update_btn)

        self._fw_flash_file_btn = QPushButton("Flash from File…")
        self._fw_flash_file_btn.setToolTip("Flash a local firmware binary you already downloaded")
        self._fw_flash_file_btn.clicked.connect(self._fw_flash_from_file)
        btn_row.addWidget(self._fw_flash_file_btn)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        parent.addWidget(group)

    # -----------------------------------------------------------------
    # Initial Flash
    # -----------------------------------------------------------------

    def _build_initial_flash(self, parent: QVBoxLayout) -> None:
        group = QGroupBox("Initial Flash (new boards)")
        lay = QVBoxLayout(group)

        self._init_flash_status = QLabel("Use for first-time flashing of blank boards.")
        self._init_flash_status.setWordWrap(True)
        lay.addWidget(self._init_flash_status)

        self._init_progress = QProgressBar()
        self._init_progress.setRange(0, 100)
        self._init_progress.setVisible(False)
        lay.addWidget(self._init_progress)

        btn_row = QHBoxLayout()
        self._init_auto_btn = QPushButton("Download && Flash Latest")
        self._init_auto_btn.setProperty("accent", True)
        self._init_auto_btn.setToolTip("Auto-download the latest firmware and flash it to a blank board")
        self._init_auto_btn.clicked.connect(self._init_flash_auto)
        btn_row.addWidget(self._init_auto_btn)

        self._init_file_btn = QPushButton("Flash Files…")
        self._init_file_btn.setToolTip("Flash firmware from pre-downloaded binary files")
        self._init_file_btn.clicked.connect(self._init_flash_from_files)
        btn_row.addWidget(self._init_file_btn)

        self._init_backup_btn = QPushButton("Backup Flash…")
        self._init_backup_btn.setToolTip("Read and save the current flash contents before making changes")
        self._init_backup_btn.clicked.connect(self._init_flash_backup)
        btn_row.addWidget(self._init_backup_btn)

        btn_row.addStretch()
        lay.addLayout(btn_row)

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
    # Firmware operations
    # -----------------------------------------------------------------

    def _fw_check_versions(self) -> None:
        self._fw_status.setText("Checking…")
        self._fw_check_btn.setEnabled(False)

        def _check():
            try:
                from ...fw_updater import FwUpdater
                updater = FwUpdater()
                info = updater.check_versions()
                QTimer.singleShot(0, lambda: self._on_fw_versions(info))
            except Exception as exc:
                QTimer.singleShot(0, lambda err=str(exc): self._on_fw_versions({"error": err}))

        threading.Thread(target=_check, daemon=True).start()

    def _on_fw_versions(self, info: dict) -> None:
        self._fw_check_btn.setEnabled(True)
        if "error" in info:
            self._fw_status.setText(f"Error: {info['error']}")
            return
        self._fw_s3_ver.setText(info.get("s3", "—"))
        self._fw_esp32_ver.setText(info.get("esp32", "—"))
        if info.get("update_available"):
            self._fw_update_btn.setEnabled(True)
            self._fw_status.setText(f"Update available: {info.get('latest', '?')}")
        else:
            self._fw_status.setText("Firmware is up to date.")

    def _fw_do_update(self) -> None:
        reply = QMessageBox.question(
            self, "Firmware Update",
            "Download and flash the latest firmware?\n"
            "The device will reboot during this process.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._fw_update_btn.setEnabled(False)
        self._fw_progress.setVisible(True)
        self._fw_progress.setValue(0)

        def _update():
            try:
                from ...fw_updater import FwUpdater
                updater = FwUpdater()
                updater.do_update(
                    progress_cb=lambda step, pct: self._flash_progress.emit(step, pct),
                )
                self._flash_done.emit(True, "Firmware updated successfully.")
            except Exception as e:
                self._flash_done.emit(False, str(e))

        threading.Thread(target=_update, daemon=True).start()

    def _fw_flash_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select firmware binary", "", "Binary files (*.bin);;All files (*)",
        )
        if not path:
            return

        self._fw_flash_file_btn.setEnabled(False)
        self._fw_progress.setVisible(True)
        self._fw_progress.setValue(0)

        def _flash():
            try:
                from ...fw_updater import FwUpdater
                updater = FwUpdater()
                updater.flash_from_file(
                    path,
                    progress_cb=lambda step, pct: self._flash_progress.emit(step, pct),
                )
                self._flash_done.emit(True, f"Flashed {path}")
            except Exception as e:
                self._flash_done.emit(False, str(e))

        threading.Thread(target=_flash, daemon=True).start()

    def _on_flash_progress(self, step: str, pct: int) -> None:
        self._fw_status.setText(step)
        self._fw_progress.setValue(pct)

    def _on_flash_done(self, ok: bool, msg: str) -> None:
        self._fw_progress.setVisible(False)
        self._fw_update_btn.setEnabled(True)
        self._fw_flash_file_btn.setEnabled(True)
        self._fw_status.setText(msg)
        if not ok:
            QMessageBox.warning(self, "Flash Failed", msg)

    # -----------------------------------------------------------------
    # Initial flash operations
    # -----------------------------------------------------------------

    def _init_flash_auto(self) -> None:
        reply = QMessageBox.question(
            self, "Initial Flash",
            "Download and flash latest firmware to a blank board?\n"
            "This will ERASE the entire flash first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_init_buttons(False)
        self._init_progress.setVisible(True)
        self._init_flash_status.setText("Downloading…")

        def _go():
            try:
                from ... import initial_flash
                initial_flash.download_and_flash_initial(
                    progress_cb=lambda s, p: self._flash_progress.emit(s, p),
                )
                self._flash_done.emit(True, "Initial flash complete.")
            except Exception as e:
                self._flash_done.emit(False, str(e))

        threading.Thread(target=_go, daemon=True).start()

    def _init_flash_from_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select firmware files", "", "Binary files (*.bin);;All files (*)",
        )
        if not paths:
            return
        self._set_init_buttons(False)
        self._init_progress.setVisible(True)

        def _go():
            try:
                from ... import initial_flash
                initial_flash.flash_firmware(
                    paths,
                    progress_cb=lambda s, p: self._flash_progress.emit(s, p),
                )
                self._flash_done.emit(True, "Flash complete.")
            except Exception as e:
                self._flash_done.emit(False, str(e))

        threading.Thread(target=_go, daemon=True).start()

    def _init_flash_backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup flash", "flash_backup.bin", "Binary files (*.bin)",
        )
        if not path:
            return
        self._set_init_buttons(False)
        self._init_progress.setVisible(True)

        def _go():
            try:
                from ... import initial_flash
                initial_flash.backup_firmware(
                    path,
                    progress_cb=lambda s, p: self._flash_progress.emit(s, p),
                )
                self._flash_done.emit(True, f"Backup saved to {path}")
            except Exception as e:
                self._flash_done.emit(False, str(e))

        threading.Thread(target=_go, daemon=True).start()

    def _set_init_buttons(self, enabled: bool) -> None:
        self._init_auto_btn.setEnabled(enabled)
        self._init_file_btn.setEnabled(enabled)
        self._init_backup_btn.setEnabled(enabled)

    # -----------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------

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
