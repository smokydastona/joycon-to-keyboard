"""Theme engine for the PyQt6 UI.

Provides light/dark colour tokens, QSS stylesheet generation, and helpers
for derived colours (blend, contrast, luma).
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

log = logging.getLogger("joycon_helper.ui.theme")

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"bad hex color: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def blend_hex(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, float(t)))
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    rr = int(ar + (br - ar) * t)
    rg = int(ag + (bg - ag) * t)
    rb = int(ab + (bb - ab) * t)
    return rgb_to_hex((rr, rg, rb))


def relative_luma(h: str) -> float:
    r, g, b = hex_to_rgb(h)
    return (0.2126 * (r / 255.0)) + (0.7152 * (g / 255.0)) + (0.0722 * (b / 255.0))


def contrast_on(bg: str) -> str:
    return "#111111" if relative_luma(bg) > 0.6 else "#fff6e1"


def lighten(h: str, amount: float = 0.15) -> str:
    return blend_hex(h, "#ffffff", amount)


def darken(h: str, amount: float = 0.15) -> str:
    return blend_hex(h, "#000000", amount)


# ---------------------------------------------------------------------------
# Built-in theme definitions
# ---------------------------------------------------------------------------

LIGHT_THEME: dict[str, Any] = {
    "name": "bind-bandit-light",
    "is_dark": False,
    "colors": {
        "bg":           "#f0ebe3",
        "surface":      "#faf7f2",
        "surface2":     "#eee8dd",
        "panel":        "#f5f0e8",
        "text":         "#1a1612",
        "text_secondary": "#6b5d48",
        "muted":        "#8a7d6a",
        "border":       "#d4c8b4",
        "border_light": "#e8dfd0",
        "accent":       "#4a7aba",
        "accent_hover": "#3a68a0",
        "accent2":      "#4a8068",
        "danger":       "#c44040",
        "danger_hover": "#a83030",
        "warning":      "#b88830",
        "success":      "#3a8a50",
        "active":       "#4a8068",
        "conflict":     "#c44040",
        "modified":     "#b88830",
        "selected":     "#4a7aba",
        "selected_bg":  "#dce8f4",
        "pulse_bright": "#60c090",
        "sidebar_bg":   "#2a2420",
        "sidebar_text": "#c8bda8",
        "sidebar_active": "#4a7aba",
        "sidebar_hover":  "#3a3228",
        "card_shadow":  "rgba(0, 0, 0, 0.08)",
        "overlay_bg":   "rgba(0, 0, 0, 0.5)",
        "scrollbar_bg": "#e0d8cc",
        "scrollbar_handle": "#c0b4a0",
        "tooltip_bg":   "#2a2420",
        "tooltip_text": "#f0ebe3",
        "input_bg":     "#ffffff",
        "input_border": "#c8bda8",
        "button_bg":    "#e8e0d4",
        "button_hover": "#ddd4c4",
        "button_pressed": "#d0c4b0",
        "tab_active_bg": "#faf7f2",
        "tab_inactive_bg": "#e0d8cc",
    },
    "typography": {
        "font_family": "Segoe UI",
        "font_family_decorative": "Segoe Print",
        "font_size": 10,
        "font_size_sm": 9,
        "font_size_lg": 12,
        "font_size_xl": 16,
        "font_size_title": 20,
        "mono_family": "Cascadia Code, Consolas",
        "mono_size": 10,
    },
    "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32},
    "radii": {"sm": 6, "md": 10, "lg": 14, "xl": 20},
    "shadows": {
        "card": "0px 2px 8px rgba(0,0,0,0.06)",
        "popup": "0px 8px 24px rgba(0,0,0,0.12)",
        "sidebar": "2px 0px 8px rgba(0,0,0,0.08)",
    },
}

DARK_THEME: dict[str, Any] = {
    "name": "bind-bandit-dark",
    "is_dark": True,
    "colors": {
        # Blueprint Navy heist palette
        "bg":              "#0A1A2F",
        "surface":         "#0d2040",
        "surface2":        "#1C2E4A",
        "panel":           "#0e1e36",
        "text":            "#F2F2F2",
        "text_secondary":  "#C9B89A",
        "muted":           "#7a8fa8",
        "border":          "#1e3555",
        "border_light":    "#163048",
        "accent":          "#4AA8FF",
        "accent_hover":    "#6bbeff",
        "accent2":         "#2b9e6a",
        "danger":          "#C62828",
        "danger_hover":    "#d63030",
        "warning":         "#F7E36A",
        "success":         "#4CAF50",
        "active":          "#2b9e6a",
        "conflict":        "#C62828",
        "modified":        "#F7E36A",
        "selected":        "#4AA8FF",
        "selected_bg":     "#0e2a4a",
        "pulse_bright":    "#4AA8FF",
        "sidebar_bg":      "#07111f",
        "sidebar_text":    "#C9B89A",
        "sidebar_active":  "#4AA8FF",
        "sidebar_hover":   "#0d1e30",
        "card_shadow":     "rgba(0, 0, 0, 0.50)",
        "overlay_bg":      "rgba(0, 0, 0, 0.72)",
        "scrollbar_bg":    "#0d1e33",
        "scrollbar_handle": "#1e3555",
        "tooltip_bg":      "#0B0B0C",
        "tooltip_text":    "#F2F2F2",
        "input_bg":        "#091524",
        "input_border":    "#1e3555",
        "button_bg":       "#1C2E4A",
        "button_hover":    "#253a5c",
        "button_pressed":  "#2a4268",
        "tab_active_bg":   "#0d2040",
        "tab_inactive_bg": "#0A1A2F",
    },
    "typography": {
        "font_family": "Segoe UI",
        "font_family_decorative": "Segoe Print",
        "font_size": 10,
        "font_size_sm": 9,
        "font_size_lg": 12,
        "font_size_xl": 16,
        "font_size_title": 20,
        "mono_family": "Cascadia Code, Consolas",
        "mono_size": 10,
    },
    "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32},
    "radii": {"sm": 6, "md": 10, "lg": 14, "xl": 20},
    "shadows": {
        "card": "0px 2px 8px rgba(0,0,0,0.20)",
        "popup": "0px 8px 24px rgba(0,0,0,0.35)",
        "sidebar": "2px 0px 8px rgba(0,0,0,0.25)",
    },
}

# Convenience mapping used by ThemeEngine.set_mode()
_THEMES: dict[str, Any] = {
    "light": LIGHT_THEME,
    "dark":  DARK_THEME,
}


# ---------------------------------------------------------------------------
# ThemeEngine
# ---------------------------------------------------------------------------

class ThemeEngine:
    """Manages the active theme and generates QSS stylesheets."""

    def __init__(self, dark: bool | None = None, mode: str | None = None) -> None:
        """Initialise the theme engine.

        *mode* (``"light"`` or ``"dark"``) takes priority over the legacy
        *dark* boolean when both are supplied.  When neither is given the
        system dark-mode preference is used.
        """
        if mode is not None:
            resolved = _THEMES.get(mode.lower(), DARK_THEME)
            self._mode = mode.lower()
        else:
            if dark is None:
                dark = self._detect_dark_preference()
            self._mode = "dark" if dark else "light"
            resolved = _THEMES[self._mode]
        self._theme = resolved

    # ── backward-compat property ──
    @property
    def is_dark(self) -> bool:
        return self._theme.get("is_dark", False)

    @property
    def mode_name(self) -> str:
        """Return the current mode name: ``"light"`` or ``"dark"``."""
        return self._mode

    @property
    def theme(self) -> dict[str, Any]:
        return self._theme

    def color(self, key: str) -> str:
        return self._theme["colors"].get(key, "#ff00ff")

    def typo(self, key: str) -> Any:
        return self._theme["typography"].get(key)

    def spacing(self, key: str) -> int:
        return self._theme["spacing"].get(key, 8)

    def radius(self, key: str) -> int:
        return self._theme["radii"].get(key, 6)

    def set_mode(self, mode: str) -> None:
        """Switch to a named theme mode (``"light"`` or ``"dark"``)."""
        resolved = _THEMES.get(mode.lower())
        if resolved is None:
            log.warning("Unknown theme mode %r, ignoring", mode)
            return
        self._mode = mode.lower()
        self._theme = resolved

    def toggle(self) -> None:
        """Toggle between light and dark."""
        self.set_mode("light" if self._mode == "dark" else "dark")

    def generate_qss(self) -> str:
        c = self._theme["colors"]
        t = self._theme["typography"]
        s = self._theme["spacing"]
        r = self._theme["radii"]

        return f"""
