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
        self.rx: "queue.Queue[SerialLine]" = queue.Queue()

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def connect(self, port: str, baud: int = 115200) -> None:
        self.disconnect()
        self._stop.clear()
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
        assert self._ser is not None
        self._ser.write(line.encode("utf-8"))

    def send_text_line(self, text: str) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected")
        if not text.endswith("\n"):
            text += "\n"
        assert self._ser is not None
        self._ser.write(text.encode("utf-8"))

    def _rx_loop(self) -> None:
        assert self._ser is not None
        buffer = bytearray()

        while not self._stop.is_set():
            try:
                chunk = self._ser.read(256)
            except Exception as exc:
                if not self._stop.is_set():
                    log.error("Serial read error: %s", exc, exc_info=True)
                break

            if chunk:
                buffer.extend(chunk)

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
