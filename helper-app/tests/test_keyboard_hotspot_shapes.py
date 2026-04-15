from joycon_helper.ui.constants import KBD_BUTTON_SHAPES, KBD_HOTSPOTS


def test_keyboard_shapes_cover_all_keyboard_hotspots():
    hotspot_names = {name for name, _, _ in KBD_HOTSPOTS["default"]}
    assert hotspot_names <= set(KBD_BUTTON_SHAPES)


def test_keyboard_shapes_capture_key_size_variants():
    standard = KBD_BUTTON_SHAPES["A"]
    backspace = KBD_BUTTON_SHAPES["Backspace"]
    kp_plus = KBD_BUTTON_SHAPES["KPPlus"]
    space = KBD_BUTTON_SHAPES["Space"]

    assert standard == ("rrect", 54, 54, 8)
    assert backspace[1] > standard[1]
    assert kp_plus[2] > standard[2]
    assert space[1] > backspace[1]