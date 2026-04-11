"""Per-app auto-profile switching.

Monitors the foreground window on Windows and sends set_active_profile
when the active application matches a configured rule.

Rules are stored as a list of dicts:
    [{"exe": "game.exe", "slot": 0}, {"exe": "notepad.exe", "slot": 1}, ...]

The "exe" field is matched case-insensitively against the foreground
process name.  It can be a bare executable name (e.g. "game.exe") or an
absolute path (e.g. "C:\\Games\\game.exe").
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("joycon_helper.app_switcher")

# Win32 API imports via ctypes (Windows-only)
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

    _user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    _kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    _psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
else:
    ctypes = None  # type: ignore[assignment]
    _user32 = None
    _kernel32 = None
    _psapi = None

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MAX_RULES = 100
_MAX_EXE_LEN = 256


def _get_foreground_exe() -> tuple[str | None, str | None]:
    """Return (basename, full_path) of the foreground window's process, or (None, None)."""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None, None

        pid = ctypes.wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return None, None

        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return None, None

        try:
            buf = (ctypes.c_wchar * 260)()
            size = ctypes.wintypes.DWORD(260)
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                full_path = buf.value
                return os.path.basename(full_path).lower(), full_path.lower()
        finally:
            _kernel32.CloseHandle(handle)
    except OSError:
        log.debug("ctypes call failed in _get_foreground_exe", exc_info=True)

    return None, None


def _get_foreground_title() -> str | None:
    """Return the window title of the foreground window, or None."""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return None
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except OSError:
        log.debug("ctypes call failed in _get_foreground_title", exc_info=True)
        return None


# Config file path (next to the helper app data)
def _rules_path() -> Path:
    """Return the path to the app-switcher rules JSON file."""
    # Store next to the executable or in the current working directory.
    return Path.cwd() / "app_profiles.json"


def load_rules() -> list[dict[str, Any]]:
    """Load app-switching rules from disk."""
    p = _rules_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            # Validate each rule: must have "exe" (str) and "slot" (int 0-3)
            valid: list[dict[str, Any]] = []
            for rule in data:
                if not isinstance(rule, dict):
                    continue
                exe = rule.get("exe")
                slot = rule.get("slot")
                if not isinstance(exe, str) or not exe:
                    log.warning("Skipping app-switcher rule with missing/invalid 'exe': %r", rule)
                    continue
                if len(exe) > _MAX_EXE_LEN:
                    log.warning("Skipping app-switcher rule — exe name too long (%d chars): %r", len(exe), rule)
                    continue
                if not isinstance(slot, int) or not (0 <= slot <= 3):
                    log.warning("Skipping app-switcher rule with invalid 'slot': %r", rule)
                    continue
                valid.append(rule)
                if len(valid) >= _MAX_RULES:
                    log.warning("App-switcher rules capped at %d", _MAX_RULES)
                    break
            return valid
    except Exception:
        log.warning("Failed to load app_profiles.json", exc_info=True)
    return []


def save_rules(rules: list[dict[str, Any]]) -> None:
    """Save app-switching rules to disk."""
    p = _rules_path()
    p.write_text(json.dumps(rules, indent=2), encoding="utf-8")


class AppSwitcher:
    """Background thread that monitors the foreground app and triggers profile switches."""

    def __init__(self, on_switch: Callable[[int], None], poll_interval: float = 1.0) -> None:
        """
        on_switch: callback(slot) invoked on the main thread when the active
                   app changes and matches a rule. The caller should send
                   set_active_profile with that slot.
        poll_interval: seconds between foreground checks.
        """
        self._on_switch = on_switch
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._rules: list[dict[str, Any]] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_exe: str | None = None
        self._last_slot: int | None = None
        self._default_slot: int = 0
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if value and not self._running:
            self.start()
        elif not value and self._running:
            self.stop()

    @property
    def rules(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._rules)

    def set_rules(self, rules: list[dict[str, Any]]) -> None:
        with self._lock:
            self._rules = list(rules)

    def set_default_slot(self, slot: int) -> None:
        self._default_slot = slot

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="app-switcher")
        self._thread.start()
        log.info("App switcher started (interval=%.1fs, %d rules)", self._poll_interval, len(self._rules))

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _poll_loop(self) -> None:
        while self._running:
            if self._enabled:
                self._check_foreground()
            time.sleep(self._poll_interval)

    def _check_foreground(self) -> None:
        try:
            exe, full_path = _get_foreground_exe()
        except Exception:
            return

        # UWP apps report as ApplicationFrameHost.exe — use window title
        title: str | None = None
        if exe == "applicationframehost.exe":
            title = _get_foreground_title()

        # Build a composite key so UWP title changes are detected
        fg_key = f"{exe}|{title}" if title else exe

        with self._lock:
            if fg_key == self._last_exe:
                return
            self._last_exe = fg_key

            if not exe:
                return

            # Find matching rule
            matched_slot: int | None = None
            for rule in self._rules:
                rule_exe = rule.get("exe", "")
                rule_title = rule.get("title", "")
                if not isinstance(rule_exe, str):
                    continue
                rule_lower = rule_exe.lower()

                # Support both basename and absolute path matching
                if os.sep in rule_exe or "/" in rule_exe:
                    # Absolute path rule — compare against full process path
                    if full_path and rule_lower == full_path:
                        pass  # match
                    else:
                        continue
                elif rule_lower == exe:
                    pass  # basename match
                else:
                    continue

                # For UWP rules that specify a title, require title match
                if rule_title and title and rule_title.lower() not in title.lower():
                    continue
                slot = rule.get("slot")
                if isinstance(slot, int) and 0 <= slot <= 3:
                    matched_slot = slot
                    break

            target_slot = matched_slot if matched_slot is not None else self._default_slot

            if target_slot != self._last_slot:
                self._last_slot = target_slot

        log.info("App switch: %s -> slot %d", exe, target_slot)
        try:
            self._on_switch(target_slot)
        except Exception:
            log.warning("App switch callback failed", exc_info=True)
