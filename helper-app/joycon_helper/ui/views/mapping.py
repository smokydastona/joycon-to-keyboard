"""Mapping view — controller canvas + key binding editor.

This is the heart of the app: the interactive Joy-Con / keyboard hotspot
canvas where users bind controller buttons to keyboard keys.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Set, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog,
    QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ..constants import (
    INCEDIUS_HOTSPOTS, JOYCON_BUTTON_SHAPES, KBD_HOTSPOTS,
    KBD_LABEL_TO_KEYCODE, KEYMAP_HOTSPOTS, M913_HOTSPOTS,
    MOUSE_HOTSPOTS, RAINBOW_COLORS, RAINBOW_NAMES,
    _KEYCODE_TO_KBD_LABEL,
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
        self._m913_skin = "Stock"
        self._overlay_color = "violet"
        self._search_text = ""
        self._clipboard_binding: Optional[Dict[str, Any]] = None
        self._locked_hotspots: Set[str] = set()

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
    # Theme key helper
    # -----------------------------------------------------------------

    @property
    def _theme_key(self) -> str:
        """Return the current theme key ('dark' or 'default')."""
        return "dark" if self._main.theme.is_dark else "default"

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
        self._device_tabs.currentChanged.connect(self._on_device_tab_changed)

        # Joy-Con canvas
        self._jc_canvas = HotspotCanvas(self._main.theme)
        self._jc_canvas.hotspot_clicked.connect(self._on_hotspot_clicked)
        self._jc_canvas.hotspot_right_clicked.connect(self._on_hotspot_right_click)
        self._jc_canvas.hotspot_hovered.connect(self._on_hotspot_hovered)
        self._device_tabs.addTab(self._jc_canvas, "Joy-Con")

        # M913 tab (with optional Incedius skin)
        m913_container = QWidget()
        m913_lay = QVBoxLayout(m913_container)
        m913_lay.setContentsMargins(0, 0, 0, 0)
        m913_lay.setSpacing(4)

        skin_row = QHBoxLayout()
        skin_row.addWidget(QLabel("Skin:"))
        self._m913_skin_combo = QComboBox()
        self._m913_skin_combo.addItems(["Stock", "Incedius"])
        self._m913_skin_combo.setToolTip("Select the M913 keypad skin overlay")
        self._m913_skin_combo.currentTextChanged.connect(self._on_m913_skin_changed)
        skin_row.addWidget(self._m913_skin_combo)
        skin_row.addStretch()
        m913_lay.addLayout(skin_row)

        self._m913_canvas = HotspotCanvas(self._main.theme)
        self._m913_canvas.hotspot_clicked.connect(self._on_hotspot_clicked)
        self._m913_canvas.hotspot_right_clicked.connect(self._on_hotspot_right_click)
        self._m913_canvas.hotspot_hovered.connect(self._on_hotspot_hovered)
        m913_lay.addWidget(self._m913_canvas, 1)

        self._device_tabs.addTab(m913_container, "M913")

        # Mouse / Razer canvas
        self._mouse_canvas = HotspotCanvas(self._main.theme)
        self._mouse_canvas.hotspot_clicked.connect(self._on_hotspot_clicked)
        self._mouse_canvas.hotspot_right_clicked.connect(self._on_hotspot_right_click)
        self._mouse_canvas.hotspot_hovered.connect(self._on_hotspot_hovered)
        self._device_tabs.addTab(self._mouse_canvas, "Mouse")

        # Keyboard canvas (popup only — not a tab)
        self._kbd_canvas = HotspotCanvas(self._main.theme)
        self._kbd_canvas.hotspot_clicked.connect(self._on_kbd_hotspot_clicked)

        lay.addWidget(self._device_tabs, 1)

        # Overlay color picker
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Overlay color:"))
        self._color_combo = QComboBox()
        self._color_combo.addItems(RAINBOW_NAMES)
        self._color_combo.setCurrentText(self._overlay_color)
        self._color_combo.setToolTip("Color used to highlight hotspot dots on the canvas")
        self._color_combo.currentTextChanged.connect(self._on_color_changed)
        color_row.addWidget(self._color_combo)
        color_row.addStretch()

        # Learn mode button
        self._learn_btn = QPushButton("🎯 Learn Mode")
        self._learn_btn.setCheckable(True)
        self._learn_btn.setProperty("accent", True)
        self._learn_btn.setToolTip("Click a hotspot then press a key on your controller to bind it")
        self._learn_btn.toggled.connect(self._on_learn_toggled)
        color_row.addWidget(self._learn_btn)

        # Position-edit mode (temporary drag-to-adjust)
        self._edit_pos_btn = QPushButton("📐 Edit Positions")
        self._edit_pos_btn.setCheckable(True)
        self._edit_pos_btn.setToolTip(
            "Enable drag mode to move hotspot dots — positions are saved to JSON"
        )
        self._edit_pos_btn.toggled.connect(self._on_edit_positions_toggled)
        color_row.addWidget(self._edit_pos_btn)

        self._export_pos_btn = QPushButton("💾 Export Positions")
        self._export_pos_btn.setToolTip("Save current hotspot positions to a JSON file")
        self._export_pos_btn.clicked.connect(self._export_positions)
        color_row.addWidget(self._export_pos_btn)

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

        # Visual keyboard picker
        kbd_picker_btn = QPushButton("⌨ Keyboard Picker")
        kbd_picker_btn.setToolTip("Open a full keyboard layout to visually pick a key")
        kbd_picker_btn.clicked.connect(self._open_kbd_picker)
        bind_lay.addWidget(kbd_picker_btn)

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
        tk = self._theme_key
        self._jc_canvas.set_hotspots(KEYMAP_HOTSPOTS[tk])
        self._jc_canvas.set_hotspot_shapes(JOYCON_BUTTON_SHAPES)
        self._m913_canvas.set_hotspots(M913_HOTSPOTS[tk])
        self._mouse_canvas.set_hotspots(MOUSE_HOTSPOTS[tk])
        self._kbd_canvas.set_hotspots(KBD_HOTSPOTS[tk])

        # Joy-Con background
        pm = self._main.assets.load_pixmap("joycons_none.png")
        if pm:
            self._jc_canvas.set_background(pm)

        # M913 background (respects current skin)
        m913_pm = self._main.assets.load_pixmap("m913_none.png")
        if m913_pm:
            self._m913_canvas.set_background(m913_pm)

        # Mouse / Razer background
        mouse_pm = self._main.assets.load_pixmap("razer_none.png")
        if mouse_pm:
            self._mouse_canvas.set_background(mouse_pm)

        # Keyboard (popup canvas)
        kbd_pm = self._main.assets.load_pixmap("keyboard.png")
        if kbd_pm:
            self._kbd_canvas.set_background(kbd_pm)

        # Load pale composite overlays for each device canvas
        self._load_pale_overlays()

    # -----------------------------------------------------------------
    # Overlay helpers (pale composite + bright individual)
    # -----------------------------------------------------------------

    # Maps canvas object-id → (device_name_for_overlays, overlay_prefix)
    _CANVAS_DEVICE_INFO = {
        "_jc_canvas":    ("joycon",   "jc"),
        "_m913_canvas":  ("m913",     "m913"),
        "_mouse_canvas": ("mouse",    "mouse"),
        "_kbd_canvas":   ("keyboard", "kbd"),
    }

    def _load_pale_overlays(self) -> None:
        """Load pale composite overlays for all device canvases."""
        color = getattr(self, "_overlay_color", "violet")
        for attr, (device, _prefix) in self._CANVAS_DEVICE_INFO.items():
            canvas: HotspotCanvas = getattr(self, attr, None)
            if canvas is None:
                continue
            # Use incedius device name when that skin is active
            actual_device = device
            if attr == "_m913_canvas" and getattr(self, "_m913_skin", "Stock") == "Incedius":
                actual_device = "incedius"
            path = self._main.assets.find_pale_overlay(actual_device, color)
            if path:
                pm = self._main.assets.load_pixmap(path.name, extra_roots=[path.parent])
                canvas.set_pale_overlay(pm)
            else:
                canvas.set_pale_overlay(None)

    def _load_bright_overlay(self, canvas: HotspotCanvas, button_name: str) -> None:
        """Load the full-brightness individual overlay for *button_name*."""
        color = getattr(self, "_overlay_color", "violet")
        # Determine device & prefix from the canvas
        device = "joycon"
        prefix = "jc"
        for attr, (d, p) in self._CANVAS_DEVICE_INFO.items():
            if getattr(self, attr, None) is canvas:
                device = d
                prefix = p
                if attr == "_m913_canvas" and getattr(self, "_m913_skin", "Stock") == "Incedius":
                    device = "incedius"
                    prefix = "inc"
                break
        safe_name = button_name.replace("/", "_").replace("\\", "_").replace(".", "_dot_")
        overlay_name = f"{prefix}_{safe_name}"
        path = self._main.assets.find_overlay_image(device, overlay_name, color)
        if path:
            pm = self._main.assets.load_pixmap(path.name, extra_roots=[path.parent])
            canvas.set_bright_overlay(pm)
        else:
            canvas.set_bright_overlay(None)

    # -----------------------------------------------------------------
    # Active device helpers
    # -----------------------------------------------------------------

    _DEVICE_CANVASES_AND_HOTSPOTS = None  # built lazily

    def _device_list(self):
        """Return list of (canvas, hotspot_list) in tab order."""
        tk = self._theme_key
        m913_hs = INCEDIUS_HOTSPOTS[tk] if self._m913_skin == "Incedius" else M913_HOTSPOTS[tk]
        return [
            (self._jc_canvas, KEYMAP_HOTSPOTS[tk]),
            (self._m913_canvas, m913_hs),
            (self._mouse_canvas, MOUSE_HOTSPOTS[tk]),
        ]

    def _active_canvas(self) -> HotspotCanvas:
        idx = self._device_tabs.currentIndex()
        return self._device_list()[idx][0]

    def _active_hotspots(self):
        idx = self._device_tabs.currentIndex()
        return self._device_list()[idx][1]

    def _on_device_tab_changed(self, index: int) -> None:
        # Clear bright overlay + selection on all canvases
        for canvas, _ in self._device_list():
            canvas.set_bright_overlay(None)
            canvas.set_selected(None)
        self._selected_hotspot = None
        # Guard: signal fires during _build_canvas_panel before _build_binding_panel
        if hasattr(self, "_sel_label"):
            self._sel_label.setText("No button selected")
            self._sel_mapping.setText("Click a button on the canvas to select it")

    def _on_m913_skin_changed(self, skin: str) -> None:
        self._m913_skin = skin
        tk = self._theme_key
        if skin == "Incedius":
            self._m913_canvas.set_hotspots(INCEDIUS_HOTSPOTS[tk])
            pm = self._main.assets.load_pixmap("incedius_none.png")
        else:
            self._m913_canvas.set_hotspots(M913_HOTSPOTS[tk])
            pm = self._main.assets.load_pixmap("m913_none.png")
        if pm:
            self._m913_canvas.set_background(pm)
        self._refresh_mapping_visuals()

    def _refresh_mapping_visuals(self) -> None:
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})

        for canvas, hotspots in self._device_list():
            labels: Dict[str, str] = {}
            for hs_name, _, _ in hotspots:
                key_id = mappings.get(hs_name, {}).get("keycode")
                is_mapped = key_id is not None
                canvas.update_hotspot_state(hs_name, mapped=is_mapped)
                if key_id is not None:
                    label = _KEYCODE_TO_KBD_LABEL.get(key_id, f"0x{key_id:02X}")
                    labels[hs_name] = label
            canvas.set_mapping_labels(labels)
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
        canvas = self._active_canvas()
        canvas.set_selected(name)
        self._load_bright_overlay(canvas, name)
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

        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        entry = mappings.get(name, {})
        keycode = entry.get("keycode") if isinstance(entry, dict) else None
        is_mapped = keycode is not None
        is_locked = name in self._locked_hotspots

        menu = QMenu(self)

        # Learn — case the controller button for this hotspot
        learn_act = menu.addAction(f"Case key_id for {name}")
        learn_act.triggered.connect(lambda: self._ctx_learn(name))

        if is_mapped:
            menu.addSeparator()

            # Unbind
            unbind_act = menu.addAction(f"Unbind {name}")
            unbind_act.triggered.connect(lambda: self._ctx_unbind(name))

            # Disable
            disable_act = menu.addAction(f"Disable {name}")
            disable_act.triggered.connect(lambda: self._ctx_disable(name))

            # Reset to passthrough
            reset_act = menu.addAction(f"Reset {name} to passthrough")
            reset_act.triggered.connect(lambda: self._ctx_unbind(name))

        menu.addSeparator()

        # Copy / Paste
        copy_act = menu.addAction("Copy Binding")
        copy_act.setEnabled(is_mapped)
        copy_act.triggered.connect(lambda: self._ctx_copy(name))

        paste_act = menu.addAction("Paste Binding")
        paste_act.setEnabled(self._clipboard_binding is not None)
        paste_act.triggered.connect(lambda: self._ctx_paste(name))

        # Swap
        swap_act = menu.addAction("Swap With…")
        swap_act.setEnabled(is_mapped)
        swap_act.triggered.connect(lambda: self._ctx_swap(name))

        menu.addSeparator()

        # Lock / Unlock
        if is_locked:
            lock_act = menu.addAction(f"Unlock {name}")
            lock_act.triggered.connect(lambda: self._locked_hotspots.discard(name))
        else:
            lock_act = menu.addAction(f"Lock {name} (prevent changes)")
            lock_act.triggered.connect(lambda: self._locked_hotspots.add(name))

        # Turbo toggle
        is_turbo = isinstance(entry, dict) and entry.get("turbo", False)
        turbo_label = "Disable Turbo" if is_turbo else "Enable Turbo"
        turbo_act = menu.addAction(turbo_label)
        turbo_act.setEnabled(is_mapped)
        turbo_act.triggered.connect(lambda: self._ctx_toggle_turbo(name))

        menu.addSeparator()

        # Info
        info_act = menu.addAction(f"Info — {name}")
        info_act.triggered.connect(lambda: self._ctx_info(name))

        # Show the menu at cursor position
        from PyQt6.QtGui import QCursor
        menu.exec(QCursor.pos())

    # -----------------------------------------------------------------
    # Context-menu actions
    # -----------------------------------------------------------------

    def _ctx_learn(self, name: str) -> None:
        self._selected_hotspot = name
        self._learn_btn.setChecked(True)
        self._sel_mapping.setText(f"Press a controller button to case {name}…")

    def _ctx_unbind(self, name: str) -> None:
        if name in self._locked_hotspots:
            QMessageBox.warning(self, "Locked", f"{name} is locked. Unlock it first.")
            return
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        mappings.pop(name, None)
        self._main.set_profile(profile)
        self._refresh_mapping_visuals()
        self._sel_mapping.setText("Unbound")

    def _ctx_disable(self, name: str) -> None:
        if name in self._locked_hotspots:
            QMessageBox.warning(self, "Locked", f"{name} is locked. Unlock it first.")
            return
        profile = self._main.get_profile()
        profile = _ensure_mappings(profile)
        profile["mappings"][name] = {"type": "disable"}
        self._main.set_profile(profile)
        self._refresh_mapping_visuals()
        self._sel_mapping.setText(f"{name} disabled")

    def _ctx_copy(self, name: str) -> None:
        profile = self._main.get_profile()
        entry = profile.get("mappings", {}).get(name)
        if isinstance(entry, dict):
            import copy
            self._clipboard_binding = copy.deepcopy(entry)

    def _ctx_paste(self, name: str) -> None:
        if name in self._locked_hotspots:
            QMessageBox.warning(self, "Locked", f"{name} is locked. Unlock it first.")
            return
        if self._clipboard_binding is None:
            return
        import copy
        profile = self._main.get_profile()
        profile = _ensure_mappings(profile)
        profile["mappings"][name] = copy.deepcopy(self._clipboard_binding)
        self._main.set_profile(profile)
        self._refresh_mapping_visuals()

    def _ctx_swap(self, name: str) -> None:
        choices = [n for n, _, _ in self._active_hotspots() if n != name]
        from PyQt6.QtWidgets import QInputDialog
        other, ok = QInputDialog.getItem(
            self, "Swap With", f"Swap {name} with:", choices, 0, False,
        )
        if not ok or not other:
            return
        if name in self._locked_hotspots or other in self._locked_hotspots:
            QMessageBox.warning(self, "Locked", "One of the hotspots is locked.")
            return
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        a = mappings.get(name)
        b = mappings.get(other)
        if a is not None:
            mappings[other] = a
        else:
            mappings.pop(other, None)
        if b is not None:
            mappings[name] = b
        else:
            mappings.pop(name, None)
        self._main.set_profile(profile)
        self._refresh_mapping_visuals()

    def _ctx_toggle_turbo(self, name: str) -> None:
        if name in self._locked_hotspots:
            QMessageBox.warning(self, "Locked", f"{name} is locked. Unlock it first.")
            return
        profile = self._main.get_profile()
        entry = profile.get("mappings", {}).get(name)
        if not isinstance(entry, dict):
            return
        entry["turbo"] = not entry.get("turbo", False)
        self._main.set_profile(profile)
        self._refresh_mapping_visuals()

    def _ctx_info(self, name: str) -> None:
        profile = self._main.get_profile()
        entry = profile.get("mappings", {}).get(name, {})
        if not isinstance(entry, dict) or not entry:
            QMessageBox.information(self, name, f"{name}: not mapped")
            return
        keycode = entry.get("keycode")
        modifier = entry.get("modifier", 0)
        turbo = entry.get("turbo", False)
        disabled = entry.get("type") == "disable"
        label = _KEYCODE_TO_KBD_LABEL.get(keycode, f"0x{keycode:02X}") if keycode else "—"
        lines = [
            f"Hotspot: {name}",
            f"Keycode: {label} (0x{keycode:02X})" if keycode else "Disabled" if disabled else "No keycode",
            f"Modifier: 0x{modifier:02X}" if modifier else "",
            f"Turbo: {'ON' if turbo else 'OFF'}",
            f"Locked: {'YES' if name in self._locked_hotspots else 'no'}",
        ]
        QMessageBox.information(self, f"Info — {name}", "\n".join(line for line in lines if line))

    def _on_hotspot_hovered(self, name: str) -> None:
        if name:
            self.setToolTip(name)
        else:
            self.setToolTip("")

    def _on_kbd_hotspot_clicked(self, name: str) -> None:
        # Clicking keyboard hotspot binds it to the selected device button
        if self._selected_hotspot:
            self._bind_key(name)
        # Close the picker dialog if open
        dlg = getattr(self, "_kbd_picker_dlg", None)
        if dlg is not None:
            dlg.accept()

    def _open_kbd_picker(self) -> None:
        """Open a popup dialog with the full keyboard canvas for key selection."""
        if not self._selected_hotspot:
            QMessageBox.information(
                self, "No Selection",
                "Select a controller / device button first, then open the keyboard picker.",
            )
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Keyboard Picker — binding {self._selected_hotspot}")
        dlg.setMinimumSize(900, 500)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        info = QLabel(f"Click a key to bind it to {self._selected_hotspot}")
        info.setStyleSheet(f"color: {self._main.theme.color('text_secondary')};")
        lay.addWidget(info)
        lay.addWidget(self._kbd_canvas, 1)
        self._kbd_picker_dlg = dlg
        dlg.exec()
        # Re-parent the canvas back (QDialog takes ownership during exec)
        self._kbd_picker_dlg = None

    def _on_color_changed(self, color_name: str) -> None:
        self._overlay_color = color_name
        hex_color = RAINBOW_COLORS.get(color_name, "#a03cc8")
        for canvas, _ in self._device_list():
            canvas.set_overlay_color(hex_color)
        # Reload pale + bright overlays for new colour
        self._load_pale_overlays()
        if self._selected_hotspot:
            canvas = self._active_canvas()
            self._load_bright_overlay(canvas, self._selected_hotspot)

    def _on_learn_toggled(self, checked: bool) -> None:
        self._learn_mode = checked
        if checked:
            self._learn_btn.setText("🔴 Learning... (press a controller button)")
        else:
            self._learn_btn.setText("🎯 Learn Mode")

    def _on_edit_positions_toggled(self, checked: bool) -> None:
        for canvas, _ in self._device_list():
            canvas.set_edit_mode(checked)
        self._kbd_canvas.set_edit_mode(checked)
        self._edit_pos_btn.setText(
            "📐 Editing..." if checked else "📐 Edit Positions"
        )

    def _export_positions(self) -> None:
        device_map = {
            "joycon":   self._jc_canvas,
            "m913":     self._m913_canvas,
            "mouse":    self._mouse_canvas,
            "keyboard": self._kbd_canvas,
        }
        data: Dict[str, list] = {}
        for device, canvas in device_map.items():
            data[device] = [
                [name, nx, ny]
                for name, nx, ny in canvas.export_positions()
            ]

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Hotspot Positions", "hotspot_positions.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        QMessageBox.information(self, "Exported", f"Positions saved to:\n{path}")

    def _on_search(self, text: str) -> None:
        self._search_text = text.strip().lower()
        canvas = self._active_canvas()
        canvas.clear_search()
        if self._search_text:
            for name, _, _ in self._active_hotspots():
                match = self._search_text in name.lower()
                canvas.update_hotspot_state(name, search_match=match)

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

        if self._selected_hotspot in self._locked_hotspots:
            QMessageBox.warning(self, "Locked", f"{self._selected_hotspot} is locked.")
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
        # Reload hotspot positions and backgrounds for the new theme
        self._load_hotspots()
        self._reload_backgrounds()
        for canvas, _ in self._device_list():
            canvas.apply_theme(theme)
        self._kbd_canvas.apply_theme(theme)
        self._refresh_mapping_visuals()

    def _reload_backgrounds(self) -> None:
        """Reload all device backgrounds from current asset search roots."""
        pm = self._main.assets.load_pixmap("joycons_none.png")
        if pm:
            self._jc_canvas.set_background(pm)

        # Respect current M913 skin
        m913_file = "incedius_none.png" if self._m913_skin == "Incedius" else "m913_none.png"
        m913_pm = self._main.assets.load_pixmap(m913_file)
        if m913_pm:
            self._m913_canvas.set_background(m913_pm)

        mouse_pm = self._main.assets.load_pixmap("razer_none.png")
        if mouse_pm:
            self._mouse_canvas.set_background(mouse_pm)

        kbd_pm = self._main.assets.load_pixmap("keyboard.png")
        if kbd_pm:
            self._kbd_canvas.set_background(kbd_pm)
