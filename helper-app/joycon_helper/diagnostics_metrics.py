from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import mean
import time
from typing import Any


_RECENT_WINDOW_SECONDS = 5.0
_MAX_RECENT_EVENTS = 512
_MAX_LATENCIES = 128
_MAX_HOLD_SAMPLES = 128


@dataclass(frozen=True)
class TelemetrySnapshot:
    session_seconds: float
    total_events: int
    total_presses: int
    total_releases: int
    recent_events_per_second: float
    average_events_per_second: float
    active_keys: int
    peak_active_keys: int
    average_hold_ms: float | None
    last_latency_ms: float | None
    average_latency_ms: float | None
    max_latency_ms: float | None


@dataclass(frozen=True)
class CalibrationAssessment:
    status: str
    summary: str
    deadzone_status: str
    range_status: str


def _rating_for_deadzone(deadzone: float | None) -> tuple[str, str]:
    if deadzone is None:
        return "Unknown", "No deadzone data reported"
    if deadzone <= 0.08:
        return "Excellent", "Deadzone is tight and responsive"
    if deadzone <= 0.15:
        return "Good", "Deadzone is acceptable for most games"
    if deadzone <= 0.22:
        return "Fair", "Deadzone is usable but may hide subtle movement"
    return "Poor", "Deadzone is large and likely masks precision input"


def _rating_for_range(range_ratio: float | None) -> tuple[str, str]:
    if range_ratio is None:
        return "Unknown", "No stick range data reported"
    if range_ratio >= 0.95:
        return "Excellent", "Stick reaches nearly full travel"
    if range_ratio >= 0.90:
        return "Good", "Stick range is strong"
    if range_ratio >= 0.80:
        return "Fair", "Stick range is reduced"
    return "Poor", "Stick range is significantly limited"


def assess_controller_calibration(
    deadzone: float | None,
    range_ratio: float | None,
) -> CalibrationAssessment:
    deadzone_status, deadzone_summary = _rating_for_deadzone(deadzone)
    range_status, range_summary = _rating_for_range(range_ratio)
    severity_rank = {
        "Unknown": 0,
        "Excellent": 1,
        "Good": 2,
        "Fair": 3,
        "Poor": 4,
    }
    overall = max((deadzone_status, range_status), key=lambda item: severity_rank[item])
    if overall == "Unknown":
        summary = "Waiting for controller calibration data"
    elif overall == "Excellent":
        summary = "Controller calibration looks excellent"
    elif overall == "Good":
        summary = "Controller calibration is healthy"
    elif overall == "Fair":
        summary = "Controller calibration is usable but could benefit from tuning"
    else:
        summary = "Controller calibration looks degraded; recalibration is recommended"
    return CalibrationAssessment(
        status=overall,
        summary=f"{summary}. {deadzone_summary}. {range_summary}.",
        deadzone_status=deadzone_status,
        range_status=range_status,
    )


class DiagnosticsTelemetry:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._session_started = time.monotonic()
        self._total_events = 0
        self._total_presses = 0
        self._total_releases = 0
        self._recent_events: deque[float] = deque(maxlen=_MAX_RECENT_EVENTS)
        self._latencies_ms: deque[float] = deque(maxlen=_MAX_LATENCIES)
        self._active_key_started: dict[int, float] = {}
        self._hold_samples_ms: deque[float] = deque(maxlen=_MAX_HOLD_SAMPLES)
        self._active_keys: set[int] = set()
        self._peak_active_keys = 0

    def record_mapped_key(self, key_id: int, pressed: bool, now: float | None = None) -> None:
        stamp = time.monotonic() if now is None else now
        self._total_events += 1
        self._recent_events.append(stamp)

        if pressed:
            self._total_presses += 1
            self._active_keys.add(key_id)
            self._active_key_started.setdefault(key_id, stamp)
            self._peak_active_keys = max(self._peak_active_keys, len(self._active_keys))
            return

        self._total_releases += 1
        self._active_keys.discard(key_id)
        started = self._active_key_started.pop(key_id, None)
        if started is not None and stamp >= started:
            self._hold_samples_ms.append((stamp - started) * 1000.0)

    def record_latency(self, latency_ms: float | None) -> None:
        if latency_ms is None:
            return
        if latency_ms < 0:
            return
        self._latencies_ms.append(float(latency_ms))

    def snapshot(self, now: float | None = None) -> TelemetrySnapshot:
        stamp = time.monotonic() if now is None else now
        cutoff = stamp - _RECENT_WINDOW_SECONDS
        while self._recent_events and self._recent_events[0] < cutoff:
            self._recent_events.popleft()

        session_seconds = max(0.001, stamp - self._session_started)
        recent_rate = len(self._recent_events) / _RECENT_WINDOW_SECONDS
        average_rate = self._total_events / session_seconds
        average_hold = mean(self._hold_samples_ms) if self._hold_samples_ms else None
        average_latency = mean(self._latencies_ms) if self._latencies_ms else None
        last_latency = self._latencies_ms[-1] if self._latencies_ms else None
        max_latency = max(self._latencies_ms) if self._latencies_ms else None

        return TelemetrySnapshot(
            session_seconds=session_seconds,
            total_events=self._total_events,
            total_presses=self._total_presses,
            total_releases=self._total_releases,
            recent_events_per_second=recent_rate,
            average_events_per_second=average_rate,
            active_keys=len(self._active_keys),
            peak_active_keys=self._peak_active_keys,
            average_hold_ms=average_hold,
            last_latency_ms=last_latency,
            average_latency_ms=average_latency,
            max_latency_ms=max_latency,
        )

    def build_report(
        self,
        *,
        profile_slot: int,
        controller_info: dict[str, Any] | None,
        calibration: CalibrationAssessment,
        recent_log_lines: list[str],
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "generated_at_unix": time.time(),
            "profile_slot": profile_slot,
            "telemetry": {
                "session_seconds": round(snapshot.session_seconds, 3),
                "total_events": snapshot.total_events,
                "total_presses": snapshot.total_presses,
                "total_releases": snapshot.total_releases,
                "recent_events_per_second": round(snapshot.recent_events_per_second, 3),
                "average_events_per_second": round(snapshot.average_events_per_second, 3),
                "active_keys": snapshot.active_keys,
                "peak_active_keys": snapshot.peak_active_keys,
                "average_hold_ms": None if snapshot.average_hold_ms is None else round(snapshot.average_hold_ms, 3),
                "last_latency_ms": None if snapshot.last_latency_ms is None else round(snapshot.last_latency_ms, 3),
                "average_latency_ms": None if snapshot.average_latency_ms is None else round(snapshot.average_latency_ms, 3),
                "max_latency_ms": None if snapshot.max_latency_ms is None else round(snapshot.max_latency_ms, 3),
            },
            "controller_info": controller_info or {},
            "calibration": {
                "status": calibration.status,
                "summary": calibration.summary,
                "deadzone_status": calibration.deadzone_status,
                "range_status": calibration.range_status,
            },
            "recent_log_lines": recent_log_lines,
        }
