from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..constants import KEYMAP_HOTSPOTS

if TYPE_CHECKING:
    from ..main_window import MainWindow
    from ..theme import ThemeEngine


_BASE_KEY_LABELS: dict[int, str] = {
    1: "Forward",
    2: "Back",
    3: "Left",
    4: "Right",
    5: "Jump",
    6: "Sprint",
    7: "Crouch",
    8: "A",
    9: "B",
    10: "X",
    11: "Y",
    12: "L",
    13: "R",
    14: "ZL",
    15: "ZR",
    16: "Plus",
    17: "Minus",
    18: "Home",
    19: "Capture",
    20: "LStick",
    21: "RStick",
    22: "RStick Up",
    23: "RStick Down",
    24: "RStick Left",
    25: "RStick Right",
    26: "Shake",
    27: "Tilt Up",
    28: "Tilt Down",
    29: "Tilt Left",
    30: "Tilt Right",
    31: "Flick",
    32: "SL(L)",
    33: "SR(L)",
    34: "SL(R)",
    35: "SR(R)",
}

_BASE_KEY_TO_HOTSPOT: dict[int, str] = {
    1: "LSUp",
    2: "LSDown",
    3: "LSLeft",
    4: "LSRight",
    8: "A",
    9: "B",
    10: "X",
    11: "Y",
    12: "L",
    13: "R",
    14: "ZL",
    15: "ZR",
    16: "Plus",
    17: "Minus",
    18: "Home",
    19: "Capture",
    20: "LStick",
    21: "RStick",
    22: "RSUp",
    23: "RSDown",
    24: "RSLeft",
    25: "RSRight",
    26: "Shake",
    27: "TiltUp",
    28: "TiltDn",
    29: "TiltL",
    30: "TiltR",
    31: "Flick",
    32: "SL(L)",
    33: "SR(L)",
    34: "SL(R)",
    35: "SR(R)",
}


def label_for_key_id(key_id: int) -> str:
    base_key_id = key_id % 128
    return _BASE_KEY_LABELS.get(base_key_id, f"key_{key_id}")


def hotspot_for_key_id(key_id: int) -> str | None:
    base_key_id = key_id % 128
    return _BASE_KEY_TO_HOTSPOT.get(base_key_id)


def describe_rssi(rssi: int | None) -> str:
    if rssi is None:
        return "—"
    if rssi >= -55:
        quality = "Excellent"
    elif rssi >= -67:
        quality = "Strong"
    elif rssi >= -75:
        quality = "Fair"
    else:
        quality = "Weak"
    return f"{rssi} dBm ({quality})"


@dataclass
class _VisualizerState:
    left_connected: bool = False
    right_connected: bool = False
    bt_state: str = "Idle"
    active_layers: set[str] = field(default_factory=set)
    last_macro: str = "—"
    controller_name: str = "Awaiting controller"


