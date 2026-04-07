import sys

from joycon_helper.logger import cleanup_old_logs, install_crash_handler, setup_logging

# Initialise logging and crash handling before anything else.
setup_logging()
install_crash_handler()
cleanup_old_logs()


def _run() -> None:
    """Select UI backend and run the application."""
    if "--legacy" in sys.argv:
        # Original Tkinter UI
        from joycon_helper.app import main  # noqa: E402
        main()
    else:
        # New PyQt6 UI (default)
        from PyQt6.QtWidgets import QApplication
        from joycon_helper.ui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName("Bind Bandit")
        app.setOrganizationName("JoyConBridge")

        window = MainWindow()
        window.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    _run()
