"""Profiles view — profile management, import/export, share codes, presets.

Merges the old Loadout + Share tabs into a unified profile management view.
Includes search, tag chips, mapping preview, and profile icons.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...app_switcher import _get_foreground_exe, list_running_processes, save_rules
from ...default_profiles import BUILT_IN_PROFILES, get_default_profile
from ..theme import ThemeEngine

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.profiles")

# Tag presets
PROFILE_TAGS = [
    "FPS", "Racing", "Platformer", "RPG", "Strategy",
    "Emulation", "Accessibility", "Custom",
]

# Quick-pick emoji icons for profiles
PROFILE_ICONS = [
    "🎮", "🕹️", "🏎️", "⚔️", "🛡️", "🏹", "🧙", "🚀",
    "🎯", "🔫", "💣", "🗡️", "🌟", "🔥", "❄️", "⚡",
]


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

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        self._build_left_panel(splitter)
        self._build_right_panel(splitter)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 560])

    # -----------------------------------------------------------------
    def _build_left_panel(self, splitter: QSplitter) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(285)
        scroll.setMaximumWidth(380)

        container = QWidget()
        scroll.setWidget(container)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(8, 10, 8, 10)
        outer.setSpacing(8)

        # Header
        header = QLabel("Profiles")
        header.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        outer.addWidget(header)

        # Search bar
        search_row = QHBoxLayout()
        search_icon = QLabel("🔍")
        search_row.addWidget(search_icon)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search profiles…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_input)
        outer.addLayout(search_row)

        # ── Tab widget: Profiles | App Switcher ──────────────────────
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        outer.addWidget(tabs, 1)

        # ── Profiles tab ─────────────────────────────────────────────
        profiles_tab = QWidget()
        pt = QVBoxLayout(profiles_tab)
        pt.setContentsMargins(2, 8, 2, 4)
        pt.setSpacing(8)

        # Slot cards
        slot_group = QGroupBox("Device Slots")
        slot_lay = QVBoxLayout(slot_group)
        slot_lay.setSpacing(4)
        self._slot_cards: list[QPushButton] = []
        for i in range(4):
            builtin = BUILT_IN_PROFILES[i]
            label = builtin.get("name", f"(slot {i})")
            icon = builtin.get("icon", "🎮")
            btn = QPushButton(f"{icon} Slot {i}: {label}")
            btn.setFixedHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, s=i: self._select_slot(s))
            slot_lay.addWidget(btn)
            self._slot_cards.append(btn)
        pt.addWidget(slot_group)

        # Profile actions — stacked buttons (no horizontal crowding)
        actions_group = QGroupBox("Actions")
        actions_lay = QVBoxLayout(actions_group)
        actions_lay.setSpacing(4)

        new_btn = QPushButton("New Profile")
        new_btn.setProperty("accent", True)
        new_btn.clicked.connect(self._new_profile)
        actions_lay.addWidget(new_btn)

        dup_btn = QPushButton("Duplicate")
        dup_btn.clicked.connect(self._duplicate_profile)
        actions_lay.addWidget(dup_btn)

        load_btn = QPushButton("Load from File")
        load_btn.clicked.connect(self._load_from_file)
        actions_lay.addWidget(load_btn)

        save_btn = QPushButton("Save to File")
        save_btn.clicked.connect(self._save_to_file)
        actions_lay.addWidget(save_btn)

        upload_btn = QPushButton("Upload to Device")
        upload_btn.setProperty("accent", True)
        upload_btn.clicked.connect(self._upload_profile)
        actions_lay.addWidget(upload_btn)

        read_btn = QPushButton("Read from Device")
        read_btn.clicked.connect(self._read_profile)
        actions_lay.addWidget(read_btn)

        rr_row = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_profile)
        rr_row.addWidget(rename_btn)
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setProperty("danger", True)
        reset_btn.clicked.connect(self._reset_to_default)
        rr_row.addWidget(reset_btn)
        actions_lay.addLayout(rr_row)

        pt.addWidget(actions_group)

        # Community presets
        preset_group = QGroupBox("Community Presets")
        preset_lay = QVBoxLayout(preset_group)

        preset_info = QLabel("Load a pre-built profile for a game genre.")
        preset_info.setWordWrap(True)
        preset_info.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        preset_lay.addWidget(preset_info)

        self._preset_combo = QComboBox()
        self._preset_combo.setToolTip("Pick a game genre to load a recommended starting key layout")
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
        pt.addWidget(preset_group)

        # Undo/Redo
        undo_group = QGroupBox("History")
        undo_lay = QHBoxLayout(undo_group)
        self._undo_btn = QPushButton("↩ Undo")
        self._undo_btn.setEnabled(False)
        self._undo_btn.setToolTip("Revert the last profile change (Ctrl+Z)")
        self._undo_btn.clicked.connect(self._main.undo)
        undo_lay.addWidget(self._undo_btn)
        self._redo_btn = QPushButton("↪ Redo")
        self._redo_btn.setEnabled(False)
        self._redo_btn.setToolTip("Re-apply the last undone change (Ctrl+Y)")
        self._redo_btn.clicked.connect(self._main.redo)
        undo_lay.addWidget(self._redo_btn)
        pt.addWidget(undo_group)

        pt.addStretch()
        tabs.addTab(profiles_tab, "Profiles")

        # ── App Switcher tab ─────────────────────────────────────────
        switch_tab = QWidget()
        st = QVBoxLayout(switch_tab)
        st.setContentsMargins(2, 8, 2, 4)
        st.setSpacing(8)

        self._switch_enable = QCheckBox("Auto-switch profiles by foreground app")
        self._switch_enable.setToolTip(
            "When enabled, the active profile slot changes automatically\n"
            "based on which application is in the foreground."
        )
        self._switch_enable.toggled.connect(self._toggle_app_switcher)
        st.addWidget(self._switch_enable)

        # Table: App Name | Slot | Remove
        self._switch_table = QTableWidget(0, 3)
        self._switch_table.setHorizontalHeaderLabels(["Application", "Slot", ""])
        self._switch_table.horizontalHeader().setStretchLastSection(False)
        self._switch_table.setColumnWidth(0, 160)
        self._switch_table.setColumnWidth(1, 52)
        self._switch_table.setColumnWidth(2, 44)
        self._switch_table.setMinimumHeight(140)
        self._switch_table.setToolTip("Rules mapping foreground applications to profile slots")
        self._switch_table.verticalHeader().setVisible(False)
        st.addWidget(self._switch_table, 1)

        # Buttons — 2 rows of 2 so they don't overflow width
        btn_row_a = QHBoxLayout()
        detect_btn = QPushButton("🔍 Detect App")
        detect_btn.setToolTip("Add a rule for the currently active foreground window")
        detect_btn.clicked.connect(self._app_switch_detect)
        btn_row_a.addWidget(detect_btn)
        browse_btn = QPushButton("📂 Browse…")
        browse_btn.setToolTip("Browse for an executable file to add a rule for")
        browse_btn.clicked.connect(self._app_switch_browse)
        btn_row_a.addWidget(browse_btn)
        st.addLayout(btn_row_a)

        btn_row_b = QHBoxLayout()
        add_btn = QPushButton("✏ Add Rule")
        add_btn.setToolTip("Manually type an executable name to add a rule")
        add_btn.clicked.connect(self._app_switch_add)
        btn_row_b.addWidget(add_btn)
        proc_btn = QPushButton("🖥 Processes…")
        proc_btn.setToolTip("Pick from a live list of all currently running processes")
        proc_btn.clicked.connect(self._app_switch_pick_process)
        btn_row_b.addWidget(proc_btn)
        st.addLayout(btn_row_b)

        # Default slot
        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("Default slot:"))
        self._default_slot_combo = QComboBox()
        self._default_slot_combo.addItems(["0", "1", "2", "3"])
        self._default_slot_combo.setToolTip("Profile slot used when no rule matches the foreground app")
        self._default_slot_combo.currentIndexChanged.connect(self._app_switch_default_changed)
        default_row.addWidget(self._default_slot_combo)
        default_row.addStretch()
        st.addLayout(default_row)

        st.addStretch()
        tabs.addTab(switch_tab, "App Switcher")

        # Populate rules from disk
        self._refresh_switch_table()

        splitter.addWidget(scroll)

    # -----------------------------------------------------------------
    def _build_right_panel(self, splitter: QSplitter) -> None:
        right_widget = QWidget()
        right_widget.setMinimumWidth(320)
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(12, 12, 12, 12)
        right.setSpacing(8)

        # Profile name + icon — inside a group box so it stays tidy
        name_group = QGroupBox("Profile")
        name_lay = QHBoxLayout(name_group)
        self._icon_btn = QPushButton("🎮")
        self._icon_btn.setFixedSize(36, 36)
        self._icon_btn.setToolTip("Change profile icon")
        self._icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_btn.clicked.connect(self._pick_icon)
        name_lay.addWidget(self._icon_btn)
        name_lay.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("My Profile")
        self._name_edit.textChanged.connect(self._on_name_changed)
        name_lay.addWidget(self._name_edit, 1)
        right.addWidget(name_group)

        # Tag chips — 2×4 grid so they never overflow horizontally
        tag_group = QGroupBox("Tags")
        tag_lay = QGridLayout(tag_group)
        tag_lay.setSpacing(4)
        self._tag_checks: dict[str, QCheckBox] = {}
        for i, tag in enumerate(PROFILE_TAGS):
            cb = QCheckBox(tag)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.toggled.connect(lambda checked, t=tag: self._on_tag_toggled(t, checked))
            tag_lay.addWidget(cb, i // 4, i % 4)
            self._tag_checks[tag] = cb
        right.addWidget(tag_group)

        # Mapping preview grid — capped height so it doesn't crowd the editor
        preview_group = QGroupBox("Mapping Preview")
        preview_group.setMaximumHeight(118)
        preview_lay = QVBoxLayout(preview_group)
        preview_lay.setContentsMargins(4, 4, 4, 4)
        self._preview_grid = QGridLayout()
        self._preview_grid.setSpacing(3)
        self._preview_labels: dict[str, QLabel] = {}
        common_buttons = [
            "A", "B", "X", "Y", "L", "R",
            "ZL", "ZR", "Plus", "Minus", "Home", "Capture",
            "D-Up", "D-Down", "D-Left", "D-Right", "L3", "R3",
        ]
        for i, bname in enumerate(common_buttons):
            lbl = QLabel(bname)
            lbl.setFixedSize(QSize(56, 22))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"background: {self._main.theme.theme['colors']['surface']}; "
                f"border: 1px solid {self._main.theme.theme['colors']['border_light']}; "
                f"border-radius: 4px; font-size: 9px;"
            )
            self._preview_grid.addWidget(lbl, i // 6, i % 6)
            self._preview_labels[bname] = lbl
        preview_lay.addLayout(self._preview_grid)
        right.addWidget(preview_group)

        # Active layer indicator
        layer_row = QHBoxLayout()
        layer_row.addWidget(QLabel("Active Layer:"))
        self._layer_indicator = QLabel("Base")
        self._layer_indicator.setStyleSheet(
            f"color: {self._main.theme.theme['colors']['accent']}; font-weight: bold;"
        )
        layer_row.addWidget(self._layer_indicator)
        layer_row.addStretch()
        right.addLayout(layer_row)

        # Profile JSON editor (takes remaining space)
        right.addWidget(QLabel("Profile JSON:"))
        self._json_editor = QTextEdit()
        self._json_editor.setFont(QFont(
            self._main.theme.typo("mono_family"),
            self._main.theme.typo("mono_size"),
        ))
        self._json_editor.setPlaceholderText("Profile JSON will appear here...")
        right.addWidget(self._json_editor, 1)

        # Validation row
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

        # Share codes
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

        splitter.addWidget(right_widget)

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
            with open(path, encoding="utf-8") as f:
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
            slot = int(self._main._slot_combo.currentText())
            self._main.set_profile(get_default_profile(slot))
            self._refresh_editor()

    def _load_preset(self) -> None:
        genre = self._preset_combo.currentText()

        # Map combo text → built-in profile slot
        _GENRE_SLOT = {
            "FPS / Shooter": 1,
            "Racing / Driving": 3,
            "Platformer / Action": 2,
            "RPG / MMO": 0,       # General all-purpose preset
            "Strategy / RTS": 0,  # General all-purpose preset
        }
        slot = _GENRE_SLOT.get(genre, 0)
        preset = get_default_profile(slot)
        preset["name"] = genre

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

    def _refresh_switch_table(self) -> None:
        rules = self._main._app_switcher.rules
        self._switch_table.setRowCount(len(rules))
        for i, rule in enumerate(rules):
            exe = rule.get("exe", "?")
            slot = rule.get("slot", 0)

            exe_item = QTableWidgetItem(exe)
            exe_item.setFlags(exe_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._switch_table.setItem(i, 0, exe_item)

            slot_combo = QComboBox()
            slot_combo.addItems(["0", "1", "2", "3"])
            slot_combo.setCurrentIndex(slot)
            slot_combo.currentIndexChanged.connect(
                lambda new_slot, row=i: self._app_switch_slot_changed(row, new_slot)
            )
            self._switch_table.setCellWidget(i, 1, slot_combo)

            rm_btn = QPushButton("×")
            rm_btn.setFixedWidth(40)
            rm_btn.setProperty("danger", True)
            rm_btn.setToolTip("Remove this rule")
            rm_btn.clicked.connect(lambda _, row=i: self._app_switch_remove(row))
            self._switch_table.setCellWidget(i, 2, rm_btn)

    def _app_switch_slot_changed(self, row: int, new_slot: int) -> None:
        rules = self._main._app_switcher.rules
        if 0 <= row < len(rules):
            rules[row]["slot"] = new_slot
            self._main._app_switcher.set_rules(rules)
            save_rules(rules)

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
        self._refresh_switch_table()

    def _app_switch_browse(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Application", "", "Executables (*.exe);;All Files (*)"
        )
        if not path:
            return
        import os
        exe = os.path.basename(path).lower()
        slot = self._main._slot
        rules = self._main._app_switcher.rules
        for r in rules:
            if r.get("exe", "").lower() == exe:
                QMessageBox.information(self, "Browse", f"'{exe}' is already mapped.")
                return
        rules.append({"exe": exe, "slot": slot})
        self._main._app_switcher.set_rules(rules)
        save_rules(rules)
        self._refresh_switch_table()

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
        self._refresh_switch_table()

    def _app_switch_pick_process(self) -> None:
        """Show a searchable dialog of all currently running processes to add a rule."""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QListWidgetItem

        procs = list_running_processes()
        if not procs:
            QMessageBox.information(
                self, "Running Processes",
                "Could not enumerate running processes (Windows-only feature)."
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Pick a Running Process")
        dlg.setMinimumWidth(420)
        dlg.setMinimumHeight(420)
        lay = QVBoxLayout(dlg)

        search = QLineEdit()
        search.setPlaceholderText("Filter by name…")
        search.setClearButtonEnabled(True)
        lay.addWidget(search)

        lst = QListWidget()
        for basename, full_path in procs:
            item = QListWidgetItem(f"{basename}  —  {full_path}")
            item.setData(Qt.ItemDataRole.UserRole, basename)
            lst.addItem(item)
        lay.addWidget(lst, 1)

        def _filter(text: str) -> None:
            q = text.strip().lower()
            for i in range(lst.count()):
                item = lst.item(i)
                if item is not None:
                    item.setHidden(bool(q) and q not in item.text().lower())

        search.textChanged.connect(_filter)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        sel = lst.currentItem()
        if sel is None:
            return
        exe = sel.data(Qt.ItemDataRole.UserRole)  # lowercased basename
        if not exe:
            return

        slot = self._main._slot
        rules = self._main._app_switcher.rules
        for r in rules:
            if r.get("exe", "").lower() == exe:
                QMessageBox.information(self, "Processes", f"'{exe}' is already mapped.")
                return
        rules.append({"exe": exe, "slot": slot})
        self._main._app_switcher.set_rules(rules)
        save_rules(rules)
        self._refresh_switch_table()

    def _app_switch_remove(self, row: int) -> None:
        rules = self._main._app_switcher.rules
        if 0 <= row < len(rules):
            rules.pop(row)
            self._main._app_switcher.set_rules(rules)
            save_rules(rules)
            self._refresh_switch_table()

    def _app_switch_default_changed(self, index: int) -> None:
        self._main._app_switcher.set_default_slot(index)

    # -----------------------------------------------------------------
    # Search, Tags, Icon, Preview
    # -----------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        """Filter slot card visibility based on search text."""
        query = text.strip().lower()
        for _i, btn in enumerate(self._slot_cards):
            label = btn.text().lower()
            btn.setVisible(not query or query in label)

    def _on_tag_toggled(self, tag: str, checked: bool) -> None:
        profile = self._main.get_profile()
        tags = set(profile.get("tags", []))
        if checked:
            tags.add(tag)
        else:
            tags.discard(tag)
        profile["tags"] = sorted(tags)
        self._main.set_profile(profile)

    def _pick_icon(self) -> None:
        """Show a simple icon picker popup."""
        from PyQt6.QtWidgets import QDialog, QGridLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Pick Profile Icon")
        dlg.setFixedSize(280, 200)
        grid = QGridLayout(dlg)
        for i, emoji in enumerate(PROFILE_ICONS):
            btn = QPushButton(emoji)
            btn.setFixedSize(40, 40)
            btn.setStyleSheet("font-size: 20px;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, e=emoji: self._set_icon(e, dlg))
            grid.addWidget(btn, i // 4, i % 4)
        dlg.exec()

    def _set_icon(self, emoji: str, dlg) -> None:
        self._icon_btn.setText(emoji)
        profile = self._main.get_profile()
        profile["icon"] = emoji
        self._main.set_profile(profile)
        dlg.accept()

    def _refresh_preview(self) -> None:
        """Update the mapping preview grid to show bound/unbound status."""
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        accent = self._main.theme.theme["colors"]["accent"]
        surface = self._main.theme.theme["colors"]["surface"]
        border = self._main.theme.theme["colors"]["border_light"]

        for bname, lbl in self._preview_labels.items():
            entry = mappings.get(bname, {})
            is_mapped = isinstance(entry, dict) and (
                entry.get("keycode") is not None or entry.get("type")
            )
            if is_mapped:
                from ...hid_keycodes import _KEYCODE_NAMES
                kc = entry.get("keycode")
                t = entry.get("type")
                if t:
                    short = t[:3].upper()
                elif kc is not None:
                    short = _KEYCODE_NAMES.get(kc, "?")
                else:
                    short = "?"
                lbl.setText(f"{bname}\n{short}")
                lbl.setStyleSheet(
                    f"background: {accent}; color: #fff; "
                    f"border: 1px solid {accent}; "
                    f"border-radius: 4px; font-size: 9px;"
                )
            else:
                lbl.setText(bname)
                lbl.setStyleSheet(
                    f"background: {surface}; "
                    f"border: 1px solid {border}; "
                    f"border-radius: 4px; font-size: 10px;"
                )

        # Update layer indicator
        layers = profile.get("layers", [])
        if layers:
            self._layer_indicator.setText(f"Base + {len(layers)} layer(s)")
        else:
            self._layer_indicator.setText("Base")

        # Update tags
        profile_tags = set(profile.get("tags", []))
        for tag, cb in self._tag_checks.items():
            cb.blockSignals(True)
            cb.setChecked(tag in profile_tags)
            cb.blockSignals(False)

        # Update icon
        icon = profile.get("icon", "🎮")
        self._icon_btn.setText(icon)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def device_event(self, obj: dict) -> None:
        pass

    def profile_loaded(self, slot: int, profile: dict) -> None:
        name = profile.get("name", f"(slot {slot})")
        if 0 <= slot < len(self._slot_cards):
            icon = profile.get("icon", "🎮")
            self._slot_cards[slot].setText(f"{icon} Slot {slot}: {name}")
        self._refresh_editor()
        self._refresh_preview()

    def profile_updated(self, profile: dict) -> None:
        self._refresh_editor()
        self._refresh_preview()

    def apply_theme(self, theme: ThemeEngine) -> None:
        pass
