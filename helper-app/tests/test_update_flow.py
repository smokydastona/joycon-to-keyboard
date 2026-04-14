from __future__ import annotations

import threading
from types import SimpleNamespace

from PyQt6.QtWidgets import QMessageBox

from joycon_helper.ui.main_window import MainWindow


class _FakeWindow:
    def __init__(self, *, connected: bool) -> None:
        self.bridge = SimpleNamespace(is_connected=connected)

    def _ensure_view(self, *_args) -> None:
        return None

    def _nav_to(self, *_args) -> None:
        return None


def test_pending_firmware_is_kept_when_user_skips_prompt(monkeypatch, tmp_path) -> None:
    pending_path = tmp_path / "esp32s3-usb-kbd.bin"
    pending_path.write_bytes(b"firmware")
    pending = {pending_path.name: pending_path}
    clear_calls: list[str] = []

    monkeypatch.setattr("joycon_helper.updater.load_pending_firmware", lambda: pending)
    monkeypatch.setattr("joycon_helper.updater.remove_pending_firmware", lambda name: clear_calls.append(name))
    monkeypatch.setattr(
        "joycon_helper.ui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    MainWindow._check_pending_firmware(_FakeWindow(connected=True))

    assert clear_calls == []
    assert pending_path.exists()


def test_pending_firmware_is_kept_when_bridge_not_connected(monkeypatch, tmp_path) -> None:
    pending_path = tmp_path / "esp32s3-usb-kbd.bin"
    pending_path.write_bytes(b"firmware")
    pending = {pending_path.name: pending_path}
    remove_calls: list[str] = []
    warnings: list[str] = []

    monkeypatch.setattr("joycon_helper.updater.load_pending_firmware", lambda: pending)
    monkeypatch.setattr("joycon_helper.updater.remove_pending_firmware", lambda name: remove_calls.append(name))
    monkeypatch.setattr(
        "joycon_helper.ui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "joycon_helper.ui.main_window.Toast.warning",
        lambda _self, message: warnings.append(message),
    )

    MainWindow._check_pending_firmware(_FakeWindow(connected=False))

    assert remove_calls == []
    assert pending_path.exists()
    assert warnings == ["Connect to the device first. The downloaded firmware will stay queued for a later retry."]


def test_pending_firmware_is_kept_when_flash_fails(monkeypatch, tmp_path) -> None:
    pending_path = tmp_path / "esp32s3-usb-kbd.bin"
    pending_path.write_bytes(b"firmware")
    pending = {pending_path.name: pending_path}
    remove_calls: list[str] = []
    warnings: list[tuple[str, str]] = []

    class _FakeProgressDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def setWindowTitle(self, *_args) -> None:
            return None

        def setWindowModality(self, *_args) -> None:
            return None

        def setMinimumDuration(self, *_args) -> None:
            return None

        def setValue(self, *_args) -> None:
            return None

        def show(self) -> None:
            return None

        def setLabelText(self, *_args) -> None:
            return None

        def close(self) -> None:
            return None

    class _ImmediateThread:
        def __init__(self, *, target, daemon=None) -> None:
            self._target = target
            self.daemon = daemon

        def start(self) -> None:
            self._target()

    class _FailingFlasher:
        def __init__(self, _client) -> None:
            pass

        def flash(self, _board, _app, progress_cb=None) -> None:
            if progress_cb is not None:
                progress_cb(1, 1)
            raise RuntimeError("flash failed")

    monkeypatch.setattr("joycon_helper.updater.load_pending_firmware", lambda: pending)
    monkeypatch.setattr("joycon_helper.updater.remove_pending_firmware", lambda name: remove_calls.append(name))
    monkeypatch.setattr(
        "joycon_helper.ui.main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        "joycon_helper.ui.main_window.QMessageBox.warning",
        lambda _self, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr("joycon_helper.ui.main_window.QProgressDialog", _FakeProgressDialog)
    monkeypatch.setattr("joycon_helper.ui.main_window.QTimer.singleShot", lambda _delay, callback: callback())
    monkeypatch.setattr(threading, "Thread", _ImmediateThread)
    monkeypatch.setattr("joycon_helper.fw_updater.FirmwareFlasher", _FailingFlasher)
    monkeypatch.setattr("joycon_helper.fw_updater.extract_app_from_merged", lambda data: data)

    fake_window = _FakeWindow(connected=True)
    fake_window.bridge.client = object()

    MainWindow._check_pending_firmware(fake_window)

    assert remove_calls == []
    assert pending_path.exists()
    assert warnings == [(
        "Firmware Flash Error",
        "flash failed\n\nAny remaining firmware will stay queued for retry on the next launch.",
    )]
