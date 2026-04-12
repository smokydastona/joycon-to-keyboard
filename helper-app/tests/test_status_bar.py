from __future__ import annotations

from joycon_helper.ui.status_helpers import format_battery_levels


def test_format_battery_levels_handles_empty_and_per_side_levels() -> None:
    assert format_battery_levels({}) == ""
    assert format_battery_levels({0: 4}) == "🔋 L:████"
    assert format_battery_levels({0: 3, 1: 1}) == "🔋 L:███░ R:█░░░"
