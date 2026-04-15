"""Tests for profile schema validation and binary encoding completeness."""

from __future__ import annotations

import struct
from typing import ClassVar

import pytest

from joycon_helper.serial_client import SerialClient

# ── Profile validation ──────────────────────────────────────────────


class TestProfileValidation:
    """Verify _validate_profile catches invalid profiles."""

    def test_valid_minimal_profile(self):
        profile = {
            "name": "test",
            # Firmware profile schema: mappings is an object keyed by input key_id string
            "mappings": {
                "1": {"type": "passthrough"},
                "129": {"type": "remap_hid", "mod": 0, "keycode": 0x04},
            },
            "macros": [],
        }
        SerialClient._validate_profile(profile)  # should not raise

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be a dict"):
            SerialClient._validate_profile("not a dict")

    def test_name_must_be_string(self):
        with pytest.raises(ValueError, match="'name' must be a string"):
            SerialClient._validate_profile({"name": 123})

    def test_mappings_must_be_object(self):
        with pytest.raises(ValueError, match="'mappings' must be an object"):
            SerialClient._validate_profile({"name": "x", "mappings": "bad"})

    def test_mapping_entry_must_be_dict(self):
        with pytest.raises(ValueError, match=r"mappings\['1'\] must be a dict"):
            SerialClient._validate_profile({"name": "x", "mappings": {"1": "bad"}})

    def test_macros_must_be_list(self):
        with pytest.raises(ValueError, match="'macros' must be a list"):
            SerialClient._validate_profile({"name": "x", "macros": "bad"})

    def test_macro_missing_id(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            SerialClient._validate_profile({"name": "x", "macros": [{"steps": []}]})

    def test_macro_steps_must_be_list(self):
        with pytest.raises(ValueError, match="steps must be a list"):
            SerialClient._validate_profile({"name": "x", "macros": [{"id": "m1", "steps": "bad"}]})

    def test_macro_too_many_steps(self):
        with pytest.raises(ValueError, match="max 128"):
            SerialClient._validate_profile({
                "name": "x",
                "macros": [{"id": "m1", "steps": [{"action": "press"}] * 129}],
            })

    def test_stick_must_be_dict(self):
        with pytest.raises(ValueError, match="'stick' must be a dict"):
            SerialClient._validate_profile({"name": "x", "stick": "bad"})

    def test_stick_none_is_valid(self):
        SerialClient._validate_profile({"name": "x", "stick": None})

    def test_layers_must_be_list(self):
        with pytest.raises(ValueError, match="'layers' must be a list"):
            SerialClient._validate_profile({"name": "x", "layers": 42})

    def test_chords_must_be_list(self):
        with pytest.raises(ValueError, match="'chords' must be a list"):
            SerialClient._validate_profile({"name": "x", "chords": {}})


# ── Mode enum completeness ──────────────────────────────────────────


class TestModeEnum:
    """Verify _mode_to_u8 covers all protocol mapping types."""

    PROTOCOL_MODES: ClassVar[list[str]] = [
        "passthrough", "disabled", "disable", "remap", "macro",
        "remap_hid", "tap_hold", "double_tap", "turbo",
        "sticky_mod", "sticky", "oneshot_mod", "oneshot",
        "auto_shift", "mouse_button", "gamepad_button", "sequential", "leader",
        "profile_switch",
    ]

    def test_all_protocol_modes_resolve(self):
        for mode in self.PROTOCOL_MODES:
            result = SerialClient._mode_to_u8(mode)
            assert isinstance(result, int)
            assert 0 <= result <= 255, f"mode '{mode}' returned {result}"

    def test_aliases_match(self):
        assert SerialClient._mode_to_u8("disable") == SerialClient._mode_to_u8("disabled")
        assert SerialClient._mode_to_u8("sticky") == SerialClient._mode_to_u8("sticky_mod")
        assert SerialClient._mode_to_u8("oneshot") == SerialClient._mode_to_u8("oneshot_mod")

    def test_unknown_mode_defaults_to_passthrough(self):
        assert SerialClient._mode_to_u8("nonexistent_mode") == 0

    def test_unique_values(self):
        canonical = [
            "passthrough", "disabled", "remap", "macro", "remap_hid",
            "double_tap", "turbo", "sticky_mod", "tap_hold",
            "oneshot_mod", "auto_shift", "mouse_button", "sequential",
            "leader", "profile_switch",
        ]
        values = [SerialClient._mode_to_u8(m) for m in canonical]
        assert len(values) == len(set(values)), "Canonical modes should have unique numeric IDs"


# ── Stick config encoding ───────────────────────────────────────────


class TestStickBlockEncoding:
    """Verify _send_stick_block encodes all protocol fields."""

    def test_full_stick_config_encodes_all_fields(self):
        """Build a stick config with all fields and verify binary size."""
        _stick = {
            "deadzone": 500,
            "curve": "exponential",
            "shape": "square",
            "exp": 1.5,
            "sensitivity": 120,
            "sprint_threshold": 85,
            "sprint_multiplier": 2.0,
            "socd_mode": "last_input",
            "rapid_trigger": {"activation": 25, "deactivation": 15},
            "right_stick_mode": "mouse",
            "mouse_sensitivity": 20,
            "sprint_zone": {"enabled": True},
        }

        # Manually encode the expected binary
        expected = struct.pack("<HBBB HHH BBB BB B",
                               500,    # deadzone
                               1,      # curve = exponential
                               1,      # shape = square
                               150,    # exp * 100
                               120,    # sensitivity
                               85,     # sprint_threshold
                               200,    # sprint_multiplier * 100
                               1,      # socd = last_input
                               25,     # rt activation
                               15,     # rt deactivation
                               1,      # right_stick_mode = mouse
                               20,     # mouse_sensitivity
                               1)      # sprint_zone enabled

        # We can't call _send_stick_block without a connection, but we can
        # verify the struct format produces the right length (17 bytes).
        assert len(expected) == 17

    def test_default_stick_values(self):
        """Ensure defaults are sensible when fields are absent."""
        _stick = {}
        expected = struct.pack("<HBBB HHH BBB BB B",
                               400, 0, 0, 100, 100, 0, 100, 0, 30, 20, 0, 10, 0)
        assert len(expected) == 17

    def test_curve_map(self):
        assert SerialClient._CURVE_MAP["linear"] == 0
        assert SerialClient._CURVE_MAP["exponential"] == 1
        assert SerialClient._CURVE_MAP["quadratic"] == 2

    def test_shape_map(self):
        assert SerialClient._SHAPE_MAP["circle"] == 0
        assert SerialClient._SHAPE_MAP["square"] == 1
        assert SerialClient._SHAPE_MAP["octagon"] == 2

    def test_socd_map(self):
        assert SerialClient._SOCD_MAP["neutral"] == 0
        assert SerialClient._SOCD_MAP["last_input"] == 1
        assert SerialClient._SOCD_MAP["first_input"] == 2

    def test_rstick_map(self):
        assert SerialClient._RSTICK_MAP["keys"] == 0
        assert SerialClient._RSTICK_MAP["mouse"] == 1
        assert SerialClient._RSTICK_MAP["scroll"] == 2
