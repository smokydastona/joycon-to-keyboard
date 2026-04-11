"""Auto-update support for Bind Bandit.

Checks the GitHub Releases API for a newer version and, when running as a
frozen PyInstaller executable, downloads and installs the update.

No personal data is sent — only an unauthenticated GET to the public GitHub
Releases API for this repository.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import ssl
import sys
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ._version import __version__

# Import build date — may be empty for local dev runs.
try:
    from ._version import __build_date__
except ImportError:
    __build_date__ = ""

log = logging.getLogger("joycon_helper.updater")

GITHUB_OWNER = "smokydastona"
GITHUB_REPO = "joycon-to-keyboard"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
EXE_ASSET_NAME = "BindBandit.exe"
FW_ASSET_S3 = "esp32s3-usb-kbd.bin"
FW_ASSET_ESP32 = "esp32-hid-host-uart.bin"
_PENDING_FW_DIR = "pending_fw"

# How long to wait for GitHub API responses (seconds).
_TIMEOUT = 15

# Whether Authenticode verification is enforced on downloaded updates.
# Enabled by default for security; set JOYCON_SKIP_SIGNATURE=1 for unsigned dev builds.
REQUIRE_SIGNATURE = os.environ.get("JOYCON_SKIP_SIGNATURE", "") != "1"


# ---------------------------------------------------------------------------
# Authenticode signature verification (Windows only)
# ---------------------------------------------------------------------------

def _verify_authenticode(path: Path) -> bool:
    """Return True if *path* has a valid Authenticode signature on Windows.

    On non-Windows platforms or when the WinTrust API is unavailable this
    returns True (verification skipped).  When ``REQUIRE_SIGNATURE`` is
    False the result is logged but never blocks the update.
    """
    if sys.platform != "win32":
        return True

    try:
        import ctypes.wintypes

        class _WINTRUST_FILE_INFO(ctypes.Structure):
            _fields_ = [
                ("cbStruct", ctypes.wintypes.DWORD),
                ("pcwszFilePath", ctypes.c_wchar_p),
                ("hFile", ctypes.wintypes.HANDLE),
                ("pgKnownSubject", ctypes.c_void_p),
            ]

        class _WINTRUST_DATA(ctypes.Structure):
            _fields_ = [
                ("cbStruct", ctypes.wintypes.DWORD),
                ("pPolicyCallbackData", ctypes.c_void_p),
                ("pSIPClientData", ctypes.c_void_p),
                ("dwUIChoice", ctypes.wintypes.DWORD),
                ("fdwRevocationChecks", ctypes.wintypes.DWORD),
                ("dwUnionChoice", ctypes.wintypes.DWORD),
                ("pFile", ctypes.c_void_p),
                ("dwStateAction", ctypes.wintypes.DWORD),
                ("hWVTStateData", ctypes.wintypes.HANDLE),
                ("pwszURLReference", ctypes.c_wchar_p),
                ("dwProvFlags", ctypes.wintypes.DWORD),
                ("dwUIContext", ctypes.wintypes.DWORD),
                ("pSignatureSettings", ctypes.c_void_p),
            ]

        WINTRUST_ACTION_GENERIC_VERIFY_V2 = (
            ctypes.c_byte * 16
        )(*[0x00, 0xAA, 0xC5, 0x6B, 0x11, 0xD0, 0x8C, 0xC5,
            0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE, 0x46, 0x02])

        WTD_UI_NONE = 2
        WTD_CHOICE_FILE = 1
        WTD_REVOKE_NONE = 0

        wintrust = ctypes.windll.wintrust  # type: ignore[attr-defined]
        wintrust.WinVerifyTrust.restype = ctypes.c_long
        wintrust.WinVerifyTrust.argtypes = [
            ctypes.wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p,
        ]

        file_info = _WINTRUST_FILE_INFO()
        file_info.cbStruct = ctypes.sizeof(_WINTRUST_FILE_INFO)
        file_info.pcwszFilePath = str(path)

        trust_data = _WINTRUST_DATA()
        trust_data.cbStruct = ctypes.sizeof(_WINTRUST_DATA)
        trust_data.dwUIChoice = WTD_UI_NONE
        trust_data.fdwRevocationChecks = WTD_REVOKE_NONE
        trust_data.dwUnionChoice = WTD_CHOICE_FILE
        trust_data.pFile = ctypes.pointer(file_info)

        result = wintrust.WinVerifyTrust(
            0,
            ctypes.byref(WINTRUST_ACTION_GENERIC_VERIFY_V2),
            ctypes.byref(trust_data),
        )

        if result == 0:
            log.info("Authenticode signature valid: %s", path)
            return True
        else:
            log.warning(
                "Authenticode verification failed (0x%08X): %s", result, path)
            return False

    except Exception:
        log.debug("WinTrust API unavailable — skipping signature check",
                  exc_info=True)
        return True


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse a version string like '0.1.42' or 'v0.1.42' into a comparable tuple."""
    tag = tag.strip().lstrip("v")
    parts = []
    for segment in tag.split("."):
        # Strip any suffix like '+push.123'
        segment = segment.split("+")[0].split("-")[0]
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


