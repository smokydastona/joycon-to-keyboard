"""InputGoblin settings dialog.

This dialog centralizes InputGoblin-specific configuration that doesn't belong in
Bind Bandit's general Safehouse settings.

- Speaker/Buzzer settings (persisted on the ESP32 BT host)
- Serial settings (app-side QSettings)
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger("joycon_helper.ui.widgets.inputgoblin_settings_dialog")


_TONE_LABELS: list[tuple[int, str]] = [
    (0, "Startup"),
    (1, "Connect"),
    (2, "Disconnect"),
    (3, "Discovery start"),
    (4, "Setup complete"),
    (5, "Error"),
    (6, "Discovery tick"),
]


class InputGoblinSettingsDialog(QDialog):
    def __init__(self, main_window: Any) -> None:
        super().__init__(main_window)
        self._main = main_window
        self._settings = QSettings()

        self.setWindowTitle("InputGoblin Settings")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)

        title = QLabel("InputGoblin Settings")
        title.setFont(
            QFont(
                self._main.theme.typo("font_family_decorative"),
                self._main.theme.typo("font_size_title"),
                QFont.Weight.Bold,
            )
        )
        root.addWidget(title)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # Speaker tab
        speaker = QWidget()
        self._build_speaker_tab(speaker)
        tabs.addTab(speaker, "Speaker")

        # Serial tab
        serial = QWidget()
        self._build_serial_tab(serial)
        tabs.addTab(serial, "Serial")

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        # Wire device event handling so we can update UI from responses.
        try:
            self._main.bridge.device_event.connect(self._on_device_event)  # type: ignore[attr-defined]
            self._main.bridge.connected.connect(self._on_connected)  # type: ignore[attr-defined]
            self._main.bridge.disconnected.connect(self._on_disconnected)  # type: ignore[attr-defined]
        except Exception:
            # Dialog can still operate in a degraded mode (serial settings only).
            log.debug("Could not connect SerialBridge signals", exc_info=True)

        self._sync_enabled_state()
        if getattr(self._main.bridge, "is_connected", False):
            self.refresh_speaker_from_device()

    # -----------------------------------------------------------------
    # Speaker tab
    # -----------------------------------------------------------------

    def _build_speaker_tab(self, parent: QWidget) -> None:
        lay = QVBoxLayout(parent)

        form = QFormLayout()
        form.setSpacing(10)

        self._spk_enabled = QCheckBox("Enable speaker")
        self._spk_enabled.setToolTip("Master enable for the ESP32 host piezo/buzzer")
        form.addRow(self._spk_enabled)

        # Volume slider + spin
        vol_row = QHBoxLayout()
        self._spk_volume = QSlider(Qt.Orientation.Horizontal)
        self._spk_volume.setRange(0, 100)
        self._spk_volume.setSingleStep(1)
        self._spk_volume.setPageStep(5)
        self._spk_volume.setToolTip("Volume (0 = mute, 100 = max)")
        vol_row.addWidget(self._spk_volume, 1)
        self._spk_volume_spin = QSpinBox()
        self._spk_volume_spin.setRange(0, 100)
        self._spk_volume_spin.setSuffix("%")
        self._spk_volume_spin.setFixedWidth(90)
        vol_row.addWidget(self._spk_volume_spin)
        self._spk_volume.valueChanged.connect(self._spk_volume_spin.setValue)
        self._spk_volume_spin.valueChanged.connect(self._spk_volume.setValue)
        form.addRow("Volume:", vol_row)

        self._spk_discovery_tick = QCheckBox("Discovery tick")
        self._spk_discovery_tick.setToolTip("Periodic tick while BT discovery is active")
        form.addRow(self._spk_discovery_tick)

        lay.addLayout(form)

        # Tone mask
        tones_group = QGroupBox("Tone enable")
        tones_lay = QVBoxLayout(tones_group)
        self._tone_checks: dict[int, QCheckBox] = {}
        for tone_id, label in _TONE_LABELS:
            cb = QCheckBox(label)
            cb.setToolTip(f"Enable/disable tone ID {tone_id}")
            self._tone_checks[tone_id] = cb
            tones_lay.addWidget(cb)
        lay.addWidget(tones_group)

        # Actions row
        actions = QHBoxLayout()
        self._spk_refresh_btn = QPushButton("Refresh")
        self._spk_refresh_btn.setToolTip("Query current speaker settings from the ESP32 host")
        self._spk_refresh_btn.clicked.connect(self.refresh_speaker_from_device)
        actions.addWidget(self._spk_refresh_btn)

        self._spk_apply_btn = QPushButton("Apply")
        self._spk_apply_btn.setProperty("accent", True)
        self._spk_apply_btn.setToolTip("Save speaker settings to the ESP32 host")
        self._spk_apply_btn.clicked.connect(self.apply_speaker_to_device)
        actions.addWidget(self._spk_apply_btn)

        actions.addStretch(1)

        self._test_tone_combo = QComboBox()
        for tone_id, label in _TONE_LABELS:
            self._test_tone_combo.addItem(f"{label} (#{tone_id})", tone_id)
        self._test_tone_combo.setToolTip("Select a tone to play on the ESP32 host")
        actions.addWidget(self._test_tone_combo)

        self._spk_test_btn = QPushButton("Play")
        self._spk_test_btn.setToolTip("Play the selected tone")
        self._spk_test_btn.clicked.connect(self._play_test_tone)
        actions.addWidget(self._spk_test_btn)

        lay.addLayout(actions)
        lay.addStretch(1)

    def _tone_mask_from_ui(self) -> int:
        mask = 0
        for tid, cb in self._tone_checks.items():
            if cb.isChecked():
                mask |= (1 << tid)
        return mask & 0xFFFF

    def _apply_tone_mask_to_ui(self, mask: int) -> None:
        for tid, cb in self._tone_checks.items():
            cb.setChecked(bool(mask & (1 << tid)))

    def refresh_speaker_from_device(self) -> None:
        if not getattr(self._main.bridge, "is_connected", False):
            self._set_status("Not connected — connect the serial bridge first.")
            return
        self._set_status("Querying speaker settings…")
        self._main.send_cmd({"cmd": "buzzer_get"})

    def apply_speaker_to_device(self) -> None:
        if not getattr(self._main.bridge, "is_connected", False):
            self._set_status("Not connected — connect the serial bridge first.")
            return

        obj = {
            "cmd": "buzzer_set",
            "enabled": bool(self._spk_enabled.isChecked()),
            "volume": int(self._spk_volume.value()),
            "discovery_tick": bool(self._spk_discovery_tick.isChecked()),
            "tone_mask": int(self._tone_mask_from_ui()),
        }
        self._set_status("Applying speaker settings…")
        self._main.send_cmd(obj)

    def _play_test_tone(self) -> None:
        if not getattr(self._main.bridge, "is_connected", False):
            self._set_status("Not connected — connect the serial bridge first.")
            return
        tone_id = int(self._test_tone_combo.currentData())
        self._set_status(f"Playing tone #{tone_id}…")
        self._main.send_cmd({"cmd": "buzzer_test", "tone_id": tone_id})

    # -----------------------------------------------------------------
    # Serial tab
    # -----------------------------------------------------------------

    def _build_serial_tab(self, parent: QWidget) -> None:
        lay = QVBoxLayout(parent)

        form = QFormLayout()
        form.setSpacing(10)

        # Baud rate
        self._baud_combo = QComboBox()
        self._baud_combo.addItems(["115200", "230400", "460800", "921600"])
        current_baud = str(self._settings.value("baud_rate", "115200"))
        idx = self._baud_combo.findText(current_baud)
        if idx >= 0:
            self._baud_combo.setCurrentIndex(idx)
        self._baud_combo.setToolTip("Serial baud rate for the ESP32-S3 bridge (applies on next connect)")
        self._baud_combo.currentTextChanged.connect(self._on_baud_changed)
        form.addRow("Baud rate:", self._baud_combo)

        # Reconnect interval
        self._reconnect_spin = QSpinBox()
        self._reconnect_spin.setRange(0, 60)
        self._reconnect_spin.setSuffix(" sec")
        self._reconnect_spin.setSpecialValueText("Disabled")
        self._reconnect_spin.setValue(self._settings.value("reconnect_interval", 5, type=int))
        self._reconnect_spin.setToolTip("Seconds between automatic reconnect attempts (0 = disabled)")
        self._reconnect_spin.valueChanged.connect(lambda v: self._settings.setValue("reconnect_interval", v))
        form.addRow("Auto-reconnect interval:", self._reconnect_spin)

        # Serial timeout
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 30)
        self._timeout_spin.setSuffix(" sec")
        self._timeout_spin.setValue(self._settings.value("serial_timeout", 5, type=int))
        self._timeout_spin.setToolTip("How long to wait for a serial response before timing out")
        self._timeout_spin.valueChanged.connect(lambda v: self._settings.setValue("serial_timeout", v))
        form.addRow("Read timeout:", self._timeout_spin)

        lay.addLayout(form)

        note = QLabel(
            "Note: serial settings are app-side. The baud rate is used the next time you connect."
        )
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)

    def _on_baud_changed(self, value: str) -> None:
        self._settings.setValue("baud_rate", value)
        # Keep the connection toolbar in sync.
        if hasattr(self._main, "_baud_edit"):
            try:
                self._main._baud_edit.setText(value)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Event handling
    # -----------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _sync_enabled_state(self) -> None:
        connected = bool(getattr(self._main.bridge, "is_connected", False))
        for w in [
            self._spk_enabled,
            self._spk_volume,
            self._spk_volume_spin,
            self._spk_discovery_tick,
            self._spk_refresh_btn,
            self._spk_apply_btn,
            self._test_tone_combo,
            self._spk_test_btn,
            *self._tone_checks.values(),
        ]:
            w.setEnabled(connected)

        if not connected:
            self._set_status("Connect the serial bridge to edit speaker settings.")

    def _on_connected(self) -> None:
        self._sync_enabled_state()
        self.refresh_speaker_from_device()

    def _on_disconnected(self) -> None:
        self._sync_enabled_state()

    def _on_device_event(self, obj: dict) -> None:
        rsp = obj.get("rsp")
        if rsp == "buzzer_get":
            if obj.get("ok") is True:
                self._spk_enabled.setChecked(bool(obj.get("enabled")))
                try:
                    self._spk_volume.setValue(int(obj.get("volume", 0)))
                except Exception:
                    self._spk_volume.setValue(0)
                self._spk_discovery_tick.setChecked(bool(obj.get("discovery_tick")))
                try:
                    self._apply_tone_mask_to_ui(int(obj.get("tone_mask", 0)))
                except Exception:
                    self._apply_tone_mask_to_ui(0)
                self._set_status("Speaker settings loaded.")
            else:
                err = str(obj.get("error", "unknown"))
                status = obj.get("status")
                if status is not None:
                    self._set_status(f"Speaker query failed: {err} (status={status})")
                else:
                    self._set_status(f"Speaker query failed: {err}")

        elif rsp == "buzzer_set":
            if obj.get("ok") is True:
                self._set_status("Speaker settings saved.")
            else:
                err = str(obj.get("error", "unknown"))
                status = obj.get("status")
                if status is not None:
                    self._set_status(f"Speaker update failed: {err} (status={status})")
                else:
                    self._set_status(f"Speaker update failed: {err}")

        elif rsp == "buzzer_test":
            if obj.get("ok") is True:
                self._set_status("Tone played.")
            else:
                err = str(obj.get("error", "unknown"))
                status = obj.get("status")
                if status is not None:
                    self._set_status(f"Tone failed: {err} (status={status})")
                else:
                    self._set_status(f"Tone failed: {err}")
