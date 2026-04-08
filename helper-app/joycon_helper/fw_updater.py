"""Firmware OTA update support for Bind Bandit.

Downloads firmware binaries from GitHub Releases and flashes them to the
ESP32-S3 (USB keyboard) and ESP32 (BT host) over the existing CDC serial
connection using NDJSON commands.

No personal data is sent — only an unauthenticated GET to the public GitHub
Releases API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import ssl
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

from .updater import RELEASES_URL

# Import build date — may be empty for local dev runs.
try:
    from ._version import __build_date__
except ImportError:
    __build_date__ = ""

log = logging.getLogger("joycon_helper.fw_updater")

# GitHub release asset names for firmware binaries.
FW_ASSET_S3 = "esp32s3-usb-kbd.bin"
FW_ASSET_ESP32 = "esp32-hid-host-uart.bin"

# Board identifiers used in the serial protocol.
BOARD_S3 = "esp32s3"
BOARD_ESP32 = "esp32"

# Chunk size for OTA data sent over CDC serial (raw bytes before base64).
# 3072 bytes → ~4096 base64 chars per NDJSON line.
OTA_CHUNK_SIZE = 3072

# Timeouts for serial commands (seconds).
_CMD_TIMEOUT = 10
_END_TIMEOUT = 30

# How long to wait for GitHub API responses (seconds).
_HTTP_TIMEOUT = 15

# OTA chunk retry settings.
_OTA_CHUNK_RETRIES = 3
_OTA_CHUNK_RETRY_DELAY = 0.5  # seconds, multiplied by attempt number

# Download retry settings.
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds; doubles each retry

# RELEASES_URL imported at top from .updater


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _parse_version(tag: str) -> Tuple[int, ...]:
    tag = tag.strip().lstrip("v")
    parts: List[int] = []
    for seg in tag.split("."):
        seg = seg.split("+")[0].split("-")[0]
        try:
            parts.append(int(seg))
        except ValueError:
            break
    return tuple(parts)


# ---------------------------------------------------------------------------
# GitHub Releases helpers
# ---------------------------------------------------------------------------

def _fetch_latest_release() -> Dict[str, Any]:
    req = Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json"})
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_asset(release: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for asset in release.get("assets", []):
        if asset.get("name", "") == name:
            return asset
    return None


def _fetch_sha256sums(release: Dict[str, Any]) -> Dict[str, str]:
    """Try to download a sha256sums.txt asset and return {filename: hash}."""
    asset = _find_asset(release, "sha256sums.txt")
    if not asset:
        return {}
    try:
        req = Request(asset["browser_download_url"])
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as resp:
            text = resp.read().decode("utf-8")
        result: Dict[str, str] = {}
        for line in text.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                sha, name = parts
                result[name.strip("* ")] = sha.lower()
        return result
    except Exception:
        log.debug("Could not fetch sha256sums.txt", exc_info=True)
        return {}


def check_firmware_updates(
    current_s3: Optional[str] = None,
    current_esp32: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Check GitHub for newer firmware binaries.

    Returns a dict with release metadata and per-board info,
    or None if everything is up to date (or check fails).
    """
    try:
        release = _fetch_latest_release()
    except Exception:
        log.warning("Failed to fetch latest release for FW check", exc_info=True)
        return None

    tag = release.get("tag_name", "")
    remote_ver = _parse_version(tag)
    if not remote_ver:
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
                        "Skipping FW update %s: release date %s is not newer than build date %s",
                        tag, published, __build_date__,
                    )
                    return None
            except (ValueError, TypeError):
                log.debug("Could not compare dates, falling back to version only")

    # Fetch SHA256 checksums if published alongside binaries.
    sha256sums = _fetch_sha256sums(release)

    # Extract release notes (Markdown body).
    release_notes = (release.get("body") or "").strip()

    result: Dict[str, Any] = {
        "tag": tag,
        "version": tag.lstrip("v"),
        "boards": {},
        "release_notes": release_notes,
    }

    # Check ESP32-S3 firmware.
    if current_s3:
        local = _parse_version(current_s3)
        if remote_ver > local:
            asset = _find_asset(release, FW_ASSET_S3)
            if asset:
                result["boards"][BOARD_S3] = {
                    "current": current_s3,
                    "download_url": asset["browser_download_url"],
                    "asset_name": FW_ASSET_S3,
                    "size": asset.get("size", 0),
                    "expected_sha256": sha256sums.get(FW_ASSET_S3),
                }

    # Check ESP32 BT host firmware.
    if current_esp32:
        local = _parse_version(current_esp32)
        if remote_ver > local:
            asset = _find_asset(release, FW_ASSET_ESP32)
            if asset:
                result["boards"][BOARD_ESP32] = {
                    "current": current_esp32,
                    "download_url": asset["browser_download_url"],
                    "asset_name": FW_ASSET_ESP32,
                    "size": asset.get("size", 0),
                    "expected_sha256": sha256sums.get(FW_ASSET_ESP32),
                }

    if not result["boards"]:
        log.info("Firmware up to date (s3=%s esp32=%s remote=%s)",
                 current_s3, current_esp32, tag)
        return None

    log.info("Firmware update available: %s (s3=%s esp32=%s)",
             tag, current_s3, current_esp32)
    return result


