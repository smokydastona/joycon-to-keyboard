"""Centralised persistent data directory for Bind Bandit.

All user-generated data lives under a single roaming directory so it
survives application updates, reinstalls, and is portable across
machines when roaming profiles are enabled.

Layout::

    %APPDATA%/BindBandit/          (Windows)
    ~/.config/BindBandit/          (Linux / macOS)
    ├── state.json                 # session state (last slot, port, window, etc.)
    ├── device_cache.json          # remembered devices
    ├── app_profiles.json          # app-switcher rules
    ├── profiles/                  # user Joy-Con / bridge mapping profiles
    │   ├── slot_0.json
    │   ├── slot_1.json
    │   └── ...
    ├── m913/                      # M913 keypad profiles + device registry
    │   └── ...
    └── razer/                     # Razer mouse profiles + device registry
        └── ...

Every path helper creates the directory if it doesn't exist yet.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger("joycon_helper.user_data")

# ------------------------------------------------------------------
# Root data directory
# ------------------------------------------------------------------

_cached_data_dir: Path | None = None


def data_dir() -> Path:
    """Return (and create) the top-level persistent data directory."""
    global _cached_data_dir
    if _cached_data_dir is not None:
        return _cached_data_dir

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", ""))
    else:
        base = Path.home() / ".config"
    d = base / "BindBandit"
    d.mkdir(parents=True, exist_ok=True)
    _cached_data_dir = d
    return d


# ------------------------------------------------------------------
# Sub-directory helpers
# ------------------------------------------------------------------

def profiles_dir() -> Path:
    """``<data>/profiles/`` — user-created Joy-Con / bridge mapping profiles."""
    d = data_dir() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def m913_profiles_dir() -> Path:
    """``<data>/m913/`` — M913 keypad profiles & device registry."""
    d = data_dir() / "m913"
    d.mkdir(parents=True, exist_ok=True)
    return d


def razer_profiles_dir() -> Path:
    """``<data>/razer/`` — Razer mouse profiles & device registry."""
    d = data_dir() / "razer"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------
# File path helpers
# ------------------------------------------------------------------

def device_cache_path() -> Path:
    """``<data>/device_cache.json``."""
    return data_dir() / "device_cache.json"


def app_rules_path() -> Path:
    """``<data>/app_profiles.json`` — app-switcher rules."""
    return data_dir() / "app_profiles.json"


def state_path() -> Path:
    """``<data>/state.json`` — lightweight session state."""
    return data_dir() / "state.json"


# ------------------------------------------------------------------
# Session state  (last slot, last port, per-slot profiles, etc.)
# ------------------------------------------------------------------

def save_state(state: dict[str, Any]) -> None:
    """Atomically persist session state to ``state.json``."""
    p = state_path()
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(p)
    except Exception as exc:
        log.warning("Could not save session state: %s", exc)


def load_state() -> dict[str, Any]:
    """Load session state, returning an empty dict on any error."""
    p = state_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as exc:
        log.warning("Could not load session state: %s", exc)
    return {}


# ------------------------------------------------------------------
# Per-slot profile persistence
# ------------------------------------------------------------------

def save_slot_profile(slot: int, profile: dict[str, Any]) -> None:
    """Save a profile dict for the given slot (0-3)."""
    d = profiles_dir()
    p = d / f"slot_{slot}.json"
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(p)
    except Exception as exc:
        log.warning("Could not save slot %d profile: %s", slot, exc)


def load_slot_profile(slot: int) -> dict[str, Any] | None:
    """Load a previously saved profile for *slot*, or ``None``."""
    p = profiles_dir() / f"slot_{slot}.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as exc:
        log.warning("Could not load slot %d profile: %s", slot, exc)
    return None


def list_saved_slot_profiles() -> list[int]:
    """Return a sorted list of slot numbers that have saved profiles on disk."""
    d = profiles_dir()
    if not d.is_dir():
        return []
    slots: list[int] = []
    for p in d.glob("slot_*.json"):
        try:
            n = int(p.stem.split("_", 1)[1])
            if 0 <= n <= 3:
                slots.append(n)
        except (ValueError, IndexError):
            continue
    return sorted(slots)


# ------------------------------------------------------------------
# Migration — move files from legacy locations to the canonical dir
# ------------------------------------------------------------------

def migrate_legacy_files() -> None:
    """One-time migration of data from older locations into ``data_dir()``.

    Handles:
    * ``device_cache.json`` in the Qt AppDataLocation (pre-unified path)
    * ``app_profiles.json`` next to the executable or in cwd
    """
    _migrate_device_cache()
    _migrate_app_rules()


def _migrate_device_cache() -> None:
    """Move device_cache.json from Qt's AppDataLocation if it exists elsewhere."""
    target = device_cache_path()
    if target.is_file():
        return  # already migrated

    # Qt's AppDataLocation on Windows is typically
    # C:\Users\<user>\AppData\Local\JoyConBridge\Bind Bandit
    try:
        from PyQt6.QtCore import QStandardPaths

        dirs = QStandardPaths.standardLocations(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        for d in dirs:
            old = Path(d) / "device_cache.json"
            if old.is_file() and old != target:
                shutil.copy2(str(old), str(target))
                log.info("Migrated device_cache.json from %s", old)
                return
    except Exception as exc:
        log.debug("Qt migration check skipped: %s", exc)


def _migrate_app_rules() -> None:
    """Move app_profiles.json from cwd / exe-adjacent to data_dir()."""
    target = app_rules_path()
    if target.is_file():
        return

    candidates = [Path.cwd() / "app_profiles.json"]
    # Also check next to the frozen executable
    import sys

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "app_profiles.json")

    for old in candidates:
        if old.is_file() and old.resolve() != target.resolve():
            shutil.copy2(str(old), str(target))
            log.info("Migrated app_profiles.json from %s", old)
            return
