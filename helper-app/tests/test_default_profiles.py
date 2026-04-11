"""Tests for built-in default profiles."""

from __future__ import annotations

from joycon_helper.default_profiles import BUILT_IN_PROFILES, get_default_profile


class TestBuiltInProfiles:
    """Validate structural invariants of the 4 built-in profiles."""

    def test_four_profiles_exist(self):
        assert len(BUILT_IN_PROFILES) == 4

    def test_each_has_required_keys(self):
        required = {"name", "mappings", "macros", "layers", "chords", "stick"}
        for i, prof in enumerate(BUILT_IN_PROFILES):
            missing = required - set(prof.keys())
            assert not missing, f"Slot {i} missing keys: {missing}"

    def test_names_are_strings(self):
        for prof in BUILT_IN_PROFILES:
            assert isinstance(prof["name"], str)
            assert len(prof["name"]) > 0

    def test_mappings_have_keycode_and_modifier(self):
        for i, prof in enumerate(BUILT_IN_PROFILES):
            for btn, mapping in prof["mappings"].items():
                assert "keycode" in mapping, f"Slot {i}, button {btn}: missing keycode"
                assert "modifier" in mapping, f"Slot {i}, button {btn}: missing modifier"
                assert 0 <= mapping["keycode"] <= 0xFF
                assert 0 <= mapping["modifier"] <= 0xFF

    def test_stick_has_deadzone_and_sensitivity(self):
        for i, prof in enumerate(BUILT_IN_PROFILES):
            stick = prof["stick"]
            assert "deadzone_inner" in stick, f"Slot {i}: missing deadzone_inner"
            assert "sensitivity" in stick, f"Slot {i}: missing sensitivity"
            assert 0 <= stick["deadzone_inner"] <= 1.0

    def test_all_profiles_have_wasd(self):
        """Every profile should map left stick to WASD movement (0x1A, 0x16, 0x04, 0x07)."""
        wasd = {"LSUp": 0x1A, "LSDown": 0x16, "LSLeft": 0x04, "LSRight": 0x07}
        for i, prof in enumerate(BUILT_IN_PROFILES):
            for btn, expected_kc in wasd.items():
                assert btn in prof["mappings"], f"Slot {i}: missing {btn}"
                assert prof["mappings"][btn]["keycode"] == expected_kc, (
                    f"Slot {i}: {btn} keycode mismatch"
                )


class TestGetDefaultProfile:
    """get_default_profile returns deep copies of built-in profiles."""

    def test_returns_copy(self):
        original = BUILT_IN_PROFILES[0]
        copy = get_default_profile(0)
        assert copy == original
        # Mutating the copy must not affect the original
        copy["name"] = "MUTATED"
        assert BUILT_IN_PROFILES[0]["name"] != "MUTATED"

    def test_slot_range(self):
        for slot in range(4):
            prof = get_default_profile(slot)
            assert prof["name"] == BUILT_IN_PROFILES[slot]["name"]

    def test_out_of_range_clamps(self):
        # Negative → slot 0
        assert get_default_profile(-1)["name"] == BUILT_IN_PROFILES[0]["name"]
        # Beyond max → last slot
        assert get_default_profile(100)["name"] == BUILT_IN_PROFILES[-1]["name"]