/* ════════════════════════════════════════════════════
   Bind Bandit — Generated QSS
   Theme: {self._theme['name']}
   ════════════════════════════════════════════════════ */

/* ── Global ── */
* {{
    font-family: "{t['font_family']}";
    font-size: {t['font_size']}pt;
    color: {c['text']};
    outline: none;
}}

QMainWindow {{
    background: {c['bg']};
}}

QWidget {{
    background: transparent;
}}

/* ── Scroll Area ── */
QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollBar:vertical {{
    background: {c['scrollbar_bg']};
    width: 10px;
    margin: 0;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {c['scrollbar_handle']};
    min-height: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {lighten(c['scrollbar_handle'], 0.15)};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: {c['scrollbar_bg']};
    height: 10px;
    margin: 0;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {c['scrollbar_handle']};
    min-width: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {lighten(c['scrollbar_handle'], 0.15)};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Labels ── */
QLabel {{
    background: transparent;
    padding: 0;
}}

/* ── Push Button ── */
QPushButton {{
    background: {c['button_bg']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']}px;
    padding: {s['sm']}px {s['md']}px;
    font-weight: 500;
    min-height: 28px;
}}
QPushButton:hover {{
    background: {c['button_hover']};
    border-color: {c['accent']};
}}
QPushButton:pressed {{
    background: {c['button_pressed']};
}}
QPushButton:disabled {{
    color: {c['muted']};
    background: {c['surface2']};
    border-color: {c['border_light']};
}}

/* Accent button */
QPushButton[accent="true"] {{
    background: {c['accent']};
    color: #ffffff;
    border: 1px solid {c['accent']};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background: {c['accent_hover']};
}}

/* Danger button */
QPushButton[danger="true"] {{
    background: {c['danger']};
    color: #ffffff;
    border: 1px solid {c['danger']};
}}
QPushButton[danger="true"]:hover {{
    background: {c['danger_hover']};
}}

/* ── Tool Button ── */
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {r['sm']}px;
    padding: {s['xs']}px;
}}
QToolButton:hover {{
    background: {c['button_hover']};
    border-color: {c['border']};
}}
QToolButton:checked {{
    background: {c['selected_bg']};
    border-color: {c['accent']};
}}

/* ── Combo Box ── */
QComboBox {{
    background: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: {r['sm']}px;
    padding: {s['xs']}px {s['sm']}px;
    min-height: 28px;
}}
QComboBox:hover {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']}px;
    selection-background-color: {c['selected_bg']};
    selection-color: {c['text']};
}}

