"""Auto-update support for Joy-Con Bridge Helper.

Checks the GitHub Releases API for a newer version and, when running as a
frozen PyInstaller executable, downloads and installs the update.

No personal data is sent — only an unauthenticated GET to the public GitHub
Releases API for this repository.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import ssl
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from ._version import __version__

log = logging.getLogger("joycon_helper.updater")

GITHUB_OWNER = "smokydastona"
GITHUB_REPO = "joycon-to-keyboard"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
EXE_ASSET_NAME = "JoyConBridgeHelper.exe"

# How long to wait for GitHub API responses (seconds).
_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def _parse_version(tag: str) -> Tuple[int, ...]:
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

def _fetch_latest_release() -> Dict[str, Any]:
    """Fetch the latest GitHub Release metadata (unauthenticated)."""
    req = Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json"})
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_exe_asset(release: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the release asset dict for the helper .exe, or None."""
    for asset in release.get("assets", []):
        if asset.get("name", "") == EXE_ASSET_NAME:
            return asset
    return None


def check_for_update() -> Optional[Dict[str, str]]:
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

    asset = _find_exe_asset(release)
    if asset is None:
        log.warning("Newer release %s found but no %s asset", tag, EXE_ASSET_NAME)
        return None

    log.info("Update available: %s → %s", __version__, tag)
    return {
        "tag": tag,
        "version": tag.lstrip("v"),
        "download_url": asset["browser_download_url"],
        "html_url": release.get("html_url", ""),
        "release_name": release.get("name", tag),
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
            log.debug("Could not remove old exe: %s", old, exc_info=True)


def download_and_install(
    download_url: str,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
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
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise

    tmp_path = Path(tmp_path_str)

    # Swap: current → .old, temp → current
    try:
        if old_exe.exists():
            old_exe.unlink()
        current_exe.rename(old_exe)
        log.info("Moved current exe to %s", old_exe)
    except OSError:
        log.error("Failed to rename current exe", exc_info=True)
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Could not move the current executable aside. Is another copy running?")

    try:
        tmp_path.rename(current_exe)
        log.info("Installed new exe as %s", current_exe)
    except OSError:
        # Roll back: restore old exe.
        log.error("Failed to install new exe, rolling back", exc_info=True)
        old_exe.rename(current_exe)
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Could not install the new executable. Rolled back to previous version.")

    return current_exe


# ---------------------------------------------------------------------------
# Background check helper (non-blocking, for UI startup)
# ---------------------------------------------------------------------------

def check_in_background(callback: Callable[[Optional[Dict[str, str]]], None]) -> None:
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
