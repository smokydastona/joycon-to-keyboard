"""Sidebar navigation widget.

A vertical left rail with icon + label nav items, collapsible between
wide (220 px) and narrow (56 px) modes.  Features animated transitions,
shortcut hints, separator lines between nav groups, and glow effects.
"""
from __future__ import annotations

from typing import ClassVar

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import ThemeEngine


class SidebarItem(QPushButton):
    """A single nav item in the sidebar."""

    def __init__(self, icon_char: str, label: str, theme: ThemeEngine,
                 shortcut_hint: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_char = icon_char
        self._label_text = label
        self._theme = theme
        self._active = False
        self._expanded = True
        self._shortcut_hint = shortcut_hint  # e.g. "Ctrl+1"

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedHeight(48)

        # Glow effect for active item
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setBlurRadius(0)
        self._glow.setOffset(0, 0)
        self._glow.setColor(QColor(theme.theme["colors"].get("sidebar_active", "#4a7aba")))
        self.setGraphicsEffect(self._glow)

        self._update_style()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._update_text()

    def set_active(self, active: bool) -> None:
        was_active = self._active
        self._active = active
        self.setChecked(active)
        self._update_style()
        # Animate glow
        if active and not was_active:
            self._animate_glow_in()
        elif not active and was_active:
            self._glow.setBlurRadius(0)

    def _animate_glow_in(self) -> None:
        """Smooth glow-in when this item becomes active."""
        from PyQt6.QtGui import QColor
        accent = self._theme.theme["colors"].get("sidebar_active", "#4a7aba")
        c = QColor(accent)
        c.setAlpha(120)
        self._glow.setColor(c)

        anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        anim.setDuration(300)
        anim.setStartValue(0)
        anim.setEndValue(18)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _update_text(self) -> None:
        if self._expanded:
            self.setText(f"  {self._icon_char}   {self._label_text}")
            if self._shortcut_hint:
                self.setToolTip(f"{self._label_text}  ({self._shortcut_hint})")
            else:
                self.setToolTip("")
        else:
            self.setText(f"  {self._icon_char}")
            tip = self._label_text
            if self._shortcut_hint:
                tip += f"  ({self._shortcut_hint})"
            self.setToolTip(tip)

    def _update_style(self) -> None:
        c = self._theme.theme["colors"]
        if self._active:
            self.setStyleSheet(f"""
                SidebarItem {{
                    background: {c['sidebar_hover']};
                    color: {c['sidebar_active']};
                    border: none;
                    border-left: 3px solid {c['sidebar_active']};
                    border-radius: 0;
                    text-align: left;
                    padding-left: 12px;
                    font-weight: 700;
                    font-size: 11pt;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                SidebarItem {{
                    background: transparent;
                    color: {c['sidebar_text']};
                    border: none;
                    border-left: 3px solid transparent;
                    border-radius: 0;
                    text-align: left;
                    padding-left: 12px;
                    font-size: 11pt;
                }}
                SidebarItem:hover {{
                    background: {c['sidebar_hover']};
                    color: {c['sidebar_active']};
                }}
            """)

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        from PyQt6.QtGui import QColor
        accent = theme.theme["colors"].get("sidebar_active", "#4a7aba")
        c = QColor(accent)
        c.setAlpha(120)
        self._glow.setColor(c)
        self._update_style()
        self._update_text()


class _SidebarSeparator(QFrame):
    """Thin horizontal line used between navigation groups."""

    def __init__(self, theme: ThemeEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setFixedHeight(1)
        self._apply_theme()

    def _apply_theme(self) -> None:
        c = self._theme.theme["colors"]
        self.setStyleSheet(f"background: {c['border']}; margin: 6px 12px;")

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self._apply_theme()


class SidebarWidget(QFrame):
    """Collapsible sidebar navigation rail."""

    EXPANDED_WIDTH = 220
    COLLAPSED_WIDTH = 56

    nav_clicked = pyqtSignal(int)
    update_clicked = pyqtSignal()

    # Group boundaries: separator inserted *before* these logical indices
    _GROUP_BREAKS: ClassVar[set[int]] = {4, 7}  # before Devices, before Settings

    def __init__(self, theme: ThemeEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._expanded = True
        self._items: list[SidebarItem] = []
        self._separators: list[_SidebarSeparator] = []

        self.setFixedWidth(self.EXPANDED_WIDTH)
        self.setObjectName("Sidebar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Header with app name + collapse button
        header = QWidget()
        header.setFixedHeight(60)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 12, 8, 12)

        self._title_label = QLabel("BIND BANDIT")
        self._title_label.setFont(QFont(theme.typo("font_family_decorative"), 14, QFont.Weight.Bold))
        h_lay.addWidget(self._title_label)
        h_lay.addStretch()

        self._collapse_btn = QPushButton("◀")
        self._collapse_btn.setFixedSize(28, 28)
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.clicked.connect(self.toggle_collapse)
        h_lay.addWidget(self._collapse_btn)

        layout.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # Nav items container
        self._nav_container = QWidget()
        self._nav_layout = QVBoxLayout(self._nav_container)
        self._nav_layout.setContentsMargins(0, 8, 0, 8)
        self._nav_layout.setSpacing(2)
        layout.addWidget(self._nav_container)

        layout.addStretch()

        # Update available button (hidden until an update is found)
        self._update_btn = QPushButton("↑ Update Available")
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.setObjectName("SidebarUpdateBtn")
        self._update_btn.setVisible(False)
        self._update_btn.clicked.connect(self.update_clicked)
        layout.addWidget(self._update_btn)
        layout.addSpacing(4)

        # Version label at bottom
        self._version_label = QLabel()
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._version_label)
        layout.addSpacing(8)

        self._apply_theme()

    def add_nav_item(self, icon_char: str, label: str) -> int:
        index = len(self._items)

        # Insert separator before group breaks
        if index in self._GROUP_BREAKS:
            sep = _SidebarSeparator(self._theme, self)
            self._nav_layout.addWidget(sep)
            self._separators.append(sep)

        shortcut = f"Ctrl+{index + 1}" if index < 9 else ""
        item = SidebarItem(icon_char, label, self._theme,
                           shortcut_hint=shortcut, parent=self)
        item.set_expanded(self._expanded)
        item._update_text()
        item.clicked.connect(lambda checked, idx=index: self._on_item_clicked(idx))
        self._nav_layout.addWidget(item)
        self._items.append(item)
        return index

    def set_active(self, index: int) -> None:
        for i, item in enumerate(self._items):
            item.set_active(i == index)

    def set_version(self, version: str) -> None:
        self._version_label.setText(f"v{version}")

    def show_update_button(self, version: str) -> None:
        """Show the update button with the available version label."""
        if self._expanded:
            self._update_btn.setText(f"↑ v{version} Available")
        else:
            self._update_btn.setText("↑")
        self._update_btn.setVisible(True)

    def hide_update_button(self) -> None:
        self._update_btn.setVisible(False)

    def toggle_collapse(self) -> None:
        self._expanded = not self._expanded
        target_width = self.EXPANDED_WIDTH if self._expanded else self.COLLAPSED_WIDTH

        anim = QPropertyAnimation(self, b"minimumWidth", self)
        anim.setDuration(200)
        anim.setStartValue(self.width())
        anim.setEndValue(target_width)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        anim2 = QPropertyAnimation(self, b"maximumWidth", self)
        anim2.setDuration(200)
        anim2.setStartValue(self.width())
        anim2.setEndValue(target_width)
        anim2.setEasingCurve(QEasingCurve.Type.InOutCubic)

        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        anim2.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        self._collapse_btn.setText("▶" if not self._expanded else "◀")
        self._title_label.setVisible(self._expanded)

        for item in self._items:
            item.set_expanded(self._expanded)

        # Update button text based on expanded state
        if self._update_btn.isVisible():
            cur = self._update_btn.text()
            if self._expanded:
                # Try to restore version from current text
                if cur == "↑":
                    self._update_btn.setText("↑ Update Available")
                # else keep whatever text it already shows (e.g. "↑ v1.2.3 Available")
            else:
                self._update_btn.setText("↑")

    def _on_item_clicked(self, index: int) -> None:
        self.set_active(index)
        self.nav_clicked.emit(index)

    def _apply_theme(self) -> None:
        c = self._theme.theme["colors"]
        accent = c.get("sidebar_active", "#4a7aba")
        self.setStyleSheet(f"""
            #Sidebar {{
                background: {c['sidebar_bg']};
                border-right: 1px solid {c['border']};
            }}
            #SidebarUpdateBtn {{
                background: {accent};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 9pt;
                font-weight: 700;
                padding: 6px 8px;
                margin: 0 12px;
            }}
            #SidebarUpdateBtn:hover {{
                background: {c.get('button_hover', accent)};
            }}
        """)
        self._title_label.setStyleSheet(f"color: {c['sidebar_active']}; background: transparent;")
        self._collapse_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {c['sidebar_text']};
                border: none;
                border-radius: 4px;
                font-size: 10pt;
            }}
            QPushButton:hover {{
                background: {c['sidebar_hover']};
            }}
        """)
        self._version_label.setStyleSheet(f"""
            color: {c['muted']};
            font-size: 8pt;
            background: transparent;
        """)
        sep = self.findChild(QFrame)
        if sep and isinstance(sep, QFrame) and sep.frameShape() == QFrame.Shape.HLine:
            sep.setStyleSheet(f"background: {c['border']};")
        for item in self._items:
            item.apply_theme(self._theme)
        for s in self._separators:
            s.apply_theme(self._theme)

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self._apply_theme()
