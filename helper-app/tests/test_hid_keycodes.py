"""Tests for HID keycode lookups and human-readable labels."""

from __future__ import annotations

from joycon_helper.hid_keycodes import (
    DEFAULT_KEYMAP,
    MOD_LALT,
    MOD_LCTRL,
    MOD_LGUI,
    MOD_LSHIFT,
    MOD_RALT,
    MOD_RCTRL,
    MOD_RGUI,
    MOD_RSHIFT,
    hid_to_name,
    keysym_to_hid,
)


class TestKeysymToHid:
    """keysym_to_hid: tkinter keysym → (modifier, keycode)."""

    def test_lowercase_letters(self):
        for ch, expected_code in [("a", 0x04), ("z", 0x1D), ("m", 0x10)]:
            mod, kc = keysym_to_hid(ch)
            assert mod == 0
            assert kc == expected_code

    def test_uppercase_maps_same_keycode(self):
        lower = keysym_to_hid("w")
        upper = keysym_to_hid("W")
        assert lower == upper

    def test_modifier_keys(self):
        mod, kc = keysym_to_hid("Shift_L")
        assert mod == MOD_LSHIFT
        assert kc == 0

        mod, kc = keysym_to_hid("Control_R")
        assert mod == MOD_RCTRL
        assert kc == 0

    def test_fkeys(self):
        mod, kc = keysym_to_hid("F1")
        assert (mod, kc) == (0, 0x3A)
        mod, kc = keysym_to_hid("F12")
        assert (mod, kc) == (0, 0x45)

    def test_extended_fkeys(self):
        mod, kc = keysym_to_hid("F13")
        assert (mod, kc) == (0, 0x68)
        mod, kc = keysym_to_hid("F24")
        assert (mod, kc) == (0, 0x73)

    def test_unknown_keysym_returns_none(self):
        assert keysym_to_hid("NoSuchKey") is None
        assert keysym_to_hid("") is None

    def test_special_keys(self):
        assert keysym_to_hid("Return") == (0, 0x28)
        assert keysym_to_hid("Escape") == (0, 0x29)
        assert keysym_to_hid("space") == (0, 0x2C)
        assert keysym_to_hid("Tab") == (0, 0x2B)

    def test_numpad(self):
        mod, kc = keysym_to_hid("KP_0")
        assert (mod, kc) == (0, 0x62)
        mod, kc = keysym_to_hid("KP_Add")
        assert (mod, kc) == (0, 0x57)


class TestHidToName:
    """hid_to_name: (modifier, keycode) → human-readable string."""

    def test_plain_key(self):
        assert hid_to_name(0, 0x04) == "A"
        assert hid_to_name(0, 0x2C) == "Space"

    def test_modifier_only(self):
        assert hid_to_name(MOD_LSHIFT, 0) == "Shift"
        assert hid_to_name(MOD_LCTRL, 0) == "Ctrl"

    def test_combo(self):
        name = hid_to_name(MOD_LCTRL | MOD_LSHIFT, 0x04)
        assert "Ctrl" in name
        assert "Shift" in name
        assert "A" in name

    def test_no_mapping(self):
        assert hid_to_name(0, 0) == "None"

    def test_unknown_keycode_shows_hex(self):
        name = hid_to_name(0, 0xFE)
        assert "0xFE" in name


class TestModifierBits:
    """Modifier constants must match the USB HID spec."""

    def test_left_modifiers(self):
        assert MOD_LCTRL == 0x01
        assert MOD_LSHIFT == 0x02
        assert MOD_LALT == 0x04
        assert MOD_LGUI == 0x08

    def test_right_modifiers(self):
        assert MOD_RCTRL == 0x10
        assert MOD_RSHIFT == 0x20
        assert MOD_RALT == 0x40
        assert MOD_RGUI == 0x80

    def test_no_overlap(self):
        all_mods = [
            MOD_LCTRL, MOD_LSHIFT, MOD_LALT, MOD_LGUI,
            MOD_RCTRL, MOD_RSHIFT, MOD_RALT, MOD_RGUI,
        ]
        # Each modifier is a single distinct bit
        combined = 0
        for m in all_mods:
            assert combined & m == 0, f"Overlap at 0x{m:02X}"
            combined |= m
        assert combined == 0xFF


class TestDefaultKeymap:
    """DEFAULT_KEYMAP entries must be valid HID values."""

    def test_all_keycodes_in_range(self):
        for key_id, (mod, kc) in DEFAULT_KEYMAP.items():
            assert 0 <= mod <= 0xFF, f"key_id {key_id}: mod out of range"
            assert 0 <= kc <= 0xFF, f"key_id {key_id}: keycode out of range"

    def test_key_ids_positive(self):
        for key_id in DEFAULT_KEYMAP:
            assert key_id > 0

    def test_wasd_present(self):
        """Key IDs 1-4 should map to W, S, A, D (0x1A, 0x16, 0x04, 0x07)."""
        assert DEFAULT_KEYMAP[1] == (0, 0x1A)  # W
        assert DEFAULT_KEYMAP[2] == (0, 0x16)  # S
        assert DEFAULT_KEYMAP[3] == (0, 0x04)  # A
        assert DEFAULT_KEYMAP[4] == (0, 0x07)  # D