class LiveInputVisualizerWidget(QWidget):
    def __init__(self, main: MainWindow, *, compact: bool = False) -> None:
        super().__init__()
        self._main = main
        self._compact = compact
        self._state = _VisualizerState()
        self._active_key_ids: set[int] = set()
        self._battery_levels: dict[int, int] = {}
        self._rssi_levels: dict[int, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(220 if compact else 280)
        layout.addWidget(self._image_label)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._active_label = QLabel("Active controls: —")
        self._active_label.setWordWrap(True)
        layout.addWidget(self._active_label)

        self._render()

    def connection_changed(self, connected: bool) -> None:
        if connected:
            return
        self._active_key_ids.clear()
        self._battery_levels.clear()
        self._rssi_levels.clear()
        self._state = _VisualizerState(bt_state="Disconnected")
        self._render()

    def apply_theme(self, theme: ThemeEngine) -> None:
        self._status_label.setStyleSheet(f"color: {theme.color('text_secondary')};")
        self._render()

    def handle_device_event(self, obj: dict) -> None:
        evt = obj.get("evt") or obj.get("event")
        if evt == "mapped_key":
            key_id = obj.get("key_id")
            pressed = self._derive_pressed(obj)
            if isinstance(key_id, int) and pressed is not None:
                if pressed:
                    self._active_key_ids.add(key_id)
                else:
                    self._active_key_ids.discard(key_id)
        elif evt == "layer":
            layer_name = str(obj.get("name") or "Unnamed")
            if bool(obj.get("active")):
                self._state.active_layers.add(layer_name)
            else:
                self._state.active_layers.discard(layer_name)
        elif evt == "macro":
            macro_id = str(obj.get("id") or "?")
            macro_state = str(obj.get("state") or "?")
            self._state.last_macro = f"{macro_id} ({macro_state})"
        elif evt == "battery":
            device_id = obj.get("device_id")
            level = obj.get("level")
            if isinstance(device_id, int) and isinstance(level, int):
                self._battery_levels[device_id] = level
        elif evt == "rssi":
            device_id = obj.get("device_id")
            rssi = obj.get("rssi")
            if isinstance(device_id, int) and isinstance(rssi, int):
                self._rssi_levels[device_id] = rssi
        elif evt == "bt_status":
            self._state.bt_state = str(obj.get("state") or "Idle").capitalize()
            self._state.left_connected = bool(getattr(self._main, "_bt_connected_left", False))
            self._state.right_connected = bool(getattr(self._main, "_bt_connected_right", False))
            name = obj.get("name")
            if isinstance(name, str) and name.strip():
                self._state.controller_name = name.strip()
        elif evt == "controller_info":
            type_name = str(obj.get("type") or "unknown")
            serial = str(obj.get("serial") or "").strip()
            pretty_name = {
                "joycon_l": "Joy-Con (L)",
                "joycon_r": "Joy-Con (R)",
                "pro": "Pro Controller",
            }.get(type_name, type_name)
            self._state.controller_name = pretty_name if not serial else f"{pretty_name} • {serial}"
        self._render()

    @staticmethod
    def _derive_pressed(obj: dict) -> bool | None:
        if isinstance(obj.get("pressed"), bool):
            return bool(obj["pressed"])
        action = obj.get("action")
        if action == "press":
            return True
        if action == "release":
            return False
        return None

    def _render(self) -> None:
        target = QSize(700 if not self._compact else 540, 340 if not self._compact else 250)
        base = self._main.assets.load_pixmap(self._device_image_name(), target)
        if base is None:
            self._image_label.setText("(visualizer image unavailable)")
        else:
            self._image_label.setPixmap(self._paint_visual_state(base))

        layers = ", ".join(sorted(self._state.active_layers)) if self._state.active_layers else "—"
        self._status_label.setText(
            f"State: {self._state.bt_state} | Controller: {self._state.controller_name} | Layers: {layers} | "
            f"Macro: {self._state.last_macro}\n"
            f"Left battery: {self._battery_text(self._battery_levels.get(0))} | "
            f"Right battery: {self._battery_text(self._battery_levels.get(1))}\n"
            f"Left RSSI: {describe_rssi(self._rssi_levels.get(0))} | "
            f"Right RSSI: {describe_rssi(self._rssi_levels.get(1))}"
        )
        active_labels = sorted(label_for_key_id(key_id) for key_id in self._active_key_ids)
        self._active_label.setText(
            "Active controls: " + (", ".join(active_labels) if active_labels else "—")
        )

    @staticmethod
    def _battery_text(level: int | None) -> str:
        if level is None:
            return "—"
        clamped = max(0, min(level, 4))
        return f"{'█' * clamped}{'░' * (4 - clamped)} ({clamped}/4)"

    def _device_image_name(self) -> str:
        if self._state.left_connected and self._state.right_connected:
            return "joycons_both.png"
        if self._state.left_connected:
            return "joycons_left.png"
        if self._state.right_connected:
            return "joycons_right.png"
        return "joycons_none.png"

    def _paint_visual_state(self, base: QPixmap) -> QPixmap:
        pixmap = base.copy()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        theme_key = "dark" if self._main.theme.is_dark else "default"
        hotspots = {name: (nx, ny) for name, nx, ny in KEYMAP_HOTSPOTS[theme_key]}
        accent = QColor(self._main.theme.color("accent"))
        accent_fill = QColor(accent)
        accent_fill.setAlpha(110)

        for key_id in sorted(self._active_key_ids):
            hotspot_name = hotspot_for_key_id(key_id)
            if not hotspot_name or hotspot_name not in hotspots:
                continue
            nx, ny = hotspots[hotspot_name]
            x = int(nx * pixmap.width())
            y = int(ny * pixmap.height())
            painter.setPen(QPen(accent, 3))
            painter.setBrush(accent_fill)
            painter.drawEllipse(x - 18, y - 18, 36, 36)

        info_fill = QColor(7, 17, 31, 185)
        painter.fillRect(12, 12, 190, 58, info_fill)
        painter.setPen(QPen(QColor(self._main.theme.color("text")), 1))
        painter.setFont(QFont(self._main.theme.typo("font_family_decorative"), 10, QFont.Weight.Bold))
        painter.drawText(20, 34, f"BT: {self._state.bt_state}")
        painter.drawText(20, 54, f"Live keys: {len(self._active_key_ids)}")
        painter.end()
        return pixmap
