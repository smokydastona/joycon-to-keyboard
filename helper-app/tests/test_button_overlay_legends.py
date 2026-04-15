import sys
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_keyboard_overlay_legends_match_keycaps() -> None:
    mod = import_module("tools.generate_button_overlays")

    assert mod._overlay_legend("keyboard", "Backspace") == "Back"
    assert mod._overlay_legend("keyboard", "KPEnter") == "Ent"
    assert mod._overlay_legend("keyboard", "A") == "A"
    assert mod._overlay_legend("keyboard", "KP7") == "7"


def test_other_devices_use_short_physical_legends() -> None:
    mod = import_module("tools.generate_button_overlays")

    assert mod._overlay_legend("joycon", "Capture") == "Cap"
    assert mod._overlay_legend("joycon", "Minus") == "-"
    assert mod._overlay_legend("gamepad", "Xbox") == "XB"
    assert mod._overlay_legend("mouse", "forward") == "Fwd"
    assert mod._overlay_legend("m913", "side12") == "12"