def download_firmware(
    url: str,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    expected_sha256: Optional[str] = None,
    expected_size: int = 0,
) -> bytes:
    """Download a firmware binary with retry, SHA-256 verification, and size check.

    Raises ``RuntimeError`` on hash mismatch or persistent download failure.
    """
    last_err: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            log.info("Downloading firmware from %s (attempt %d/%d)", url, attempt, _MAX_RETRIES)
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

            # Size sanity check.
            if expected_size and len(data) != expected_size:
                raise RuntimeError(
                    f"Size mismatch: expected {expected_size}, got {len(data)}"
                )

            # SHA-256 integrity verification.
            actual_hash = hashlib.sha256(data).hexdigest()
            log.info("Firmware download complete: %d bytes, SHA-256=%s", len(data), actual_hash)

            if expected_sha256:
                if actual_hash != expected_sha256.lower():
                    raise RuntimeError(
                        f"SHA-256 mismatch: expected {expected_sha256}, got {actual_hash}"
                    )
                log.info("SHA-256 verified OK")

            return bytes(data)

        except RuntimeError:
            raise  # integrity errors are not retryable
        except Exception as e:
            last_err = e
            log.warning("Download attempt %d/%d failed: %s", attempt, _MAX_RETRIES, e)
            if attempt < _MAX_RETRIES:
                backoff = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                log.info("Retrying in %.1fs…", backoff)
                time.sleep(backoff)

    raise RuntimeError(f"Download failed after {_MAX_RETRIES} attempts: {last_err}")


def compute_sha256(data: bytes) -> str:
    """Return the hex SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Serial OTA flashing
# ---------------------------------------------------------------------------

class FirmwareFlasher:
    """Sends a firmware binary to a board via the serial NDJSON protocol.

    Requires a connected ``SerialClient`` instance.
    """

    def __init__(self, serial_client: Any) -> None:
        self._ser = serial_client

    def get_version(self, board: str = BOARD_S3) -> Optional[str]:
        """Query firmware version from a board. Returns version string or None."""
        cmd: Dict[str, Any] = {"cmd": "fw_version"}
        if board == BOARD_ESP32:
            cmd["board"] = "esp32"

        self._ser.send_obj(cmd)
        rsp = self._wait_response("fw_version", timeout=_CMD_TIMEOUT)
        if rsp and rsp.get("ok"):
            return rsp.get("version")
        return None

    def flash(
        self,
        board: str,
        firmware: bytes,
        *,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Flash firmware to a board over serial.

        Raises RuntimeError on failure.
        """
        total = len(firmware)
        log.info("Starting OTA flash: board=%s size=%d", board, total)

        # 1. Begin
        cmd_begin: Dict[str, Any] = {"cmd": "fw_update_begin", "size": total}
        if board == BOARD_ESP32:
            cmd_begin["board"] = "esp32"
        self._ser.send_obj(cmd_begin)

        rsp = self._wait_response("fw_update_begin", timeout=_CMD_TIMEOUT)
        if not rsp or not rsp.get("ok"):
            err = rsp.get("error", "unknown") if rsp else "no_response"
            raise RuntimeError(f"fw_update_begin failed: {err}")

        # 2. Send data chunks
        offset = 0
        try:
            while offset < total:
                chunk = firmware[offset:offset + OTA_CHUNK_SIZE]
                b64 = base64.b64encode(chunk).decode("ascii")

                last_err = ""
                for attempt in range(1, _OTA_CHUNK_RETRIES + 1):
                    cmd_data: Dict[str, Any] = {"cmd": "fw_update_data", "data": b64}
                    if board == BOARD_ESP32:
                        cmd_data["board"] = "esp32"
                    self._ser.send_obj(cmd_data)

                    rsp = self._wait_response("fw_update_data", timeout=_CMD_TIMEOUT)
                    if rsp and rsp.get("ok"):
                        break
                    last_err = rsp.get("error", "unknown") if rsp else "no_response"
                    log.warning(
                        "OTA chunk at offset %d failed (attempt %d/%d): %s",
                        offset, attempt, _OTA_CHUNK_RETRIES, last_err,
                    )
                    if attempt < _OTA_CHUNK_RETRIES:
                        time.sleep(_OTA_CHUNK_RETRY_DELAY * attempt)
                else:
                    raise RuntimeError(
                        f"fw_update_data failed at offset {offset} after "
                        f"{_OTA_CHUNK_RETRIES} attempts: {last_err}"
                    )

                offset += len(chunk)
                if progress_cb:
                    progress_cb(offset, total)
        except Exception:
            # Abort on any failure.
            try:
                abort_cmd: Dict[str, Any] = {"cmd": "fw_update_abort"}
                if board == BOARD_ESP32:
                    abort_cmd["board"] = "esp32"
                self._ser.send_obj(abort_cmd)
            except Exception:
                pass
            raise

        # 3. Finalize
        cmd_end: Dict[str, Any] = {"cmd": "fw_update_end"}
        if board == BOARD_ESP32:
            cmd_end["board"] = "esp32"
        self._ser.send_obj(cmd_end)

        rsp = self._wait_response("fw_update_end", timeout=_END_TIMEOUT)
        if not rsp or not rsp.get("ok"):
            err = rsp.get("error", "unknown") if rsp else "no_response"
            raise RuntimeError(f"fw_update_end failed: {err}")

        log.info("OTA flash complete for %s — device will reboot", board)

    def _wait_response(self, expected_rsp: str, timeout: float = 10) -> Optional[Dict[str, Any]]:
        """Drain RX queue looking for a JSON response matching expected_rsp."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self._ser.rx.get(timeout=0.1)
            except Exception:
                continue
            if line.parsed and line.parsed.get("rsp") == expected_rsp:
                return line.parsed
        return None
