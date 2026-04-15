from __future__ import annotations

import threading
from types import SimpleNamespace

from joycon_helper import _version
from joycon_helper.ui.main_window import MainWindow


class _FakeDialog:
    def __init__(self) -> None:
        self.status = ""
        self.progress = 0
        self.closed = False

    def setWindowTitle(self, _title: str) -> None:
        return None

    def set_status(self, message: str) -> None:
        self.status = message

    def set_progress(self, value: int) -> None:
        self.progress = value

    def show(self) -> None:
        return None

    def raise_(self) -> None:
        return None

    def activateWindow(self) -> None:
        return None

    def unlock_and_close(self) -> None:
        self.closed = True

    def is_locked(self) -> bool:
        return not self.closed


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.tool_tip = ""
        self.enabled = True
        self.style = ""

    def setText(self, text: str) -> None:
        self.text = text

    def setToolTip(self, text: str) -> None:
        self.tool_tip = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setStyleSheet(self, style: str) -> None:
        self.style = style


class _FakeTimer:
    def __init__(self) -> None:
        self.active = False

    def isActive(self) -> bool:
        return self.active

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


class _FakeTheme:
    def __init__(self) -> None:
        self.is_dark = False
        self.theme = {
            "colors": {
                "text": "#111111",
                "border": "#222222",
                "button_bg": "#333333",
                "button_hover": "#444444",
                "button_pressed": "#555555",
                "accent": "#666666",
                "accent_hover": "#777777",
                "warning": "#888888",
                "bg": "#ffffff",
            }
        }


class _FakeWindow:
    def __init__(self, *, connected: bool) -> None:
        self.bridge = SimpleNamespace(is_connected=connected)
        self._blocking_update_dialog = _FakeDialog()
        self._pending_firmware_files = {}
        self._pending_firmware_started = False
        self._update_info = {}
        self._update_check_in_progress = False
        self._update_install_in_progress = False
        self._update_blink_on = False
        self._update_btn = _FakeButton()
        self._theme_btn = _FakeButton()
        self._update_blink_timer = _FakeTimer()
        self.theme = _FakeTheme()
        self.update_available_calls: list[tuple[str, dict]] = []
        self._refresh_calls = 0
        self._wait_called = 0
        self._start_called = 0
        self.begin_update_calls: list[tuple[bool, bool]] = []
        self.install_calls = 0
        self.info_messages: list[tuple[str, str]] = []
        self.warn_messages: list[tuple[str, str]] = []

    def _show_blocking_update_dialog(self, _title: str, _message: str) -> None:
        return None

    def _set_blocking_update_progress(self, value: int) -> None:
        self._blocking_update_dialog.set_progress(value)

    def _close_blocking_update_dialog(self) -> None:
        self._blocking_update_dialog.unlock_and_close()

    def _try_connect_bridge_for_update(self) -> None:
        self._refresh_calls += 1

    def _wait_for_pending_firmware_connection(self) -> None:
        self._wait_called += 1

    def _start_pending_firmware_flash(self) -> None:
        self._start_called += 1

    def _apply_header_icon_button_styles(self) -> None:
        return None

    def _refresh_update_button_state(self) -> None:
        MainWindow._refresh_update_button_state(self)

    def _begin_update_check(self, *, manual: bool, install_if_found: bool) -> None:
        self.begin_update_calls.append((manual, install_if_found))

    def _do_full_update(self) -> None:
        self.install_calls += 1

    def _notify_update_available(self, *, version: str, info: dict) -> None:
        self.update_available_calls.append((version, info))

    def _ensure_view(self, *_args) -> None:
        return None

    def _nav_to(self, *_args) -> None:
        return None


def test_pending_firmware_enters_mandatory_flow_on_launch(monkeypatch, tmp_path) -> None:
    pending_path = tmp_path / "esp32s3-usb-kbd.bin"
    pending_path.write_bytes(b"firmware")
    pending = {pending_path.name: pending_path}

    monkeypatch.setattr("joycon_helper.updater.load_pending_firmware", lambda: pending)

    fake_window = _FakeWindow(connected=False)
    MainWindow._check_pending_firmware(fake_window)

    assert fake_window._pending_firmware_files == pending
    assert fake_window._pending_firmware_started is False
    assert fake_window._wait_called == 1


def test_wait_for_pending_firmware_connection_starts_flash_once_connected() -> None:
    fake_window = _FakeWindow(connected=True)
    fake_window._pending_firmware_files = {"esp32s3-usb-kbd.bin": object()}

    MainWindow._wait_for_pending_firmware_connection(fake_window)

    assert fake_window._start_called == 1
    assert fake_window._refresh_calls == 0


