"""Razer mouse configuration over USB HID Feature Reports.

Implements the 90-byte Razer USB protocol reverse-engineered by the
OpenRazer and OpenSnek projects.  Supports reading device info, battery,
DPI, poll rate, idle time, and button remapping on supported Razer mice.

Anti-cheat safe: all remapping is written to the mouse's **onboard memory**
via standard USB HID Feature Reports.  The mouse's own MCU handles
everything — no software input injection, no kernel driver hooks, no
Synapse dependency.

Primary target: Razer Basilisk X HyperSpeed (VID 0x1532, PID 0x0083).
Protocol should work with other Razer mice using the same 90-byte report
structure (see SUPPORTED_DEVICES below).
"""

from __future__ import annotations

import json
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("joycon_helper.razer")

try:
    import hid as _hid  # type: ignore[import-untyped]
    HID_AVAILABLE = True
except ImportError:
    _hid = None  # type: ignore[assignment]
    HID_AVAILABLE = False
    log.warning("hidapi not installed — Razer mouse support disabled")


# ===================================================================
# USB identifiers
# ===================================================================
RAZER_VID = 0x1532
REPORT_SIZE = 90

# Supported devices: PID → (display_name, transaction_id, max_dpi, dpi_stages)
SUPPORTED_DEVICES: Dict[int, Dict[str, Any]] = {
    0x0083: {
        "name": "Basilisk X HyperSpeed",
        "txn_id": 0xFF,       # older wireless device
        "max_dpi": 16000,
        "dpi_stages": 5,
        "has_battery": True,
        "battery_type": "AA",
        "poll_rates": [125, 500, 1000],
    },
    0x0064: {
        "name": "Basilisk",
        "txn_id": 0x3F,
        "max_dpi": 16000,
        "dpi_stages": 5,
        "has_battery": False,
        "battery_type": None,
        "poll_rates": [125, 500, 1000],
    },
    0x0085: {
        "name": "Basilisk V2",
        "txn_id": 0x3F,
        "max_dpi": 20000,
        "dpi_stages": 5,
        "has_battery": False,
        "battery_type": None,
        "poll_rates": [125, 500, 1000],
    },
    0x0099: {
        "name": "Basilisk V3",
        "txn_id": 0x1F,
        "max_dpi": 26000,
        "dpi_stages": 5,
        "has_battery": False,
        "battery_type": None,
        "poll_rates": [125, 500, 1000],
    },
    0x00B9: {
        "name": "Basilisk V3 X HyperSpeed",
        "txn_id": 0x1F,
        "max_dpi": 18000,
        "dpi_stages": 5,
        "has_battery": True,
        "battery_type": "AA",
        "poll_rates": [125, 500, 1000],
    },
}

# ===================================================================
# Protocol constants (from OpenRazer / OpenSnek documentation)
# ===================================================================

# Status bytes
STATUS_NEW_COMMAND = 0x00
STATUS_BUSY = 0x01
STATUS_SUCCESS = 0x02
STATUS_FAILURE = 0x03
STATUS_TIMEOUT = 0x04
STATUS_NOT_SUPPORTED = 0x05

# Command classes
CLASS_STANDARD = 0x00
CLASS_CONFIG = 0x02
CLASS_DPI = 0x04
CLASS_MISC = 0x07
CLASS_LED = 0x0F

# Storage modes
NOSTORE = 0x00   # Apply immediately, don't persist
VARSTORE = 0x01  # Apply and save to device memory

# Poll rate encoding
POLL_RATE_MAP = {1000: 0x01, 500: 0x02, 125: 0x08}
POLL_RATE_REVERSE = {v: k for k, v in POLL_RATE_MAP.items()}

# Button slot IDs (physical/logical button → slot number)
BUTTON_SLOTS: Dict[str, int] = {
    "left":       0x01,
    "right":      0x02,
    "middle":     0x03,
    "back":       0x04,
    "forward":    0x05,
    "scroll_up":  0x09,
    "scroll_down": 0x0A,
}

BUTTON_SLOT_NAMES = {v: k for k, v in BUTTON_SLOTS.items()}

