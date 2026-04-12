from __future__ import annotations

from joycon_helper.ui.widgets.live_input_visualizer import (
    activity_category_title,
    activity_decay_amount,
    build_active_controls_summary,
    compact_recent_activity_groups,
    describe_layer_activity,
    describe_macro_activity,
    describe_mapped_key_activity,
    describe_rssi,
    device_index_for_key_id,
    display_label_for_key_id,
    group_recent_activity,
    hotspot_for_key_id,
    label_for_key_id,
    overflow_summary_label,
)


def test_hotspot_for_stick_and_face_keys() -> None:
    assert hotspot_for_key_id(1) == "LSUp"
    assert hotspot_for_key_id(22) == "RSUp"
    assert hotspot_for_key_id(8) == "A"
    assert hotspot_for_key_id(35) == "SR(R)"


def test_hotspot_missing_for_abstract_action_key() -> None:
    assert hotspot_for_key_id(5) is None
    assert hotspot_for_key_id(6) is None
    assert hotspot_for_key_id(7) is None


def test_label_for_key_id_uses_base_key_space() -> None:
    assert label_for_key_id(1) == "Forward"
    assert label_for_key_id(129) == "Forward"
    assert label_for_key_id(35) == "SR(R)"


def test_display_label_for_key_id_is_device_aware() -> None:
    assert device_index_for_key_id(1) == 0
    assert device_index_for_key_id(129) == 1
    assert display_label_for_key_id(1) == "Forward"
    assert display_label_for_key_id(129) == "Forward [D1]"


def test_active_controls_summary_groups_multi_device_keys() -> None:
    assert build_active_controls_summary(set()) == "—"
    assert build_active_controls_summary({1, 5}) == "Forward, Jump"
    assert build_active_controls_summary({1, 5, 133}) == "D0: Forward, Jump | D1: Jump"


def test_activity_descriptions_are_human_readable() -> None:
    assert describe_mapped_key_activity(5, True) == "Jump pressed"
    assert describe_mapped_key_activity(133, False) == "Jump [D1] released"
    assert describe_layer_activity("Precision", True) == "Layer Precision enabled"
    assert describe_layer_activity("Precision", False) == "Layer Precision disabled"
    assert describe_macro_activity("loot-run", "started") == "Macro loot-run started"


def test_activity_decay_amount_is_bounded_and_ordered() -> None:
    assert activity_decay_amount(0) == 0.0
    assert activity_decay_amount(1) > activity_decay_amount(0)
    assert activity_decay_amount(3) > activity_decay_amount(1)
    assert activity_decay_amount(50) == 0.60


def test_recent_activity_grouping_preserves_lane_order() -> None:
    grouped = group_recent_activity([
        ("macro", "Macro loot-run started"),
        ("input", "Jump pressed"),
        ("layer", "Layer Precision enabled"),
        ("input", "Jump released"),
    ])
    assert grouped == [
        ("input", ["Jump pressed", "Jump released"]),
        ("layer", ["Layer Precision enabled"]),
        ("macro", ["Macro loot-run started"]),
    ]
    assert activity_category_title("input") == "Inputs"
    assert activity_category_title("layer") == "Layers"
    assert activity_category_title("macro") == "Macros"


def test_recent_activity_compaction_adds_lane_overflow_counts() -> None:
    compacted = compact_recent_activity_groups([
        ("input", ["A", "B", "C", "D", "E", "F"]),
        ("layer", ["Layer Alpha enabled", "Layer Beta enabled", "Layer Gamma enabled"]),
        ("macro", ["Macro loot-run started"]),
    ])
    assert compacted == [
        ("input", ["A", "B", "C", "D"], 2),
        ("layer", ["Layer Alpha enabled", "Layer Beta enabled"], 1),
        ("macro", ["Macro loot-run started"], 0),
    ]
    assert overflow_summary_label(3) == "+3 older"


def test_describe_rssi_quality_bands() -> None:
    assert "Excellent" in describe_rssi(-45)
    assert "Strong" in describe_rssi(-60)
    assert "Fair" in describe_rssi(-72)
    assert "Weak" in describe_rssi(-88)
    assert describe_rssi(None) == "—"
