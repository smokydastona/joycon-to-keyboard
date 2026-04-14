from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

_REDACTED = "<redacted>"


def _app_dir_candidates() -> list[str]:
    candidates: set[str] = set()
    if getattr(sys, "frozen", False):
        candidates.add(str(Path(sys.executable).resolve().parent))
    candidates.add(str(Path(__file__).resolve().parent.parent))
    with_candidates = [value for value in candidates if value]
    return sorted(with_candidates, key=len, reverse=True)


_STATIC_REPLACEMENTS = [
    (value, "<APP_DIR>") for value in _app_dir_candidates()
] + [
    (str(Path.home()), "<HOME>"),
    (os.environ.get("USERPROFILE", ""), "<USERPROFILE>"),
    (os.environ.get("HOMEPATH", ""), "<HOMEPATH>"),
    (os.environ.get("USERNAME", ""), "<USERNAME>"),
    (os.environ.get("COMPUTERNAME", ""), "<COMPUTERNAME>"),
]


_WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:\\[^\r\n\t\"']+")
_UNIX_HOME_RE = re.compile(r"(?:(?<=\s)|^)(/home/[^/\s]+|/Users/[^/\s]+)(?:/[^\s\"']*)?")
_BT_ADDR_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
_SERIAL_JSON_RE = re.compile(r'(?i)("serial"\s*:\s*")[^"]*(")')
_SERIAL_TEXT_RE = re.compile(r"(?im)(\bserial\b\s*[:=]\s*)([^\r\n]+)")
_BDA_JSON_RE = re.compile(r'(?i)("bda"\s*:\s*")[^"]*(")')
_TOKEN_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


def sanitize_text(text: str) -> str:
    result = text

    for original, replacement in _STATIC_REPLACEMENTS:
        if original:
            result = result.replace(original, replacement)

    result = _WINDOWS_PATH_RE.sub("<PATH>", result)
    result = _UNIX_HOME_RE.sub("<HOME_PATH>", result)
    result = _BT_ADDR_RE.sub("<BT_ADDR>", result)
    result = _SERIAL_JSON_RE.sub(rf"\1{_REDACTED}\2", result)
    result = _SERIAL_TEXT_RE.sub(rf"\1{_REDACTED}", result)
    result = _BDA_JSON_RE.sub(r"\1<BT_ADDR>\2", result)
    result = _TOKEN_RE.sub("<TOKEN>", result)
    return result


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in {"serial", "serial_number", "bda", "bluetooth_address"}:
                sanitized[key] = _REDACTED if key_text.lower().startswith("serial") else "<BT_ADDR>"
            else:
                sanitized[key] = sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value