# Button display names
BUTTON_DISPLAY_NAMES: Dict[str, str] = {
    "left":       "Left Click",
    "right":      "Right Click",
    "middle":     "Middle Click",
    "back":       "Back (Side)",
    "forward":    "Forward (Side)",
    "scroll_up":  "Scroll Up",
    "scroll_down": "Scroll Down",
}

BUTTON_ORDER = ["left", "right", "middle", "back", "forward",
                "scroll_up", "scroll_down"]

# Button function classes (from OpenSnek protocol docs)
FUNC_DISABLED = 0x00
FUNC_MOUSE = 0x01
FUNC_KEYBOARD = 0x02
FUNC_DPI_CYCLE = 0x06

# Default button function blocks (7 bytes each: class, len, data[5])
DEFAULT_BUTTON_FUNCTIONS: Dict[int, bytes] = {
    0x01: bytes([0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00]),  # left click
    0x02: bytes([0x01, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00]),  # right click
    0x03: bytes([0x01, 0x01, 0x03, 0x00, 0x00, 0x00, 0x00]),  # middle click
    0x04: bytes([0x01, 0x01, 0x04, 0x00, 0x00, 0x00, 0x00]),  # back
    0x05: bytes([0x01, 0x01, 0x05, 0x00, 0x00, 0x00, 0x00]),  # forward
    0x09: bytes([0x01, 0x01, 0x09, 0x00, 0x00, 0x00, 0x00]),  # scroll up
    0x0A: bytes([0x01, 0x01, 0x0A, 0x00, 0x00, 0x00, 0x00]),  # scroll down
}

# HID keyboard keycodes (subset for button remapping actions)
HID_KEYCODES: Dict[str, int] = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "enter": 0x28, "escape": 0x29, "backspace": 0x2A, "tab": 0x2B,
    "space": 0x2C,
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D, "f5": 0x3E,
    "f6": 0x3F, "f7": 0x40, "f8": 0x41, "f9": 0x42, "f10": 0x43,
    "f11": 0x44, "f12": 0x45,
    # Extended function keys (F13–F24)
    "f13": 0x68, "f14": 0x69, "f15": 0x6A, "f16": 0x6B,
    "f17": 0x6C, "f18": 0x6D, "f19": 0x6E, "f20": 0x6F,
    "f21": 0x70, "f22": 0x71, "f23": 0x72, "f24": 0x73,
}

HID_KEYCODE_NAMES = {v: k.upper() for k, v in HID_KEYCODES.items()}

# Mouse button IDs used in function blocks
MOUSE_BUTTON_IDS: Dict[str, int] = {
    "left": 0x01, "right": 0x02, "middle": 0x03,
    "back": 0x04, "forward": 0x05,
    "scroll_up": 0x09, "scroll_down": 0x0A,
}

# Action strings for dropdown menus
REMAP_ACTIONS = [
    "default", "disabled",
    # Mouse actions
    "left_click", "right_click", "middle_click",
    "back", "forward", "scroll_up", "scroll_down",
    "dpi_cycle",
    # Keyboard keys (most useful for gaming)
    "key_a", "key_b", "key_c", "key_d", "key_e", "key_f",
    "key_g", "key_h", "key_i", "key_j", "key_k", "key_l",
    "key_m", "key_n", "key_o", "key_p", "key_q", "key_r",
    "key_s", "key_t", "key_u", "key_v", "key_w", "key_x",
    "key_y", "key_z",
    "key_1", "key_2", "key_3", "key_4", "key_5",
    "key_6", "key_7", "key_8", "key_9", "key_0",
    "key_space", "key_enter", "key_escape", "key_tab",
    "key_f1", "key_f2", "key_f3", "key_f4", "key_f5", "key_f6",
    "key_f7", "key_f8", "key_f9", "key_f10", "key_f11", "key_f12",
    "key_f13", "key_f14", "key_f15", "key_f16", "key_f17", "key_f18",
    "key_f19", "key_f20", "key_f21", "key_f22", "key_f23", "key_f24",
]


# ===================================================================
# CRC / report building
# ===================================================================

