"""Add Device dialog — scan for Bluetooth (via ESP32) and USB HID devices.

Two tabs:
  * **Via ESP32 Bluetooth** — sends ``bt_set_target`` + ``bt_connect`` and shows
    a live status progression as the ESP32 discovers and connects to a device.
  * **Via PC USB (HID)** — scans hidapi for supported devices (M913, Razer) and lists common HID classes (keyboards/mice/gamepads/joysticks).

On a successful connection the dialog emits :pyqt:`device_added` with the
:class:`~joycon_helper.device_cache.DeviceEntry` that was added to the cache.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...device_cache import DeviceCache, DeviceEntry

if TYPE_CHECKING:
    from ..main_window import MainWindow

log = logging.getLogger("joycon_helper.ui.widgets.add_device_dialog")

# ---------------------------------------------------------------------------
# Small background worker for USB HID scanning
# ---------------------------------------------------------------------------

class _HidScanWorker(QObject):
    finished = pyqtSignal(list)   # list of dicts: {type, name, vid, pid, serial, kind?, usage_page?, usage?, interface?}
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            import hid as _hid  # type: ignore[import-untyped]
        except Exception as exc:
            log.warning("USB HID scan unavailable (hidapi import failed): %s", exc)
            self.error.emit(
                "USB HID scanning requires hidapi. Install deps from helper-app/requirements.txt"
            )
            return

        results: list[dict[str, Any]] = []

        # Scan for M913
        try:
            from ... import m913_device as m
            for d in m.M913Device.enumerate():
                results.append({
                    "type": "m913",
                    "kind": "mouse",
                    "name": d.display_name,
                    "vid": getattr(d, "vendor_id", 0),
                    "pid": getattr(d, "product_id", 0),
                    "serial": getattr(d, "serial_number", ""),
                })
        except Exception as exc:
            log.debug("M913 scan skipped: %s", exc)

        # Scan for Razer
        try:
            from ... import razer_device as r
            for d in r.RazerDevice.enumerate():
                results.append({
                    "type": "razer",
                    "kind": "mouse",
                    "name": d.display_name,
                    "vid": getattr(d, "vendor_id", 0),
                    "pid": getattr(d, "product_id", 0),
                    "serial": getattr(d, "serial_number", ""),
                })
        except Exception as exc:
            log.debug("Razer scan skipped: %s", exc)

        # Generic HID scan (keyboards/mice/gamepads/joysticks).
        # We only list common Generic Desktop usages to avoid flooding the list.
        kind_by_usage: dict[tuple[int, int], str] = {
            (0x01, 0x06): "keyboard",
            (0x01, 0x02): "mouse",
            (0x01, 0x05): "gamepad",
            (0x01, 0x04): "joystick",
            (0x01, 0x08): "multiaxis",
        }
        seen: set[tuple[int, int, str, int, int]] = set()  # vid,pid,serial,usage_page,usage
        try:
            for info in _hid.enumerate(0, 0):
                vid = int(info.get("vendor_id") or 0)
                pid = int(info.get("product_id") or 0)
                serial = str(info.get("serial_number") or "")
                usage_page = int(info.get("usage_page") or 0)
                usage = int(info.get("usage") or 0)

                kind = kind_by_usage.get((usage_page, usage))
                if not kind:
                    continue

                key = (vid, pid, serial, usage_page, usage)
                if key in seen:
                    continue
                seen.add(key)

                product = str(info.get("product_string") or "").strip()
                manufacturer = str(info.get("manufacturer_string") or "").strip()
                display = product or "HID Device"
                if manufacturer and product and manufacturer.lower() not in product.lower():
                    display = f"{manufacturer} {product}".strip()

                results.append({
                    "type": "hid",
                    "kind": kind,
                    "name": display,
                    "vid": vid,
                    "pid": pid,
                    "serial": serial,
                    "usage_page": usage_page,
                    "usage": usage,
                    "interface": int(info.get("interface_number") or 0),
                })
        except Exception as exc:
            log.debug("Generic HID scan skipped: %s", exc)

        self.finished.emit(results)


# ---------------------------------------------------------------------------
# AddDeviceDialog
# ---------------------------------------------------------------------------

# BT scan phases (in order)
_BT_PHASES = ["idle", "discovering", "found", "connecting", "connected", "error"]
_BT_PHASE_LABELS = {
    "idle":        ("—", ""),
    "discovering": ("📡  Scanning for devices…", "#88aaff"),
    "found":       ("🔍  Device detected, auto-connecting…", "#ffdd55"),
    "connecting":  ("🔗  Connecting…", "#ffaa33"),
    "connected":   ("✓  Connected!", "#44dd88"),
    "error":       ("✗  Scan timed out — no device found.", "#ff5555"),
}

_BT_SCAN_TIMEOUT_MS = 20_000   # 20 s before we show a timeout error


class AddDeviceDialog(QDialog):
    """Two-tab dialog: connect via ESP32 BT or directly via PC USB."""

    device_added = pyqtSignal(object)   # DeviceEntry

    def __init__(self, main: MainWindow, cache: DeviceCache) -> None:
        super().__init__(main)
        self._main = main
        self._cache = cache

        self.setWindowTitle("Add a Device")
        self.setMinimumSize(520, 460)
        self.setModal(True)

        self._bt_phase = "idle"
        self._bt_found_devices: list[dict[str, str]] = []   # {name, bda}
        self._bt_listed_bdas: set[str] = set()
        self._bt_connected_entry: DeviceEntry | None = None

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(_BT_SCAN_TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._bt_on_timeout)

        self._hid_thread: QThread | None = None
        self._hid_found: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_bt_tab(), "🎮  Via ESP32 Bluetooth")
        self._tabs.addTab(self._build_usb_tab(), "🖱  Via PC USB (HID)")
        root.addWidget(self._tabs)

        # Close button only — we close programmatically on success
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self._on_close)
        root.addWidget(close_box)

    # ------------------------------------------------------------------
    # Build: BT tab
    # ------------------------------------------------------------------

    def _build_bt_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setSpacing(12)
        lay.setContentsMargins(12, 12, 12, 12)

        desc = QLabel(
            "Start a scan on the ESP32 Bluetooth host.  The ESP32 will look for "
            "any device whose name contains the filter text and auto-connect to "
            "the first one it finds."
        )
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # Name filter
        filter_group = QGroupBox("Device name filter")
        filter_lay = QHBoxLayout(filter_group)
        filter_lay.addWidget(QLabel("Name contains:"))
        self._bt_filter_edit = QLineEdit("Joy-Con")
        self._bt_filter_edit.setPlaceholderText("e.g. Joy-Con")
        self._bt_filter_edit.setToolTip(
            "The ESP32 will connect to the first device whose BT name contains this text.")
        filter_lay.addWidget(self._bt_filter_edit, 1)

        # Dual-controller option
        self._bt_dual_radio_group = QButtonGroup(self)
        single_rb = QRadioButton("Single")
        single_rb.setChecked(True)
        single_rb.setToolTip("Connect one Joy-Con")
        self._bt_dual_radio_group.addButton(single_rb, 0)
        filter_lay.addWidget(single_rb)
        dual_rb = QRadioButton("Dual (L + R)")
        dual_rb.setToolTip("Connect both Joy-Con halves simultaneously")
        self._bt_dual_radio_group.addButton(dual_rb, 1)
        filter_lay.addWidget(dual_rb)

        self._bt_scan_btn = QPushButton("🔍  Scan")
        self._bt_scan_btn.setProperty("accent", True)
        self._bt_scan_btn.setFixedWidth(100)
        self._bt_scan_btn.clicked.connect(self._bt_start_scan)
        filter_lay.addWidget(self._bt_scan_btn)
        lay.addWidget(filter_group)

        # Status area
        status_group = QGroupBox("Status")
        status_lay = QVBoxLayout(status_group)
        self._bt_status_label = QLabel("—")
        self._bt_status_label.setFont(QFont("", 11, QFont.Weight.Bold))
        status_lay.addWidget(self._bt_status_label)
        lay.addWidget(status_group)

        # Discovered devices list
        found_group = QGroupBox("Devices found during scan")
        found_lay = QVBoxLayout(found_group)
        self._bt_found_list = QListWidget()
        self._bt_found_list.setMaximumHeight(130)
        found_lay.addWidget(self._bt_found_list)
        lay.addWidget(found_group)

        lay.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Build: USB tab
    # ------------------------------------------------------------------

    def _build_usb_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setSpacing(12)
        lay.setContentsMargins(12, 12, 12, 12)

        desc = QLabel(
            "Scan for USB HID devices plugged into <b>this PC</b>.  "
            "Shows common device types (keyboards, mice, gamepads, joysticks), plus supported devices like M913 and Razer."
        )
        desc.setWordWrap(True)
        lay.addWidget(desc)

        scan_row = QHBoxLayout()
        self._usb_scan_btn = QPushButton("🔍  Scan for USB Devices")
        self._usb_scan_btn.setProperty("accent", True)
        self._usb_scan_btn.clicked.connect(self._usb_start_scan)
        scan_row.addWidget(self._usb_scan_btn)
        self._usb_status_label = QLabel("")
        scan_row.addWidget(self._usb_status_label, 1)
        lay.addLayout(scan_row)

        found_group = QGroupBox("Found devices")
        found_lay = QVBoxLayout(found_group)
        self._usb_found_list = QListWidget()
        self._usb_found_list.setMinimumHeight(140)
        found_lay.addWidget(self._usb_found_list)

        add_row = QHBoxLayout()
        self._usb_add_btn = QPushButton("＋  Add Selected Device")
        self._usb_add_btn.setProperty("accent", True)
        self._usb_add_btn.setEnabled(False)
        self._usb_add_btn.clicked.connect(self._usb_add_selected)
        add_row.addWidget(self._usb_add_btn)
        add_row.addStretch()
        found_lay.addLayout(add_row)
        lay.addWidget(found_group)

        self._usb_found_list.itemSelectionChanged.connect(
            lambda: self._usb_add_btn.setEnabled(
                len(self._usb_found_list.selectedItems()) > 0
            )
        )

        lay.addStretch()
        return tab

    # ------------------------------------------------------------------
    # BT scan logic
    # ------------------------------------------------------------------

    def _bt_start_scan(self) -> None:
        if not self._main.bridge.is_connected:
            QMessageBox.warning(
                self, "Not Connected",
                "Connect to the ESP32-S3 serial port first."
            )
            return

        name_substr = self._bt_filter_edit.text().strip()
        if not name_substr:
            QMessageBox.warning(self, "Empty Filter", "Enter a device name filter.")
            return

        # Reset state
        self._bt_phase = "idle"
        self._bt_found_devices.clear()
        self._bt_listed_bdas.clear()
        self._bt_found_list.clear()
        self._bt_connected_entry = None
        self._bt_scan_btn.setEnabled(False)

        # Send bt_set_target, then bt_connect
        both = self._bt_dual_radio_group.checkedId() == 1
        self._main.send_cmd({"cmd": "bt_set_target", "name_substr": name_substr})
        cmd: dict[str, Any] = {"cmd": "bt_connect"}
        if both:
            cmd["both"] = True
        self._main.send_cmd(cmd)

        self._bt_set_phase("discovering")
        self._timeout_timer.start()

    def _bt_set_phase(self, phase: str, detail: str = "") -> None:
        self._bt_phase = phase
        text, color = _BT_PHASE_LABELS.get(phase, ("?", ""))
        if detail:
            text = f"{text}  ({detail})"
        self._bt_status_label.setText(text)
        if color:
            self._bt_status_label.setStyleSheet(f"color: {color};")
        else:
            self._bt_status_label.setStyleSheet("")

    def handle_bt_status(self, obj: dict) -> None:
        """Called by the parent window when a ``bt_status`` event arrives."""
        state = str(obj.get("state", ""))
        name: str | None = obj.get("name")
        bda: str = obj.get("bda") or ""

        if state == "discovering":
            self._bt_set_phase("discovering")

        elif state == "seen":
            # Discovered device that does not match the filter.
            # We list it for visibility but do not reset the timeout.
            if bda and bda in self._bt_listed_bdas:
                return
            if bda:
                self._bt_listed_bdas.add(bda)
            info = {"name": name or "Unknown", "bda": bda}
            self._bt_found_devices.append(info)
            item = QListWidgetItem(f"👀  {info['name']}   [{bda}]")
            self._bt_found_list.addItem(item)

        elif state == "found":
            # Filter matched; the ESP32 will attempt to connect.
            if bda and bda in self._bt_listed_bdas:
                return
            if bda:
                self._bt_listed_bdas.add(bda)

            self._timeout_timer.start()   # reset timeout
            info = {"name": name or "Unknown", "bda": bda}
            self._bt_found_devices.append(info)
            item = QListWidgetItem(f"🎮  {info['name']}   [{bda}]")
            self._bt_found_list.addItem(item)
            self._bt_set_phase("found", name or "")

        elif state == "connecting":
            self._bt_set_phase("connecting", bda)

        elif state == "reconnecting":
            self._bt_set_phase("connecting", name or bda)

        elif state == "connected":
            self._timeout_timer.stop()
            # Determine device name from BDA lookup table maintained by main_window
            resolved_name = self._main._bda_name_map.get(bda, "")
            if not resolved_name and name:
                resolved_name = name

            entry = self._bt_make_entry(resolved_name, bda)
            self._cache.add_or_update(entry)
            self._bt_set_phase("connected", resolved_name or bda)
            self._bt_scan_btn.setEnabled(True)
            self.device_added.emit(entry)

        elif state == "disconnected" and self._bt_phase not in ("connected",):
                self._bt_on_timeout()

    def _bt_make_entry(self, name: str, bda: str) -> DeviceEntry:
        """Build a DeviceEntry from the bt_status connected event."""
        side = "R" if "(R)" in name else "L"
        device_id = DeviceCache.make_joycon_id(side)
        return DeviceEntry(
            id=device_id,
            type="joycon",
            source="esp32-bt",
            name=name or f"Joy-Con ({side})",
            bda=bda,
        )

    def _bt_on_timeout(self) -> None:
        self._timeout_timer.stop()
        self._bt_set_phase("error")
        self._bt_scan_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # USB HID scan logic
    # ------------------------------------------------------------------

    def _usb_start_scan(self) -> None:
        if self._hid_thread and self._hid_thread.isRunning():
            return

        self._usb_found_list.clear()
        self._hid_found.clear()
        self._usb_scan_btn.setEnabled(False)
        self._usb_status_label.setText("Scanning…")
        self._usb_add_btn.setEnabled(False)

        self._hid_thread = QThread(self)
        worker = _HidScanWorker()
        worker.moveToThread(self._hid_thread)

        def _done(results: list[dict]) -> None:
            self._hid_found = results
            self._usb_found_list.clear()

            def _icon_for(dev: dict) -> str:
                dtype = str(dev.get("type", ""))
                if dtype == "m913":
                    return "🖱"
                if dtype == "razer":
                    return "🐍"
                if dtype == "hid":
                    kind = str(dev.get("kind", ""))
                    if kind == "keyboard":
                        return "⌨"
                    if kind == "mouse":
                        return "🖱"
                    if kind == "gamepad":
                        return "🎮"
                    if kind in ("joystick", "multiaxis"):
                        return "🕹"
                    return "🔌"
                return "📦"

            if results:
                for dev in results:
                    vid = int(dev.get("vid") or 0)
                    pid = int(dev.get("pid") or 0)
                    suffix = f"  [VID:{vid:04X} PID:{pid:04X}]" if vid else ""
                    item = QListWidgetItem(f"{_icon_for(dev)}  {dev.get('name','')}" + suffix)
                    item.setData(0x0100, dev)   # Qt.UserRole = 0x0100
                    self._usb_found_list.addItem(item)
                self._usb_status_label.setText(f"Found {len(results)} device(s).")
            else:
                self._usb_status_label.setText("No compatible USB HID devices found.")

            self._usb_scan_btn.setEnabled(True)
            self._hid_thread.quit()

        def _fail(msg: str) -> None:
            self._usb_status_label.setText(f"Error: {msg}")
            self._usb_scan_btn.setEnabled(True)
            self._hid_thread.quit()

        worker.finished.connect(_done)
        worker.error.connect(_fail)
        self._hid_thread.started.connect(worker.run)
        self._hid_thread.start()

    def _usb_add_selected(self) -> None:
        items = self._usb_found_list.selectedItems()
        if not items:
            return
        dev: dict = items[0].data(0x0100)
        if not dev:
            return

        device_id = DeviceCache.make_hid_id(dev["type"], dev["vid"], dev["pid"])
        meta: dict[str, Any] = {}
        if dev.get("type") == "hid":
            meta = {
                "kind": dev.get("kind", ""),
                "usage_page": dev.get("usage_page", 0),
                "usage": dev.get("usage", 0),
                "interface": dev.get("interface", 0),
            }

        entry = DeviceEntry(
            id=device_id,
            type=dev["type"],
            source="pc-hid",
            name=dev["name"],
            hid_vendor=dev["vid"],
            hid_product=dev["pid"],
            hid_serial=dev.get("serial", ""),
            meta=meta,
        )
        self._cache.add_or_update(entry)
        entry.connected = True
        self.device_added.emit(entry)
        self._usb_status_label.setText(
            f"✓  {dev['name']} added."
        )
        self._usb_add_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        self._timeout_timer.stop()
        self.reject()

    def closeEvent(self, event: Any) -> None:  # type: ignore[override]
        self._timeout_timer.stop()
        super().closeEvent(event)
