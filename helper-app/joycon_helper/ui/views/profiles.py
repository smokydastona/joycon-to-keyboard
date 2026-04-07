"""Profiles view — profile management, import/export, share codes, presets.

Merges the old Loadout + Share tabs into a unified profile management view.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from ..theme import ThemeEngine
from ..widgets.card import Card
from ...app_switcher import load_rules, save_rules, _get_foreground_exe

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.profiles")


# Default empty profile structure
def _default_profile() -> dict:
    return {
        "name": "New Profile",
        "mappings": {},
        "macros": [],
        "layers": [],
        "chords": [],
        "stick": {
            "deadzone_inner": 0.05,
            "deadzone_outer": 1.0,
            "sensitivity": 1.0,
            "curve_type": "linear",
        },
    }


class ProfilesView(QWidget):
    """Profile management: CRUD, import/export, share codes."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        self._build_left_panel(layout)
        self._build_right_panel(layout)

    # -----------------------------------------------------------------
    def _build_left_panel(self, parent_layout: QHBoxLayout) -> None:
        left = QVBoxLayout()

        # Header
        header = QLabel("Profiles")
        header.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        left.addWidget(header)

        # Slot cards
        slot_group = QGroupBox("Device Slots")
        slot_lay = QVBoxLayout(slot_group)

        self._slot_cards: List[QPushButton] = []
        for i in range(4):
            btn = QPushButton(f"Slot {i}: (empty)")
            btn.setFixedHeight(48)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, s=i: self._select_slot(s))
            slot_lay.addWidget(btn)
            self._slot_cards.append(btn)

        left.addWidget(slot_group)

        # Profile actions
        actions_group = QGroupBox("Actions")
        actions_lay = QVBoxLayout(actions_group)

        btn_row1 = QHBoxLayout()
        new_btn = QPushButton("New Profile")
        new_btn.setProperty("accent", True)
        new_btn.clicked.connect(self._new_profile)
        btn_row1.addWidget(new_btn)

        dup_btn = QPushButton("Duplicate")
        dup_btn.clicked.connect(self._duplicate_profile)
        btn_row1.addWidget(dup_btn)
        actions_lay.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        load_btn = QPushButton("Load from File")
        load_btn.clicked.connect(self._load_from_file)
        btn_row2.addWidget(load_btn)

        save_btn = QPushButton("Save to File")
        save_btn.clicked.connect(self._save_to_file)
        btn_row2.addWidget(save_btn)
        actions_lay.addLayout(btn_row2)

        btn_row3 = QHBoxLayout()
        upload_btn = QPushButton("Upload to Device")
        upload_btn.setProperty("accent", True)
        upload_btn.clicked.connect(self._upload_profile)
        btn_row3.addWidget(upload_btn)

        read_btn = QPushButton("Read from Device")
        read_btn.clicked.connect(self._read_profile)
        btn_row3.addWidget(read_btn)
        actions_lay.addLayout(btn_row3)

        btn_row4 = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_profile)
        btn_row4.addWidget(rename_btn)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setProperty("danger", True)
        reset_btn.clicked.connect(self._reset_to_default)
        btn_row4.addWidget(reset_btn)
        actions_lay.addLayout(btn_row4)

        left.addWidget(actions_group)

        # Community presets
        preset_group = QGroupBox("Community Presets")
        preset_lay = QVBoxLayout(preset_group)

        preset_info = QLabel("Load a pre-built profile optimized for a game genre.")
        preset_info.setWordWrap(True)
        preset_info.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        preset_lay.addWidget(preset_info)

        self._preset_combo = QComboBox()
        self._preset_combo.addItems([
            "FPS / Shooter",
            "Racing / Driving",
            "Platformer / Action",
            "RPG / MMO",
            "Strategy / RTS",
        ])
        preset_lay.addWidget(self._preset_combo)

        load_preset_btn = QPushButton("Load Preset")
        load_preset_btn.clicked.connect(self._load_preset)
        preset_lay.addWidget(load_preset_btn)

        left.addWidget(preset_group)

        # Undo/Redo
        undo_group = QGroupBox("History")
        undo_lay = QHBoxLayout(undo_group)

        self._undo_btn = QPushButton("↩ Undo (Ctrl+Z)")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._main.undo)
        undo_lay.addWidget(self._undo_btn)

        self._redo_btn = QPushButton("↪ Redo (Ctrl+Y)")
        self._redo_btn.setEnabled(False)
        self._redo_btn.clicked.connect(self._main.redo)
        undo_lay.addWidget(self._redo_btn)

        left.addWidget(undo_group)

        # App Switcher
        switch_group = QGroupBox("App Switcher")
        switch_lay = QVBoxLayout(switch_group)

        self._switch_enable = QCheckBox("Auto-switch profiles by foreground app")
        self._switch_enable.toggled.connect(self._toggle_app_switcher)
        switch_lay.addWidget(self._switch_enable)

        self._switch_list = QListWidget()
        self._switch_list.setMaximumHeight(120)
        switch_lay.addWidget(self._switch_list)

        switch_btn_row = QHBoxLayout()
        detect_btn = QPushButton("Detect App")
        detect_btn.setToolTip("Add a rule for the currently active window")
        detect_btn.clicked.connect(self._app_switch_detect)
        switch_btn_row.addWidget(detect_btn)

        add_btn = QPushButton("Add Rule")
        add_btn.clicked.connect(self._app_switch_add)
        switch_btn_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._app_switch_remove)
        switch_btn_row.addWidget(remove_btn)
        switch_lay.addLayout(switch_btn_row)

        # Default slot
        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("Default slot:"))
        self._default_slot_combo = QComboBox()
        self._default_slot_combo.addItems(["0", "1", "2", "3"])
        self._default_slot_combo.currentIndexChanged.connect(self._app_switch_default_changed)
        default_row.addWidget(self._default_slot_combo)
        default_row.addStretch()
        switch_lay.addLayout(default_row)

        left.addWidget(switch_group)

        # Populate rules from disk
        self._refresh_switch_list()

        left.addStretch()

        parent_layout.addLayout(left, 1)

    # -----------------------------------------------------------------
    def _build_right_panel(self, parent_layout: QHBoxLayout) -> None:
        right = QVBoxLayout()

        # Profile name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Profile Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("My Profile")
        self._name_edit.textChanged.connect(self._on_name_changed)
        name_row.addWidget(self._name_edit)
        right.addLayout(name_row)

        # Profile JSON editor
        right.addWidget(QLabel("Profile JSON:"))
        self._json_editor = QTextEdit()
        self._json_editor.setFont(QFont(
            self._main.theme.typo("mono_family"),
            self._main.theme.typo("mono_size"),
        ))
        self._json_editor.setPlaceholderText("Profile JSON will appear here...")
        right.addWidget(self._json_editor, 1)

        # Validation
        val_row = QHBoxLayout()
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self._validate_json)
        val_row.addWidget(validate_btn)

        apply_btn = QPushButton("Apply Changes")
        apply_btn.setProperty("accent", True)
        apply_btn.clicked.connect(self._apply_json)
        val_row.addWidget(apply_btn)

        self._validation_label = QLabel("")
        val_row.addWidget(self._validation_label, 1)
        right.addLayout(val_row)

        # Share code section
        share_group = QGroupBox("Share Codes")
        share_lay = QVBoxLayout(share_group)

        export_row = QHBoxLayout()
        self._share_code_out = QLineEdit()
        self._share_code_out.setReadOnly(True)
        self._share_code_out.setPlaceholderText("Generate a share code...")
        export_row.addWidget(self._share_code_out, 1)
        gen_btn = QPushButton("Generate")
        gen_btn.clicked.connect(self._generate_share_code)
        export_row.addWidget(gen_btn)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy_share_code)
        export_row.addWidget(copy_btn)
        share_lay.addLayout(export_row)

        import_row = QHBoxLayout()
        self._share_code_in = QLineEdit()
        self._share_code_in.setPlaceholderText("Paste a share code here...")
        import_row.addWidget(self._share_code_in, 1)
        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self._import_share_code)
        import_row.addWidget(import_btn)
        share_lay.addLayout(import_row)

        right.addWidget(share_group)

        parent_layout.addLayout(right, 2)

    # -----------------------------------------------------------------
    # Operations
    # -----------------------------------------------------------------

    def _select_slot(self, slot: int) -> None:
        self._main._slot_combo.setCurrentIndex(slot)
        self._main._cmd_read_profile()

    def _new_profile(self) -> None:
        profile = _default_profile()
        self._main.set_profile(profile)
        self._refresh_editor()

    def _duplicate_profile(self) -> None:
        import copy
        profile = copy.deepcopy(self._main.get_profile())
        name = profile.get("name", "Profile")
        profile["name"] = f"{name} (copy)"
        self._main.set_profile(profile)
        self._refresh_editor()

    def _load_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Failed", str(e))
            return
        self._main.set_profile(data)
        self._refresh_editor()

    def _save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "profile.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._main.get_profile(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def _upload_profile(self) -> None:
        self._main._cmd_write_profile()

    def _read_profile(self) -> None:
        self._main._cmd_read_profile()

    def _rename_profile(self) -> None:
        profile = self._main.get_profile()
        old_name = profile.get("name", "")
        new_name, ok = QInputDialog.getText(
            self, "Rename Profile", "New name:", text=old_name,
        )
        if ok and new_name.strip():
            profile["name"] = new_name.strip()
            self._main.set_profile(profile)
            self._refresh_editor()

    def _reset_to_default(self) -> None:
        reply = QMessageBox.question(
            self, "Reset to Default",
            "Reset the current profile to factory defaults?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._main.set_profile(_default_profile())
            self._refresh_editor()

    def _load_preset(self) -> None:
        genre = self._preset_combo.currentText()
        preset = _default_profile()
        preset["name"] = genre

        # Genre-specific defaults
        if "FPS" in genre:
            preset["mappings"] = {
                "L_Stick_Press": {"keycode": 0x1A, "modifier": 0},  # W
                "R_Stick_Press": {"keycode": 0x16, "modifier": 0},  # S
                "ZL": {"keycode": 0x00, "modifier": 0x02},          # LShift (sprint)
                "ZR": {"keycode": 0x00, "modifier": 0x01},          # LCtrl (crouch)
                "A": {"keycode": 0x2C, "modifier": 0},              # Space (jump)
                "B": {"keycode": 0x15, "modifier": 0},              # R (reload)
                "X": {"keycode": 0x08, "modifier": 0},              # E (interact)
                "Y": {"keycode": 0x0A, "modifier": 0},              # G (grenade)
            }
        elif "Racing" in genre:
            preset["mappings"] = {
                "ZR": {"keycode": 0x1A, "modifier": 0},   # W (accel)
                "ZL": {"keycode": 0x16, "modifier": 0},   # S (brake)
                "L_Stick_Press": {"keycode": 0x04, "modifier": 0},  # A (left)
                "R_Stick_Press": {"keycode": 0x07, "modifier": 0},  # D (right)
                "A": {"keycode": 0x11, "modifier": 0},    # N (nitro)
                "X": {"keycode": 0x2C, "modifier": 0},    # Space (handbrake)
            }
        elif "Platformer" in genre:
            preset["mappings"] = {
                "A": {"keycode": 0x2C, "modifier": 0},    # Space (jump)
                "B": {"keycode": 0x1B, "modifier": 0},    # X (attack)
                "X": {"keycode": 0x1D, "modifier": 0},    # Z (special)
                "Y": {"keycode": 0x06, "modifier": 0},    # C (interact)
            }
        elif "RPG" in genre:
            preset["mappings"] = {
                "A": {"keycode": 0x2C, "modifier": 0},    # Space (confirm)
                "B": {"keycode": 0x29, "modifier": 0},    # Esc (cancel)
                "X": {"keycode": 0x0C, "modifier": 0},    # I (inventory)
                "Y": {"keycode": 0x10, "modifier": 0},    # M (map)
                "L": {"keycode": 0x14, "modifier": 0},    # Q (prev)
                "R": {"keycode": 0x08, "modifier": 0},    # E (next)
            }
        elif "Strategy" in genre:
            preset["mappings"] = {
                "A": {"keycode": 0x2C, "modifier": 0},    # Space (pause)
                "L": {"keycode": 0x2B, "modifier": 0},    # Tab (cycle)
                "ZL": {"keycode": 0x00, "modifier": 0x01},  # LCtrl (group)
            }

        self._main.set_profile(preset)
        self._refresh_editor()

    def _on_name_changed(self, text: str) -> None:
        profile = self._main.get_profile()
        profile["name"] = text

    def _refresh_editor(self) -> None:
        profile = self._main.get_profile()
        self._name_edit.setText(profile.get("name", ""))
        self._json_editor.setText(json.dumps(profile, indent=2, ensure_ascii=False))

    def _validate_json(self) -> None:
        try:
            json.loads(self._json_editor.toPlainText())
            self._validation_label.setText("✓ Valid JSON")
            self._validation_label.setStyleSheet(
                f"color: {self._main.theme.color('success')};"
            )
        except json.JSONDecodeError as e:
            self._validation_label.setText(f"✗ {e}")
            self._validation_label.setStyleSheet(
                f"color: {self._main.theme.color('danger')};"
            )

    def _apply_json(self) -> None:
        try:
            data = json.loads(self._json_editor.toPlainText())
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            return
        self._main.set_profile(data)

    # -----------------------------------------------------------------
    # Share codes
    # -----------------------------------------------------------------

    def _generate_share_code(self) -> None:
        import base64
        import zlib
        profile = self._main.get_profile()
        raw = json.dumps(profile, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        compressed = zlib.compress(raw, 9)
        encoded = base64.urlsafe_b64encode(compressed).decode("ascii")
        code = f"JCB1:{encoded}"
        self._share_code_out.setText(code)

    def _copy_share_code(self) -> None:
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._share_code_out.text())

    def _import_share_code(self) -> None:
        import base64
        import zlib
        code = self._share_code_in.text().strip()
        if not code.startswith("JCB1:"):
            QMessageBox.warning(self, "Invalid Code", "Share code must start with 'JCB1:'")
            return
        payload = code[5:]
        try:
            compressed = base64.urlsafe_b64decode(payload)
            raw = zlib.decompress(compressed)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            QMessageBox.warning(self, "Import Failed", str(e))
            return
        self._main.set_profile(data)
        self._refresh_editor()

    # -----------------------------------------------------------------
    # App Switcher
    # -----------------------------------------------------------------

    def _toggle_app_switcher(self, checked: bool) -> None:
        self._main._app_switcher.enabled = checked

    def _refresh_switch_list(self) -> None:
        self._switch_list.clear()
        for rule in self._main._app_switcher.rules:
            exe = rule.get("exe", "?")
            slot = rule.get("slot", 0)
            self._switch_list.addItem(f"{exe}  →  Slot {slot}")

    def _app_switch_detect(self) -> None:
        exe = _get_foreground_exe()
        if not exe:
            QMessageBox.information(self, "Detect", "Could not detect the foreground application.")
            return
        slot = self._main._slot
        rules = self._main._app_switcher.rules
        # Don't duplicate
        for r in rules:
            if r.get("exe", "").lower() == exe:
                QMessageBox.information(self, "Detect", f"'{exe}' is already mapped.")
                return
        rules.append({"exe": exe, "slot": slot})
        self._main._app_switcher.set_rules(rules)
        save_rules(rules)
        self._refresh_switch_list()

    def _app_switch_add(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        exe, ok = QInputDialog.getText(self, "Add Rule", "Executable name (e.g. game.exe):")
        if not ok or not exe.strip():
            return
        exe = exe.strip().lower()
        slot = self._main._slot
        rules = self._main._app_switcher.rules
        for r in rules:
            if r.get("exe", "").lower() == exe:
                QMessageBox.information(self, "Add Rule", f"'{exe}' is already mapped.")
                return
        rules.append({"exe": exe, "slot": slot})
        self._main._app_switcher.set_rules(rules)
        save_rules(rules)
        self._refresh_switch_list()

    def _app_switch_remove(self) -> None:
        row = self._switch_list.currentRow()
        if row < 0:
            return
        rules = self._main._app_switcher.rules
        if 0 <= row < len(rules):
            rules.pop(row)
            self._main._app_switcher.set_rules(rules)
            save_rules(rules)
            self._refresh_switch_list()

    def _app_switch_default_changed(self, index: int) -> None:
        self._main._app_switcher.set_default_slot(index)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def device_event(self, obj: dict) -> None:
        pass

    def profile_loaded(self, slot: int, profile: dict) -> None:
        name = profile.get("name", f"(slot {slot})")
        if 0 <= slot < len(self._slot_cards):
            self._slot_cards[slot].setText(f"Slot {slot}: {name}")
        self._refresh_editor()

    def profile_updated(self, profile: dict) -> None:
        self._refresh_editor()

    def apply_theme(self, theme: ThemeEngine) -> None:
        pass
