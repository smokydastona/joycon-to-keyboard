from __future__ import annotations


def format_battery_levels(levels: dict[int, int]) -> str:
    if not levels:
        return ""

    parts: list[str] = []
    for device_id, prefix in ((0, "L"), (1, "R")):
        level = levels.get(device_id)
        if level is None:
            continue
        clamped = max(0, min(level, 4))
        bars = "█" * clamped + "░" * (4 - clamped)
        parts.append(f"{prefix}:{bars}")
    return f"🔋 {' '.join(parts)}" if parts else ""