def current_version() -> str:
    return __version__


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


# ---------------------------------------------------------------------------
# GitHub Releases API
# ---------------------------------------------------------------------------

def _fetch_latest_release() -> dict[str, Any]:
    """Fetch the latest GitHub Release metadata (unauthenticated)."""
    req = Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json"})
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_exe_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    """Return the release asset dict for the helper .exe, or None."""
    for asset in release.get("assets", []):
        if asset.get("name", "") == EXE_ASSET_NAME:
            return asset
    return None


def check_for_update() -> dict[str, str] | None:
    """Check GitHub for a newer release.

    Returns a dict with 'tag', 'version', 'download_url', 'html_url',
    and 'release_name' if a newer version is available, else None.
    """
    try:
        release = _fetch_latest_release()
    except Exception:
        log.warning("Failed to check for updates", exc_info=True)
        return None

    tag = release.get("tag_name", "")
    remote_ver = _parse_version(tag)
    local_ver = _parse_version(__version__)

    if not remote_ver or remote_ver <= local_ver:
        log.info("Up to date (local=%s, remote=%s)", __version__, tag)
        return None

    # Date guard: skip update if this build is newer than the release.
    if __build_date__:
        published = release.get("published_at", "")
        if published:
            try:
                release_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                build_dt = datetime.fromisoformat(__build_date__.replace("Z", "+00:00"))
                if build_dt >= release_dt:
                    log.info(
                        "Skipping update %s: release date %s is not newer than build date %s",
                        tag, published, __build_date__,
                    )
                    return None
            except (ValueError, TypeError):
                log.debug("Could not compare dates, falling back to version only")

    asset = _find_exe_asset(release)
    if asset is None:
        log.warning("Newer release %s found but no %s asset", tag, EXE_ASSET_NAME)
        return None

    # Collect firmware assets from the same release.
    fw_assets: dict[str, dict[str, Any]] = {}
    for rel_asset in release.get("assets", []):
        name = rel_asset.get("name", "")
        if name in (FW_ASSET_S3, FW_ASSET_ESP32):
            fw_assets[name] = {
                "url": rel_asset["browser_download_url"],
                "size": rel_asset.get("size", 0),
            }

    log.info("Update available: %s → %s", __version__, tag)
    return {
        "tag": tag,
        "version": tag.lstrip("v"),
        "download_url": asset["browser_download_url"],
        "html_url": release.get("html_url", ""),
        "release_name": release.get("name", tag),
        "fw_assets": fw_assets,
    }


# ---------------------------------------------------------------------------
# Download & install (frozen exe only)
# ---------------------------------------------------------------------------

def _cleanup_old_exe() -> None:
    """Remove leftover .old exe from a previous update."""
    if not is_frozen():
        return
    old = Path(sys.executable).with_suffix(".old.exe")
    if old.exists():
        try:
            old.unlink()
            log.info("Cleaned up old exe: %s", old)
        except OSError:
            log.warning("Could not remove old exe: %s", old, exc_info=True)


def download_and_install(
    download_url: str,
    *,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """Download the new exe and swap it into place.

    On Windows a running .exe can be renamed (but not deleted), so the flow is:
      1. Download to a temp file next to the current exe.
      2. Rename the current exe → .old.exe
      3. Rename the temp → current exe name.

    The caller should prompt the user to restart.  On next launch,
    ``_cleanup_old_exe()`` removes the .old copy.

    Returns the Path of the newly-installed exe.
    """
    if not is_frozen():
        raise RuntimeError("Auto-update is only supported for the packaged .exe build.")

    current_exe = Path(sys.executable).resolve()
    parent = current_exe.parent
    old_exe = current_exe.with_suffix(".old.exe")
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        suffix=".exe", prefix="jcb_update_", dir=str(parent)
    )

    log.info("Downloading update from %s", download_url)
    try:
        req = Request(download_url)
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=120, context=ctx) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with os.fdopen(tmp_fd, "wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total > 0:
                        progress_cb(downloaded, total)
        log.info("Download complete: %d bytes", downloaded)
    except Exception:
        # Clean up partial download.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path_str)
        raise

    tmp_path = Path(tmp_path_str)

    # Verify Authenticode signature before installing
    if not _verify_authenticode(tmp_path) and REQUIRE_SIGNATURE:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Downloaded update failed Authenticode signature verification. "
            "The file may be tampered with — update aborted."
        )

    # Swap: current → .old, temp → current
    try:
        if old_exe.exists():
            old_exe.unlink()
        current_exe.rename(old_exe)
        log.info("Moved current exe to %s", old_exe)
    except OSError as e:
        log.error("Failed to rename current exe", exc_info=True)
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Could not move the current executable aside. Is another copy running?") from e

    try:
        tmp_path.rename(current_exe)
        log.info("Installed new exe as %s", current_exe)
    except OSError as e:
        # Roll back: restore old exe.
        log.error("Failed to install new exe, rolling back", exc_info=True)
        old_exe.rename(current_exe)
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Could not install the new executable. Rolled back to previous version.") from e

    return current_exe


