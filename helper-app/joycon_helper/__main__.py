import sys

from joycon_helper.logger import cleanup_old_logs, install_crash_handler, setup_logging

# Initialise logging and crash handling before anything else.
setup_logging()
install_crash_handler()
cleanup_old_logs()


def _run() -> None:
    """Launch the PyQt6 application."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    from joycon_helper.ui.assets import register_app_fonts
    from joycon_helper.ui.main_window import MainWindow
    from joycon_helper.user_data import migrate_legacy_files

    # Ensure persistent data directory exists and migrate legacy files.
    migrate_legacy_files()

    app = QApplication(sys.argv)
    app.setApplicationName("Bind Bandit")
    app.setOrganizationName("JoyConBridge")

    # Register custom fonts before any widgets are created.
    register_app_fonts()

    # Keep the app alive when the window is hidden (system tray mode).
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()

    settings = QSettings()
    start_minimized = (
        "--minimized" in sys.argv
        or settings.value("start_minimized", False, type=bool)
    )
    if not start_minimized:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    _run()
