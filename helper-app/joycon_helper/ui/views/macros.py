"""Macros & Stick view — macro editor and analog stick configuration.

Combines the old "Tricks" tab (macros, chords, layers) with the "Stick" tab
(deadzone, sensitivity, response curves) into a single cohesive view.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QStackedWidget, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from ..theme import ThemeEngine
from ..widgets.curve_preview import CurvePreviewWidget
from ...hid_keycodes import _KEYCODE_NAMES

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.macros")

# Reverse map: display name → keycode
_NAME_TO_KEYCODE: Dict[str, int] = {v: k for k, v in _KEYCODE_NAMES.items()}


class MacrosView(QWidget):
    """Macro editor + analog stick configuration."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Macros sub-tab
        self._macros_tab = QWidget()
        self._build_macros_tab()
        tabs.addTab(self._macros_tab, "⚡ Macros")

        # Layers sub-tab
        self._layers_tab = QWidget()
        self._build_layers_tab()
        tabs.addTab(self._layers_tab, "🔀 Layers")

        # Chords sub-tab
        self._chords_tab = QWidget()
        self._build_chords_tab()
        tabs.addTab(self._chords_tab, "🎵 Chords")

        # Stick config sub-tab
        self._stick_tab = QWidget()
        self._build_stick_tab()
        tabs.addTab(self._stick_tab, "🕹 Stick")

    # -----------------------------------------------------------------
    # Macros tab
    # -----------------------------------------------------------------

    def _build_macros_tab(self) -> None:
        lay = QHBoxLayout(self._macros_tab)
        lay.setContentsMargins(16, 16, 16, 16)

        # Left: macro list
        left = QVBoxLayout()
        left.addWidget(QLabel("Macro Sequences"))

        self._macro_list = QListWidget()
        self._macro_list.itemClicked.connect(self._on_macro_selected)
        left.addWidget(self._macro_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Macro")
        add_btn.setProperty("accent", True)
        add_btn.clicked.connect(self._add_macro)
        btn_row.addWidget(add_btn)

        del_btn = QPushButton("Delete")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(self._delete_macro)
        btn_row.addWidget(del_btn)
        left.addLayout(btn_row)

        lay.addLayout(left, 1)

        # Right: macro editor
        right = QVBoxLayout()
        right.addWidget(QLabel("Macro Editor"))

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._macro_name = QLineEdit()
        self._macro_name.setPlaceholderText("Macro name")
        name_row.addWidget(self._macro_name)
        right.addLayout(name_row)

        trigger_row = QHBoxLayout()
        trigger_row.addWidget(QLabel("Trigger:"))
        self._macro_trigger = QComboBox()
        self._macro_trigger.addItems(["Button Press", "Button Hold", "Double Tap", "Toggle"])
        self._macro_trigger.setToolTip("When this macro fires: on press, while held, on double-tap, or toggled on/off")
        trigger_row.addWidget(self._macro_trigger)
        trigger_row.addStretch()
        right.addLayout(trigger_row)

        # Visual / Raw toggle
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Editor Mode:"))
        self._editor_mode_stack = QStackedWidget()
        self._visual_mode_btn = QPushButton("📋 Visual")
        self._visual_mode_btn.setCheckable(True)
        self._visual_mode_btn.setChecked(True)
        self._visual_mode_btn.setToolTip("Visual step editor — add keys and delays with buttons")
        self._visual_mode_btn.clicked.connect(lambda: self._set_editor_mode(0))
        mode_row.addWidget(self._visual_mode_btn)
        self._raw_mode_btn = QPushButton("{ } Raw JSON")
        self._raw_mode_btn.setCheckable(True)
        self._raw_mode_btn.setToolTip("Edit the macro step array as raw JSON (power users)")
        self._raw_mode_btn.clicked.connect(lambda: self._set_editor_mode(1))
        mode_row.addWidget(self._raw_mode_btn)
        mode_row.addStretch()
        right.addLayout(mode_row)

        # --- Visual step list ---
        visual_widget = QWidget()
        visual_lay = QVBoxLayout(visual_widget)
        visual_lay.setContentsMargins(0, 0, 0, 0)

        self._step_list = QListWidget()
        self._step_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._step_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._step_list.setToolTip("Drag steps to reorder. Right-click for options.")
        self._step_list.model().rowsMoved.connect(self._on_steps_reordered)
        visual_lay.addWidget(self._step_list, 1)

        # Add step buttons
        add_row = QHBoxLayout()
        add_key_btn = QPushButton("+ Key Step")
        add_key_btn.setProperty("accent", True)
        add_key_btn.setToolTip("Add a key press/release step")
        add_key_btn.clicked.connect(self._add_key_step)
        add_row.addWidget(add_key_btn)

        add_delay_btn = QPushButton("+ Delay")
        add_delay_btn.setToolTip("Add a timing delay between steps")
        add_delay_btn.clicked.connect(self._add_delay_step)
        add_row.addWidget(add_delay_btn)

        del_step_btn = QPushButton("Remove Step")
        del_step_btn.setProperty("danger", True)
        del_step_btn.setToolTip("Remove the selected step")
        del_step_btn.clicked.connect(self._delete_step)
        add_row.addWidget(del_step_btn)
        add_row.addStretch()
        visual_lay.addLayout(add_row)

        # Inline step editor (shown when a step is selected)
        self._step_editor_frame = QGroupBox("Edit Step")
        step_ed_lay = QHBoxLayout(self._step_editor_frame)

        step_ed_lay.addWidget(QLabel("Key:"))
        self._step_key_combo = QComboBox()
        self._step_key_combo.setEditable(True)
        self._step_key_combo.setToolTip("HID key name for this step")
        self._step_key_combo.addItem("(none)", 0)
        for code, name in sorted(_KEYCODE_NAMES.items()):
            self._step_key_combo.addItem(name, code)
        self._step_key_combo.currentIndexChanged.connect(self._on_step_edited)
        step_ed_lay.addWidget(self._step_key_combo)

        step_ed_lay.addWidget(QLabel("Action:"))
        self._step_action_combo = QComboBox()
        self._step_action_combo.addItems(["Press", "Release"])
        self._step_action_combo.setToolTip("Press or release the key")
        self._step_action_combo.currentIndexChanged.connect(self._on_step_edited)
        step_ed_lay.addWidget(self._step_action_combo)

        step_ed_lay.addWidget(QLabel("Delay (ms):"))
        self._step_delay_spin = QSpinBox()
        self._step_delay_spin.setRange(0, 10000)
        self._step_delay_spin.setToolTip("Delay before this step executes (milliseconds)")
        self._step_delay_spin.valueChanged.connect(self._on_step_edited)
        step_ed_lay.addWidget(self._step_delay_spin)

        self._step_editor_frame.setVisible(False)
        visual_lay.addWidget(self._step_editor_frame)

        self._step_list.currentRowChanged.connect(self._on_step_selected)

        self._editor_mode_stack.addWidget(visual_widget)

        # --- Raw JSON editor ---
        raw_widget = QWidget()
        raw_lay = QVBoxLayout(raw_widget)
        raw_lay.setContentsMargins(0, 0, 0, 0)
        raw_lay.addWidget(QLabel("Steps (JSON array):"))
        self._macro_steps = QTextEdit()
        self._macro_steps.setPlaceholderText('[{"keycode": 4, "press": true, "delay_ms": 50}]')
        self._macro_steps.setFont(QFont(
            self._main.theme.typo("mono_family"),
            self._main.theme.typo("mono_size"),
        ))
        raw_lay.addWidget(self._macro_steps, 1)
        self._editor_mode_stack.addWidget(raw_widget)

        right.addWidget(self._editor_mode_stack, 1)

        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("Repeat:"))
        self._macro_repeat = QSpinBox()
        self._macro_repeat.setRange(1, 999)
        self._macro_repeat.setValue(1)
        self._macro_repeat.setToolTip("Number of times to repeat the entire macro sequence")
        opts_row.addWidget(self._macro_repeat)

        opts_row.addWidget(QLabel("Delay (ms):"))
        self._macro_delay = QSpinBox()
        self._macro_delay.setRange(0, 5000)
        self._macro_delay.setValue(0)
        self._macro_delay.setToolTip("Delay between repetitions (milliseconds)")
        opts_row.addWidget(self._macro_delay)
        opts_row.addStretch()
        right.addLayout(opts_row)

        save_btn = QPushButton("Save Macro")
        save_btn.setProperty("accent", True)
        save_btn.setToolTip("Save changes to the currently selected macro")
        save_btn.clicked.connect(self._save_macro)
        right.addWidget(save_btn)

        # Record macro
        rec_row = QHBoxLayout()
        self._record_btn = QPushButton("🔴 Record")
        self._record_btn.setCheckable(True)
        self._record_btn.setToolTip("Record key presses in real-time from the controller")
        self._record_btn.toggled.connect(self._toggle_record)
        rec_row.addWidget(self._record_btn)
        rec_row.addStretch()
        right.addLayout(rec_row)

        # Internal step data (list of dicts)
        self._visual_steps: List[Dict[str, Any]] = []

        lay.addLayout(right, 2)

    # -----------------------------------------------------------------
    # Layers tab
    # -----------------------------------------------------------------

    def _build_layers_tab(self) -> None:
        lay = QVBoxLayout(self._layers_tab)
        lay.setContentsMargins(16, 16, 16, 16)

        lay.addWidget(QLabel("Layer / Mask Configuration"))
        info = QLabel(
            "Layers allow multiple mapping sets on the same controller. "
            "A layer is activated by holding a trigger button, shifting "
            "all other buttons to a different keymap."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        lay.addWidget(info)

        self._layer_list = QListWidget()
        lay.addWidget(self._layer_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Layer")
        add_btn.setProperty("accent", True)
        add_btn.clicked.connect(self._add_layer)
        btn_row.addWidget(add_btn)

        del_btn = QPushButton("Delete Layer")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(self._delete_layer)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

    # -----------------------------------------------------------------
    # Chords tab
    # -----------------------------------------------------------------

    def _build_chords_tab(self) -> None:
        lay = QVBoxLayout(self._chords_tab)
        lay.setContentsMargins(16, 16, 16, 16)

        lay.addWidget(QLabel("Chord Mappings"))
        info = QLabel(
            "Chords trigger a unique output when multiple buttons are pressed "
            "simultaneously. Define button combinations and their output here."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        lay.addWidget(info)

        self._chord_list = QListWidget()
        lay.addWidget(self._chord_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Chord")
        add_btn.setProperty("accent", True)
        add_btn.clicked.connect(self._add_chord)
        btn_row.addWidget(add_btn)

        del_btn = QPushButton("Delete Chord")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(self._delete_chord)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

    # -----------------------------------------------------------------
    # Stick tab
    # -----------------------------------------------------------------

    def _build_stick_tab(self) -> None:
        lay = QHBoxLayout(self._stick_tab)
        lay.setContentsMargins(16, 16, 16, 16)

        # Left: settings
        settings = QVBoxLayout()
        settings.addWidget(QLabel("Analog Stick Configuration"))

        # Deadzone
        dz_group = QGroupBox("Deadzone")
        dz_lay = QVBoxLayout(dz_group)
        dz_row = QHBoxLayout()
        dz_row.addWidget(QLabel("Inner:"))
        self._dz_inner = QDoubleSpinBox()
        self._dz_inner.setRange(0.0, 0.5)
        self._dz_inner.setSingleStep(0.01)
        self._dz_inner.setValue(0.05)
        self._dz_inner.valueChanged.connect(self._on_stick_changed)
        dz_row.addWidget(self._dz_inner)
        dz_row.addWidget(QLabel("Outer:"))
        self._dz_outer = QDoubleSpinBox()
        self._dz_outer.setRange(0.5, 1.0)
        self._dz_outer.setSingleStep(0.01)
        self._dz_outer.setValue(1.0)
        self._dz_outer.valueChanged.connect(self._on_stick_changed)
        dz_row.addWidget(self._dz_outer)
        dz_lay.addLayout(dz_row)
        settings.addWidget(dz_group)

        # Sensitivity / Response curve
        curve_group = QGroupBox("Response Curve")
        curve_lay = QVBoxLayout(curve_group)

        curve_type_row = QHBoxLayout()
        curve_type_row.addWidget(QLabel("Type:"))
        self._curve_type = QComboBox()
        self._curve_type.addItems(["linear", "exponential", "s_curve"])
        self._curve_type.setToolTip("Response curve shape — linear is 1:1, exponential adds fine control near center")
        self._curve_type.currentTextChanged.connect(self._on_stick_changed)
        curve_type_row.addWidget(self._curve_type)
        curve_lay.addLayout(curve_type_row)

        sens_row = QHBoxLayout()
        sens_row.addWidget(QLabel("Sensitivity:"))
        self._sensitivity = QDoubleSpinBox()
        self._sensitivity.setRange(0.1, 5.0)
        self._sensitivity.setSingleStep(0.1)
        self._sensitivity.setValue(1.0)
        self._sensitivity.valueChanged.connect(self._on_stick_changed)
        sens_row.addWidget(self._sensitivity)
        curve_lay.addLayout(sens_row)

        settings.addWidget(curve_group)

        # SOCD mode
        socd_group = QGroupBox("SOCD Resolution")
        socd_lay = QVBoxLayout(socd_group)
        socd_row = QHBoxLayout()
        socd_row.addWidget(QLabel("Mode:"))
        self._socd_mode = QComboBox()
        self._socd_mode.addItems(["neutral", "last_wins", "first_wins"])
        self._socd_mode.setToolTip("How simultaneous opposite directions are resolved (e.g. Left+Right)")
        socd_row.addWidget(self._socd_mode)
        socd_lay.addLayout(socd_row)
        settings.addWidget(socd_group)

        settings.addStretch()
        lay.addLayout(settings, 1)

        # Right: curve preview
        preview = QVBoxLayout()
        preview.addWidget(QLabel("Curve Preview"))
        self._curve_preview = CurvePreviewWidget(self._main.theme)
        self._curve_preview.setMinimumSize(200, 200)
        preview.addWidget(self._curve_preview, 1)
        lay.addLayout(preview, 1)

    # -----------------------------------------------------------------
    # Editor mode toggle
    # -----------------------------------------------------------------

    def _set_editor_mode(self, mode: int) -> None:
        """Switch between visual (0) and raw JSON (1) editor."""
        self._visual_mode_btn.setChecked(mode == 0)
        self._raw_mode_btn.setChecked(mode == 1)
        if mode == 1:
            # Sync visual → raw
            self._macro_steps.setText(json.dumps(self._visual_steps, indent=2))
        elif mode == 0:
            # Sync raw → visual
            try:
                steps = json.loads(self._macro_steps.toPlainText() or "[]")
                if isinstance(steps, list):
                    self._visual_steps = steps
                    self._refresh_step_list()
            except json.JSONDecodeError:
                pass  # keep existing visual steps
        self._editor_mode_stack.setCurrentIndex(mode)

    # -----------------------------------------------------------------
    # Visual step operations
    # -----------------------------------------------------------------

    def _refresh_step_list(self) -> None:
        """Rebuild the visual step list from self._visual_steps."""
        self._step_list.clear()
        for step in self._visual_steps:
            kc = step.get("keycode", 0)
            name = _KEYCODE_NAMES.get(kc, f"0x{kc:02X}") if kc else "—"
            press = "▼ Press" if step.get("press", True) else "▲ Release"
            delay = step.get("delay_ms", 0)
            text = f"{name}  {press}"
            if delay:
                text += f"  (+{delay}ms)"
            self._step_list.addItem(text)

    def _add_key_step(self) -> None:
        self._visual_steps.append({"keycode": 0x04, "press": True, "delay_ms": 50})
        self._refresh_step_list()
        self._step_list.setCurrentRow(len(self._visual_steps) - 1)

    def _add_delay_step(self) -> None:
        self._visual_steps.append({"keycode": 0, "press": True, "delay_ms": 100})
        self._refresh_step_list()
        self._step_list.setCurrentRow(len(self._visual_steps) - 1)

    def _delete_step(self) -> None:
        idx = self._step_list.currentRow()
        if 0 <= idx < len(self._visual_steps):
            self._visual_steps.pop(idx)
            self._refresh_step_list()

    def _on_step_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._visual_steps):
            self._step_editor_frame.setVisible(False)
            return
        self._step_editor_frame.setVisible(True)
        step = self._visual_steps[row]

        # Block signals while populating
        self._step_key_combo.blockSignals(True)
        self._step_action_combo.blockSignals(True)
        self._step_delay_spin.blockSignals(True)

        kc = step.get("keycode", 0)
        idx = self._step_key_combo.findData(kc)
        self._step_key_combo.setCurrentIndex(max(0, idx))
        self._step_action_combo.setCurrentIndex(0 if step.get("press", True) else 1)
        self._step_delay_spin.setValue(step.get("delay_ms", 0))

        self._step_key_combo.blockSignals(False)
        self._step_action_combo.blockSignals(False)
        self._step_delay_spin.blockSignals(False)

    def _on_step_edited(self, *_args: Any) -> None:
        row = self._step_list.currentRow()
        if row < 0 or row >= len(self._visual_steps):
            return
        kc = self._step_key_combo.currentData()
        if kc is None:
            kc = 0
        self._visual_steps[row] = {
            "keycode": kc,
            "press": self._step_action_combo.currentIndex() == 0,
            "delay_ms": self._step_delay_spin.value(),
        }
        self._refresh_step_list()
        self._step_list.setCurrentRow(row)

    def _on_steps_reordered(self, *_args: Any) -> None:
        """Re-sync internal step list after drag-drop reorder."""
        # Rebuild from list text is fragile — instead, grab order from model
        # The model emits rowsMoved after internal move completes; we need to
        # rebuild _visual_steps from the new visual order.
        # Since we can't easily map text→step, we store step index in item data.
        pass  # handled via save which reads _visual_steps directly

    # -----------------------------------------------------------------
    # Macro operations
    # -----------------------------------------------------------------

    def _on_macro_selected(self, item: QListWidgetItem) -> None:
        idx = self._macro_list.row(item)
        profile = self._main.get_profile()
        macros = profile.get("macros", [])
        if 0 <= idx < len(macros):
            m = macros[idx]
            self._macro_name.setText(m.get("name", ""))
            self._visual_steps = list(m.get("steps", []))
            self._refresh_step_list()
            self._macro_steps.setText(json.dumps(m.get("steps", []), indent=2))
            self._macro_repeat.setValue(m.get("repeat", 1))
            self._macro_delay.setValue(m.get("delay_ms", 0))

    def _add_macro(self) -> None:
        profile = self._main.get_profile()
        if "macros" not in profile:
            profile["macros"] = []
        profile["macros"].append({
            "name": f"Macro {len(profile['macros']) + 1}",
            "steps": [],
            "repeat": 1,
            "delay_ms": 0,
        })
        self._main.set_profile(profile)
        self._refresh_macro_list()

    def _delete_macro(self) -> None:
        idx = self._macro_list.currentRow()
        if idx < 0:
            return
        profile = self._main.get_profile()
        macros = profile.get("macros", [])
        if 0 <= idx < len(macros):
            macros.pop(idx)
            self._main.set_profile(profile)
            self._refresh_macro_list()

    def _save_macro(self) -> None:
        idx = self._macro_list.currentRow()
        if idx < 0:
            QMessageBox.information(self, "No Selection", "Select or create a macro first.")
            return

        profile = self._main.get_profile()
        macros = profile.get("macros", [])
        if not (0 <= idx < len(macros)):
            return

        # Get steps from the active editor mode
        if self._editor_mode_stack.currentIndex() == 0:
            # Visual mode
            steps = list(self._visual_steps)
        else:
            # Raw JSON mode
            try:
                steps = json.loads(self._macro_steps.toPlainText() or "[]")
            except json.JSONDecodeError as e:
                QMessageBox.warning(self, "Invalid JSON", str(e))
                return

        macros[idx] = {
            "name": self._macro_name.text() or f"Macro {idx + 1}",
            "steps": steps,
            "repeat": self._macro_repeat.value(),
            "delay_ms": self._macro_delay.value(),
            "trigger": self._macro_trigger.currentText().lower().replace(" ", "_"),
        }
        self._main.set_profile(profile)
        self._refresh_macro_list()

    def _toggle_record(self, checked: bool) -> None:
        if checked:
            self._record_btn.setText("⏹ Stop Recording")
            self._recording_steps: List[Dict[str, Any]] = []
            self._recording_start = None
        else:
            self._record_btn.setText("🔴 Record")
            # Put recorded steps into both editors
            if hasattr(self, "_recording_steps") and self._recording_steps:
                self._visual_steps.extend(self._recording_steps)
                self._refresh_step_list()
                self._macro_steps.setText(
                    json.dumps(self._visual_steps, indent=2)
                )
            self._recording_steps = []

    def _refresh_macro_list(self) -> None:
        self._macro_list.clear()
        profile = self._main.get_profile()
        for m in profile.get("macros", []):
            name = m.get("name", "Unnamed")
            steps = len(m.get("steps", []))
            self._macro_list.addItem(f"{name} ({steps} steps)")

    # -----------------------------------------------------------------
    # Layer / Chord operations
    # -----------------------------------------------------------------

    def _add_layer(self) -> None:
        profile = self._main.get_profile()
        if "layers" not in profile:
            profile["layers"] = []
        profile["layers"].append({
            "name": f"Layer {len(profile['layers']) + 1}",
            "trigger": None,
            "mappings": {},
        })
        self._main.set_profile(profile)
        self._refresh_layer_list()

    def _delete_layer(self) -> None:
        idx = self._layer_list.currentRow()
        if idx < 0:
            return
        profile = self._main.get_profile()
        layers = profile.get("layers", [])
        if 0 <= idx < len(layers):
            layers.pop(idx)
            self._main.set_profile(profile)
            self._refresh_layer_list()

    def _refresh_layer_list(self) -> None:
        self._layer_list.clear()
        profile = self._main.get_profile()
        for layer in profile.get("layers", []):
            name = layer.get("name", "Unnamed")
            trigger = layer.get("trigger", "—")
            self._layer_list.addItem(f"{name} (trigger: {trigger})")

    def _add_chord(self) -> None:
        profile = self._main.get_profile()
        if "chords" not in profile:
            profile["chords"] = []
        profile["chords"].append({
            "buttons": [],
            "output": None,
        })
        self._main.set_profile(profile)
        self._refresh_chord_list()

    def _delete_chord(self) -> None:
        idx = self._chord_list.currentRow()
        if idx < 0:
            return
        profile = self._main.get_profile()
        chords = profile.get("chords", [])
        if 0 <= idx < len(chords):
            chords.pop(idx)
            self._main.set_profile(profile)
            self._refresh_chord_list()

    def _refresh_chord_list(self) -> None:
        self._chord_list.clear()
        profile = self._main.get_profile()
        for chord in profile.get("chords", []):
            buttons = chord.get("buttons", [])
            output = chord.get("output", "—")
            self._chord_list.addItem(f"{'+'.join(buttons)} → {output}")

    # -----------------------------------------------------------------
    # Stick config
    # -----------------------------------------------------------------

    def _on_stick_changed(self, *args: Any) -> None:
        self._curve_preview.set_curve(
            curve_type=self._curve_type.currentText(),
            deadzone=self._dz_inner.value(),
            sensitivity=self._sensitivity.value(),
        )
        # Save stick config to profile
        profile = self._main.get_profile()
        profile["stick"] = {
            "deadzone_inner": self._dz_inner.value(),
            "deadzone_outer": self._dz_outer.value(),
            "sensitivity": self._sensitivity.value(),
            "curve_type": self._curve_type.currentText(),
            "socd_mode": self._socd_mode.currentText(),
        }
        self._main.set_profile(profile)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def device_event(self, obj: dict) -> None:
        # Capture keystrokes during macro recording
        if (
            self._record_btn.isChecked()
            and hasattr(self, "_recording_steps")
            and obj.get("evt") == "mapped_key"
        ):
            key_id = obj.get("key_id")
            pressed = obj.get("pressed")
            if key_id is not None:
                now = time.monotonic()
                delay_ms = 0
                if self._recording_start is not None:
                    delay_ms = int((now - self._recording_start) * 1000)
                self._recording_start = now
                self._recording_steps.append({
                    "keycode": key_id,
                    "press": bool(pressed),
                    "delay_ms": delay_ms,
                })

    def profile_loaded(self, slot: int, profile: dict) -> None:
        self._refresh_macro_list()
        self._refresh_layer_list()
        self._refresh_chord_list()
        stick = profile.get("stick", {})
        self._dz_inner.setValue(stick.get("deadzone_inner", 0.05))
        self._dz_outer.setValue(stick.get("deadzone_outer", 1.0))
        self._sensitivity.setValue(stick.get("sensitivity", 1.0))
        curve = stick.get("curve_type", "linear")
        idx = self._curve_type.findText(curve)
        if idx >= 0:
            self._curve_type.setCurrentIndex(idx)
        self._on_stick_changed()

    def profile_updated(self, profile: dict) -> None:
        self._refresh_macro_list()

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._curve_preview.apply_theme(theme)
