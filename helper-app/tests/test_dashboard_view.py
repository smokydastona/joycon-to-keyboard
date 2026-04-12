from __future__ import annotations

from joycon_helper.ui.views.dashboard import build_profile_briefing, mapped_input_preview


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