"""Sidebar navigation widget.

A vertical left rail with icon + label nav items, collapsible between
wide (200 px) and narrow (56 px) modes.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..theme import ThemeEngine


class SidebarItem(QPushButton):
    """A single nav item in the sidebar."""

    def __init__(self, icon_char: str, label: str, theme: ThemeEngine,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon_char = icon_char
        self._label_text = label
        self._theme = theme
        self._active = False
        self._expanded = True

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedHeight(48)
        self._update_style()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._update_text()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setChecked(active)
        self._update_style()

    def _update_text(self) -> None:
        if self._expanded:
            self.setText(f"  {self._icon_char}   {self._label_text}")
            self.setToolTip("")
        else:
            self.setText(f"  {self._icon_char}")
            self.setToolTip(self._label_text)

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
        self._update_style()
        self._update_text()


class SidebarWidget(QFrame):
    """Collapsible sidebar navigation rail."""

    EXPANDED_WIDTH = 220
    COLLAPSED_WIDTH = 56

    nav_clicked = pyqtSignal(int)

    def __init__(self, theme: ThemeEngine, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._expanded = True
        self._items: List[SidebarItem] = []

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

        # Version label at bottom
        self._version_label = QLabel()
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._version_label)
        layout.addSpacing(8)

        self._apply_theme()

    def add_nav_item(self, icon_char: str, label: str) -> int:
        index = len(self._items)
        item = SidebarItem(icon_char, label, self._theme, self)
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

    def _on_item_clicked(self, index: int) -> None:
        self.set_active(index)
        self.nav_clicked.emit(index)

    def _apply_theme(self) -> None:
        c = self._theme.theme["colors"]
        self.setStyleSheet(f"""
            #Sidebar {{
                background: {c['sidebar_bg']};
                border-right: 1px solid {c['border']};
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

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._theme = theme
        self._apply_theme()
