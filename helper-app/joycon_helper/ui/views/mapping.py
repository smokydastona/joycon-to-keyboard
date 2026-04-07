"""Mapping view — controller canvas + key binding editor.

This is the heart of the app: the interactive Joy-Con / keyboard hotspot
canvas where users bind controller buttons to keyboard keys.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ..constants import (
    KBD_HOTSPOTS, KBD_LABEL_TO_KEYCODE, KEYMAP_HOTSPOTS,
    RAINBOW_COLORS, RAINBOW_NAMES, _KEYCODE_TO_KBD_LABEL,
)
from ..theme import ThemeEngine
from ..widgets.card import Card
from ..widgets.hotspot_canvas import HotspotCanvas

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.mapping")


def _ensure_mappings(profile: dict) -> dict:
    if "mappings" not in profile:
        profile["mappings"] = {}
    return profile


class MappingView(QWidget):
    """Interactive controller mapping editor."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main
        self._selected_hotspot: Optional[str] = None
        self._learn_mode = False
        self._overlay_color = "violet"
        self._search_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Splitter: canvas (left) + binding panel (right)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._splitter)

        self._build_canvas_panel()
        self._build_binding_panel()

        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 1)

        # Initialize hotspots
        self._load_hotspots()

    # -----------------------------------------------------------------
    # Canvas panel (left)
    # -----------------------------------------------------------------

    def _build_canvas_panel(self) -> None:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 8, 16)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("Controller Mapping")
        title.setFont(QFont(
            self._main.theme.typo("font_family_decorative"),
            self._main.theme.typo("font_size_title"),
            QFont.Weight.Bold,
        ))
        header_row.addWidget(title)
        header_row.addStretch()

        # Search
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search keys...")
        self._search_input.setFixedWidth(200)
        self._search_input.textChanged.connect(self._on_search)
        header_row.addWidget(self._search_input)

        lay.addLayout(header_row)

        # Device selector tabs
        self._device_tabs = QTabWidget()
        self._device_tabs.setTabPosition(QTabWidget.TabPosition.North)

        # Joy-Con canvas
        self._jc_canvas = HotspotCanvas(self._main.theme)
        self._jc_canvas.hotspot_clicked.connect(self._on_hotspot_clicked)
        self._jc_canvas.hotspot_right_clicked.connect(self._on_hotspot_right_click)
        self._jc_canvas.hotspot_hovered.connect(self._on_hotspot_hovered)
        self._device_tabs.addTab(self._jc_canvas, "Joy-Con")

        # Keyboard canvas
        self._kbd_canvas = HotspotCanvas(self._main.theme)
        self._kbd_canvas.hotspot_clicked.connect(self._on_kbd_hotspot_clicked)
        self._device_tabs.addTab(self._kbd_canvas, "Keyboard Preview")

        lay.addWidget(self._device_tabs, 1)

        # Overlay color picker
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Overlay color:"))
        self._color_combo = QComboBox()
        self._color_combo.addItems(RAINBOW_NAMES)
        self._color_combo.setCurrentText(self._overlay_color)
        self._color_combo.currentTextChanged.connect(self._on_color_changed)
        color_row.addWidget(self._color_combo)
        color_row.addStretch()

        # Learn mode button
        self._learn_btn = QPushButton("🎯 Learn Mode")
        self._learn_btn.setCheckable(True)
        self._learn_btn.setProperty("accent", True)
        self._learn_btn.toggled.connect(self._on_learn_toggled)
        color_row.addWidget(self._learn_btn)

        lay.addLayout(color_row)
        self._splitter.addWidget(panel)

    # -----------------------------------------------------------------
    # Binding panel (right)
    # -----------------------------------------------------------------

    def _build_binding_panel(self) -> None:
        panel = QScrollArea()
        panel.setWidgetResizable(True)
        panel.setFrameShape(QScrollArea.Shape.NoFrame)
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(400)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(8, 16, 16, 16)
        lay.setSpacing(12)

        # Selected hotspot info
        info_card = Card(self._main.theme)
        info_lay = QVBoxLayout(info_card)

        self._sel_label = QLabel("No button selected")
        self._sel_label.setFont(QFont(
            self._main.theme.typo("font_family"), 14, QFont.Weight.Bold
        ))
        info_lay.addWidget(self._sel_label)

        self._sel_mapping = QLabel("Click a button on the canvas to select it")
        self._sel_mapping.setWordWrap(True)
        self._sel_mapping.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        info_lay.addWidget(self._sel_mapping)

        lay.addWidget(info_card)

        # Binding controls
        bind_group = QGroupBox("Bind Key")
        bind_lay = QVBoxLayout(bind_group)

        # Quick-bind buttons grid
        quick_label = QLabel("Quick bind:")
        quick_label.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        bind_lay.addWidget(quick_label)

        quick_grid = QGridLayout()
        quick_keys = [
            "W", "A", "S", "D", "Space", "LShift",
            "E", "Q", "R", "F", "Tab", "Esc",
            "1", "2", "3", "4", "5", "LCtrl",
        ]
        for i, key in enumerate(quick_keys):
            btn = QPushButton(key)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._bind_key(k))
            quick_grid.addWidget(btn, i // 6, i % 6)
        bind_lay.addLayout(quick_grid)

        # Custom keycode entry
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Keycode:"))
        self._keycode_input = QLineEdit()
        self._keycode_input.setPlaceholderText("e.g. 0x04 (A)")
        custom_row.addWidget(self._keycode_input)
        bind_btn = QPushButton("Bind")
        bind_btn.setProperty("accent", True)
        bind_btn.clicked.connect(self._bind_custom_keycode)
        custom_row.addWidget(bind_btn)
        bind_lay.addLayout(custom_row)

        # Modifier checkboxes row
        mod_row = QHBoxLayout()
        mod_row.addWidget(QLabel("Modifier:"))
        self._mod_input = QLineEdit()
        self._mod_input.setPlaceholderText("modifier bits (hex)")
        self._mod_input.setFixedWidth(120)
        mod_row.addWidget(self._mod_input)
        mod_row.addStretch()
        bind_lay.addLayout(mod_row)

        # Unbind
        unbind_btn = QPushButton("Unbind Selected")
        unbind_btn.setProperty("danger", True)
        unbind_btn.clicked.connect(self._unbind_selected)
        bind_lay.addWidget(unbind_btn)

        lay.addWidget(bind_group)

        # Mappings list
        list_group = QGroupBox("All Mappings")
        list_lay = QVBoxLayout(list_group)
        self._mapping_list = QListWidget()
        self._mapping_list.setMinimumHeight(150)
        self._mapping_list.itemClicked.connect(self._on_mapping_list_clicked)
        list_lay.addWidget(self._mapping_list)

        clear_btn = QPushButton("Clear All Mappings")
        clear_btn.setProperty("danger", True)
        clear_btn.clicked.connect(self._clear_all_mappings)
        list_lay.addWidget(clear_btn)

        lay.addWidget(list_group)
        lay.addStretch()

        panel.setWidget(container)
        self._splitter.addWidget(panel)

    # -----------------------------------------------------------------
    # Hotspot loading
    # -----------------------------------------------------------------

    def _load_hotspots(self) -> None:
        self._jc_canvas.set_hotspots(KEYMAP_HOTSPOTS)
        self._kbd_canvas.set_hotspots(KBD_HOTSPOTS)

        # Load device background
        pm = self._main.assets.load_pixmap("joycons_none.png")
        if pm:
            self._jc_canvas.set_background(pm)

        kbd_pm = self._main.assets.load_pixmap("keyboard.png")
        if kbd_pm:
            self._kbd_canvas.set_background(kbd_pm)

    def _refresh_mapping_visuals(self) -> None:
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})

        labels: Dict[str, str] = {}
        for hs_name, _, _ in KEYMAP_HOTSPOTS:
            key_id = mappings.get(hs_name, {}).get("keycode")
            is_mapped = key_id is not None
            self._jc_canvas.update_hotspot_state(hs_name, mapped=is_mapped)
            if key_id is not None:
                label = _KEYCODE_TO_KBD_LABEL.get(key_id, f"0x{key_id:02X}")
                labels[hs_name] = label

        self._jc_canvas.set_mapping_labels(labels)
        self._refresh_mapping_list()

    def _refresh_mapping_list(self) -> None:
        self._mapping_list.clear()
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})

        for hs_name in sorted(mappings.keys()):
            entry = mappings[hs_name]
            if not isinstance(entry, dict):
                continue
            keycode = entry.get("keycode")
            if keycode is None:
                continue
            label = _KEYCODE_TO_KBD_LABEL.get(keycode, f"0x{keycode:02X}")
            mod = entry.get("modifier", 0)
            mod_str = f" +mod(0x{mod:02X})" if mod else ""
            item = QListWidgetItem(f"{hs_name} → {label}{mod_str}")
            item.setData(Qt.ItemDataRole.UserRole, hs_name)
            self._mapping_list.addItem(item)

    # -----------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------

    def _on_hotspot_clicked(self, name: str) -> None:
        self._selected_hotspot = name
        self._jc_canvas.set_selected(name)
        self._sel_label.setText(f"Selected: {name}")

        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        entry = mappings.get(name, {})
        keycode = entry.get("keycode")
        if keycode is not None:
            label = _KEYCODE_TO_KBD_LABEL.get(keycode, f"0x{keycode:02X}")
            mod = entry.get("modifier", 0)
            mod_str = f"\nModifier: 0x{mod:02X}" if mod else ""
            self._sel_mapping.setText(f"Mapped to: {label} (0x{keycode:02X}){mod_str}")
        else:
            self._sel_mapping.setText("Not mapped — bind a key below")

    def _on_hotspot_right_click(self, name: str, pos: object) -> None:
        self._on_hotspot_clicked(name)

    def _on_hotspot_hovered(self, name: str) -> None:
        if name:
            self.setToolTip(name)
        else:
            self.setToolTip("")

    def _on_kbd_hotspot_clicked(self, name: str) -> None:
        # Clicking keyboard hotspot binds it to the selected Joy-Con button
        if self._selected_hotspot:
            self._bind_key(name)

    def _on_color_changed(self, color_name: str) -> None:
        self._overlay_color = color_name
        hex_color = RAINBOW_COLORS.get(color_name, "#a03cc8")
        self._jc_canvas.set_overlay_color(hex_color)

    def _on_learn_toggled(self, checked: bool) -> None:
        self._learn_mode = checked
        if checked:
            self._learn_btn.setText("🔴 Learning... (press a controller button)")
        else:
            self._learn_btn.setText("🎯 Learn Mode")

    def _on_search(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self._jc_canvas.clear_search()
        if self._search_text:
            for name, _, _ in KEYMAP_HOTSPOTS:
                match = self._search_text in name.lower()
                self._jc_canvas.update_hotspot_state(name, search_match=match)

    def _on_mapping_list_clicked(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if name:
            self._on_hotspot_clicked(name)

    # -----------------------------------------------------------------
    # Binding
    # -----------------------------------------------------------------

    def _bind_key(self, key_label: str) -> None:
        if not self._selected_hotspot:
            QMessageBox.information(self, "No Selection", "Select a controller button first.")
            return

        keycode = KBD_LABEL_TO_KEYCODE.get(key_label)
        if keycode is None:
            QMessageBox.warning(self, "Unknown Key", f"No HID keycode for '{key_label}'.")
            return

        profile = self._main.get_profile()
        profile = _ensure_mappings(profile)

        modifier = 0
        if keycode < 0:
            modifier = -keycode
            keycode = 0

        # Parse modifier from input
        mod_text = self._mod_input.text().strip()
        if mod_text:
            try:
                modifier = int(mod_text, 16) if mod_text.startswith("0x") else int(mod_text)
            except ValueError:
                pass

        profile["mappings"][self._selected_hotspot] = {
            "keycode": keycode,
            "modifier": modifier,
        }

        self._main.set_profile(profile)
        self._refresh_mapping_visuals()
        self._sel_mapping.setText(f"Bound to: {key_label}")

    def _bind_custom_keycode(self) -> None:
        if not self._selected_hotspot:
            QMessageBox.information(self, "No Selection", "Select a controller button first.")
            return

        text = self._keycode_input.text().strip()
        if not text:
            return

        try:
            keycode = int(text, 16) if text.startswith("0x") else int(text)
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Enter a valid keycode (decimal or 0x hex).")
            return

        profile = self._main.get_profile()
        profile = _ensure_mappings(profile)

        modifier = 0
        mod_text = self._mod_input.text().strip()
        if mod_text:
            try:
                modifier = int(mod_text, 16) if mod_text.startswith("0x") else int(mod_text)
            except ValueError:
                pass

        profile["mappings"][self._selected_hotspot] = {
            "keycode": keycode,
            "modifier": modifier,
        }

        self._main.set_profile(profile)
        self._refresh_mapping_visuals()

    def _unbind_selected(self) -> None:
        if not self._selected_hotspot:
            return
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        mappings.pop(self._selected_hotspot, None)
        self._main.set_profile(profile)
        self._refresh_mapping_visuals()
        self._sel_mapping.setText("Unbound")

    def _clear_all_mappings(self) -> None:
        reply = QMessageBox.question(
            self, "Clear All",
            "Remove all key mappings from the current profile?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            profile = self._main.get_profile()
            profile["mappings"] = {}
            self._main.set_profile(profile)
            self._refresh_mapping_visuals()

    # -----------------------------------------------------------------
    # Device events
    # -----------------------------------------------------------------

    def device_event(self, obj: dict) -> None:
        evt = obj.get("evt")
        if evt == "mapped_key" and self._learn_mode and self._selected_hotspot:
            pressed = obj.get("pressed")
            key_id = obj.get("key_id")
            if pressed and isinstance(key_id, int):
                label = _KEYCODE_TO_KBD_LABEL.get(key_id, f"0x{key_id:02X}")
                self._bind_key(label)
                self._learn_btn.setChecked(False)

    def profile_loaded(self, slot: int, profile: dict) -> None:
        self._refresh_mapping_visuals()

    def profile_updated(self, profile: dict) -> None:
        self._refresh_mapping_visuals()

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._jc_canvas.apply_theme(theme)
        self._kbd_canvas.apply_theme(theme)
