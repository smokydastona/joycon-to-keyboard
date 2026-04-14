"""Logging and crash-log infrastructure for Joy-Con Helper.

Creates two log directories next to the installed application:
  logs/        – rotating daily application logs
  crash-logs/  – unhandled exception dumps

Auto-cleans files older than 15 days on startup.
No personal data is collected.
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
import time
import traceback
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .debug_privacy import sanitize_text

# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def _app_base_dir() -> Path:
    """Return the directory where log folders should be created.

    When running as a PyInstaller exe  → next to the .exe
    When running from source           → helper-app/joycon_helper/../../ (project root of helper-app)
    """
    if getattr(sys, "frozen", False):
        # PyInstaller: sys.executable is the .exe path
        return Path(sys.executable).resolve().parent
    # Running from source – place logs next to the helper-app package
    return Path(__file__).resolve().parent.parent


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    return _ensure_dir(_app_base_dir() / "logs")


def crash_logs_dir() -> Path:
    return _ensure_dir(_app_base_dir() / "crash-logs")


# ---------------------------------------------------------------------------
# Auto-cleanup
# ---------------------------------------------------------------------------

_MAX_AGE_DAYS = 15


def cleanup_old_logs() -> None:
    """Delete log and crash-log files older than 15 days."""
    cutoff = time.time() - (_MAX_AGE_DAYS * 86400)
    for folder in (logs_dir(), crash_logs_dir()):
        if not folder.is_dir():
            continue
        for entry in folder.iterdir():
            if entry.is_file():
                try:
                    if entry.stat().st_mtime < cutoff:
                        entry.unlink()
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_initialised = False


class _SanitizingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return sanitize_text(rendered)


def setup_logging(*, level: int = logging.DEBUG) -> logging.Logger:
    """Initialise application-wide logging.  Safe to call more than once."""
    global _initialised
    root = logging.getLogger()

    if _initialised:
        return logging.getLogger("joycon_helper")

    root.setLevel(level)

    # ---- File handler (daily rotation, kept 15 days) ----
    log_file = logs_dir() / "helper.log"
    fh = TimedRotatingFileHandler(
        str(log_file),
        when="midnight",
        interval=1,
        backupCount=_MAX_AGE_DAYS,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_SanitizingFormatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT))
    root.addHandler(fh)

    # ---- Console / stderr handler (INFO+) ----
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(_SanitizingFormatter(_LOG_FORMAT, datefmt=_LOG_DATE_FMT))
    root.addHandler(sh)

    _initialised = True

    log = logging.getLogger("joycon_helper")
    log.info("Logging initialised")
    log.info("Platform: %s %s", platform.system(), platform.release())
    log.info("Python: %s", sys.version.split()[0])
    log.info("Frozen: %s", getattr(sys, "frozen", False))

    return log


# ---------------------------------------------------------------------------
# Crash handler
# ---------------------------------------------------------------------------

def _write_crash_file(exc_type, exc_value, exc_tb) -> None:
    """Write a timestamped crash log file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    crash_file = crash_logs_dir() / f"crash_{ts}.log"
    try:
        lines = [
            f"Crash at {datetime.now().isoformat()}",
            f"Platform: {platform.system()} {platform.release()}",
            f"Python: {sys.version}",
            f"Frozen: {getattr(sys, 'frozen', False)}",
            "",
            "--- Traceback ---",
            "",
        ]
        lines.extend(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_file.write_text(sanitize_text("\n".join(lines)), encoding="utf-8")
    except Exception:
        pass  # last resort — don't crash the crash handler


def _sys_excepthook(exc_type, exc_value, exc_tb):
    """Global unhandled-exception handler."""
    log = logging.getLogger("joycon_helper.crash")
    log.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    _write_crash_file(exc_type, exc_value, exc_tb)


def _threading_excepthook(args):
    """Handler for unhandled exceptions in threads (Python 3.8+)."""
    log = logging.getLogger("joycon_helper.crash")
    log.critical(
        "Unhandled exception in thread %s",
        args.thread.name if args.thread else "<unknown>",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
    _write_crash_file(args.exc_type, args.exc_value, args.exc_traceback)


def install_crash_handler() -> None:
    """Install global crash handlers for main thread and worker threads."""
    sys.excepthook = _sys_excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _threading_excepthook