def _calculate_crc(report: bytearray) -> int:
    """XOR of bytes 2 through 87."""
    crc = 0
    for i in range(2, 88):
        crc ^= report[i]
    return crc


def _build_report(txn_id: int, cmd_class: int, cmd_id: int,
                  data_size: int, args: bytes = b"") -> bytearray:
    """Build a 90-byte Razer USB HID feature report."""
    report = bytearray(REPORT_SIZE)
    report[0] = STATUS_NEW_COMMAND
    report[1] = txn_id
    # bytes 2-3: remaining packets (0x0000)
    report[4] = 0x00  # protocol type
    report[5] = data_size
    report[6] = cmd_class
    report[7] = cmd_id
    # Copy args into bytes 8..87
    for i, b in enumerate(args):
        if i >= 80:
            break
        report[8 + i] = b
    report[88] = _calculate_crc(report)
    # byte 89 reserved = 0x00
    return report


def _parse_response(report: bytes) -> Optional[Dict[str, Any]]:
    """Parse a 90-byte response report.

    Returns dict with status, class, id, data_size, args on success.
    Returns None on failure or if status is not SUCCESS.
    """
    if len(report) < REPORT_SIZE:
        return None
    status = report[0]
    return {
        "status": status,
        "txn_id": report[1],
        "data_size": report[5],
        "cmd_class": report[6],
        "cmd_id": report[7],
        "args": bytes(report[8:88]),
        "crc": report[88],
    }


# ===================================================================
# Action encoding (action name → 7-byte function block for 0x02:0x0C)
# ===================================================================

def encode_button_action(action: str) -> Optional[bytes]:
    """Convert a user-facing action string to a 7-byte function block.

    Returns None if the action is not recognised.
    """
    action = action.strip().lower()

    if action == "disabled":
        return bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    if action == "dpi_cycle":
        return bytes([0x06, 0x01, 0x06, 0x00, 0x00, 0x00, 0x00])

    # Mouse button actions
    mouse_map = {
        "left_click":  0x01, "right_click": 0x02, "middle_click": 0x03,
        "back":        0x04, "forward":     0x05,
        "scroll_up":   0x09, "scroll_down": 0x0A,
    }
    if action in mouse_map:
        bid = mouse_map[action]
        return bytes([FUNC_MOUSE, 0x01, bid, 0x00, 0x00, 0x00, 0x00])

    # Keyboard key actions: "key_a" → HID keycode 0x04
    if action.startswith("key_"):
        key_name = action[4:]
        kc = HID_KEYCODES.get(key_name)
        if kc is not None:
            return bytes([FUNC_KEYBOARD, 0x02, 0x00, kc, 0x00, 0x00, 0x00])

    return None


def decode_button_action(block: bytes) -> str:
    """Convert a 7-byte function block to a user-facing action string."""
    if len(block) < 7:
        return "unknown"

    func_class = block[0]

    if func_class == FUNC_DISABLED:
        return "disabled"

    if func_class == FUNC_MOUSE:
        bid = block[2]
        reverse = {v: k for k, v in {
            "left_click": 0x01, "right_click": 0x02, "middle_click": 0x03,
            "back": 0x04, "forward": 0x05,
            "scroll_up": 0x09, "scroll_down": 0x0A,
        }.items()}
        return reverse.get(bid, f"mouse_0x{bid:02x}")

    if func_class == FUNC_KEYBOARD:
        kc = block[3]
        name = HID_KEYCODE_NAMES.get(kc)
        if name:
            return f"key_{name.lower()}"
        return f"key_0x{kc:02x}"

    if func_class == FUNC_DPI_CYCLE:
        return "dpi_cycle"

    return f"func_0x{func_class:02x}"


# ===================================================================
# Data classes
# ===================================================================

