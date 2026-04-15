"""Mapping view — controller canvas + key binding editor.

This is the heart of the app: the interactive Joy-Con / keyboard hotspot
canvas where users bind controller buttons to keyboard keys.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    _KEYCODE_TO_KBD_LABEL,
    GAMEPAD_BUTTON_SHAPES,
    GAMEPAD_HOTSPOTS,
    GAMEPAD_WIDE,
    INCEDIUS_HOTSPOTS,
    INCEDIUS_WIDE,
    JOYCON_BUTTON_SHAPES,
    KBD_HOTSPOTS,
    KBD_LABEL_TO_KEYCODE,
    KBD_WIDE,
    KEYMAP_HOTSPOTS,
    M913_HOTSPOTS,
    M913_WIDE,
    MOUSE_HOTSPOTS,
    MOUSE_WIDE,
    RAINBOW_COLORS,
    RAINBOW_NAMES,
)
from ..theme import ThemeEngine
from ..widgets.card import Card
from ..widgets.hotspot_canvas import HotspotCanvas

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.views.mapping")


def _coerce_hotspot_list(raw: Any) -> list[tuple[str, float, float]] | None:
    if not isinstance(raw, list):
        return None

    parsed: list[tuple[str, float, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return None
        name, x, y = item
        if not isinstance(name, str):
            return None
        try:
            parsed.append((name, float(x), float(y)))
        except (TypeError, ValueError):
            return None
    return parsed


def _find_startup_hotspot_positions() -> tuple[str, dict[str, list[tuple[str, float, float]]]] | None:
    import os
    import sys

    candidates = [
        os.path.join(os.path.dirname(sys.argv[0]), "hotspot_positions.json"),
        os.path.join(os.getcwd(), "hotspot_positions.json"),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue

        parsed: dict[str, list[tuple[str, float, float]]] = {}
        for device_name, raw_hotspots in data.items():
            hotspots = _coerce_hotspot_list(raw_hotspots)
            if hotspots is not None:
                parsed[device_name] = hotspots
        if parsed:
            return path, parsed
    return None


def _ensure_mappings(profile: dict) -> dict:
    if "mappings" not in profile:
        profile["mappings"] = {}
    return profile


class MappingView(QWidget):
    """Interactive controller mapping editor."""

    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self._main = main
        self._selected_hotspot: str | None = None
        self._learn_mode = False
        self._m913_skin = "Stock"
        self._overlay_color = "violet"
        self._search_text = ""
        self._clipboard_binding: dict[str, Any] | None = None
        self._locked_hotspots: set[str] = set()

        # Per-skin editable position caches (survive skin switching)
        tk = "dark" if main.theme.is_dark else "default"
        self._joycon_pos = list(KEYMAP_HOTSPOTS[tk])
        self._m913_stock_pos = list(M913_HOTSPOTS[tk])
        self._m913_incedius_pos = list(INCEDIUS_HOTSPOTS[tk])
        self._mouse_pos = list(MOUSE_HOTSPOTS[tk])
        self._gamepad_pos = list(GAMEPAD_HOTSPOTS[tk])
        self._keyboard_pos = list(KBD_HOTSPOTS[tk])

        self._init_complete = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Splitter: canvas (left) + profile quick-edit panel (right)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._splitter)

        self._build_canvas_panel()
        self._build_binding_panel()

        # Connect the tab-changed signal AFTER both panels are fully built
        # so that `_on_device_tab_changed` never fires before `_sel_label`,
        # `_m913_canvas`, etc. exist.
        self._device_tabs.currentChanged.connect(self._on_device_tab_changed)
        self._init_complete = True

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
        # NOTE: currentChanged signal is connected AFTER _build_binding_panel()
        # in __init__ to avoid firing before all widgets exist.

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

        # Gamepad / Xbox Elite canvas
        self._gp_canvas = HotspotCanvas(self._main.theme)
        self._gp_canvas.hotspot_clicked.connect(self._on_hotspot_clicked)
        self._gp_canvas.hotspot_right_clicked.connect(self._on_hotspot_right_click)
        self._gp_canvas.hotspot_hovered.connect(self._on_hotspot_hovered)
        self._device_tabs.addTab(self._gp_canvas, "Gamepad")

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

        self._import_pos_btn = QPushButton("📂 Import Positions")
        self._import_pos_btn.setToolTip("Load hotspot positions from a JSON file")
        self._import_pos_btn.clicked.connect(self._import_positions)
        color_row.addWidget(self._import_pos_btn)

        lay.addLayout(color_row)
        self._splitter.addWidget(panel)

    # -----------------------------------------------------------------
    # Profile Quick-Edit panel (right)
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

        # ----- Profile Quick-Edit -----

        # Slot selector
        slot_group = QGroupBox("Profile Slot")
        slot_lay = QVBoxLayout(slot_group)
        slot_btn_row = QHBoxLayout()
        self._pq_slot_btns: list[QPushButton] = []
        for i in range(4):
            btn = QPushButton(f"{i}")
            btn.setFixedHeight(36)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Switch to profile slot {i}")
            btn.clicked.connect(lambda checked, s=i: self._pq_select_slot(s))
            slot_btn_row.addWidget(btn)
            self._pq_slot_btns.append(btn)
        slot_lay.addLayout(slot_btn_row)
        lay.addWidget(slot_group)

        # Profile name
        name_group = QGroupBox("Profile")
        name_lay = QVBoxLayout(name_group)
        name_row = QHBoxLayout()
        self._pq_name_edit = QLineEdit()
        self._pq_name_edit.setPlaceholderText("Profile name")
        self._pq_name_edit.editingFinished.connect(self._pq_on_name_edited)
        name_row.addWidget(self._pq_name_edit)
        rename_btn = QPushButton("✏")
        rename_btn.setFixedWidth(32)
        rename_btn.setToolTip("Rename profile")
        rename_btn.clicked.connect(self._pq_rename)
        name_row.addWidget(rename_btn)
        name_lay.addLayout(name_row)
        lay.addWidget(name_group)

        # Quick actions
        actions_group = QGroupBox("Quick Actions")
        actions_lay = QVBoxLayout(actions_group)

        row1 = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.setProperty("accent", True)
        new_btn.setToolTip("Create a blank profile")
        new_btn.clicked.connect(self._pq_new)
        row1.addWidget(new_btn)
        dup_btn = QPushButton("Duplicate")
        dup_btn.setToolTip("Copy the current profile")
        dup_btn.clicked.connect(self._pq_duplicate)
        row1.addWidget(dup_btn)
        actions_lay.addLayout(row1)

        row2 = QHBoxLayout()
        upload_btn = QPushButton("Upload ↑")
        upload_btn.setProperty("accent", True)
        upload_btn.setToolTip("Send the current profile to the device")
        upload_btn.clicked.connect(self._pq_upload)
        row2.addWidget(upload_btn)
        read_btn = QPushButton("Read ↓")
        read_btn.setToolTip("Read the profile from the device")
        read_btn.clicked.connect(self._pq_read)
        row2.addWidget(read_btn)
        actions_lay.addLayout(row2)

        row3 = QHBoxLayout()
        save_btn = QPushButton("Save File")
        save_btn.setToolTip("Save profile to a JSON file")
        save_btn.clicked.connect(self._pq_save_file)
        row3.addWidget(save_btn)
        load_btn = QPushButton("Load File")
        load_btn.setToolTip("Load profile from a JSON file")
        load_btn.clicked.connect(self._pq_load_file)
        row3.addWidget(load_btn)
        actions_lay.addLayout(row3)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setProperty("danger", True)
        reset_btn.setToolTip("Reset this profile to factory defaults")
        reset_btn.clicked.connect(self._pq_reset)
        actions_lay.addWidget(reset_btn)

        lay.addWidget(actions_group)

        # Mapping summary
        summary_card = Card(self._main.theme)
        summary_lay = QVBoxLayout(summary_card)
        summary_title = QLabel("Mapping Summary")
        summary_title.setFont(QFont(
            self._main.theme.typo("font_family"), 11, QFont.Weight.Bold
        ))
        summary_lay.addWidget(summary_title)
        self._pq_summary_label = QLabel("0 keys bound")
        self._pq_summary_label.setWordWrap(True)
        self._pq_summary_label.setStyleSheet(
            f"color: {self._main.theme.color('text_secondary')};"
        )
        summary_lay.addWidget(self._pq_summary_label)
        lay.addWidget(summary_card)

        # Undo / Redo
        undo_group = QGroupBox("History")
        undo_lay = QHBoxLayout(undo_group)
        self._pq_undo_btn = QPushButton("↩ Undo")
        self._pq_undo_btn.setEnabled(False)
        self._pq_undo_btn.setToolTip("Undo last change (Ctrl+Z)")
        self._pq_undo_btn.clicked.connect(self._main.undo)
        undo_lay.addWidget(self._pq_undo_btn)
        self._pq_redo_btn = QPushButton("↪ Redo")
        self._pq_redo_btn.setEnabled(False)
        self._pq_redo_btn.setToolTip("Redo last change (Ctrl+Y)")
        self._pq_redo_btn.clicked.connect(self._main.redo)
        undo_lay.addWidget(self._pq_redo_btn)
        lay.addWidget(undo_group)

        # Clear all mappings (compact danger button at bottom)
        clear_btn = QPushButton("Clear All Mappings")
        clear_btn.setProperty("danger", True)
        clear_btn.setToolTip("Remove every binding from this profile")
        clear_btn.clicked.connect(self._pq_clear_all)
        lay.addWidget(clear_btn)

        lay.addStretch()

        panel.setWidget(container)
        self._splitter.addWidget(panel)

    # -----------------------------------------------------------------
    # Hotspot loading
    # -----------------------------------------------------------------

    def _load_hotspots(self) -> None:
        # Try loading saved positions from hotspot_positions.json
        self._try_load_saved_positions()

        self._jc_canvas.set_hotspots(self._joycon_pos)
        self._jc_canvas.set_hotspot_shapes(JOYCON_BUTTON_SHAPES)
        # M913 uses the cached per-skin positions
        self._m913_canvas.set_hotspots(self._m913_stock_pos)
        self._m913_canvas.set_wide_set(M913_WIDE)
        self._mouse_canvas.set_hotspots(self._mouse_pos)
        self._mouse_canvas.set_wide_set(MOUSE_WIDE)
        self._gp_canvas.set_hotspots(self._gamepad_pos)
        self._gp_canvas.set_hotspot_shapes(GAMEPAD_BUTTON_SHAPES)
        self._gp_canvas.set_wide_set(GAMEPAD_WIDE)
        self._kbd_canvas.set_hotspots(self._keyboard_pos)
        self._kbd_canvas.set_wide_set(KBD_WIDE)

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

        # Gamepad background
        gp_pm = self._main.assets.load_pixmap("gamepad_none.png")
        if gp_pm:
            self._gp_canvas.set_background(gp_pm)

        # Keyboard (popup canvas)
        kbd_pm = self._main.assets.load_pixmap("keyboard.png")
        if kbd_pm:
            self._kbd_canvas.set_background(kbd_pm)

        # Load pale composite overlays for each device canvas
        self._load_pale_overlays()

        # Load per-button overlay textures for sketch-style brush fills
        self._load_overlay_textures()

    def _try_load_saved_positions(self) -> None:
        """Load per-device positions from hotspot_positions.json if it
        exists next to the executable / working directory.  Updates the
        internal position caches so M913 and Incedius each keep their
        own coordinates."""
        result = _find_startup_hotspot_positions()
        if result is None:
            return

        path, data = result
        self._joycon_pos = list(data.get("joycon", self._joycon_pos))
        self._m913_stock_pos = list(data.get("m913", self._m913_stock_pos))
        self._m913_incedius_pos = list(data.get("incedius", self._m913_incedius_pos))
        self._mouse_pos = list(data.get("mouse", self._mouse_pos))
        self._gamepad_pos = list(data.get("gamepad", self._gamepad_pos))
        self._keyboard_pos = list(data.get("keyboard", self._keyboard_pos))
        log.info("Loaded hotspot positions from %s", path)

    # -----------------------------------------------------------------
    # Overlay helpers (pale composite + bright individual)
    # -----------------------------------------------------------------

    # Maps canvas object-id → (device_name_for_overlays, overlay_prefix)
    _CANVAS_DEVICE_INFO: ClassVar[dict[str, tuple[str, str]]] = {
        "_jc_canvas":    ("joycon",   "jc"),
        "_m913_canvas":  ("m913",     "m913"),
        "_mouse_canvas": ("mouse",    "mouse"),
        "_gp_canvas":    ("gamepad",  "gp"),
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

    def _load_overlay_textures(self) -> None:
        """Load individual button overlay paths for texture brush fills."""
        color = getattr(self, "_overlay_color", "violet")
        for attr, (device, prefix) in self._CANVAS_DEVICE_INFO.items():
            canvas: HotspotCanvas = getattr(self, attr, None)
            if canvas is None:
                continue
            actual_device = device
            actual_prefix = prefix
            if attr == "_m913_canvas" and getattr(self, "_m913_skin", "Stock") == "Incedius":
                actual_device = "incedius"
                actual_prefix = "inc"
            paths: dict[str, str] = {}
            for name in canvas.get_hotspot_names():
                safe_name = name.replace("/", "_").replace("\\", "_").replace(".", "_dot_")
                overlay_name = f"{actual_prefix}_{safe_name}"
                path = self._main.assets.find_overlay_image(actual_device, overlay_name, color)
                if path:
                    paths[name] = str(path)
            canvas.set_overlay_paths(paths)

    # -----------------------------------------------------------------
    # Active device helpers
    # -----------------------------------------------------------------

    _DEVICE_CANVASES_AND_HOTSPOTS = None  # built lazily

    def _device_list(self):
        """Return list of (canvas, hotspot_list) in tab order."""
        m913_hs = self._m913_incedius_pos if self._m913_skin == "Incedius" else self._m913_stock_pos
        return [
            (self._jc_canvas, self._joycon_pos),
            (self._m913_canvas, m913_hs),
            (self._mouse_canvas, self._mouse_pos),
            (self._gp_canvas, self._gamepad_pos),
        ]

    def _active_canvas(self) -> HotspotCanvas:
        idx = self._device_tabs.currentIndex()
        return self._device_list()[idx][0]

    def _active_hotspots(self):
        idx = self._device_tabs.currentIndex()
        return self._device_list()[idx][1]

    def _on_device_tab_changed(self, index: int) -> None:
        # Guard: signal may fire before init completes
        if not getattr(self, "_init_complete", False):
            return
        # Clear bright overlay + selection on all canvases
        for canvas, _ in self._device_list():
            canvas.set_bright_overlay(None)
            canvas.set_selected(None)
        self._selected_hotspot = None
        self._sel_label.setText("No button selected")
        self._sel_mapping.setText("Click a button on the canvas to select it")

    def _on_m913_skin_changed(self, skin: str) -> None:
        # Capture current canvas positions before switching
        if self._m913_skin == "Stock":
            self._m913_stock_pos = self._m913_canvas.export_positions()
        else:
            self._m913_incedius_pos = self._m913_canvas.export_positions()

        self._m913_skin = skin
        if skin == "Incedius":
            self._m913_canvas.set_hotspots(self._m913_incedius_pos)
            self._m913_canvas.set_wide_set(INCEDIUS_WIDE)
            pm = self._main.assets.load_pixmap("incedius_none.png")
        else:
            self._m913_canvas.set_hotspots(self._m913_stock_pos)
            self._m913_canvas.set_wide_set(M913_WIDE)
            pm = self._main.assets.load_pixmap("m913_none.png")
        if pm:
            self._m913_canvas.set_background(pm)
        self._load_pale_overlays()
        self._load_overlay_textures()
        self._refresh_mapping_visuals()

    def _refresh_mapping_visuals(self) -> None:
        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})

        for canvas, hotspots in self._device_list():
            labels: dict[str, str] = {}
            for hs_name, _, _ in hotspots:
                key_id = mappings.get(hs_name, {}).get("keycode")
                is_mapped = key_id is not None
                canvas.update_hotspot_state(hs_name, mapped=is_mapped)
                if key_id is not None:
                    label = _KEYCODE_TO_KBD_LABEL.get(key_id, f"0x{key_id:02X}")
                    labels[hs_name] = label
            canvas.set_mapping_labels(labels)
        self._refresh_profile_panel()

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
            self._sel_mapping.setText("Not mapped — double-click or press Edit to configure")

        # Open the mapping popup on click
        self._open_mapping_popup(name)

    def _on_hotspot_right_click(self, name: str, pos: object) -> None:
        self._on_hotspot_clicked(name)

        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        entry = mappings.get(name, {})
        keycode = entry.get("keycode") if isinstance(entry, dict) else None
        is_mapped = keycode is not None
        is_locked = name in self._locked_hotspots

        menu = QMenu(self)

        # Edit Binding (opens the full popup)
        edit_act = menu.addAction(f"\u270F Edit Binding — {name}")
        edit_act.triggered.connect(lambda: self._open_mapping_popup(name))

        menu.addSeparator()

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

    def _open_mapping_popup(self, name: str) -> None:
        """Open the rich mapping editor popup for *name*."""
        from .mapping_popup import open_mapping_popup

        if name in self._locked_hotspots:
            QMessageBox.warning(self, "Locked", f"{name} is locked. Unlock it first.")
            return

        profile = self._main.get_profile()
        current_entry = profile.get("mappings", {}).get(name)

        result = open_mapping_popup(self._main, name, current_entry, self)

        if result == "__unbind__":
            self._ctx_unbind(name)
        elif result is not None:
            profile = _ensure_mappings(profile)
            profile["mappings"][name] = result
            self._main.set_profile(profile)
            self._refresh_mapping_visuals()
            from .mapping_popup import MappingPopup
            desc = MappingPopup._describe_entry(result)
            self._sel_mapping.setText(f"Bound to: {desc}")

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

    def _on_color_changed(self, color_name: str) -> None:
        self._overlay_color = color_name
        hex_color = RAINBOW_COLORS.get(color_name, "#a03cc8")
        for canvas, _ in self._device_list():
            canvas.set_overlay_color(hex_color)
        # Reload pale + bright overlays and textures for new colour
        self._load_pale_overlays()
        self._load_overlay_textures()
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
        # Capture current M913 canvas positions into the active skin cache
        if self._m913_skin == "Stock":
            self._m913_stock_pos = self._m913_canvas.export_positions()
        else:
            self._m913_incedius_pos = self._m913_canvas.export_positions()

        data: dict[str, list] = {
            "joycon":   [[n, x, y] for n, x, y in self._jc_canvas.export_positions()],
            "m913":     [[n, x, y] for n, x, y in self._m913_stock_pos],
            "incedius": [[n, x, y] for n, x, y in self._m913_incedius_pos],
            "mouse":    [[n, x, y] for n, x, y in self._mouse_canvas.export_positions()],
            "gamepad":  [[n, x, y] for n, x, y in self._gp_canvas.export_positions()],
            "keyboard": [[n, x, y] for n, x, y in self._kbd_canvas.export_positions()],
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Hotspot Positions", "hotspot_positions.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        QMessageBox.information(self, "Exported", f"Positions saved to:\n{path}")

    def _import_positions(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Hotspot Positions", "",
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            QMessageBox.warning(self, "Import Error", str(exc))
            return
        if not isinstance(data, dict):
            QMessageBox.warning(self, "Import Error", "Expected a JSON object.")
            return

        loaded: list[str] = []
        if "joycon" in data:
            self._joycon_pos = [(n, x, y) for n, x, y in data["joycon"]]
            self._jc_canvas.set_hotspots(self._joycon_pos)
            loaded.append("Joy-Con")
        if "m913" in data:
            self._m913_stock_pos = [(n, x, y) for n, x, y in data["m913"]]
            if self._m913_skin == "Stock":
                self._m913_canvas.set_hotspots(self._m913_stock_pos)
            loaded.append("M913 Stock")
        if "incedius" in data:
            self._m913_incedius_pos = [(n, x, y) for n, x, y in data["incedius"]]
            if self._m913_skin == "Incedius":
                self._m913_canvas.set_hotspots(self._m913_incedius_pos)
            loaded.append("M913 Incedius")
        if "mouse" in data:
            self._mouse_pos = [(n, x, y) for n, x, y in data["mouse"]]
            self._mouse_canvas.set_hotspots(self._mouse_pos)
            loaded.append("Mouse")
        if "gamepad" in data:
            self._gamepad_pos = [(n, x, y) for n, x, y in data["gamepad"]]
            self._gp_canvas.set_hotspots(self._gamepad_pos)
            loaded.append("Gamepad")
        if "keyboard" in data:
            self._keyboard_pos = [(n, x, y) for n, x, y in data["keyboard"]]
            self._kbd_canvas.set_hotspots(self._keyboard_pos)
            loaded.append("Keyboard")

        self._refresh_mapping_visuals()
        QMessageBox.information(
            self, "Imported",
            f"Loaded positions for: {', '.join(loaded)}",
        )

    def _on_search(self, text: str) -> None:
        self._search_text = text.strip().lower()
        canvas = self._active_canvas()
        canvas.clear_search()
        if self._search_text:
            for name, _, _ in self._active_hotspots():
                match = self._search_text in name.lower()
                canvas.update_hotspot_state(name, search_match=match)

    # -----------------------------------------------------------------
    # Binding (used by Learn Mode)
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

        profile["mappings"][self._selected_hotspot] = {
            "keycode": keycode,
            "modifier": modifier,
        }

        self._main.set_profile(profile)
        self._refresh_mapping_visuals()
        self._sel_mapping.setText(f"Bound to: {key_label}")

    # -----------------------------------------------------------------
    # Profile Quick-Edit panel actions
    # -----------------------------------------------------------------

    def _pq_select_slot(self, slot: int) -> None:
        self._main._slot_combo.setCurrentIndex(slot)
        self._main._cmd_read_profile()

    def _pq_on_name_edited(self) -> None:
        name = self._pq_name_edit.text().strip()
        if not name:
            return
        profile = self._main.get_profile()
        if profile.get("name") != name:
            profile["name"] = name
            self._main.set_profile(profile)

    def _pq_rename(self) -> None:
        profile = self._main.get_profile()
        old = profile.get("name", "")
        new_name, ok = QInputDialog.getText(
            self, "Rename Profile", "New name:", text=old,
        )
        if ok and new_name.strip():
            profile["name"] = new_name.strip()
            self._main.set_profile(profile)
            self._pq_name_edit.setText(new_name.strip())

    def _pq_new(self) -> None:
        from .profiles import _default_profile
        self._main.set_profile(_default_profile())

    def _pq_duplicate(self) -> None:
        import copy as _copy
        profile = _copy.deepcopy(self._main.get_profile())
        profile["name"] = profile.get("name", "Profile") + " (copy)"
        self._main.set_profile(profile)

    def _pq_upload(self) -> None:
        self._main._cmd_write_profile()

    def _pq_read(self) -> None:
        self._main._cmd_read_profile()

    def _pq_save_file(self) -> None:
        profile = self._main.get_profile()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Profile", "profile.json", "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def _pq_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Profile", "", "JSON Files (*.json);;All Files (*)",
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

    def _pq_reset(self) -> None:
        reply = QMessageBox.question(
            self, "Reset to Default",
            "Reset the current profile to factory defaults?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from ...default_profiles import get_default_profile
            slot = int(self._main._slot_combo.currentText())
            self._main.set_profile(get_default_profile(slot))

    def _pq_clear_all(self) -> None:
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

    def _refresh_profile_panel(self) -> None:
        """Sync the profile quick-edit panel with the current state."""
        profile = self._main.get_profile()

        # Update name field (avoid re-triggering editingFinished)
        self._pq_name_edit.blockSignals(True)
        self._pq_name_edit.setText(profile.get("name", ""))
        self._pq_name_edit.blockSignals(False)

        # Highlight active slot button
        active_slot = self._main._slot
        accent = self._main.theme.color("accent")
        surface = self._main.theme.theme["colors"]["surface"]
        border = self._main.theme.theme["colors"]["border_light"]
        for i, btn in enumerate(self._pq_slot_btns):
            if i == active_slot:
                btn.setChecked(True)
                btn.setStyleSheet(
                    f"background: {accent}; color: #fff; "
                    f"border: 1px solid {accent}; border-radius: 6px; font-weight: bold;"
                )
            else:
                btn.setChecked(False)
                btn.setStyleSheet(
                    f"background: {surface}; "
                    f"border: 1px solid {border}; border-radius: 6px;"
                )

        # Mapping summary
        mappings = profile.get("mappings", {})
        bound = sum(
            1 for v in mappings.values()
            if isinstance(v, dict) and (v.get("keycode") is not None or v.get("type"))
        )
        macros = len(profile.get("macros", []))
        layers = len(profile.get("layers", []))
        chords = len(profile.get("chords", []))
        parts = [f"{bound} binding{'s' if bound != 1 else ''}"]
        if macros:
            parts.append(f"{macros} macro{'s' if macros != 1 else ''}")
        if layers:
            parts.append(f"{layers} layer{'s' if layers != 1 else ''}")
        if chords:
            parts.append(f"{chords} chord{'s' if chords != 1 else ''}")
        self._pq_summary_label.setText(" \u2022 ".join(parts))

        # Undo/redo button state
        self._pq_undo_btn.setEnabled(bool(self._main._undo_stack))
        self._pq_redo_btn.setEnabled(bool(self._main._redo_stack))

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
        self._refresh_profile_panel()

    def profile_updated(self, profile: dict) -> None:
        self._refresh_mapping_visuals()
        self._refresh_profile_panel()

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

        gp_pm = self._main.assets.load_pixmap("gamepad_none.png")
        if gp_pm:
            self._gp_canvas.set_background(gp_pm)

        kbd_pm = self._main.assets.load_pixmap("keyboard.png")
        if kbd_pm:
            self._kbd_canvas.set_background(kbd_pm)