/* ── Line Edit ── */
QLineEdit {{
    background: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: {r['sm']}px;
    padding: {s['xs']}px {s['sm']}px;
    min-height: 28px;
    selection-background-color: {c['selected_bg']};
}}
QLineEdit:focus {{
    border-color: {c['accent']};
}}

/* ── Text Edit / Plain Text ── */
QTextEdit, QPlainTextEdit {{
    background: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: {r['sm']}px;
    padding: {s['sm']}px;
    selection-background-color: {c['selected_bg']};
    font-family: "{t['mono_family']}";
    font-size: {t['mono_size']}pt;
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {c['accent']};
}}

/* ── Spin Box ── */
QSpinBox, QDoubleSpinBox {{
    background: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: {r['sm']}px;
    padding: {s['xs']}px {s['sm']}px;
    min-height: 28px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['accent']};
}}

/* ── Slider ── */
QSlider::groove:horizontal {{
    background: {c['border']};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {c['accent']};
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {c['accent_hover']};
}}
QSlider::sub-page:horizontal {{
    background: {c['accent']};
    border-radius: 2px;
}}

/* ── Check Box / Radio ── */
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {c['border']};
    border-radius: 4px;
    background: {c['input_bg']};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
}}
QRadioButton::indicator {{
    border-radius: 9px;
}}