@dataclass
class RazerDeviceInfo:
    """Info about a discovered Razer device."""
    path: bytes              # hidapi device path
    pid: int                 # USB product ID
    serial_number: str
    product_string: str
    interface_number: int
    manufacturer_string: str = ""

    @property
    def device_meta(self) -> Dict[str, Any]:
        return SUPPORTED_DEVICES.get(self.pid, {})

    @property
    def display_name(self) -> str:
        meta = self.device_meta
        name = meta.get("name", f"Razer 0x{self.pid:04x}")
        sn = self.serial_number or "no-serial"
        return f"{name} ({sn})"

    @property
    def device_id(self) -> str:
        if self.serial_number:
            return f"razer_{self.pid:04x}_{self.serial_number}"
        return f"razer_{self.pid:04x}_{hash(self.path) & 0xFFFFFFFF:08x}"

    @property
    def txn_id(self) -> int:
        return self.device_meta.get("txn_id", 0xFF)


@dataclass
class RazerDeviceState:
    """Live state read from a Razer device."""
    serial: str = ""
    firmware_version: str = ""
    battery_level: int = -1       # 0–100, or -1 if unavailable
    battery_charging: bool = False
    dpi_x: int = 0
    dpi_y: int = 0
    dpi_stages: List[Tuple[int, int]] = field(default_factory=list)
    active_dpi_stage: int = 0     # 1-indexed
    poll_rate: int = 0            # Hz
    idle_time: int = 0            # seconds
    button_bindings: Dict[str, str] = field(default_factory=dict)
    hypershift_bindings: Dict[str, str] = field(default_factory=dict)


