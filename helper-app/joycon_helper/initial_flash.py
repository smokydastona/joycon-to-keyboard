"""First-time firmware flashing via esptool.

Uses esptool (Espressif's official flash tool) to program blank ESP32 / ESP32-S3
boards through the ROM bootloader over USB.  This replaces the need for users to
install ESP-IDF or run esptool from the command line.

Supports:
 - Single merged binary  (bootloader + partition table + app at offset 0x0)
 - App-only binary       (flashed at the standard app offset 0x10000)
 - Full 3-file flash     (bootloader + partition table + app at correct offsets)

The board type (ESP32 vs ESP32-S3) is auto-detected from the connected chip.
"""

from __future__ import annotations

import io
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("joycon_helper.initial_flash")

# Standard ESP-IDF flash offsets.
_OFFSETS: Dict[str, Dict[str, int]] = {
    # ESP32-S3: bootloader at 0x0 (v5.x default).
    "esp32s3": {
        "bootloader": 0x0000,
        "partition_table": 0x8000,
        "app": 0x10000,
    },
    # ESP32 (original): bootloader at 0x1000.
    "esp32": {
        "bootloader": 0x1000,
        "partition_table": 0x8000,
        "app": 0x10000,
    },
}

# Maps esptool chip detection strings to our board names.
_CHIP_MAP: Dict[str, str] = {
    "ESP32-S3": "esp32s3",
    "ESP32-S3(beta2)": "esp32s3",
    "ESP32-S3(beta3)": "esp32s3",
    "ESP32": "esp32",
}


def detect_chip(port: str) -> Optional[str]:
    """Connect to the ROM bootloader and return the chip type.

    Returns ``"esp32s3"`` or ``"esp32"`` on success, ``None`` on failure.
    """
    try:
        import esptool
        # Capture esptool's stdout chatter.
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            args = ["--port", port, "chip_id"]
            esptool.main(args)
        except SystemExit:
            pass
        finally:
            output = sys.stdout.getvalue()
            sys.stdout, sys.stderr = old_stdout, old_stderr

        for line in output.splitlines():
            for chip_str, board in _CHIP_MAP.items():
                if chip_str in line:
                    log.info("Detected chip: %s → %s", chip_str, board)
                    return board
    except Exception:
        log.warning("Chip detection failed", exc_info=True)
    return None


