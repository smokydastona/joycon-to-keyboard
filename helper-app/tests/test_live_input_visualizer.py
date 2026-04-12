from __future__ import annotations

from joycon_helper.ui.widgets.live_input_visualizer import (
    describe_rssi,
    hotspot_for_key_id,
    label_for_key_id,
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


def test_describe_rssi_quality_bands() -> None:
    assert "Excellent" in describe_rssi(-45)
    assert "Strong" in describe_rssi(-60)
    assert "Fair" in describe_rssi(-72)
    assert "Weak" in describe_rssi(-88)
    assert describe_rssi(None) == "—"