def test_pending_firmware_is_kept_when_flash_fails(monkeypatch, tmp_path) -> None:
    pending_path = tmp_path / "esp32s3-usb-kbd.bin"
    pending_path.write_bytes(b"firmware")
    pending = {pending_path.name: pending_path}
    remove_calls: list[str] = []
    class _ImmediateThread:
        def __init__(self, *, target, daemon=None) -> None:
            self._target = target
            self.daemon = daemon

        def start(self) -> None:
            self._target()

    class _FailingFlasher:
        def __init__(self, _client) -> None:
            pass

        def flash(self, _board, _app, *, expected_version=None, progress_cb=None) -> None:
            assert expected_version is not None
            if progress_cb is not None:
                progress_cb(1, 1)
            raise RuntimeError("flash failed")

    monkeypatch.setattr("joycon_helper.updater.load_pending_firmware", lambda: pending)
    monkeypatch.setattr("joycon_helper.updater.remove_pending_firmware", lambda name: remove_calls.append(name))
    monkeypatch.setattr("joycon_helper.ui.main_window.QTimer.singleShot", lambda _delay, callback: callback())
    monkeypatch.setattr(threading, "Thread", _ImmediateThread)
    monkeypatch.setattr("joycon_helper.fw_updater.FirmwareFlasher", _FailingFlasher)
    monkeypatch.setattr("joycon_helper.fw_updater.extract_app_from_merged", lambda data: data)

    fake_window = _FakeWindow(connected=True)
    fake_window.bridge.client = object()
    retry_errors: list[str] = []
    fake_window._retry_pending_firmware_flash = lambda error: retry_errors.append(error)
    fake_window._finish_pending_firmware_flash = lambda flashed: None

    fake_window._pending_firmware_files = pending

    MainWindow._start_pending_firmware_flash(fake_window)

    assert remove_calls == []
    assert pending_path.exists()
    assert retry_errors == ["flash failed"]


def test_update_button_checks_when_no_update_is_cached() -> None:
    fake_window = _FakeWindow(connected=False)

    MainWindow._on_update_button_clicked(fake_window)

    assert fake_window.begin_update_calls == [(True, True)]
    assert fake_window.install_calls == 0


def test_update_button_installs_when_update_is_cached() -> None:
    fake_window = _FakeWindow(connected=False)
    fake_window._update_info = {"version": "0.1.318"}

    MainWindow._on_update_button_clicked(fake_window)

    assert fake_window.install_calls == 1
    assert fake_window.begin_update_calls == []


def test_refresh_update_button_state_blinks_when_update_available() -> None:
    fake_window = _FakeWindow(connected=False)
    fake_window._update_info = {"version": "0.1.318"}

    MainWindow._refresh_update_button_state(fake_window)

    assert fake_window._update_btn.text == "↑"
    assert fake_window._update_btn.tool_tip == "Install Bind Bandit v0.1.318"
    assert fake_window._update_btn.enabled is True
    assert fake_window._update_blink_on is True
    assert fake_window._update_blink_timer.isActive() is True


def test_apply_update_result_reports_manual_up_to_date(monkeypatch) -> None:
    fake_window = _FakeWindow(connected=False)
    messages: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "joycon_helper.ui.main_window.QMessageBox.information",
        lambda _parent, title, text: messages.append((title, text)),
    )

    MainWindow._apply_update_result(
        fake_window,
        "up_to_date",
        {},
        "",
        manual=True,
        install_if_found=True,
    )

    assert messages == [("Up to Date", f"Bind Bandit v{_version.__version__} is already up to date.")]


def test_apply_update_result_notifies_when_automatic_update_available() -> None:
    fake_window = _FakeWindow(connected=False)

    MainWindow._apply_update_result(
        fake_window,
        "available",
        {"version": "0.1.318"},
        "",
        manual=False,
        install_if_found=False,
    )

    assert fake_window._update_info.get("version") == "0.1.318"
    assert fake_window.update_available_calls == [("0.1.318", {"version": "0.1.318"})]


def test_apply_update_result_installs_after_manual_check_finds_update() -> None:
    fake_window = _FakeWindow(connected=False)

    MainWindow._apply_update_result(
        fake_window,
        "available",
        {"version": "0.1.318"},
        "",
        manual=True,
        install_if_found=True,
    )

    assert fake_window._update_info == {"version": "0.1.318"}
    assert fake_window.install_calls == 1
