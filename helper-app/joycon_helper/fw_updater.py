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
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

from .logger import logs_dir
from .updater import RELEASES_URL

# Import build date — may be empty for local dev runs.
try:
    from ._version import __build_date__
except ImportError:
    __build_date__ = ""

log = logging.getLogger("joycon_helper.fw_updater")

# GitHub release asset names for firmware binaries (merged: bootloader +
# partition table + app).  OTA needs only the app portion, so we strip the
# leading 0x10000 bytes after download — see ``extract_app_from_merged()``.
FW_ASSET_S3 = "esp32s3-usb-kbd.bin"
FW_ASSET_ESP32 = "esp32-hid-host-uart.bin"

# Offset where the app image starts inside a merged binary produced by
# ``esptool.py merge_bin`` (bootloader @ 0x0, partition-table @ 0x8000,
# app @ 0x10000).
_APP_OFFSET = 0x10000

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

# OTA data writes are not retried per chunk. The transport protocol does not
# provide chunk sequence deduplication, so re-sending a chunk after a lost ACK
# can duplicate bytes in flash and corrupt the image.

# Post-flash version verification settings.
_VERIFY_RETRIES = 20
_VERIFY_DELAY = 0.5

# Diagnostics capture.
_SERIAL_HISTORY_LIMIT = 80
_QUEUE_DRAIN_LIMIT = 512

# Download retry settings.
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds; doubles each retry

# RELEASES_URL imported at top from .updater


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _parse_version(tag: str) -> tuple[int, ...]:
    tag = tag.strip().lstrip("v")
    parts: list[int] = []
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

def _fetch_latest_release() -> dict[str, Any]:
    req = Request(RELEASES_URL, headers={"Accept": "application/vnd.github+json"})
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_asset(release: dict[str, Any], name: str) -> dict[str, Any] | None:
    for asset in release.get("assets", []):
        if asset.get("name", "") == name:
            return asset
    return None


def _fetch_sha256sums(release: dict[str, Any]) -> dict[str, str]:
    """Try to download a sha256sums.txt asset and return {filename: hash}."""
    asset = _find_asset(release, "sha256sums.txt")
    if not asset:
        return {}
    try:
        req = Request(asset["browser_download_url"])
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=_HTTP_TIMEOUT, context=ctx) as resp:
            text = resp.read().decode("utf-8")
        result: dict[str, str] = {}
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
    current_s3: str | None = None,
    current_esp32: str | None = None,
) -> dict[str, Any] | None:
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

    result: dict[str, Any] = {
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
    progress_cb: Callable[[int, int], None] | None = None,
    expected_sha256: str | None = None,
    expected_size: int = 0,
) -> bytes:
    """Download a firmware binary with retry, SHA-256 verification, and size check.

    Raises ``RuntimeError`` on hash mismatch or persistent download failure.
    """
    last_err: Exception | None = None
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