@dataclass
class RazerProfile:
    """A saveable Razer mouse configuration."""
    name: str = "Default"
    dpi_stages: List[Tuple[int, int]] = field(
        default_factory=lambda: [(800, 800), (1800, 1800), (4000, 4000),
                                 (9000, 9000), (16000, 16000)]
    )
    active_dpi_stage: int = 1
    poll_rate: int = 1000
    idle_time: int = 300    # seconds
    button_bindings: Dict[str, str] = field(default_factory=lambda: {
        "left": "default", "right": "default", "middle": "default",
        "back": "default", "forward": "default",
        "scroll_up": "default", "scroll_down": "default",
    })
    hypershift_bindings: Dict[str, str] = field(default_factory=lambda: {
        "left": "default", "right": "default", "middle": "default",
        "back": "default", "forward": "default",
        "scroll_up": "default", "scroll_down": "default",
    })

    # Sister profile linking: which Joy-Con slot this should auto-apply with
    sister_slot: Optional[int] = None  # 0–3, or None

    def to_dict(self) -> dict:
        return {
            "ver": 2,
            "name": self.name,
            "dpi_stages": [list(s) for s in self.dpi_stages],
            "active_dpi_stage": self.active_dpi_stage,
            "poll_rate": self.poll_rate,
            "idle_time": self.idle_time,
            "button_bindings": dict(self.button_bindings),
            "hypershift_bindings": dict(self.hypershift_bindings),
            "sister_slot": self.sister_slot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RazerProfile":
        p = cls()
        p.name = d.get("name", "Default")
        raw_stages = d.get("dpi_stages", [])
        if raw_stages:
            p.dpi_stages = [(s[0], s[1]) for s in raw_stages]
        p.active_dpi_stage = d.get("active_dpi_stage", 1)
        p.poll_rate = d.get("poll_rate", 1000)
        p.idle_time = d.get("idle_time", 300)
        p.button_bindings = d.get("button_bindings", p.button_bindings)
        p.hypershift_bindings = d.get("hypershift_bindings",
                                      p.hypershift_bindings)
        p.sister_slot = d.get("sister_slot", None)
        return p

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        log.info("Saved Razer profile '%s' → %s", self.name, path)

    @classmethod
    def load(cls, path: str) -> "RazerProfile":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ===================================================================
# Device communication
# ===================================================================

class RazerDevice:
    """Manages USB HID communication with a Razer mouse."""

    def __init__(self) -> None:
        self._dev: Any = None
        self._info: Optional[RazerDeviceInfo] = None

    @property
    def is_open(self) -> bool:
        return self._dev is not None

    @property
    def info(self) -> Optional[RazerDeviceInfo]:
        return self._info

    # ── Enumeration ──────────────────────────────────────────────

    @staticmethod
    def enumerate() -> List[RazerDeviceInfo]:
        """Find all connected supported Razer devices.

        Returns one entry per device (filtered to the control interface).
        """
        if not HID_AVAILABLE:
            return []

        results: List[RazerDeviceInfo] = []
        try:
            devs = _hid.enumerate(RAZER_VID, 0)  # all Razer devices
        except Exception as e:
            log.error("HID enumerate failed: %s", e)
            return []

        seen_pids: set = set()
        for d in devs:
            pid = d.get("product_id", 0)
            if pid not in SUPPORTED_DEVICES:
                continue
            iface = d.get("interface_number", -1)
            # Use interface 0 for Razer mice (control interface)
            if iface != 0:
                continue
            # Deduplicate by PID+serial
            key = (pid, d.get("serial_number", ""))
            if key in seen_pids:
                continue
            seen_pids.add(key)

            path = d.get("path")
            if not path:
                continue
            results.append(RazerDeviceInfo(
                path=path,
                pid=pid,
                serial_number=d.get("serial_number", "") or "",
                product_string=d.get("product_string", "") or "",
                interface_number=iface,
                manufacturer_string=d.get("manufacturer_string", "") or "",
            ))

        log.info("Found %d supported Razer device(s)", len(results))
        return results

    # ── Open / close ─────────────────────────────────────────────

    def open(self, device_info: RazerDeviceInfo) -> None:
        if not HID_AVAILABLE:
            raise RuntimeError("hidapi not installed")
        self.close()
        self._dev = _hid.device()
        self._dev.open_path(device_info.path)
        self._info = device_info
        log.info("Opened Razer device: %s", device_info.display_name)

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None
            self._info = None

    # ── Low-level transport ──────────────────────────────────────

    def _send_report(self, report: bytearray) -> Optional[Dict[str, Any]]:
        """Send a feature report and read the response.

        Validates CRC and transaction ID in the response.
        Returns parsed response dict or None on failure.
        """
        if self._dev is None:
            raise RuntimeError("Device not open")

        expected_txn = report[1]

        # hidapi: send_feature_report expects report[0] = report ID (0x00)
        try:
            self._dev.send_feature_report(bytes(report))
        except Exception as e:
            log.error("Razer HID write failed: %s", e)
            raise RuntimeError(f"Razer USB write failed (device disconnected?): {e}") from e

        # Small delay for device to process
        time.sleep(0.02)

        # Read feature report back (report ID 0x00)
        try:
            resp = self._dev.get_feature_report(0x00, REPORT_SIZE)
        except Exception as e:
            log.debug("Feature report read failed: %s", e)
            return None

        if resp is None or len(resp) < REPORT_SIZE:
            return None

        parsed = _parse_response(bytes(resp))
        if parsed is None:
            return None

        # Validate CRC: XOR of bytes 2–87
        expected_crc = _calculate_crc(bytearray(resp))
        if resp[88] != expected_crc:
            log.warning("Razer CRC mismatch: got 0x%02X, expected 0x%02X",
                        resp[88], expected_crc)
            # Still return the data — CRC failures can be transient

        # Validate transaction ID
        if parsed["txn_id"] != expected_txn:
            log.debug("Razer txn_id mismatch: got 0x%02X, expected 0x%02X",
                      parsed["txn_id"], expected_txn)

        return parsed

    def _command(self, cmd_class: int, cmd_id: int,
                 data_size: int, args: bytes = b"",
                 retries: int = 2) -> Optional[Dict[str, Any]]:
        """Send a command and return parsed response. Retries on BUSY."""
        if self._info is None:
            return None

        report = _build_report(self._info.txn_id, cmd_class, cmd_id,
                               data_size, args)

        for attempt in range(retries + 1):
            resp = self._send_report(report)
            if resp is None:
                continue
            if resp["status"] == STATUS_SUCCESS:
                return resp
            if resp["status"] == STATUS_BUSY and attempt < retries:
                time.sleep(0.05)
                continue
            if resp["status"] == STATUS_NOT_SUPPORTED:
                log.debug("Command 0x%02x:0x%02x not supported",
                          cmd_class, cmd_id)
                return None
            if resp["status"] == STATUS_FAILURE:
                log.debug("Command 0x%02x:0x%02x failed (status 0x03)",
                          cmd_class, cmd_id)
                return None
        return None

    # ── Read commands ────────────────────────────────────────────

    def get_serial(self) -> str:
        """Read device serial number (Class 0x00, ID 0x82)."""
        resp = self._command(CLASS_STANDARD, 0x82, 0x16)
        if resp:
            raw = resp["args"][:22]
            return raw.rstrip(b"\x00").decode("ascii", errors="replace")
        return ""

    def get_firmware_version(self) -> str:
        """Read firmware version (Class 0x00, ID 0x81)."""
        resp = self._command(CLASS_STANDARD, 0x81, 0x02)
        if resp:
            major = resp["args"][0]
            minor = resp["args"][1]
            return f"{major}.{minor}"
        return ""

    def get_poll_rate(self) -> int:
        """Read current poll rate (Class 0x00, ID 0x85)."""
        resp = self._command(CLASS_STANDARD, 0x85, 0x01)
        if resp:
            rate_byte = resp["args"][0]
            return POLL_RATE_REVERSE.get(rate_byte, 0)
        return 0

    def set_poll_rate(self, hz: int) -> bool:
        """Set poll rate (Class 0x00, ID 0x05)."""
        rate_byte = POLL_RATE_MAP.get(hz)
        if rate_byte is None:
            log.error("Invalid poll rate: %d", hz)
            return False
        resp = self._command(CLASS_STANDARD, 0x05, 0x01, bytes([rate_byte]))
        return resp is not None

    def get_dpi(self) -> Tuple[int, int]:
        """Read current DPI XY (Class 0x04, ID 0x85)."""
        resp = self._command(CLASS_DPI, 0x85, 0x07, bytes([NOSTORE]))
        if resp:
            args = resp["args"]
            dpi_x = (args[1] << 8) | args[2]
            dpi_y = (args[3] << 8) | args[4]
            return (dpi_x, dpi_y)
        return (0, 0)

    def set_dpi(self, dpi_x: int, dpi_y: int,
                persist: bool = True) -> bool:
        """Set DPI XY (Class 0x04, ID 0x05).

        DPI values are clamped to device max_dpi.
        """
        max_dpi = 16000
        if self._info:
            max_dpi = self._info.device_meta.get("max_dpi", 16000)
        dpi_x = max(100, min(dpi_x, max_dpi))
        dpi_y = max(100, min(dpi_y, max_dpi))
        store = VARSTORE if persist else NOSTORE
        args = bytearray(7)
        args[0] = store
        args[1] = (dpi_x >> 8) & 0xFF
        args[2] = dpi_x & 0xFF
        args[3] = (dpi_y >> 8) & 0xFF
        args[4] = dpi_y & 0xFF
        resp = self._command(CLASS_DPI, 0x05, 0x07, bytes(args))
        return resp is not None

    def get_dpi_stages(self) -> Tuple[int, List[Tuple[int, int]]]:
        """Read DPI stage table (Class 0x04, ID 0x86).

        Returns (active_stage_1indexed, [(dpi_x, dpi_y), ...]).
        """
        resp = self._command(CLASS_DPI, 0x86, 0x26, bytes([VARSTORE]))
        if resp:
            args = resp["args"]
            active = args[1]   # 1-indexed stage ID
            count = args[2]
            stages: List[Tuple[int, int]] = []
            for i in range(min(count, 5)):
                off = 3 + i * 7
                # stage_id = args[off]
                dpi_x = (args[off + 1] << 8) | args[off + 2]
                dpi_y = (args[off + 3] << 8) | args[off + 4]
                stages.append((dpi_x, dpi_y))
            return (active, stages)
        return (0, [])

    def set_dpi_stages(self, active: int,
                       stages: List[Tuple[int, int]]) -> bool:
        """Write DPI stage table (Class 0x04, ID 0x06).

        ``active``: 1-indexed active stage.
        ``stages``: list of (dpi_x, dpi_y) tuples (max 5).
        """
        args = bytearray(0x26)  # 38 bytes
        args[0] = VARSTORE
        args[1] = active
        args[2] = len(stages)
        for i, (dx, dy) in enumerate(stages[:5]):
            off = 3 + i * 7
            args[off] = i + 1   # stage ID (1-indexed)
            args[off + 1] = (dx >> 8) & 0xFF
            args[off + 2] = dx & 0xFF
            args[off + 3] = (dy >> 8) & 0xFF
            args[off + 4] = dy & 0xFF
        resp = self._command(CLASS_DPI, 0x06, 0x26, bytes(args))
        return resp is not None

    def get_battery(self) -> Tuple[int, bool]:
        """Read battery level (Class 0x07, ID 0x80).

        Returns (percent 0-100, is_charging).
        Returns (-1, False) if battery is not available.
        """
        resp = self._command(CLASS_MISC, 0x80, 0x02)
        if resp:
            charging = resp["args"][0] != 0x00
            raw_level = resp["args"][1]
            # Scale 0-255 → 0-100
            if raw_level <= 100:
                pct = raw_level
            else:
                pct = int(raw_level / 255 * 100)
            return (pct, charging)
        return (-1, False)

    def get_idle_time(self) -> int:
        """Read idle/sleep timeout in seconds (Class 0x07, ID 0x83)."""
        resp = self._command(CLASS_MISC, 0x83, 0x02)
        if resp:
            return (resp["args"][0] << 8) | resp["args"][1]
        return 0

    def set_idle_time(self, seconds: int) -> bool:
        """Set idle/sleep timeout (Class 0x07, ID 0x03). 60–900 seconds."""
        seconds = max(60, min(900, seconds))
        args = bytes([(seconds >> 8) & 0xFF, seconds & 0xFF])
        resp = self._command(CLASS_MISC, 0x03, 0x02, args)
        return resp is not None

    def get_button_function(self, slot: int,
                            hypershift: bool = False) -> Optional[bytes]:
        """Read a button's function block (Class 0x02, ID 0x8C).

        ``hypershift``: if True, reads from the HyperShift layer (0x01)
        instead of the normal layer (0x00).
        Returns 7-byte function block or None.
        """
        args = bytearray(10)
        args[0] = 0x00   # profile: direct/effective layer
        args[1] = slot
        args[2] = 0x01 if hypershift else 0x00
        resp = self._command(CLASS_CONFIG, 0x8C, 0x0A, bytes(args))
        if resp:
            return bytes(resp["args"][3:10])
        return None

    def set_button_function(self, slot: int, func_block: bytes,
                            persist: bool = True,
                            hypershift: bool = False) -> bool:
        """Write a button's function block (Class 0x02, ID 0x0C).

        ``func_block``: 7-byte function block (class, len, data[5]).
        ``hypershift``: if True, writes to the HyperShift layer (0x01).
        """
        args = bytearray(10)
        args[0] = 0x01 if persist else 0x00  # profile slot
        args[1] = slot
        args[2] = 0x01 if hypershift else 0x00
        args[3:10] = func_block[:7]
        resp = self._command(CLASS_CONFIG, 0x0C, 0x0A, bytes(args))
        return resp is not None

    def get_led_brightness(self, led_id: int = 0x01) -> int:
        """Read LED brightness (Class 0x0F, ID 0x84)."""
        args = bytes([VARSTORE, led_id, 0x00])
        resp = self._command(CLASS_LED, 0x84, 0x03, args)
        if resp:
            return resp["args"][2]
        return -1

    def set_led_brightness(self, brightness: int,
                           led_id: int = 0x01) -> bool:
        """Set LED brightness (Class 0x0F, ID 0x04)."""
        args = bytes([VARSTORE, led_id, brightness & 0xFF])
        resp = self._command(CLASS_LED, 0x04, 0x03, args)
        return resp is not None

    # ── Composite reads ──────────────────────────────────────────

    def read_full_state(self) -> RazerDeviceState:
        """Read all available state from the device."""
        state = RazerDeviceState()

        state.serial = self.get_serial()
        state.firmware_version = self.get_firmware_version()

        meta = self._info.device_meta if self._info else {}
        if meta.get("has_battery", False):
            pct, charging = self.get_battery()
            state.battery_level = pct
            state.battery_charging = charging

        state.dpi_x, state.dpi_y = self.get_dpi()
        active, stages = self.get_dpi_stages()
        state.active_dpi_stage = active
        state.dpi_stages = stages

        state.poll_rate = self.get_poll_rate()
        state.idle_time = self.get_idle_time()

        # Read button bindings (normal layer)
        for name, slot in BUTTON_SLOTS.items():
            block = self.get_button_function(slot)
            if block:
                state.button_bindings[name] = decode_button_action(block)
            else:
                state.button_bindings[name] = "unknown"

        # Read HyperShift bindings
        for name, slot in BUTTON_SLOTS.items():
            block = self.get_button_function(slot, hypershift=True)
            if block:
                state.hypershift_bindings[name] = decode_button_action(block)
            else:
                state.hypershift_bindings[name] = "unknown"

        return state

    # ── Profile application ──────────────────────────────────────

    def apply_profile(self, profile: RazerProfile) -> Tuple[int, int]:
        """Apply a full profile. Returns (success_count, error_count)."""
        ok = 0
        err = 0

        # DPI stages
        if profile.dpi_stages:
            if self.set_dpi_stages(profile.active_dpi_stage,
                                   profile.dpi_stages):
                ok += 1
            else:
                err += 1

        # Poll rate
        if profile.poll_rate:
            if self.set_poll_rate(profile.poll_rate):
                ok += 1
            else:
                err += 1

        # Idle time
        if profile.idle_time:
            if self.set_idle_time(profile.idle_time):
                ok += 1
            else:
                err += 1

        # Button bindings
        for name, action in profile.button_bindings.items():
            if action == "default":
                slot = BUTTON_SLOTS.get(name)
                if slot and slot in DEFAULT_BUTTON_FUNCTIONS:
                    if self.set_button_function(slot,
                                               DEFAULT_BUTTON_FUNCTIONS[slot]):
                        ok += 1
                    else:
                        err += 1
            else:
                block = encode_button_action(action)
                if block:
                    slot = BUTTON_SLOTS.get(name)
                    if slot and self.set_button_function(slot, block):
                        ok += 1
                    else:
                        err += 1

        # HyperShift button bindings
        for name, action in profile.hypershift_bindings.items():
            if action == "default":
                slot = BUTTON_SLOTS.get(name)
                if slot and slot in DEFAULT_BUTTON_FUNCTIONS:
                    if self.set_button_function(slot,
                                               DEFAULT_BUTTON_FUNCTIONS[slot],
                                               hypershift=True):
                        ok += 1
                    else:
                        err += 1
            else:
                block = encode_button_action(action)
                if block:
                    slot = BUTTON_SLOTS.get(name)
                    if slot and self.set_button_function(slot, block,
                                                        hypershift=True):
                        ok += 1
                    else:
                        err += 1

        log.info("Razer profile '%s' applied: %d ok, %d errors",
                 profile.name, ok, err)
        return (ok, err)


# ===================================================================
# Profile storage
# ===================================================================

def get_profiles_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", ""))
    else:
        base = Path.home() / ".config"
    d = base / "BindBandit" / "razer"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_saved_profiles() -> List[str]:
    d = get_profiles_dir()
    return sorted(p.stem for p in d.glob("*.json"))


def save_profile(profile: RazerProfile) -> str:
    path = get_profiles_dir() / f"{profile.name}.json"
    profile.save(str(path))
    return str(path)


def load_profile(name: str) -> RazerProfile:
    path = get_profiles_dir() / f"{name}.json"
    return RazerProfile.load(str(path))


def delete_profile(name: str) -> None:
    path = get_profiles_dir() / f"{name}.json"
    if path.exists():
        path.unlink()
        log.info("Deleted Razer profile '%s'", name)


def _registry_path() -> Path:
    return get_profiles_dir() / "_devices.json"


def load_device_registry() -> Dict[str, dict]:
    p = _registry_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_device_registry(registry: Dict[str, dict]) -> None:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
        f.write("\n")
