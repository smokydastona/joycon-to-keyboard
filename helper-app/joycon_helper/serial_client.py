from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import serial

log = logging.getLogger("joycon_helper.serial")


@dataclass
class SerialLine:
    raw: str
    parsed: Optional[dict[str, Any]]


class SerialClient:
    def __init__(self) -> None:
        self._ser: Optional[serial.Serial] = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connection_lost = threading.Event()
        self.rx: "queue.Queue[SerialLine]" = queue.Queue()

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    @property
    def connection_lost(self) -> bool:
        """True when the RX thread exited due to a read error (cable unplug, etc.)."""
        return self._connection_lost.is_set()

    def connect(self, port: str, baud: int = 115200) -> None:
        self.disconnect()
        self._stop.clear()
        self._connection_lost.clear()
        log.info("Opening serial port %s @ %d", port, baud)
        self._ser = serial.Serial(port=port, baudrate=baud, timeout=0.1)
        self._rx_thread = threading.Thread(target=self._rx_loop, name="serial-rx", daemon=True)
        self._rx_thread.start()
        log.info("Serial RX thread started")

    def disconnect(self) -> None:
        self._stop.set()
        if self._ser is not None:
            log.info("Closing serial port")
            try:
                self._ser.close()
            except Exception:
                log.debug("Error closing serial port", exc_info=True)
        self._ser = None
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=2.0)
            self._rx_thread = None

    def send_obj(self, obj: dict[str, Any]) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected")
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
        if self._ser is None:
            raise RuntimeError("Serial port not open")
        self._ser.write(line.encode("utf-8"))

    def send_text_line(self, text: str) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected")
        if not text.endswith("\n"):
            text += "\n"
        if self._ser is None:
            raise RuntimeError("Serial port not open")
        self._ser.write(text.encode("utf-8"))

    def _rx_loop(self) -> None:
        if self._ser is None:
            return
        buffer = bytearray()
        _MAX_BUFFER = 65536  # 64 KB cap to prevent unbounded growth

        while not self._stop.is_set():
            try:
                chunk = self._ser.read(256)
            except Exception as exc:
                if not self._stop.is_set():
                    log.error("Serial read error: %s", exc, exc_info=True)
                    self._connection_lost.set()
                break

            if chunk:
                buffer.extend(chunk)

                # A3: Cap buffer size to prevent memory exhaustion
                if len(buffer) > _MAX_BUFFER:
                    log.warning("Serial RX buffer exceeded %d bytes — resetting", _MAX_BUFFER)
                    buffer.clear()
                    continue

                while True:
                    nl = buffer.find(b"\n")
                    if nl < 0:
                        break
                    raw_line = buffer[:nl + 1]
                    del buffer[:nl + 1]

                    raw = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    parsed = None
                    if raw.startswith("{") and raw.endswith("}"):
                        try:
                            parsed = json.loads(raw)
                        except Exception:
                            log.debug("JSON parse failed for line: %s", raw[:200])
                            parsed = None
                    self.rx.put(SerialLine(raw=raw, parsed=parsed))
            else:
                time.sleep(0.01)

        log.info("Serial RX thread exiting")