def _make_operation_id(board: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"ota-{board}-{ts}"


def _normalise_version(version: str | None) -> str | None:
    if version is None:
        return None
    return version.strip().lstrip("v")


def _history_to_lines(serial_client: Any, *, limit: int = _SERIAL_HISTORY_LIMIT) -> list[str]:
    if not hasattr(serial_client, "snapshot_history"):
        return []

    lines: list[str] = []
    for entry in serial_client.snapshot_history(limit=limit):
        stamp = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S.%f")[:-3]
        lines.append(f"{stamp} {entry.direction.upper()}: {entry.raw}")
    return lines


def _write_ota_failure_report(report: dict[str, Any]) -> str | None:
    try:
        report_dir = logs_dir()
        report_path = report_dir / (
            f"ota_failure_{report['board']}_{report['operation_id']}.json"
        )
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(report_path)
    except Exception:
        log.exception("Failed to write OTA failure report")
        return None


# ---------------------------------------------------------------------------
# Merged-binary helpers
# ---------------------------------------------------------------------------

def extract_app_from_merged(data: bytes) -> bytes:
    """Return the app-only portion of a merged firmware binary.

    Merged binaries produced by ``esptool.py merge_bin`` contain:
      0x0000  bootloader
      0x8000  partition table
      0x10000 application

    OTA writes directly to the app partition, so we strip the first
    ``_APP_OFFSET`` (0x10000 = 64 KiB) bytes.
    """
    if len(data) <= _APP_OFFSET:
        raise ValueError(
            f"Firmware binary too small ({len(data)} bytes) to contain an app "
            f"image at offset {_APP_OFFSET:#x}."
        )
    return data[_APP_OFFSET:]


# ---------------------------------------------------------------------------
# Serial OTA flashing
# ---------------------------------------------------------------------------

class FirmwareFlasher:
    """Sends a firmware binary to a board via the serial NDJSON protocol.

    Requires a connected ``SerialClient`` instance.
    """

    def __init__(self, serial_client: Any) -> None:
        self._ser = serial_client

    def get_version(self, board: str = BOARD_S3) -> str | None:
        """Query firmware version from a board. Returns version string or None."""
        self._flush_rx_queue(reason=f"pre-fw_version:{board}")
        cmd: dict[str, Any] = {"cmd": "fw_version"}
        if board == BOARD_ESP32:
            cmd["board"] = "esp32"

        self._ser.send_obj(cmd)
        rsp = self._wait_response(
            "fw_version",
            timeout=_CMD_TIMEOUT,
            stage=f"fw_version:{board}",
            response_filter=lambda item: item.get("board") == board,
        )
        if rsp and rsp.get("ok"):
            return rsp.get("version")
        return None

    def flash(
        self,
        board: str,
        firmware: bytes,
        *,
        expected_version: str | None = None,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> None:
        """Flash firmware to a board over serial.

        Raises RuntimeError on failure.
        """
        total = len(firmware)
        operation_id = _make_operation_id(board)
        firmware_sha256 = compute_sha256(firmware)
        stage = "start"
        offset = 0
        log.info(
            "Starting OTA flash: op=%s board=%s size=%d sha256=%s expected_version=%s",
            operation_id,
            board,
            total,
            firmware_sha256,
            expected_version or "<unknown>",
        )

        try:
            self._flush_rx_queue(reason=f"pre-flash:{operation_id}")

            # 1. Begin
            stage = "begin"
            cmd_begin: dict[str, Any] = {"cmd": "fw_update_begin", "size": total}
            if board == BOARD_ESP32:
                cmd_begin["board"] = "esp32"
            self._ser.send_obj(cmd_begin)

            rsp = self._wait_response(
                "fw_update_begin",
                timeout=_CMD_TIMEOUT,
                operation_id=operation_id,
                stage=stage,
            )
            if not rsp or not rsp.get("ok"):
                err = rsp.get("error", "unknown") if rsp else "no_response"
                raise RuntimeError(f"fw_update_begin failed: {err}")

            # 2. Send data chunks
            stage = "data"
            while offset < total:
                chunk = firmware[offset:offset + OTA_CHUNK_SIZE]
                b64 = base64.b64encode(chunk).decode("ascii")
                cmd_data: dict[str, Any] = {"cmd": "fw_update_data", "data": b64}
                if board == BOARD_ESP32:
                    cmd_data["board"] = "esp32"
                self._ser.send_obj(cmd_data)

                rsp = self._wait_response(
                    "fw_update_data",
                    timeout=_CMD_TIMEOUT,
                    operation_id=operation_id,
                    stage=f"{stage}@{offset}",
                )
                if not rsp or not rsp.get("ok"):
                    err = rsp.get("error", "unknown") if rsp else "no_response"
                    raise RuntimeError(
                        f"fw_update_data failed at offset {offset}: {err}. "
                        "Per-chunk retry is disabled because the OTA protocol is not idempotent."
                    )

                offset += len(chunk)
                if progress_cb:
                    progress_cb(offset, total)
        except Exception as exc:
            # Abort on any failure.
            stage = f"{stage}-abort"
            try:
                abort_cmd: dict[str, Any] = {"cmd": "fw_update_abort"}
                if board == BOARD_ESP32:
                    abort_cmd["board"] = "esp32"
                self._ser.send_obj(abort_cmd)
            except Exception:
                log.warning("Failed to send OTA abort: op=%s board=%s", operation_id, board, exc_info=True)

            self._handle_flash_failure(
                operation_id=operation_id,
                board=board,
                stage=stage,
                expected_version=expected_version,
                firmware_size=total,
                firmware_sha256=firmware_sha256,
                offset=offset,
                error=exc,
            )
            raise

        # 3. Finalize
        try:
            stage = "end"
            cmd_end: dict[str, Any] = {"cmd": "fw_update_end"}
            if board == BOARD_ESP32:
                cmd_end["board"] = "esp32"
            self._ser.send_obj(cmd_end)

            rsp = self._wait_response(
                "fw_update_end",
                timeout=_END_TIMEOUT,
                operation_id=operation_id,
                stage=stage,
            )
            if not rsp or not rsp.get("ok"):
                err = rsp.get("error", "unknown") if rsp else "no_response"
                if expected_version:
                    verified = self._verify_version_after_flash(
                        board,
                        expected_version,
                        operation_id=operation_id,
                        stage="verify-after-end-failure",
                    )
                    if verified:
                        log.warning(
                            "OTA end response was not clean, but version verified: "
                            "op=%s board=%s version=%s err=%s",
                            operation_id,
                            board,
                            expected_version,
                            err,
                        )
                        return
                raise RuntimeError(f"fw_update_end failed: {err}")

            if expected_version and not self._verify_version_after_flash(
                board,
                expected_version,
                operation_id=operation_id,
                stage="verify-after-success",
            ):
                raise RuntimeError(
                    f"Flash completed but {board} did not report version {expected_version} after reboot"
                )
        except Exception as exc:
            self._handle_flash_failure(
                operation_id=operation_id,
                board=board,
                stage=stage,
                expected_version=expected_version,
                firmware_size=total,
                firmware_sha256=firmware_sha256,
                offset=offset,
                error=exc,
            )
            raise

        log.info("OTA flash complete for %s — device will reboot (op=%s)", board, operation_id)

    def _flush_rx_queue(self, *, reason: str) -> int:
        if not hasattr(self._ser, "drain_rx_queue"):
            return 0
        drained = self._ser.drain_rx_queue(limit=_QUEUE_DRAIN_LIMIT)
        if drained:
            log.debug(
                "Drained %d stale RX line(s) before %s: %s",
                len(drained),
                reason,
                "; ".join(line.raw for line in drained[-8:]),
            )
        return len(drained)

    def _verify_version_after_flash(
        self,
        board: str,
        expected_version: str,
        *,
        operation_id: str,
        stage: str,
    ) -> bool:
        wanted = _normalise_version(expected_version)
        for attempt in range(1, _VERIFY_RETRIES + 1):
            time.sleep(_VERIFY_DELAY)
            try:
                version = self.get_version(board)
            except Exception:
                log.debug(
                    "Version verify attempt %d/%d failed: op=%s board=%s stage=%s",
                    attempt,
                    _VERIFY_RETRIES,
                    operation_id,
                    board,
                    stage,
                    exc_info=True,
                )
                continue

            normalised = _normalise_version(version)
            log.info(
                "Version verify attempt %d/%d: op=%s board=%s reported=%s expected=%s",
                attempt,
                _VERIFY_RETRIES,
                operation_id,
                board,
                version,
                expected_version,
            )
            if normalised == wanted:
                return True
        return False

    def _handle_flash_failure(
        self,
        *,
        operation_id: str,
        board: str,
        stage: str,
        expected_version: str | None,
        firmware_size: int,
        firmware_sha256: str,
        offset: int,
        error: Exception,
    ) -> None:
        report_path = _write_ota_failure_report(
            {
                "timestamp": datetime.now().isoformat(),
                "operation_id": operation_id,
                "board": board,
                "stage": stage,
                "expected_version": expected_version,
                "firmware_size": firmware_size,
                "firmware_sha256": firmware_sha256,
                "last_confirmed_offset": offset,
                "connection_lost": bool(getattr(self._ser, "connection_lost", False)),
                "error_type": type(error).__name__,
                "error_message": str(error),
                "recent_serial_history": _history_to_lines(self._ser),
            }
        )
        log.exception(
            "OTA flash failed: op=%s board=%s stage=%s offset=%d/%d report=%s",
            operation_id,
            board,
            stage,
            offset,
            firmware_size,
            report_path or "<none>",
        )

    def _wait_response(
        self,
        expected_rsp: str,
        timeout: float = 10,
        *,
        operation_id: str = "",
        stage: str = "",
        response_filter: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any] | None:
        """Drain RX queue looking for a JSON response matching expected_rsp."""
        deadline = time.monotonic() + timeout
        unexpected: list[str] = []
        while time.monotonic() < deadline:
            if getattr(self._ser, "connection_lost", False):
                log.error(
                    "Serial connection lost while waiting for %s: op=%s stage=%s",
                    expected_rsp,
                    operation_id,
                    stage,
                )
                return None
            try:
                line = self._ser.rx.get(timeout=0.1)
            except Exception:
                continue

            if line.parsed and line.parsed.get("rsp") == expected_rsp:
                if response_filter and not response_filter(line.parsed):
                    unexpected.append(f"rejected:{line.raw}")
                    continue
                log.debug(
                    "Received expected response: op=%s stage=%s rsp=%s raw=%s",
                    operation_id,
                    stage,
                    expected_rsp,
                    line.raw,
                )
                return line.parsed

            if line.raw:
                unexpected.append(line.raw)

        recent_serial = _history_to_lines(self._ser)
        log.error(
            "Timeout waiting for %s: op=%s stage=%s timeout=%.1fs unexpected=%s recent_serial=%s",
            expected_rsp,
            operation_id,
            stage,
            timeout,
            unexpected[-8:],
            recent_serial[-12:],
        )
        return None


# ---------------------------------------------------------------------------
# High-level OTA helper used by the diagnostics UI
# ---------------------------------------------------------------------------

class FwUpdater:
    """Convenience wrapper around the lower-level OTA helpers.

    Provides the three operations the diagnostics view needs:
    ``check_versions``, ``do_update``, and ``flash_from_file``.
    """

    def __init__(self, serial_client: Any = None) -> None:
        self._ser = serial_client

    # -- version check (network only, serial optional) -------------------

    def check_versions(self) -> dict[str, Any]:
        """Return dict with *s3*, *esp32*, *update_available*, *latest* keys."""
        s3_ver: str | None = None
        esp32_ver: str | None = None

        # Try to read current device versions via serial.
        if self._ser:
            try:
                flasher = FirmwareFlasher(self._ser)
                s3_ver = flasher.get_version(BOARD_S3)
            except Exception:
                log.debug("Could not read S3 version", exc_info=True)
            try:
                flasher = FirmwareFlasher(self._ser)
                esp32_ver = flasher.get_version(BOARD_ESP32)
            except Exception:
                log.debug("Could not read ESP32 version", exc_info=True)

        info: dict[str, Any] = {
            "s3": s3_ver or "—",
            "esp32": esp32_ver or "—",
            "update_available": False,
            "latest": "—",
        }

        result = check_firmware_updates(
            current_s3=s3_ver,
            current_esp32=esp32_ver,
        )
        if result:
            info["update_available"] = True
            info["latest"] = result.get("version", "?")
            info["_result"] = result  # stash for do_update
        return info

    # -- OTA update from GitHub ------------------------------------------

    def do_update(
        self,
        *,
        progress_cb: Callable[[str, int], None] | None = None,
    ) -> None:
        """Download latest firmware from GitHub and flash via OTA."""
        if not self._ser:
            raise RuntimeError("No serial connection — cannot OTA flash.")

        # Re-fetch update info.
        flasher = FirmwareFlasher(self._ser)
        s3_ver = flasher.get_version(BOARD_S3)
        esp32_ver = flasher.get_version(BOARD_ESP32)
        result = check_firmware_updates(current_s3=s3_ver, current_esp32=esp32_ver)
        if not result:
            raise RuntimeError("No firmware update available.")

        boards = result["boards"]
        log.info(
            "Beginning coordinated firmware update: target=%s current_s3=%s current_esp32=%s boards=%s",
            result["version"],
            s3_ver,
            esp32_ver,
            ", ".join(boards.keys()),
        )
        for board, binfo in boards.items():
            if progress_cb:
                progress_cb(f"Downloading {binfo['asset_name']}…", 0)
            data = download_firmware(
                binfo["download_url"],
                expected_sha256=binfo.get("expected_sha256"),
                expected_size=binfo.get("size", 0),
            )
            # Release binaries are merged images — extract app portion for OTA.
            app_data = extract_app_from_merged(data)
            if progress_cb:
                progress_cb(f"Flashing {board}…", 0)
            flasher.flash(
                board, app_data,
                expected_version=result["version"],
                progress_cb=lambda done, tot, _b=board: (
                    progress_cb(f"Flashing {_b}…", int(done * 100 / tot))
                    if progress_cb else None
                ),
            )

        final_versions = {
            BOARD_S3: flasher.get_version(BOARD_S3),
            BOARD_ESP32: flasher.get_version(BOARD_ESP32),
        }
        target = _normalise_version(result["version"])
        missing = [board for board, version in final_versions.items() if not version]
        if missing:
            raise RuntimeError(
                "Firmware update finished but could not verify version from: "
                + ", ".join(missing)
            )
        mismatched = {
            board: version
            for board, version in final_versions.items()
            if _normalise_version(version) != target
        }
        if mismatched:
            raise RuntimeError(
                "Firmware update finished but versions are out of sync: "
                + ", ".join(f"{board}={version}" for board, version in mismatched.items())
            )

        log.info(
            "Firmware update sync verified: target=%s s3=%s esp32=%s",
            result["version"],
            final_versions[BOARD_S3],
            final_versions[BOARD_ESP32],
        )
        if progress_cb:
            progress_cb("Done", 100)

    # -- flash a local file ----------------------------------------------

    def flash_from_file(
        self,
        path: str,
        *,
        board: str = BOARD_S3,
        progress_cb: Callable[[str, int], None] | None = None,
    ) -> None:
        """Read a local firmware binary and flash via OTA."""
        if not self._ser:
            raise RuntimeError("No serial connection — cannot OTA flash.")

        import pathlib
        data = pathlib.Path(path).read_bytes()
        log.info("Flashing firmware from local file: path=%s board=%s size=%d", path, board, len(data))
        # If the file looks like a merged binary (has bootloader header before
        # the app offset), extract the app portion.
        if len(data) > _APP_OFFSET:
            app_data = extract_app_from_merged(data)
        else:
            app_data = data

        if progress_cb:
            progress_cb("Flashing…", 0)
        flasher = FirmwareFlasher(self._ser)
        flasher.flash(
            board, app_data,
            progress_cb=lambda done, tot: (
                progress_cb("Flashing…", int(done * 100 / tot))
                if progress_cb else None
            ),
        )
        if progress_cb:
            progress_cb("Done", 100)
