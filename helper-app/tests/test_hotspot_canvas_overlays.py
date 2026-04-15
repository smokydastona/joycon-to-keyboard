import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _dispose_canvas(canvas) -> None:
    canvas._pulse_timer.stop()
    canvas.hide()
    canvas.setParent(None)
    canvas.deleteLater()


def test_hotspot_canvas_builds_overlay_brushes_without_file_assets() -> None:
    from PyQt6.QtGui import QPixmap

    from joycon_helper.ui.theme import ThemeEngine
    from joycon_helper.ui.widgets.hotspot_canvas import HotspotCanvas

    app = _app()
    canvas = HotspotCanvas(ThemeEngine(mode="light"))
    background = QPixmap(400, 200)
    background.fill()
    canvas.set_background(background)
    canvas.set_hotspot_shapes({"A": ("rrect", 60, 40, 8)})
    canvas.set_hotspots([("A", 0.25, 0.5)])
    canvas.set_overlay_paths({})

    brush = canvas._overlay_brushes["A"]

    assert brush.texture().isNull() is False
    assert brush.transform().m31() > 0
    _dispose_canvas(canvas)
    assert app is not None


def test_hotspot_canvas_realigns_overlay_brushes_after_hotspot_moves() -> None:
    from PyQt6.QtGui import QPixmap

    from joycon_helper.ui.theme import ThemeEngine
    from joycon_helper.ui.widgets.hotspot_canvas import HotspotCanvas

    app = _app()
    canvas = HotspotCanvas(ThemeEngine(mode="light"))
    background = QPixmap(400, 200)
    background.fill()
    canvas.set_background(background)
    canvas.set_hotspot_shapes({"A": ("rrect", 60, 40, 8)})
    canvas.set_hotspots([("A", 0.20, 0.50)])

    before = canvas._overlay_brushes["A"].transform().m31()
    canvas._hotspots[0].norm_x = 0.70
    canvas._build_overlay_brushes()
    after = canvas._overlay_brushes["A"].transform().m31()

    assert after > before
    _dispose_canvas(canvas)
    assert app is not None
