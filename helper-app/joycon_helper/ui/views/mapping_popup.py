"""Mapping Editor Popup — rich per-button binding dialog.

Launched when a hotspot is clicked/double-clicked on the canvas.  Provides
categorised output selection (Keyboard, Mouse, Macro, Advanced), modifier
checkboxes, turbo/toggle/sticky/tap-hold options, conflict warnings, and
Apply/Cancel.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow

from ..theme import ThemeEngine
from ...hid_keycodes import (
    MOD_LCTRL, MOD_LSHIFT, MOD_LALT, MOD_LGUI,
    MOD_RCTRL, MOD_RSHIFT, MOD_RALT, MOD_RGUI,
    _KEYCODE_NAMES, hid_to_name,
)

log = logging.getLogger("joycon_helper.ui.views.mapping_popup")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Keyboard rows for the visual picker (HID keycodes)
_KBD_ROWS: List[List[tuple]] = [
    # Row 0 — Esc, F-keys
    [("Esc", 0x29), ("F1", 0x3A), ("F2", 0x3B), ("F3", 0x3C), ("F4", 0x3D),
     ("F5", 0x3E), ("F6", 0x3F), ("F7", 0x40), ("F8", 0x41),
     ("F9", 0x42), ("F10", 0x43), ("F11", 0x44), ("F12", 0x45)],
    # Row 1 — number row
    [("`", 0x35), ("1", 0x1E), ("2", 0x1F), ("3", 0x20), ("4", 0x21),
     ("5", 0x22), ("6", 0x23), ("7", 0x24), ("8", 0x25), ("9", 0x26),
     ("0", 0x27), ("-", 0x2D), ("=", 0x2E), ("Bksp", 0x2A)],
    # Row 2 — QWERTY
    [("Tab", 0x2B), ("Q", 0x14), ("W", 0x1A), ("E", 0x08), ("R", 0x15),
     ("T", 0x17), ("Y", 0x1C), ("U", 0x18), ("I", 0x0C), ("O", 0x12),
     ("P", 0x13), ("[", 0x2F), ("]", 0x30), ("\\", 0x31)],
    # Row 3 — home row
    [("Caps", 0x39), ("A", 0x04), ("S", 0x16), ("D", 0x07), ("F", 0x09),
     ("G", 0x0A), ("H", 0x0B), ("J", 0x0D), ("K", 0x0E), ("L", 0x0F),
     (";", 0x33), ("'", 0x34), ("Enter", 0x28)],
    # Row 4 — bottom row
    [("Z", 0x1D), ("X", 0x1B), ("C", 0x06), ("V", 0x19), ("B", 0x05),
     ("N", 0x11), ("M", 0x10), (",", 0x36), (".", 0x37), ("/", 0x38)],
    # Row 5 — space bar + arrows
    [("Space", 0x2C), ("Ins", 0x49), ("Del", 0x4C), ("Home", 0x4A),
     ("End", 0x4D), ("PgUp", 0x4B), ("PgDn", 0x4E),
     ("\u2190", 0x50), ("\u2191", 0x52), ("\u2193", 0x51), ("\u2192", 0x4F)],
]

_MODIFIER_DEFS: List[tuple] = [
    ("LCtrl", MOD_LCTRL),
    ("LShift", MOD_LSHIFT),
    ("LAlt", MOD_LALT),
    ("LWin", MOD_LGUI),
    ("RCtrl", MOD_RCTRL),
    ("RShift", MOD_RSHIFT),
    ("RAlt", MOD_RALT),
    ("RWin", MOD_RGUI),
]

# Mouse buttons — stored as negative keycodes to signal firmware
MOUSE_BUTTONS: List[tuple] = [
    ("Left Click", 1),
    ("Right Click", 2),
    ("Middle Click", 3),
    ("Back (X1)", 4),
    ("Forward (X2)", 5),
    ("Scroll Up", 6),
    ("Scroll Down", 7),
]

# Advanced binding types
ADVANCED_TYPES: List[tuple] = [
    ("turbo", "Turbo", "Repeat the key at a set interval while held"),
    ("toggle", "Toggle", "Press once to hold, press again to release"),
    ("sticky", "Sticky", "Key stays down until another key is pressed"),
    ("oneshot", "One-Shot", "Next key press includes this modifier, then releases"),
    ("autoshift", "Auto-Shift", "Tap = key, hold = Shift+key"),
    ("taphold", "Tap-Hold", "Tap = key A, hold = key B"),
    ("sequential", "Sequential", "Cycle through a sequence of keys"),
    ("doubletap", "Double-Tap", "Different action on double-tap vs single"),
    ("leader", "Leader Key", "Starts a leader-key sequence"),
    ("profileswitch", "Profile Switch", "Switch to a different profile slot"),
    ("disable", "Disable", "Button does nothing"),
]


class MappingPopup(QDialog):
    """Per-button binding popup with categorised output selection."""

    def __init__(self, main: "MainWindow", button_name: str,
                 current_entry: Optional[Dict[str, Any]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent or main)
        self._main = main
        self._button_name = button_name
        self._entry = copy.deepcopy(current_entry) if current_entry else {}
        self._result_entry: Optional[Dict[str, Any]] = None

        self.setWindowTitle(f"Edit Binding — {button_name}")
        self.setMinimumSize(680, 560)
        self.setModal(True)

        # Theme-aware styling
        theme = main.theme
        colors = theme.theme["colors"]
        self.setStyleSheet(f"""
            QDialog {{
                background: {colors['bg']};
                color: {colors['text']};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {colors['border_light']};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 16px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }}
            QPushButton {{
                padding: 6px 14px;
                border-radius: 4px;
                border: 1px solid {colors['border_light']};
                background: {colors['surface']};
                color: {colors['text']};
            }}
            QPushButton:hover {{
                background: {colors.get('surface_hover', colors['accent'])};
            }}
            QPushButton[accent="true"] {{
                background: {colors['accent']};
                color: #fff;
                border: none;
            }}
            QPushButton[danger="true"] {{
                background: #d32f2f;
                color: #fff;
                border: none;
            }}
            QTabWidget::pane {{
                border: 1px solid {colors['border_light']};
                border-radius: 4px;
                background: {colors['surface']};
            }}
            QTabBar::tab {{
                padding: 8px 16px;
                border: 1px solid {colors['border_light']};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                background: {colors['bg']};
                color: {colors['text_secondary']};
            }}
            QTabBar::tab:selected {{
                background: {colors['surface']};
                color: {colors['text']};
                border-bottom: 2px solid {colors['accent']};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 1) Input preview header
        self._build_header(root, theme)

        # 2) Output type tabs
        self._tabs = QTabWidget()
        self._build_keyboard_tab()
        self._build_mouse_tab()
        self._build_macro_tab()
        self._build_advanced_tab()
        root.addWidget(self._tabs, 1)

        # 3) Conflict warning area
        self._conflict_label = QLabel()
        self._conflict_label.setStyleSheet("color: #ff9800; font-size: 12px;")
        self._conflict_label.setWordWrap(True)
        self._conflict_label.hide()
        root.addWidget(self._conflict_label)

        # 4) Bottom buttons
        self._build_footer(root, theme)

        # Pre-populate from current entry
        self._populate_from_entry()

    # =================================================================
    # Header
    # =================================================================

    def _build_header(self, parent_layout: QVBoxLayout,
                      theme: ThemeEngine) -> None:
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QFrame {{
                background: {theme.theme['colors']['surface']};
                border: 1px solid {theme.theme['colors']['border_light']};
                border-radius: 8px;
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 8, 16, 8)

        # Button name
        name_lbl = QLabel(f"\u25CF  {self._button_name}")
        name_lbl.setFont(QFont(theme.typo("font_family"), 14, QFont.Weight.Bold))
        h_lay.addWidget(name_lbl)

        h_lay.addStretch()

        # Current mapping summary
        self._summary_label = QLabel(self._describe_entry(self._entry))
        self._summary_label.setStyleSheet(
            f"color: {theme.theme['colors']['text_secondary']}; font-size: 12px;"
        )
        h_lay.addWidget(self._summary_label)

        parent_layout.addWidget(header)

    # =================================================================
    # Keyboard tab
    # =================================================================

    def _build_keyboard_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Modifier checkboxes
        mod_group = QGroupBox("Modifiers")
        mod_lay = QHBoxLayout(mod_group)
        self._mod_checks: Dict[int, QCheckBox] = {}
        for label, bit in _MODIFIER_DEFS:
            cb = QCheckBox(label)
            cb.setToolTip(f"Toggle {label} modifier (bit 0x{bit:02X})")
            cb.toggled.connect(self._update_preview)
            mod_lay.addWidget(cb)
            self._mod_checks[bit] = cb
        lay.addWidget(mod_group)

        # Visual keyboard grid
        kbd_scroll = QScrollArea()
        kbd_scroll.setWidgetResizable(True)
        kbd_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        kbd_container = QWidget()
        kbd_main_lay = QVBoxLayout(kbd_container)
        kbd_main_lay.setSpacing(4)

        self._kbd_buttons: Dict[int, QPushButton] = {}
        for row in _KBD_ROWS:
            row_lay = QHBoxLayout()
            row_lay.setSpacing(3)
            for label, keycode in row:
                btn = QPushButton(label)
                btn.setFixedSize(QSize(46, 36))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setToolTip(f"{label} (0x{keycode:02X})")
                btn.clicked.connect(
                    lambda checked, kc=keycode, lb=label: self._select_keycode(kc, lb)
                )
                row_lay.addWidget(btn)
                self._kbd_buttons[keycode] = btn
            row_lay.addStretch()
            kbd_main_lay.addLayout(row_lay)

        kbd_main_lay.addStretch()
        kbd_scroll.setWidget(kbd_container)
        lay.addWidget(kbd_scroll, 1)

        # Custom keycode entry
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom HID keycode:"))
        self._custom_keycode = QLineEdit()
        self._custom_keycode.setPlaceholderText("0x04 (A)")
        self._custom_keycode.setMaximumWidth(120)
        custom_row.addWidget(self._custom_keycode)
        apply_custom = QPushButton("Set")
        apply_custom.clicked.connect(self._set_custom_keycode)
        custom_row.addWidget(apply_custom)
        custom_row.addStretch()
        lay.addLayout(custom_row)

        # Selected key display
        self._selected_key_label = QLabel("No key selected")
        self._selected_key_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        lay.addWidget(self._selected_key_label)

        self._selected_keycode: Optional[int] = None
        self._tabs.addTab(page, "\u2328  Keyboard")

    def _select_keycode(self, keycode: int, label: str) -> None:
        # Un-highlight previous
        if self._selected_keycode is not None:
            prev_btn = self._kbd_buttons.get(self._selected_keycode)
            if prev_btn:
                prev_btn.setStyleSheet("")

        self._selected_keycode = keycode
        btn = self._kbd_buttons.get(keycode)
        if btn:
            accent = self._main.theme.theme["colors"]["accent"]
            btn.setStyleSheet(f"background: {accent}; color: #fff; border: none;")
        self._selected_key_label.setText(f"Selected: {label} (0x{keycode:02X})")
        self._update_preview()

    def _set_custom_keycode(self) -> None:
        text = self._custom_keycode.text().strip()
        if not text:
            return
        try:
            kc = int(text, 16) if text.startswith("0x") else int(text)
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Enter a valid keycode (decimal or 0xHex).")
            return
        label = _KEYCODE_NAMES.get(kc, f"0x{kc:02X}")
        self._select_keycode(kc, label)

    # =================================================================
    # Mouse tab
    # =================================================================

    def _build_mouse_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel("Select a mouse button or scroll action to bind.")
        info.setStyleSheet("color: grey; font-size: 12px;")
        lay.addWidget(info)

        self._mouse_selected: Optional[int] = None
        self._mouse_btns: Dict[int, QPushButton] = {}

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (label, btn_id) in enumerate(MOUSE_BUTTONS):
            btn = QPushButton(label)
            btn.setFixedHeight(40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked, bid=btn_id, lb=label: self._select_mouse(bid, lb)
            )
            grid.addWidget(btn, i // 3, i % 3)
            self._mouse_btns[btn_id] = btn
        lay.addLayout(grid)

        self._mouse_label = QLabel("No mouse button selected")
        self._mouse_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        lay.addWidget(self._mouse_label)

        lay.addStretch()
        self._tabs.addTab(page, "\U0001F5B1  Mouse")

    def _select_mouse(self, btn_id: int, label: str) -> None:
        accent = self._main.theme.theme["colors"]["accent"]
        for bid, btn in self._mouse_btns.items():
            btn.setStyleSheet(
                f"background: {accent}; color: #fff;" if bid == btn_id else ""
            )
        self._mouse_selected = btn_id
        self._mouse_label.setText(f"Selected: {label}")
        self._update_preview()

    # =================================================================
    # Macro tab
    # =================================================================

    def _build_macro_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        info = QLabel("Assign a macro from the current profile.")
        info.setStyleSheet("color: grey; font-size: 12px;")
        lay.addWidget(info)

        self._macro_combo = QComboBox()
        self._macro_combo.setMinimumWidth(250)
        macros = self._main.get_profile().get("macros", [])
        if macros:
            for m in macros:
                name = m.get("name", "Unnamed")
                self._macro_combo.addItem(name, m)
        else:
            self._macro_combo.addItem("(no macros defined)")
            self._macro_combo.setEnabled(False)
        lay.addWidget(self._macro_combo)

        hint = QLabel("Create macros in the Macros tab, then assign them here.")
        hint.setStyleSheet("color: grey; font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        lay.addStretch()
        self._tabs.addTab(page, "\u26A1  Macro")

    # =================================================================
    # Advanced tab
    # =================================================================

    def _build_advanced_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        info = QLabel("Choose an advanced binding behaviour.")
        info.setStyleSheet("color: grey; font-size: 12px;")
        lay.addWidget(info)

        # Type selector
        self._adv_type_combo = QComboBox()
        for type_id, label, desc in ADVANCED_TYPES:
            self._adv_type_combo.addItem(f"{label} — {desc}", type_id)
        self._adv_type_combo.currentIndexChanged.connect(self._on_adv_type_changed)
        lay.addWidget(self._adv_type_combo)

        # Stacked config per advanced type
        self._adv_stack = QStackedWidget()
        self._adv_configs: Dict[str, Dict[str, Any]] = {}

        # 0: turbo
        self._adv_stack.addWidget(self._build_turbo_config())
        # 1: toggle (no extra config)
        self._adv_stack.addWidget(self._build_placeholder("Toggle: press once to hold, again to release."))
        # 2: sticky (no extra config)
        self._adv_stack.addWidget(self._build_placeholder("Sticky: key stays down until another key is pressed."))
        # 3: oneshot
        self._adv_stack.addWidget(self._build_placeholder("One-Shot: next key press includes this modifier, then releases."))
        # 4: autoshift (no extra config)
        self._adv_stack.addWidget(self._build_placeholder("Auto-Shift: tap = key, hold = Shift+key."))
        # 5: taphold
        self._adv_stack.addWidget(self._build_taphold_config())
        # 6: sequential
        self._adv_stack.addWidget(self._build_sequential_config())
        # 7: doubletap
        self._adv_stack.addWidget(self._build_doubletap_config())
        # 8: leader
        self._adv_stack.addWidget(self._build_placeholder("Leader Key: starts a leader-key sequence."))
        # 9: profileswitch
        self._adv_stack.addWidget(self._build_profile_switch_config())
        # 10: disable
        self._adv_stack.addWidget(self._build_placeholder("Disable: this button does nothing when pressed."))

        lay.addWidget(self._adv_stack, 1)
        self._tabs.addTab(page, "\u2699  Advanced")

    def _build_placeholder(self, text: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: grey; font-size: 12px;")
        lay.addWidget(lbl)
        lay.addStretch()
        return w

    def _build_turbo_config(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        lay.setSpacing(10)

        lbl = QLabel("Turbo repeats the key press at the configured interval while the button is held.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: grey; font-size: 12px;")
        lay.addRow(lbl)

        self._turbo_interval = QSpinBox()
        self._turbo_interval.setRange(10, 1000)
        self._turbo_interval.setValue(50)
        self._turbo_interval.setSuffix(" ms")
        self._turbo_interval.setToolTip("Interval between repeated key presses")
        lay.addRow("Interval:", self._turbo_interval)

        # Underlying key — use whatever is selected on keyboard tab
        note = QLabel("The turbo key is taken from the Keyboard tab selection.")
        note.setWordWrap(True)
        note.setStyleSheet("color: grey; font-size: 11px;")
        lay.addRow(note)

        return w

    def _build_taphold_config(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        lay.setSpacing(10)

        lbl = QLabel("Tap-Hold: emits one key on quick tap, a different key when held past the threshold.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: grey; font-size: 12px;")
        lay.addRow(lbl)

        self._taphold_tap_keycode = QLineEdit()
        self._taphold_tap_keycode.setPlaceholderText("Tap keycode (hex/dec)")
        lay.addRow("Tap key:", self._taphold_tap_keycode)

        self._taphold_hold_keycode = QLineEdit()
        self._taphold_hold_keycode.setPlaceholderText("Hold keycode (hex/dec)")
        lay.addRow("Hold key:", self._taphold_hold_keycode)

        self._taphold_threshold = QSpinBox()
        self._taphold_threshold.setRange(50, 1000)
        self._taphold_threshold.setValue(200)
        self._taphold_threshold.setSuffix(" ms")
        lay.addRow("Hold threshold:", self._taphold_threshold)

        return w

    def _build_sequential_config(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        lbl = QLabel("Sequential: cycles through up to 8 keycodes, one per press.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: grey; font-size: 12px;")
        lay.addWidget(lbl)

        self._seq_inputs: List[QLineEdit] = []
        grid = QGridLayout()
        grid.setSpacing(4)
        for i in range(8):
            inp = QLineEdit()
            inp.setPlaceholderText(f"Key {i+1} (hex/dec)")
            inp.setMaximumWidth(140)
            grid.addWidget(QLabel(f"{i+1}:"), i // 4, (i % 4) * 2)
            grid.addWidget(inp, i // 4, (i % 4) * 2 + 1)
            self._seq_inputs.append(inp)
        lay.addLayout(grid)
        lay.addStretch()
        return w

    def _build_doubletap_config(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        lay.setSpacing(10)

        lbl = QLabel("Double-Tap: single press does one key, double-tap does another.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: grey; font-size: 12px;")
        lay.addRow(lbl)

        self._dt_single_keycode = QLineEdit()
        self._dt_single_keycode.setPlaceholderText("Single-tap keycode")
        lay.addRow("Single tap:", self._dt_single_keycode)

        self._dt_double_keycode = QLineEdit()
        self._dt_double_keycode.setPlaceholderText("Double-tap keycode")
        lay.addRow("Double tap:", self._dt_double_keycode)

        self._dt_window = QSpinBox()
        self._dt_window.setRange(80, 500)
        self._dt_window.setValue(200)
        self._dt_window.setSuffix(" ms")
        lay.addRow("Tap window:", self._dt_window)

        return w

    def _build_profile_switch_config(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)
        lay.setSpacing(10)

        lbl = QLabel("Profile Switch: pressing this button switches to the selected profile slot.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: grey; font-size: 12px;")
        lay.addRow(lbl)

        self._ps_slot = QSpinBox()
        self._ps_slot.setRange(0, 3)
        self._ps_slot.setValue(0)
        self._ps_slot.setToolTip("Target profile slot (0-3)")
        lay.addRow("Profile slot:", self._ps_slot)

        return w

    def _on_adv_type_changed(self, index: int) -> None:
        self._adv_stack.setCurrentIndex(index)
        self._update_preview()

    # =================================================================
    # Footer
    # =================================================================

    def _build_footer(self, parent_layout: QVBoxLayout,
                      theme: ThemeEngine) -> None:
        footer = QHBoxLayout()

        # Unbind
        unbind_btn = QPushButton("Unbind")
        unbind_btn.setProperty("danger", True)
        unbind_btn.setToolTip("Remove binding for this button")
        unbind_btn.clicked.connect(self._on_unbind)
        footer.addWidget(unbind_btn)

        footer.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setProperty("accent", True)
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply)
        footer.addWidget(apply_btn)

        parent_layout.addLayout(footer)

    # =================================================================
    # Preview / conflict
    # =================================================================

    def _update_preview(self) -> None:
        entry = self._build_entry_from_ui()
        if entry:
            self._summary_label.setText(self._describe_entry(entry))
            self._check_conflicts(entry)
        else:
            self._summary_label.setText("Configure a binding above")

    def _check_conflicts(self, entry: Dict[str, Any]) -> None:
        keycode = entry.get("keycode")
        if keycode is None:
            self._conflict_label.hide()
            return

        profile = self._main.get_profile()
        mappings = profile.get("mappings", {})
        conflicts = []
        for name, mapping in mappings.items():
            if name == self._button_name:
                continue
            if not isinstance(mapping, dict):
                continue
            if mapping.get("keycode") == keycode and mapping.get("modifier", 0) == entry.get("modifier", 0):
                conflicts.append(name)

        if conflicts:
            self._conflict_label.setText(
                f"\u26A0 Conflict: same binding on {', '.join(conflicts)}"
            )
            self._conflict_label.show()
        else:
            self._conflict_label.hide()

    # =================================================================
    # Build entry from UI
    # =================================================================

    def _build_entry_from_ui(self) -> Optional[Dict[str, Any]]:
        tab = self._tabs.currentIndex()

        if tab == 0:  # Keyboard
            if self._selected_keycode is None:
                return None
            modifier = 0
            for bit, cb in self._mod_checks.items():
                if cb.isChecked():
                    modifier |= bit
            return {"keycode": self._selected_keycode, "modifier": modifier}

        elif tab == 1:  # Mouse
            if self._mouse_selected is None:
                return None
            return {"type": "mouse", "button": self._mouse_selected}

        elif tab == 2:  # Macro
            idx = self._macro_combo.currentIndex()
            data = self._macro_combo.itemData(idx)
            if data is None:
                return None
            return {"type": "macro", "macro_name": data.get("name", "Unnamed")}

        elif tab == 3:  # Advanced
            adv_idx = self._adv_type_combo.currentIndex()
            type_id = self._adv_type_combo.itemData(adv_idx)
            entry: Dict[str, Any] = {"type": type_id}

            if type_id == "turbo":
                if self._selected_keycode is not None:
                    entry["keycode"] = self._selected_keycode
                    modifier = 0
                    for bit, cb in self._mod_checks.items():
                        if cb.isChecked():
                            modifier |= bit
                    entry["modifier"] = modifier
                entry["turbo"] = True
                entry["turbo_interval_ms"] = self._turbo_interval.value()

            elif type_id in ("toggle", "sticky", "oneshot", "autoshift"):
                if self._selected_keycode is not None:
                    entry["keycode"] = self._selected_keycode
                    modifier = 0
                    for bit, cb in self._mod_checks.items():
                        if cb.isChecked():
                            modifier |= bit
                    entry["modifier"] = modifier

            elif type_id == "taphold":
                entry["tap_keycode"] = self._parse_keycode(self._taphold_tap_keycode.text())
                entry["hold_keycode"] = self._parse_keycode(self._taphold_hold_keycode.text())
                entry["threshold_ms"] = self._taphold_threshold.value()

            elif type_id == "sequential":
                seq = []
                for inp in self._seq_inputs:
                    kc = self._parse_keycode(inp.text())
                    if kc is not None:
                        seq.append(kc)
                entry["sequence"] = seq

            elif type_id == "doubletap":
                entry["single_keycode"] = self._parse_keycode(self._dt_single_keycode.text())
                entry["double_keycode"] = self._parse_keycode(self._dt_double_keycode.text())
                entry["window_ms"] = self._dt_window.value()

            elif type_id == "profileswitch":
                entry["target_slot"] = self._ps_slot.value()

            return entry

        return None

    # =================================================================
    # Populate from existing entry
    # =================================================================

    def _populate_from_entry(self) -> None:
        if not self._entry:
            return

        entry_type = self._entry.get("type")
        keycode = self._entry.get("keycode")
        modifier = self._entry.get("modifier", 0)

        if entry_type == "mouse":
            self._tabs.setCurrentIndex(1)
            btn_id = self._entry.get("button")
            if btn_id is not None:
                for label_text, bid in MOUSE_BUTTONS:
                    if bid == btn_id:
                        self._select_mouse(bid, label_text)
                        break

        elif entry_type == "macro":
            self._tabs.setCurrentIndex(2)
            macro_name = self._entry.get("macro_name", "")
            for i in range(self._macro_combo.count()):
                data = self._macro_combo.itemData(i)
                if data and data.get("name") == macro_name:
                    self._macro_combo.setCurrentIndex(i)
                    break

        elif entry_type in {t[0] for t in ADVANCED_TYPES}:
            self._tabs.setCurrentIndex(3)
            for i, (tid, _, _) in enumerate(ADVANCED_TYPES):
                if tid == entry_type:
                    self._adv_type_combo.setCurrentIndex(i)
                    break

            if entry_type == "turbo":
                self._turbo_interval.setValue(self._entry.get("turbo_interval_ms", 50))
                if keycode is not None:
                    label = _KEYCODE_NAMES.get(keycode, f"0x{keycode:02X}")
                    self._select_keycode(keycode, label)

            elif entry_type == "taphold":
                tap = self._entry.get("tap_keycode")
                hold = self._entry.get("hold_keycode")
                if tap is not None:
                    self._taphold_tap_keycode.setText(f"0x{tap:02X}")
                if hold is not None:
                    self._taphold_hold_keycode.setText(f"0x{hold:02X}")
                self._taphold_threshold.setValue(self._entry.get("threshold_ms", 200))

            elif entry_type == "sequential":
                seq = self._entry.get("sequence", [])
                for i, kc in enumerate(seq[:8]):
                    self._seq_inputs[i].setText(f"0x{kc:02X}")

            elif entry_type == "doubletap":
                sk = self._entry.get("single_keycode")
                dk = self._entry.get("double_keycode")
                if sk is not None:
                    self._dt_single_keycode.setText(f"0x{sk:02X}")
                if dk is not None:
                    self._dt_double_keycode.setText(f"0x{dk:02X}")
                self._dt_window.setValue(self._entry.get("window_ms", 200))

            elif entry_type == "profileswitch":
                self._ps_slot.setValue(self._entry.get("target_slot", 0))

            # Populate modifiers for types that use keyboard tab keycodes
            if entry_type in ("turbo", "toggle", "sticky", "oneshot", "autoshift"):
                if keycode is not None:
                    label = _KEYCODE_NAMES.get(keycode, f"0x{keycode:02X}")
                    self._select_keycode(keycode, label)
                for bit, cb in self._mod_checks.items():
                    cb.setChecked(bool(modifier & bit))

        elif keycode is not None:
            # Plain keyboard binding
            self._tabs.setCurrentIndex(0)
            label = _KEYCODE_NAMES.get(keycode, f"0x{keycode:02X}")
            self._select_keycode(keycode, label)
            for bit, cb in self._mod_checks.items():
                cb.setChecked(bool(modifier & bit))

        self._update_preview()

    # =================================================================
    # Actions
    # =================================================================

    def _on_apply(self) -> None:
        entry = self._build_entry_from_ui()
        if entry is None:
            QMessageBox.warning(
                self, "Incomplete",
                "Select a key, mouse button, macro, or advanced type before applying.",
            )
            return
        self._result_entry = entry
        self.accept()

    def _on_unbind(self) -> None:
        self._result_entry = None  # sentinel: caller should remove the binding
        self.done(2)  # custom result code — "unbind"

    def get_result(self) -> Optional[Dict[str, Any]]:
        """Return the configured entry, or *None* if the user chose Unbind."""
        return self._result_entry

    # =================================================================
    # Helpers
    # =================================================================

    @staticmethod
    def _parse_keycode(text: str) -> Optional[int]:
        text = text.strip()
        if not text:
            return None
        try:
            return int(text, 16) if text.startswith("0x") else int(text)
        except ValueError:
            return None

    @staticmethod
    def _describe_entry(entry: Dict[str, Any]) -> str:
        if not entry:
            return "Not mapped"
        t = entry.get("type")
        kc = entry.get("keycode")
        mod = entry.get("modifier", 0)
        if t == "mouse":
            for label, bid in MOUSE_BUTTONS:
                if bid == entry.get("button"):
                    return f"Mouse: {label}"
            return "Mouse"
        if t == "macro":
            return f"Macro: {entry.get('macro_name', '?')}"
        if t == "disable":
            return "Disabled"
        if t == "profileswitch":
            return f"Profile Switch → slot {entry.get('target_slot', '?')}"
        if t in {tid for tid, _, _ in ADVANCED_TYPES}:
            for tid, label, _ in ADVANCED_TYPES:
                if tid == t:
                    suffix = ""
                    if kc is not None:
                        suffix = f" ({hid_to_name(mod, kc)})"
                    return f"{label}{suffix}"
        if kc is not None:
            return hid_to_name(mod, kc)
        return "Not mapped"


# Convenience launcher
def open_mapping_popup(main: "MainWindow", button_name: str,
                       current_entry: Optional[Dict[str, Any]] = None,
                       parent: Optional[QWidget] = None,
                       ) -> Optional[Dict[str, Any]]:
    """Open the mapping popup and return the new entry dict, or *None*.

    Returns:
        - A dict if the user clicked Apply.
        - ``None`` if the user cancelled.
        - The string ``"__unbind__"`` if the user clicked Unbind.
    """
    dlg = MappingPopup(main, button_name, current_entry, parent)
    result = dlg.exec()
    if result == 2:  # unbind
        return "__unbind__"  # type: ignore[return-value]
    if result == QDialog.DialogCode.Accepted:
        return dlg.get_result()
    return None
