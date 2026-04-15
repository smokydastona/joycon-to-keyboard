from __future__ import annotations

import io
import zipfile
from pathlib import Path

from joycon_helper import updater


def test_check_for_update_returns_release_with_firmware_assets(monkeypatch) -> None:
    monkeypatch.setattr(updater, "__version__", "0.1.289")
    monkeypatch.setattr(updater, "__build_date__", "")
    monkeypatch.setattr(
        updater,
        "_fetch_latest_release",
        lambda: {
            "tag_name": "v0.1.290",
            "html_url": "https://example.invalid/release",
            "name": "v0.1.290",
            "assets": [
                {"name": "BindBandit.exe", "browser_download_url": "https://example.invalid/BindBandit.exe"},
                {"name": "esp32s3-usb-kbd.bin", "browser_download_url": "https://example.invalid/s3.bin", "size": 10},
                {"name": "esp32-hid-host-uart.bin", "browser_download_url": "https://example.invalid/esp32.bin", "size": 20},
            ],
        },
    )

    info = updater.check_for_update()

    assert info is not None
    assert info["version"] == "0.1.290"
    assert info["download_url"].endswith("BindBandit.exe")
    assert sorted(info["fw_assets"]) == ["esp32-hid-host-uart.bin", "esp32s3-usb-kbd.bin"]


def test_check_for_update_accepts_bundle_only_release(monkeypatch) -> None:
    monkeypatch.setattr(updater, "__version__", "0.1.289")
    monkeypatch.setattr(updater, "__build_date__", "")
    monkeypatch.setattr(
        updater,
        "_fetch_latest_release",
        lambda: {
            "tag_name": "v0.1.290",
            "html_url": "https://example.invalid/release",
            "name": "v0.1.290",
            "assets": [
                {
                    "name": "bind-bandit-release-bundle-v0.1.290-push.1.zip",
                    "browser_download_url": "https://example.invalid/bundle.zip",
                },
            ],
        },
    )

    status, info, message = updater.check_for_update_status()

    assert status == "available"
    assert message == ""
    assert info["download_kind"] == "bundle"
    assert info["download_url"].endswith("bundle.zip")


def test_check_for_update_status_reports_up_to_date(monkeypatch) -> None:
    monkeypatch.setattr(updater, "__version__", "0.1.317")
    monkeypatch.setattr(
        updater,
        "_fetch_latest_release",
        lambda: {
            "tag_name": "v0.1.317",
            "assets": [],
        },
    )

    status, info, message = updater.check_for_update_status()

    assert status == "up_to_date"
    assert info == {}
    assert message == ""


def test_check_for_update_status_reports_error_when_fetch_fails(monkeypatch) -> None:
    def _boom() -> dict:
        raise RuntimeError("offline")

    monkeypatch.setattr(updater, "_fetch_latest_release", _boom)

    status, info, message = updater.check_for_update_status()

    assert status == "error"
    assert info == {}
    assert "check for updates" in message.lower()


def test_download_update_bundle_saves_firmware_before_install(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def _download_bytes(url: str, *, progress_cb=None) -> bytes:
        calls.append(("download", url))
        if progress_cb is not None:
            progress_cb(5, 10)
        return f"payload:{url}".encode()

    def _save_pending(name: str, data: bytes) -> None:
        calls.append(("save", f"{name}:{data.decode('utf-8')}"))

    def _install(download_url: str, *, progress_cb=None) -> Path:
        calls.append(("install", download_url))
        if progress_cb is not None:
            progress_cb(10, 10)
        return Path("C:/BindBandit.exe")

    monkeypatch.setattr(updater, "download_bytes", _download_bytes)
    monkeypatch.setattr(updater, "save_pending_firmware", _save_pending)
    monkeypatch.setattr(updater, "download_and_install", _install)

    result = updater.download_update_bundle(
        {
            "download_url": "https://example.invalid/BindBandit.exe",
            "fw_assets": {
                "esp32s3-usb-kbd.bin": {"url": "https://example.invalid/s3.bin"},
                "esp32-hid-host-uart.bin": {"url": "https://example.invalid/esp32.bin"},
            },
        }
    )

    assert result == Path("C:/BindBandit.exe")
    assert calls == [
        ("download", "https://example.invalid/s3.bin"),
        ("save", "esp32s3-usb-kbd.bin:payload:https://example.invalid/s3.bin"),
        ("download", "https://example.invalid/esp32.bin"),
        ("save", "esp32-hid-host-uart.bin:payload:https://example.invalid/esp32.bin"),
        ("install", "https://example.invalid/BindBandit.exe"),
    ]


def test_download_update_bundle_from_release_bundle_zip(monkeypatch) -> None:
    exe_payload = b"EXE_BYTES"
    fw_s3_payload = b"S3_FW"
    fw_esp32_payload = b"ESP32_FW"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bind-bandit-release-bundle-v0.1.290/helper-app/BindBandit.exe", exe_payload)
        zf.writestr(
            "bind-bandit-release-bundle-v0.1.290/firmware/esp32s3-usb-kbd/esp32s3-usb-kbd-merged.bin",
            fw_s3_payload,
        )
        zf.writestr(
            "bind-bandit-release-bundle-v0.1.290/firmware/esp32-hid-host-uart/esp32-hid-host-uart-merged.bin",
            fw_esp32_payload,
        )

    calls: list[tuple[str, str]] = []

    def _download_bytes(url: str, *, progress_cb=None) -> bytes:
        calls.append(("download", url))
        return buf.getvalue()

    def _save_pending(name: str, data: bytes) -> None:
        calls.append(("save", f"{name}:{data!r}"))

    def _install_exe(exe_bytes: bytes) -> Path:
        assert exe_bytes == exe_payload
        calls.append(("install", "ok"))
        return Path("C:/BindBandit.exe")

    monkeypatch.setattr(updater, "download_bytes", _download_bytes)
    monkeypatch.setattr(updater, "save_pending_firmware", _save_pending)
    monkeypatch.setattr(updater, "install_exe", _install_exe)

    result = updater.download_update_bundle(
        {
            "download_kind": "bundle",
            "download_url": "https://example.invalid/bundle.zip",
            "fw_assets": {},
        }
    )

    assert result == Path("C:/BindBandit.exe")
    # Pending firmware names come from the files in the bundle.
    assert ("download", "https://example.invalid/bundle.zip") in calls
    assert any(c[0] == "save" and "esp32s3-usb-kbd-merged.bin" in c[1] for c in calls)
    assert any(c[0] == "save" and "esp32-hid-host-uart-merged.bin" in c[1] for c in calls)
    assert ("install", "ok") in calls


def test_remove_pending_firmware_cleans_up_empty_directory(monkeypatch, tmp_path) -> None:
    pending_dir = tmp_path / "pending_fw"
    pending_dir.mkdir()
    (pending_dir / "esp32s3-usb-kbd.bin").write_bytes(b"123")

    monkeypatch.setattr(updater, "_pending_fw_dir", lambda: pending_dir)

    updater.remove_pending_firmware("esp32s3-usb-kbd.bin")

    assert not pending_dir.exists()
