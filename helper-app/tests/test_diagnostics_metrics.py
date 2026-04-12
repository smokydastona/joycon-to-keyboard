from __future__ import annotations

from joycon_helper.diagnostics_metrics import (
    DiagnosticsTelemetry,
    assess_controller_calibration,
)


def test_telemetry_counts_and_rates() -> None:
    tracker = DiagnosticsTelemetry()
    tracker.record_mapped_key(10, True, now=100.0)
    tracker.record_mapped_key(10, False, now=100.2)
    tracker.record_mapped_key(11, True, now=101.0)
    snapshot = tracker.snapshot(now=102.0)

    assert snapshot.total_events == 3
    assert snapshot.total_presses == 2
    assert snapshot.total_releases == 1
    assert snapshot.active_keys == 1
    assert snapshot.peak_active_keys == 1
    assert snapshot.recent_events_per_second > 0
    assert snapshot.average_hold_ms is not None
    assert 199.0 <= snapshot.average_hold_ms <= 201.0


def test_telemetry_latency_and_export_report() -> None:
    tracker = DiagnosticsTelemetry()
    tracker.record_latency(12.5)
    tracker.record_latency(15.0)
    report = tracker.build_report(
        profile_slot=2,
        controller_info={"type": "joycon_l", "serial": "abc"},
        calibration=assess_controller_calibration(0.07, 0.96),
        recent_log_lines=["hello"],
    )

    assert report["profile_slot"] == 2
    assert report["telemetry"]["last_latency_ms"] == 15.0
    assert report["telemetry"]["average_latency_ms"] == 13.75
    assert report["controller_info"]["serial"] == "abc"
    assert report["recent_log_lines"] == ["hello"]


def test_calibration_assessment_bands() -> None:
    excellent = assess_controller_calibration(0.05, 0.98)
    fair = assess_controller_calibration(0.18, 0.82)
    poor = assess_controller_calibration(0.28, 0.70)

    assert excellent.status == "Excellent"
    assert fair.status == "Fair"
    assert poor.status == "Poor"
    assert "recalibration" in poor.summary.lower()
