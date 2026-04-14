from __future__ import annotations

import io
import json
import logging
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol

from ._version import __version__
from .debug_privacy import sanitize_text, sanitize_value
from .logger import crash_logs_dir, logs_dir
from .updater import GITHUB_OWNER, GITHUB_REPO

log = logging.getLogger("joycon_helper.debug_reporting")

_MAX_TEXT_FILE_BYTES = 512 * 1024
_MAX_LOG_FILES_PER_GROUP = 6
_MAX_SESSION_LINES = 200


@dataclass
class DebugArtifact:
    archive_path: str
    content: bytes


@dataclass
class DebugSection:
    key: str
    title: str
    data: Any


@dataclass
class DebugContext:
    main_window: Any | None
    settings: Any | None


@dataclass
class DebugReport:
    report_id: str
    generated_at: str
    sections: list[DebugSection] = field(default_factory=list)
    artifacts: list[DebugArtifact] = field(default_factory=list)

    def section_map(self) -> dict[str, Any]:
        return {section.key: section.data for section in self.sections}


class DebugCollector(Protocol):
    collector_id: str

    def collect(self, context: DebugContext) -> tuple[list[DebugSection], list[DebugArtifact]]:
        ...


def _make_report_id() -> str:
    return datetime.now(UTC).strftime("debug-%Y%m%d-%H%M%S")


def _safe_json_bytes(value: Any) -> bytes:
    return json.dumps(sanitize_value(value), indent=2, ensure_ascii=False).encode("utf-8")


def _truncate_bytes(data: bytes, *, limit: int = _MAX_TEXT_FILE_BYTES) -> bytes:
    if len(data) <= limit:
        return data
    suffix = f"\n\n[truncated {len(data) - limit} bytes]".encode()
    return data[: limit - len(suffix)] + suffix


def _read_text_artifact(path: Path) -> bytes:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        log.exception("Failed reading debug artifact: %s", path)
        data = "<failed to read artifact>"
    return _truncate_bytes(sanitize_text(data).encode("utf-8"))


