"""Persistent device cache — remembers every device the app has connected to.

Stored in the OS application-data folder as ``device_cache.json``.  Used to:

* Show a "quick reconnect" list on the dashboard after a firmware update.
* Pre-seed the Devices view with device tabs for previously configured
  peripherals before they are physically reconnected.
* Persist device-level metadata (BDA, HID IDs) across sessions.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("joycon_helper.device_cache")

# ---------------------------------------------------------------------------
# DeviceEntry
# ---------------------------------------------------------------------------

@dataclass
class DeviceEntry:
    """One cached device record."""

    #: Stable ID used as a dict key and tab identifier.
    #: Format: ``"joycon-L"``, ``"joycon-R"``, ``"m913-<vid>-<pid>"``, ``"razer-<vid>-<pid>"``.
    id: str

    #: Broad category: ``"joycon"`` | ``"m913"`` | ``"razer"``
    type: str

    #: Transport: ``"esp32-bt"`` (Bluetooth via ESP32) | ``"pc-hid"`` (USB HID on host PC)
    source: str

    #: Human-readable name (e.g. ``"Joy-Con (L)"``)
    name: str

    #: Bluetooth device address, colon-separated hex (BT devices only)
    bda: str = ""

    #: USB Vendor ID (decimal) for HID devices
    hid_vendor: int = 0

    #: USB Product ID (decimal) for HID devices
    hid_product: int = 0

    #: USB serial number string (may be empty)
    hid_serial: str = ""

    #: UTC ISO timestamp of last successful connection
    last_seen: str = ""

    #: True while the device is connected in this session (not persisted)
    connected: bool = field(default=False, compare=False)

    #: Latest battery level 0-4 (runtime only, not persisted)
    battery: int | None = field(default=None, compare=False)

    #: Latest round-trip latency in ms (BT devices, runtime only, not persisted)
    latency_ms: float | None = field(default=None, compare=False)

    #: Arbitrary extra metadata (persisted if present)
    meta: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    def touch(self) -> None:
        """Update last_seen to now (UTC)."""
        self.last_seen = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Strip runtime-only fields before saving
        d.pop("connected", None)
        d.pop("battery", None)
        d.pop("latency_ms", None)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DeviceEntry":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# DeviceCache
# ---------------------------------------------------------------------------

class DeviceCache:
    """Loads and persists a list of :class:`DeviceEntry` records."""

    def __init__(self) -> None:
        self._devices: dict[str, DeviceEntry] = {}
        self._path = self._default_path()
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _default_path() -> str:
        try:
            from PyQt6.QtCore import QStandardPaths
            dirs = QStandardPaths.standardLocations(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            base = dirs[0] if dirs else os.path.expanduser("~")
        except Exception:
            base = os.path.expanduser("~")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "device_cache.json")

    def _load(self) -> None:
        try:
            if not os.path.isfile(self._path):
                return
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("devices", []):
                try:
                    entry = DeviceEntry.from_dict(item)
                    self._devices[entry.id] = entry
                except Exception as exc:
                    log.debug("Skipping malformed cache entry: %s", exc)
        except Exception as exc:
            log.warning("Could not load device cache: %s", exc)

    def save(self) -> None:
        """Persist the cache to disk."""
        try:
            payload = {"devices": [e.to_dict() for e in self._devices.values()]}
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except Exception as exc:
            log.warning("Could not save device cache: %s", exc)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_or_update(self, entry: DeviceEntry, autosave: bool = True) -> None:
        """Insert or replace a device entry."""
        entry.touch()
        self._devices[entry.id] = entry
        if autosave:
            self.save()

    def remove(self, device_id: str, autosave: bool = True) -> None:
        """Remove a device by ID (no-op if not found)."""
        self._devices.pop(device_id, None)
        if autosave:
            self.save()

    def get(self, device_id: str) -> DeviceEntry | None:
        """Return the entry for *device_id*, or ``None``."""
        return self._devices.get(device_id)

    def get_all(self) -> list[DeviceEntry]:
        """Return all entries, most-recently-seen first."""
        return sorted(
            self._devices.values(),
            key=lambda e: e.last_seen or "",
            reverse=True,
        )

    def get_by_source(self, source: str) -> list[DeviceEntry]:
        """Return all entries with the given source (``'esp32-bt'`` or ``'pc-hid'``)."""
        return [e for e in self.get_all() if e.source == source]

    def mark_connected(self, device_id: str, connected: bool) -> None:
        """Set runtime ``connected`` flag; does **not** persist."""
        entry = self._devices.get(device_id)
        if entry is not None:
            entry.connected = connected
            if connected:
                entry.touch()

    def set_battery(self, device_id: str, level: int) -> None:
        """Update runtime battery level; does **not** persist."""
        entry = self._devices.get(device_id)
        if entry is not None:
            entry.battery = level

    def set_latency(self, device_id: str, latency_ms: float) -> None:
        """Update runtime latency; does **not** persist."""
        entry = self._devices.get(device_id)
        if entry is not None:
            entry.latency_ms = latency_ms

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def make_joycon_id(side: str) -> str:
        """Return the stable ID for a Joy-Con side (``'L'`` or ``'R'``)."""
        return f"joycon-{side.upper()}"

    @staticmethod
    def make_hid_id(device_type: str, vendor_id: int, product_id: int) -> str:
        """Return a stable ID for a USB HID device."""
        return f"{device_type}-{vendor_id:04x}-{product_id:04x}"
