import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_keyboard_shapes_cover_all_keyboard_hotspots():
    from joycon_helper.ui.constants import KBD_BUTTON_SHAPES, KBD_HOTSPOTS

    hotspot_names = {name for name, _, _ in KBD_HOTSPOTS["default"]}
    assert hotspot_names <= set(KBD_BUTTON_SHAPES)


def test_keyboard_shapes_capture_key_size_variants():
    from joycon_helper.ui.constants import KBD_BUTTON_SHAPES

    standard = KBD_BUTTON_SHAPES["A"]
    backspace = KBD_BUTTON_SHAPES["Backspace"]
    kp_plus = KBD_BUTTON_SHAPES["KPPlus"]
    space = KBD_BUTTON_SHAPES["Space"]

    assert standard == ("rrect", 54, 54, 8)
    assert backspace[1] > standard[1]
    assert kp_plus[2] > standard[2]
    assert space[1] > backspace[1]


def test_keyboard_default_hotspots_match_applied_layout():
    from joycon_helper.ui.constants import KBD_HOTSPOTS

    dark = dict((name, (x, y)) for name, x, y in KBD_HOTSPOTS["dark"])
    default = dict((name, (x, y)) for name, x, y in KBD_HOTSPOTS["default"])

    assert dark == default
    assert default["Esc"] == (0.137511, 0.298956)
    assert default["Space"] == (0.367276, 0.56658)
    assert default["KPEnter"] == (0.850305, 0.562663)


def test_keyboard_overlay_generator_uses_keyboard_shapes():
    from importlib import import_module

    DEVICES = import_module("tools.generate_button_overlays").DEVICES
    KBD_BUTTON_SHAPES = import_module("joycon_helper.ui.constants").KBD_BUTTON_SHAPES

    assert DEVICES["keyboard"]["shapes"] is KBD_BUTTON_SHAPES