def _iter_recent_files(folder: Path, *, limit: int = _MAX_LOG_FILES_PER_GROUP) -> list[Path]:
    if not folder.is_dir():
        return []
    files = [entry for entry in folder.iterdir() if entry.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files[:limit]


def _settings_snapshot(settings: Any | None) -> dict[str, str]:
    if settings is None:
        return {}
    snapshot: dict[str, str] = {}
    for key in settings.allKeys():
        snapshot[key] = str(settings.value(key))
    return sanitize_value(snapshot)


def _profile_snapshot(main_window: Any | None) -> dict[str, Any]:
    if main_window is None or not hasattr(main_window, "get_profile"):
        return {}
    profile = main_window.get_profile()
    if not isinstance(profile, dict):
        return {}
    profile_copy = sanitize_value(profile)
    if isinstance(profile_copy, dict) and "name" in profile_copy:
        profile_copy["name"] = "<profile-name>"
    return profile_copy


def _runtime_snapshot(main_window: Any | None) -> dict[str, Any]:
    if main_window is None:
        return {"app_version": __version__}

    bridge = getattr(main_window, "bridge", None)
    port = None
    try:
        port = main_window._port_combo.currentData()
    except Exception:
        port = None

    battery_levels = getattr(main_window, "_battery_levels", {}) or {}
    connected_devices = getattr(main_window, "_connected_devices", {}) or {}

    return sanitize_value(
        {
            "app_version": __version__,
            "connected": bool(getattr(bridge, "is_connected", False)),
            "selected_port": port,
            "active_slot": getattr(main_window, "_slot", 0),
            "bt_status": getattr(main_window, "_bt_status", ""),
            "latency_ms": getattr(main_window, "_latency_ms", None),
            "battery_levels": battery_levels,
            "connected_device_count": len(connected_devices),
            "connected_devices": [
                {
                    "id": getattr(entry, "id", ""),
                    "type": getattr(entry, "type", ""),
                    "source": getattr(entry, "source", ""),
                    "name": getattr(entry, "name", ""),
                }
                for entry in connected_devices.values()
            ],
        }
    )


def _diagnostics_snapshot(main_window: Any | None) -> dict[str, Any]:
    if main_window is None:
        return {}

    diagnostics_view = None
    try:
        diagnostics_view = main_window._views[5] if getattr(main_window, "_views", None) else None
    except Exception:
        diagnostics_view = None

    if diagnostics_view is None:
        return {"available": False}

    telemetry = getattr(diagnostics_view, "_telemetry", None)
    calibration = getattr(diagnostics_view, "_calibration", None)
    controller_info = getattr(diagnostics_view, "_last_controller_info", {}) or {}

    recent_lines: list[str] = []
    input_log = getattr(diagnostics_view, "_input_log", None)
    if input_log is not None:
        block_count = input_log.blockCount()
        start = max(0, block_count - 50)
        recent_lines = [
            input_log.document().findBlockByNumber(index).text()
            for index in range(start, block_count)
        ]

    if telemetry is None or calibration is None:
        return {"available": False}

    return sanitize_value(
        telemetry.build_report(
            profile_slot=getattr(main_window, "_slot", 0),
            controller_info=controller_info,
            calibration=calibration,
            recent_log_lines=[line for line in recent_lines if line],
        )
    )


def _session_log_artifact(main_window: Any | None) -> DebugArtifact | None:
    if main_window is None:
        return None
    log_widget = getattr(main_window, "_log_text", None)
    if log_widget is None:
        return None
    block_count = log_widget.blockCount()
    start = max(0, block_count - _MAX_SESSION_LINES)
    lines = [
        log_widget.document().findBlockByNumber(index).text()
        for index in range(start, block_count)
    ]
    text = "\n".join(line for line in lines if line)
    if not text.strip():
        return None
    return DebugArtifact(
        archive_path="session/ui-session-log.txt",
        content=_truncate_bytes(sanitize_text(text).encode("utf-8")),
    )


class RuntimeCollector:
    collector_id = "runtime"

    def collect(self, context: DebugContext) -> tuple[list[DebugSection], list[DebugArtifact]]:
        return [DebugSection("runtime", "Runtime", _runtime_snapshot(context.main_window))], []


class SettingsCollector:
    collector_id = "settings"

    def collect(self, context: DebugContext) -> tuple[list[DebugSection], list[DebugArtifact]]:
        snapshot = _settings_snapshot(context.settings)
        artifact = DebugArtifact("report/settings.json", _safe_json_bytes(snapshot))
        return [DebugSection("settings", "Settings", snapshot)], [artifact]


class ProfileCollector:
    collector_id = "profile"

    def collect(self, context: DebugContext) -> tuple[list[DebugSection], list[DebugArtifact]]:
        snapshot = _profile_snapshot(context.main_window)
        artifact = DebugArtifact("report/current-profile.json", _safe_json_bytes(snapshot))
        return [DebugSection("profile", "Current Profile", snapshot)], [artifact]


class DiagnosticsCollector:
    collector_id = "diagnostics"

    def collect(self, context: DebugContext) -> tuple[list[DebugSection], list[DebugArtifact]]:
        snapshot = _diagnostics_snapshot(context.main_window)
        artifact = DebugArtifact("report/forensics.json", _safe_json_bytes(snapshot))
        artifacts = [artifact]
        session_log = _session_log_artifact(context.main_window)
        if session_log is not None:
            artifacts.append(session_log)
        return [DebugSection("diagnostics", "Diagnostics", snapshot)], artifacts


class LogFilesCollector:
    collector_id = "files"

    def collect(self, context: DebugContext) -> tuple[list[DebugSection], list[DebugArtifact]]:
        artifacts: list[DebugArtifact] = []
        summary: dict[str, list[str]] = {"logs": [], "crash_logs": []}

        for path in _iter_recent_files(logs_dir()):
            summary["logs"].append(path.name)
            artifacts.append(DebugArtifact(f"logs/{path.name}", _read_text_artifact(path)))

        for path in _iter_recent_files(crash_logs_dir()):
            summary["crash_logs"].append(path.name)
            artifacts.append(DebugArtifact(f"crash-logs/{path.name}", _read_text_artifact(path)))

        return [DebugSection("files", "Collected Files", summary)], artifacts


class DebugReportBuilder:
    _collectors: ClassVar[tuple[DebugCollector, ...]] = (
        RuntimeCollector(),
        SettingsCollector(),
        ProfileCollector(),
        DiagnosticsCollector(),
        LogFilesCollector(),
    )

    @classmethod
    def register_collector(cls, collector: DebugCollector) -> None:
        cls._collectors = (*cls._collectors, collector)

    @classmethod
    def build(cls, context: DebugContext) -> DebugReport:
        report = DebugReport(
            report_id=_make_report_id(),
            generated_at=datetime.now(UTC).isoformat(),
        )

        for collector in cls._collectors:
            try:
                sections, artifacts = collector.collect(context)
            except Exception:
                log.exception("Debug collector failed: %s", getattr(collector, "collector_id", type(collector).__name__))
                continue
            report.sections.extend(sections)
            report.artifacts.extend(artifacts)

        report.artifacts.insert(
            0,
            DebugArtifact(
                "report/report.json",
                _safe_json_bytes(
                    {
                        "report_id": report.report_id,
                        "generated_at": report.generated_at,
                        "sections": [
                            {"key": section.key, "title": section.title, "data": sanitize_value(section.data)}
                            for section in report.sections
                        ],
                    }
                ),
            ),
        )

        issue_markdown = build_issue_markdown(report)
        report.artifacts.append(DebugArtifact("report/github-issue.md", issue_markdown.encode("utf-8")))
        return report


def build_issue_markdown(report: DebugReport) -> str:
    section_map = report.section_map()
    runtime = section_map.get("runtime", {})
    diagnostics = section_map.get("diagnostics", {})
    files = section_map.get("files", {})

    telemetry = diagnostics.get("telemetry", {}) if isinstance(diagnostics, dict) else {}
    calibration = diagnostics.get("calibration", {}) if isinstance(diagnostics, dict) else {}

    lines = [
        f"## Anonymized Debug Report: {report.report_id}",
        "",
        f"Generated: {report.generated_at}",
        f"App Version: {runtime.get('app_version', __version__)}",
        f"Connected: {runtime.get('connected', False)}",
        f"Selected Port: {runtime.get('selected_port', 'n/a')}",
        f"Active Slot: {runtime.get('active_slot', 0)}",
        f"Bluetooth Status: {runtime.get('bt_status', '')}",
        f"Last Latency: {runtime.get('latency_ms', 'n/a')}",
        "",
        "## Diagnostics",
        f"Total Events: {telemetry.get('total_events', 'n/a')}",
        f"Recent EPS: {telemetry.get('recent_events_per_second', 'n/a')}",
        f"Average Hold: {telemetry.get('average_hold_ms', 'n/a')}",
        f"Calibration: {calibration.get('status', 'n/a')} — {calibration.get('summary', 'n/a')}",
        "",
        "## Included Artifacts",
        f"Logs: {', '.join(files.get('logs', [])) if isinstance(files, dict) else ''}",
        f"Crash Logs: {', '.join(files.get('crash_logs', [])) if isinstance(files, dict) else ''}",
        "",
        "An anonymized debug bundle was generated locally. Attach the ZIP produced by Bind Bandit if more detail is needed.",
    ]
    return sanitize_text("\n".join(lines))


def build_issue_url(report: DebugReport) -> str:
    title = f"[debug] {report.report_id}"
    body = build_issue_markdown(report)
    query = urllib.parse.urlencode(
        {
            "title": title,
            "body": body,
            "labels": "debug-report",
        }
    )
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/issues/new?{query}"


def export_debug_bundle(path: str | Path, context: DebugContext) -> DebugReport:
    target = Path(path)
    report = DebugReportBuilder.build(context)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in report.artifacts:
            archive.writestr(artifact.archive_path, artifact.content)
    return report


def build_debug_bundle_bytes(context: DebugContext) -> tuple[DebugReport, bytes]:
    report = DebugReportBuilder.build(context)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in report.artifacts:
            archive.writestr(artifact.archive_path, artifact.content)
    return report, buffer.getvalue()