# ---------------------------------------------------------------------------
# Generic asset download
# ---------------------------------------------------------------------------

def download_bytes(
    url: str,
    *,
    progress_cb: Callable[[int, int], None] | None = None,
) -> bytes:
    """Download a URL and return raw bytes with optional progress callback."""
    req = Request(url)
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=120, context=ctx) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        data = bytearray()
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            data.extend(chunk)
            if progress_cb and total > 0:
                progress_cb(len(data), total)
    return bytes(data)


# ---------------------------------------------------------------------------
# Pending firmware management
# ---------------------------------------------------------------------------

def _pending_fw_dir() -> Path:
    """Return path to the pending firmware directory (next to the exe)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent / _PENDING_FW_DIR
    return Path(__file__).resolve().parent.parent / _PENDING_FW_DIR


def save_pending_firmware(name: str, data: bytes) -> None:
    """Save firmware bytes to the pending directory."""
    d = _pending_fw_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    log.info("Saved pending firmware: %s (%d bytes)", name, len(data))


def load_pending_firmware() -> dict[str, Path]:
    """Return {filename: path} for any saved firmware binaries."""
    d = _pending_fw_dir()
    if not d.is_dir():
        return {}
    result: dict[str, Path] = {}
    for f in d.iterdir():
        if f.suffix == ".bin" and f.is_file():
            result[f.name] = f
    return result


def clear_pending_firmware() -> None:
    """Remove the pending firmware directory."""
    d = _pending_fw_dir()
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        log.info("Cleared pending firmware directory")


# ---------------------------------------------------------------------------
# Install pre-downloaded exe
# ---------------------------------------------------------------------------

def install_exe(exe_bytes: bytes) -> Path:
    """Write *exe_bytes* to a temp file and swap it into place.

    Same rename strategy as ``download_and_install``, but separated from
    the download step so callers can download everything first.

    Returns the path of the newly-installed executable.
    """
    if not is_frozen():
        raise RuntimeError("Auto-update is only supported for the packaged .exe build.")

    current_exe = Path(sys.executable).resolve()
    parent = current_exe.parent
    old_exe = current_exe.with_suffix(".old.exe")
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        suffix=".exe", prefix="jcb_update_", dir=str(parent)
    )
    try:
        with os.fdopen(tmp_fd, "wb") as out:
            out.write(exe_bytes)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path_str)
        raise

    tmp_path = Path(tmp_path_str)

    # Verify Authenticode signature before installing
    if not _verify_authenticode(tmp_path) and REQUIRE_SIGNATURE:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            "Update exe failed Authenticode signature verification — "
            "update aborted."
        )

    try:
        if old_exe.exists():
            old_exe.unlink()
        current_exe.rename(old_exe)
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Could not move the current executable aside.") from e

    try:
        tmp_path.rename(current_exe)
    except OSError as e:
        old_exe.rename(current_exe)
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Could not install the new executable. Rolled back.") from e

    log.info("Installed new exe as %s", current_exe)
    return current_exe


# ---------------------------------------------------------------------------
# Relaunch
# ---------------------------------------------------------------------------

def relaunch() -> None:
    """Launch the (new) executable and exit this process."""
    import subprocess
    exe = Path(sys.executable).resolve()
    log.info("Relaunching: %s", exe)
    subprocess.Popen([str(exe)])
    sys.exit(0)


# ---------------------------------------------------------------------------
# Background check helper (non-blocking, for UI startup)
# ---------------------------------------------------------------------------

def check_in_background(callback: Callable[[dict[str, str] | None], None]) -> None:
    """Run ``check_for_update()`` on a daemon thread and deliver result via *callback*.

    *callback* is called from the background thread — the caller is responsible
    for marshalling back to the UI thread (e.g. ``root.after()``).
    """
    def _worker():
        result = check_for_update()
        callback(result)

    t = threading.Thread(target=_worker, name="update-check", daemon=True)
    t.start()


# Cleanup leftover .old exe on import (safe no-op if not frozen).
_cleanup_old_exe()
