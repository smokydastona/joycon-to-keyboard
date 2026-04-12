from __future__ import annotations

from joycon_helper.ui.dashboard_summary import (
    battery_text,
    build_battery_briefing,
    build_profile_briefing,
    mapped_input_preview,
)


def test_mapped_input_preview_handles_empty_and_overflow() -> None:
    assert mapped_input_preview({}) == "No mapped inputs yet"
    assert mapped_input_preview({"mappings": {"B": {}, "A": {}, "X": {}, "Y": {}, "ZR": {}}}) == "A, B, X, Y +1 more"


def test_build_profile_briefing_summarizes_slot_profile() -> None:
    briefing = build_profile_briefing(
        {
            "name": "Stealth",
            "icon": "🕵",
            "tags": ["quiet", "pve"],
            "mappings": {"A": {}, "B": {}, "ZR": {}},
            "macros": [{"name": "loot"}],
            "layers": [{"name": "Precision"}],
            "chords": [{"name": "Ping"}, {"name": "Heal"}],
            "stick": {"curve_type": "expo_soft"},
        },
        2,
    )
    assert briefing == {
        "slot": "Slot 2",
        "name": "🕵 Stealth",
        "counts": "3 mapped | 1 macro(s) | 1 layer(s) | 2 chord(s)",
        "details": "Tags: quiet, pve | Stick curve: Expo Soft",
        "preview": "Mapped inputs: A, B, ZR",
    }


def test_build_battery_briefing_formats_per_side_levels() -> None:
    assert battery_text(None) == "—"
    assert battery_text(3) == "███░ (3/4)"
    assert build_battery_briefing({0: 4, 1: 2}) == {
        "headline": "L 4/4 | R 2/4",
        "details": "Left ████ (4/4) | Right ██░░ (2/4)",
    }
