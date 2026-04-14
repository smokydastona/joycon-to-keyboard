from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass

from joycon_helper.debug_privacy import sanitize_text, sanitize_value
from joycon_helper.debug_reporting import (
    DebugArtifact,
    DebugContext,
    DebugReportBuilder,
    DebugSection,
    build_debug_bundle_bytes,
    build_issue_url,
)


class FakeSettings:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def allKeys(self) -> list[str]:
        return list(self._values)

    def value(self, key: str) -> object:
        return self._values[key]


class FakePlainTextDocument:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def findBlockByNumber(self, index: int):
        @dataclass
        class _Block:
            text_value: str

            def text(self) -> str:
                return self.text_value

        return _Block(self._lines[index])


class FakePlainTextEdit:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self._document = FakePlainTextDocument(lines)

    def blockCount(self) -> int:
        return len(self._lines)

    def document(self) -> FakePlainTextDocument:
        return self._document


class FakeMainWindow:
    def __init__(self) -> None:
        self.bridge = type("Bridge", (), {"is_connected": True})()
        self._slot = 2
        self._bt_status = "connected"
        self._latency_ms = 12.5
        self._battery_levels = {0: 4}
        self._connected_devices = {}
        self._port_combo = type("PortCombo", (), {"currentData": lambda self: "COM7"})()
        self._views = []
        self._log_text = FakePlainTextEdit([
            r"[rx] path C:\Users\Alice\repo",
            '{"rsp":"fw_version","serial":"ABC123","bda":"AA:BB:CC:DD:EE:FF"}',
        ])

    def get_profile(self) -> dict[str, object]:
        return {"name": "Alice Profile", "mappings": {"1": {"type": "remap"}}}


def test_sanitize_text_redacts_paths_serials_and_bt_addresses() -> None:
    raw = (
        r'Path: C:\Users\Alice\OneDrive\file.txt | '
        r'{"serial":"ABC123","bda":"AA:BB:CC:DD:EE:FF"}'
    )
    cleaned = sanitize_text(raw)
    assert "Alice" not in cleaned
    assert "ABC123" not in cleaned
    assert "AA:BB:CC:DD:EE:FF" not in cleaned
    assert "<PATH>" in cleaned or "<HOME>" in cleaned or "<USERPROFILE>" in cleaned


def test_sanitize_value_redacts_sensitive_keys() -> None:
    cleaned = sanitize_value({"serial": "ABC", "bda": "AA:BB:CC:DD:EE:FF"})
    assert cleaned["serial"] == "<redacted>"
    assert cleaned["bda"] == "<BT_ADDR>"


def test_debug_bundle_contains_sanitized_artifacts(monkeypatch, tmp_path) -> None:
    logs_dir = tmp_path / "logs"
    crash_dir = tmp_path / "crash-logs"
    logs_dir.mkdir()
    crash_dir.mkdir()
    (logs_dir / "helper.log").write_text(r"User path C:\Users\Alice\repo", encoding="utf-8")
    (crash_dir / "crash.log").write_text('{"serial":"ABC123"}', encoding="utf-8")

    monkeypatch.setattr("joycon_helper.debug_reporting.logs_dir", lambda: logs_dir)
    monkeypatch.setattr("joycon_helper.debug_reporting.crash_logs_dir", lambda: crash_dir)

    report, bundle_bytes = build_debug_bundle_bytes(
        DebugContext(
            main_window=FakeMainWindow(),
            settings=FakeSettings({"last_profile_path": r"C:\Users\Alice\profile.json"}),
        )
    )

    assert report.report_id.startswith("debug-")

    with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as archive:
        names = set(archive.namelist())
        assert "report/report.json" in names
        assert "report/github-issue.md" in names
        assert "logs/helper.log" in names
        assert "crash-logs/crash.log" in names

        helper_log = archive.read("logs/helper.log").decode("utf-8")
        crash_log = archive.read("crash-logs/crash.log").decode("utf-8")
        report_json = json.loads(archive.read("report/report.json").decode("utf-8"))

    assert "Alice" not in helper_log
    assert "ABC123" not in crash_log
    assert report_json["sections"]


def test_debug_report_builder_is_extendable(monkeypatch) -> None:
    class CustomCollector:
        collector_id = "custom"

        def collect(self, context: DebugContext):
            return [DebugSection("custom", "Custom", {"ok": True})], [DebugArtifact("custom.txt", b"ok")]

    monkeypatch.setattr(DebugReportBuilder, "_collectors", [CustomCollector()])
    report, bundle_bytes = build_debug_bundle_bytes(DebugContext(main_window=None, settings=None))

    assert report.section_map()["custom"] == {"ok": True}
    with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as archive:
        assert "custom.txt" in archive.namelist()


def test_build_issue_url_targets_repo_issue_creation(monkeypatch) -> None:
    monkeypatch.setattr(DebugReportBuilder, "_collectors", [])
    report, _bundle = build_debug_bundle_bytes(DebugContext(main_window=None, settings=None))
    issue_url = build_issue_url(report)
    assert "/issues/new?" in issue_url
    assert "template=debug-report.md" in issue_url
    assert "debug-report" in issue_url
