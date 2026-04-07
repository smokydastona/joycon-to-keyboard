"""Qt signal bridge for :class:`SerialClient`.

Wraps the threading-based ``SerialClient`` so that UI code can connect to
Qt signals instead of polling a queue.  A ``QTimer`` drains the RX queue
and emits typed signals on the main thread.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..serial_client import SerialClient

log = logging.getLogger("joycon_helper.ui.serial_bridge")


class SerialBridge(QObject):
    """Bridges :class:`SerialClient` to Qt signals."""

    # Signals
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    raw_line = pyqtSignal(str)
    device_event = pyqtSignal(dict)
    connection_error = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.client = SerialClient()
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(16)
        self._drain_timer.timeout.connect(self._drain_rx)

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    def connect_serial(self, port: str, baud: int = 115200) -> None:
        try:
            self.client.connect(port, baud)
            self._drain_timer.start()
            self.connected.emit()
            log.info("Serial connected: %s @ %d", port, baud)
        except Exception as exc:
            log.error("Serial connect failed: %s", exc)
            self.connection_error.emit(str(exc))

    def disconnect_serial(self) -> None:
        self._drain_timer.stop()
        self.client.disconnect()
        self.disconnected.emit()
        log.info("Serial disconnected")

    def send_cmd(self, obj: Dict[str, Any]) -> None:
        if not self.is_connected:
            log.warning("send_cmd called while disconnected")
            return
        try:
            self.client.send_obj(obj)
        except Exception as exc:
            log.error("send_cmd failed: %s", exc)

    def send_text(self, text: str) -> None:
        if not self.is_connected:
            return
        try:
            self.client.send_text_line(text)
        except Exception as exc:
            log.error("send_text failed: %s", exc)

    def _drain_rx(self) -> None:
        while True:
            try:
                item = self.client.rx.get_nowait()
            except Exception:
                break
            self.raw_line.emit(item.raw)
            if item.parsed is not None:
                self.device_event.emit(item.parsed)

        if self.client.connection_lost:
            log.warning("Connection lost detected — disconnecting")
            self.disconnect_serial()