/* ── Group Box ── */
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: {r['md']}px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 {s['sm']}px;
    color: {c['text_secondary']};
}}

/* ── Tab Widget ── */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: {r['md']}px;
    background: {c['surface']};
    top: -1px;
}}
QTabBar::tab {{
    background: {c['tab_inactive_bg']};
    border: 1px solid {c['border']};
    border-bottom: none;
    border-top-left-radius: {r['sm']}px;
    border-top-right-radius: {r['sm']}px;
    padding: {s['sm']}px {s['lg']}px;
    margin-right: 2px;
    color: {c['text_secondary']};
}}
QTabBar::tab:selected {{
    background: {c['tab_active_bg']};
    color: {c['text']};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {c['button_hover']};
}}

/* ── List Widget ── */
QListWidget {{
    background: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: {r['sm']}px;
    padding: {s['xs']}px;
}}
QListWidget::item {{
    padding: {s['xs']}px {s['sm']}px;
    border-radius: {r['sm']}px;
}}
QListWidget::item:selected {{
    background: {c['selected_bg']};
    color: {c['text']};
}}
QListWidget::item:hover:!selected {{
    background: {c['button_hover']};
}}

/* ── Table ── */
QTableWidget, QTableView {{
    background: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: {r['sm']}px;
    gridline-color: {c['border_light']};
}}
QHeaderView::section {{
    background: {c['surface2']};
    border: none;
    border-right: 1px solid {c['border_light']};
    border-bottom: 1px solid {c['border']};
    padding: {s['sm']}px;
    font-weight: 600;
    color: {c['text_secondary']};
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {c['border']};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}

/* ── Dock Widget ── */
QDockWidget {{
    titlebar-close-icon: none;
    font-weight: 600;
    color: {c['text_secondary']};
}}
QDockWidget::title {{
    background: {c['surface2']};
    padding: {s['sm']}px;
    border-bottom: 1px solid {c['border']};
}}

/* ── Status Bar ── */
QStatusBar {{
    background: {c['surface2']};
    border-top: 1px solid {c['border']};
    padding: {s['xs']}px {s['sm']}px;
    font-size: {t['font_size_sm']}pt;
    color: {c['text_secondary']};
}}

/* ── ToolTip ── */
QToolTip {{
    background: {c['tooltip_bg']};
    color: {c['tooltip_text']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']}px;
    padding: {s['xs']}px {s['sm']}px;
    font-size: {t['font_size_sm']}pt;
}}

/* ── Menu ── */
QMenu {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r['md']}px;
    padding: {s['xs']}px;
}}
QMenu::item {{
    padding: {s['sm']}px {s['lg']}px;
    border-radius: {r['sm']}px;
}}
QMenu::item:selected {{
    background: {c['selected_bg']};
}}
QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin: {s['xs']}px {s['sm']}px;
}}

/* ── Progress Bar ── */
QProgressBar {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']}px;
    text-align: center;
    min-height: 20px;
}}
QProgressBar::chunk {{
    background: {c['accent']};
    border-radius: {r['sm']}px;
}}
"""

    # -----------------------------------------------------------------
    @staticmethod
    def _detect_dark_preference() -> bool:
        env = os.environ.get("BIND_BANDIT_THEME", "").lower()
        if env == "dark":
            return True
        if env == "light":
            return False
        if "--dark" in sys.argv:
            return True
        if "--light" in sys.argv:
            return False
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return val == 0
        except Exception:
            pass
        return False