def flash_firmware(
    port: str,
    *,
    app_bin: Optional[str] = None,
    bootloader_bin: Optional[str] = None,
    partition_table_bin: Optional[str] = None,
    merged_bin: Optional[str] = None,
    chip: Optional[str] = None,
    erase_all: bool = False,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> None:
    """Flash firmware to a board using esptool.

    Modes (pick one):
      1. ``merged_bin`` — a single file containing everything, flashed at 0x0.
      2. ``app_bin`` alone — flashed at the standard app offset (0x10000).
      3. ``app_bin`` + ``bootloader_bin`` + ``partition_table_bin`` — full flash.

    ``chip`` can be ``"esp32s3"`` or ``"esp32"``.  If *None*, auto-detected.
    ``erase_all`` erases the entire flash before writing (recommended for first flash).
    ``progress_cb`` is called with status strings for UI feedback.

    Raises ``RuntimeError`` on failure.
    """
    import esptool  # deferred to keep import cost low

    def _status(msg: str) -> None:
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # Validate inputs.
    if not merged_bin and not app_bin:
        raise RuntimeError("Provide either merged_bin or app_bin")

    # Auto-detect chip if needed.
    if not chip:
        _status("Detecting chip…")
        chip = detect_chip(port)
        if not chip:
            raise RuntimeError(
                "Could not detect chip type. Make sure the board is in download mode "
                "(hold BOOT + press RESET, then release BOOT)."
            )
    _status(f"Chip: {chip}")

    offsets = _OFFSETS.get(chip)
    if not offsets:
        raise RuntimeError(f"Unknown chip type: {chip}")

    # Build esptool argument list.
    args: List[str] = ["--port", port, "--chip", chip, "--baud", "921600"]

    if erase_all:
        _status("Erasing flash…")
        _run_esptool(args + ["erase_flash"])
        _status("Flash erased.")

    # Build write_flash command.
    write_args = args + ["write_flash", "--flash_mode", "dio", "--flash_size", "detect"]

    if merged_bin:
        # Merged binary: everything at offset 0.
        write_args += ["0x0", merged_bin]
        _status(f"Flashing merged binary: {Path(merged_bin).name}")
    elif bootloader_bin and partition_table_bin and app_bin:
        # Full 3-file flash.
        write_args += [
            hex(offsets["bootloader"]), bootloader_bin,
            hex(offsets["partition_table"]), partition_table_bin,
            hex(offsets["app"]), app_bin,
        ]
        _status("Flashing bootloader + partition table + app…")
    elif app_bin:
        # App-only flash (assumes bootloader + partition table already present).
        write_args += [hex(offsets["app"]), app_bin]
        _status(f"Flashing app binary at {hex(offsets['app'])}: {Path(app_bin).name}")
    else:
        raise RuntimeError("Invalid file combination")

    _run_esptool(write_args)
    _status("Flash complete! Reset the board to run the new firmware.")


def _run_esptool(args: List[str]) -> None:
    """Run esptool.main() with the given args.  Raises RuntimeError on failure."""
    import esptool

    log.info("esptool args: %s", args)

    old_stdout, old_stderr = sys.stdout, sys.stderr
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    sys.stdout = captured_out
    sys.stderr = captured_err
    try:
        esptool.main(args)
    except SystemExit as e:
        if e.code not in (None, 0):
            err_text = captured_err.getvalue() or captured_out.getvalue()
            raise RuntimeError(f"esptool failed (exit {e.code}): {err_text.strip()}")
    except Exception as e:
        err_text = captured_err.getvalue()
        raise RuntimeError(f"esptool error: {e}\n{err_text.strip()}")
    finally:
        output = captured_out.getvalue()
        sys.stdout, sys.stderr = old_stdout, old_stderr

    if output:
        for line in output.strip().splitlines():
            log.debug("esptool: %s", line)


def download_and_flash_initial(
    port: str,
    *,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> None:
    """Download the latest release binaries from GitHub and do a first-time flash.

    Downloads: bootloader.bin, partition-table.bin, and the app binary for
    the detected chip, then flashes all three at the correct offsets.
    Erases flash first (clean slate recommended for first flash).

    Falls back to app-only flash if bootloader/partition-table assets are
    not found in the release (the user would need an existing bootloader).

    Raises ``RuntimeError`` on failure.
    """
    from . import fw_updater

    def _status(msg: str) -> None:
        log.info(msg)
        if progress_cb:
            progress_cb(msg)

    # Detect chip first.
    _status("Detecting chip…")
    chip = detect_chip(port)
    if not chip:
        raise RuntimeError(
            "Could not detect chip. Ensure the board is in download mode "
            "(hold BOOT + press RESET, then release BOOT)."
        )
    _status(f"Detected: {chip}")

    # Figure out which app binary to download.
    if chip == "esp32s3":
        app_asset = fw_updater.FW_ASSET_S3
    else:
        app_asset = fw_updater.FW_ASSET_ESP32

    # Fetch release info.
    _status("Fetching latest release…")
    try:
        release = fw_updater._fetch_latest_release()
    except Exception as e:
        raise RuntimeError(f"Could not fetch release info: {e}")

    tag = release.get("tag_name", "unknown")
    _status(f"Release: {tag}")

    import tempfile, os

    with tempfile.TemporaryDirectory(prefix="bindbnd_") as tmpdir:
        # Download app binary (required).
        app_dl = fw_updater._find_asset(release, app_asset)
        if not app_dl:
            raise RuntimeError(f"Release {tag} has no asset named '{app_asset}'")

        _status(f"Downloading {app_asset}…")
        app_data = fw_updater.download_firmware(
            app_dl["browser_download_url"],
            expected_sha256=None,
        )
        app_path = os.path.join(tmpdir, app_asset)
        with open(app_path, "wb") as f:
            f.write(app_data)

        # Try to download bootloader + partition table (optional release assets).
        bl_name = f"{chip}-bootloader.bin"
        pt_name = f"{chip}-partition-table.bin"

        bl_asset = fw_updater._find_asset(release, bl_name)
        pt_asset = fw_updater._find_asset(release, pt_name)

        bl_path: Optional[str] = None
        pt_path: Optional[str] = None

        if bl_asset and pt_asset:
            _status(f"Downloading {bl_name}…")
            bl_data = fw_updater.download_firmware(bl_asset["browser_download_url"])
            bl_path = os.path.join(tmpdir, bl_name)
            with open(bl_path, "wb") as f:
                f.write(bl_data)

            _status(f"Downloading {pt_name}…")
            pt_data = fw_updater.download_firmware(pt_asset["browser_download_url"])
            pt_path = os.path.join(tmpdir, pt_name)
            with open(pt_path, "wb") as f:
                f.write(pt_data)
        else:
            _status("Bootloader/partition-table not in release — app-only flash.")

        # Flash.
        flash_firmware(
            port,
            app_bin=app_path,
            bootloader_bin=bl_path,
            partition_table_bin=pt_path,
            chip=chip,
            erase_all=True,
            progress_cb=progress_cb,
        )
