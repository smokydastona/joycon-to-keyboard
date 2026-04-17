from __future__ import annotations

import queue
import time

import pytest

from joycon_helper.fw_updater import BOARD_ESP32, BOARD_S3, FirmwareFlasher
from joycon_helper.serial_client import SerialHistoryEntry, SerialLine


class FakeSerialClient:
    def __init__(self) -> None:
        self.rx: queue.Queue[SerialLine] = queue.Queue()
        self.sent: list[dict[str, object]] = []
        self.connection_lost = False
        self._history: list[SerialHistoryEntry] = []
        self.fail_data_ack = False
        self.skip_end_response = False
        self.version_responses: list[str] = []

    def send_obj(self, obj: dict[str, object]) -> None:
        self.sent.append(obj)
        self._history.append(
            SerialHistoryEntry(
                timestamp=time.time(),
                direction="tx",
                raw=str(obj),
                parsed=None,
            )
        )

        cmd = obj["cmd"]
        if cmd == "fw_update_begin":
            self._push_response({"rsp": "fw_update_begin", "ok": True})
        elif cmd == "fw_update_data":
            if not self.fail_data_ack:
                self._push_response({"rsp": "fw_update_data", "ok": True, "written": 4})
        elif cmd == "fw_update_end":
            if not self.skip_end_response:
                self._push_response({"rsp": "fw_update_end", "ok": True})
        elif cmd == "fw_version" and self.version_responses:
            board = obj.get("board", BOARD_S3)
            self._push_response(
                {
                    "rsp": "fw_version",
                    "ok": True,
                    "board": board,
                    "version": self.version_responses.pop(0),
                }
            )

    def drain_rx_queue(self, *, limit: int | None = None) -> list[SerialLine]:
        drained: list[SerialLine] = []
        max_items = limit if limit is not None else 999
        while len(drained) < max_items:
            try:
                drained.append(self.rx.get_nowait())
            except queue.Empty:
                break
        return drained

    def snapshot_history(self, *, limit: int = 50) -> list[SerialHistoryEntry]:
        return self._history[-limit:]

    def _push_response(self, payload: dict[str, object]) -> None:
        raw = str(payload)
        self._history.append(
            SerialHistoryEntry(
                timestamp=time.time(),
                direction="rx",
                raw=raw,
                parsed=payload,
            )
        )
        self.rx.put_nowait(SerialLine(raw=raw, parsed=payload))


def test_flash_does_not_retry_data_chunk_when_ack_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("joycon_helper.fw_updater._CMD_TIMEOUT", 0.01)
    monkeypatch.setattr("joycon_helper.fw_updater.logs_dir", lambda: tmp_path)

    fake = FakeSerialClient()
    fake.fail_data_ack = True
    flasher = FirmwareFlasher(fake)

    with pytest.raises(RuntimeError, match="not idempotent"):
        flasher.flash(BOARD_S3, b"test")

    data_cmds = [cmd for cmd in fake.sent if cmd["cmd"] == "fw_update_data"]
    abort_cmds = [cmd for cmd in fake.sent if cmd["cmd"] == "fw_update_abort"]

    assert len(data_cmds) == 1
    assert len(abort_cmds) == 1
    assert list(tmp_path.glob("ota_failure_*.json"))


def test_flash_can_verify_success_after_missing_end_response(monkeypatch, tmp_path):
    monkeypatch.setattr("joycon_helper.fw_updater._CMD_TIMEOUT", 0.01)
    monkeypatch.setattr("joycon_helper.fw_updater._END_TIMEOUT", 0.01)
    monkeypatch.setattr("joycon_helper.fw_updater._VERIFY_RETRIES", 2)
    monkeypatch.setattr("joycon_helper.fw_updater._VERIFY_DELAY", 0)
    monkeypatch.setattr("joycon_helper.fw_updater.logs_dir", lambda: tmp_path)

    fake = FakeSerialClient()
    fake.skip_end_response = True
    fake.version_responses = ["0.1.290"]
    flasher = FirmwareFlasher(fake)

    flasher.flash(BOARD_S3, b"test", expected_version="0.1.290")

    end_cmds = [cmd for cmd in fake.sent if cmd["cmd"] == "fw_update_end"]
    version_cmds = [cmd for cmd in fake.sent if cmd["cmd"] == "fw_version"]

    assert len(end_cmds) == 1
    assert len(version_cmds) >= 1
    assert not list(tmp_path.glob("ota_failure_*.json"))


def test_flash_esp32_uses_smaller_relay_chunks(monkeypatch, tmp_path):
    monkeypatch.setattr("joycon_helper.fw_updater.ESP32_RELAY_INTER_CHUNK_DELAY_S", 0)
    monkeypatch.setattr("joycon_helper.fw_updater.logs_dir", lambda: tmp_path)

    fake = FakeSerialClient()
    flasher = FirmwareFlasher(fake)

    # 2050 bytes should split into 3 fw_update_data commands when using
    # 1024-byte relay chunks.
    flasher.flash(BOARD_ESP32, b"x" * 2050)

    data_cmds = [cmd for cmd in fake.sent if cmd["cmd"] == "fw_update_data"]
    assert len(data_cmds) == 3
    assert all(cmd.get("board") == BOARD_ESP32 for cmd in data_cmds)
