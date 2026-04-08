"""First-run onboarding wizard.

A 5-page guided setup shown on first launch to walk new users through
connecting their hardware and verifying input.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow

_SETTINGS_KEY = "onboarding_done"


def should_show_onboarding() -> bool:
    """Return True if the onboarding wizard has not been completed."""
    settings = QSettings()
    return not settings.value(_SETTINGS_KEY, False, type=bool)


class OnboardingWizard(QDialog):
    """Modal 5-page setup wizard for first-time users."""

    def __init__(self, main: MainWindow, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent or main)
        self._main = main
        self.setWindowTitle("Welcome to Bind Bandit")
        self.setMinimumSize(600, 420)
        self.setModal(True)

        outer = QVBoxLayout(self)

        # Page stack
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        self._build_pages()

        # Navigation buttons
        nav = QHBoxLayout()

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setToolTip("Skip the setup wizard — you can reopen it from Settings")
        self._skip_btn.clicked.connect(self._finish)
        nav.addWidget(self._skip_btn)

        nav.addStretch()

        self._back_btn = QPushButton("← Back")
        self._back_btn.clicked.connect(self._go_back)
        self._back_btn.setEnabled(False)
        nav.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setProperty("accent", True)
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn)

        outer.addLayout(nav)

        # Progress label
        self._progress = QLabel("Step 1 of 5")
        self._progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._progress)

        self._update_nav()

    # -----------------------------------------------------------------

    def _build_pages(self) -> None:
        # Page 0: Welcome
        p0 = QWidget()
        lay0 = QVBoxLayout(p0)
        lay0.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Welcome to Bind Bandit!")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay0.addWidget(title)
        desc = QLabel(
            "This wizard will help you set up your Joy-Con → Keyboard bridge.\n\n"
            "You'll need:\n"
            "  • ESP32 board (Bluetooth host)\n"
            "  • ESP32-S3 board (USB keyboard)\n"
            "  • A Joy-Con or compatible Bluetooth controller\n"
            "  • USB cable for the ESP32-S3\n\n"
            "Let's get started!"
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay0.addWidget(desc)
        self._stack.addWidget(p0)

        # Page 1: Connect USB
        p1 = QWidget()
        lay1 = QVBoxLayout(p1)
        lay1.setAlignment(Qt.AlignmentFlag.AlignTop)
        t1 = QLabel("Step 1: Connect the ESP32-S3 via USB")
        t1.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lay1.addWidget(t1)
        lay1.addWidget(QLabel(
            "Plug the ESP32-S3 board into your PC with a USB cable.\n"
            "It should appear as a COM port below.\n\n"
            "If you don't see it, click Refresh."
        ))
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self._wiz_port_combo = QComboBox()
        self._wiz_port_combo.setMinimumWidth(200)
        port_row.addWidget(self._wiz_port_combo)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_wiz_ports)
        port_row.addWidget(refresh_btn)
        port_row.addStretch()
        lay1.addLayout(port_row)
        lay1.addStretch()
        self._stack.addWidget(p1)

        # Page 2: Pair Controller
        p2 = QWidget()
        lay2 = QVBoxLayout(p2)
        lay2.setAlignment(Qt.AlignmentFlag.AlignTop)
        t2 = QLabel("Step 2: Pair Your Controller")
        t2.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lay2.addWidget(t2)
        lay2.addWidget(QLabel(
            "Put your Joy-Con into pairing mode:\n\n"
            "  1. Hold the Sync button on the Joy-Con rail until\n"
            "     the player LEDs blink rapidly.\n"
            "  2. The ESP32 host will discover and pair automatically.\n\n"
            "Once paired, the controller LEDs will settle on a\n"
            "single player indicator.\n\n"
            "You can verify connection status on the Dashboard tab."
        ))
        lay2.addStretch()
        self._stack.addWidget(p2)

        # Page 3: Test Input
        p3 = QWidget()
        lay3 = QVBoxLayout(p3)
        lay3.setAlignment(Qt.AlignmentFlag.AlignTop)
        t3 = QLabel("Step 3: Test Input")
        t3.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lay3.addWidget(t3)
        lay3.addWidget(QLabel(
            "Press any button on your Joy-Con.\n\n"
            "If everything is wired correctly, you should see\n"
            "key events appear in the Device Log at the bottom\n"
            "of the main window.\n\n"
            "Try the A, B, X, Y buttons and the D-pad.\n\n"
            "If nothing appears, check:\n"
            "  • Wiring between the two ESP32 boards (UART TX→RX)\n"
            "  • That both boards are powered and flashed\n"
            "  • The correct COM port is selected"
        ))
        lay3.addStretch()
        self._stack.addWidget(p3)

        # Page 4: Done
        p4 = QWidget()
        lay4 = QVBoxLayout(p4)
        lay4.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t4 = QLabel("You're All Set!")
        t4.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        t4.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay4.addWidget(t4)
        lay4.addWidget(QLabel(
            "Your Joy-Con bridge is ready to use.\n\n"
            "  • Go to Mapping to assign controller buttons to keyboard keys\n"
            "  • Use Macros & Stick to create macro sequences\n"
            "  • Visit Profiles to save and share your setups\n"
            "  • Check the Help tab for detailed documentation\n\n"
            "Happy gaming!"
        ))
        self._dont_show = QCheckBox("Don't show this again")
        self._dont_show.setChecked(True)
        lay4.addWidget(self._dont_show, alignment=Qt.AlignmentFlag.AlignCenter)
        lay4.addStretch()
        self._stack.addWidget(p4)

    # -----------------------------------------------------------------

    def _refresh_wiz_ports(self) -> None:
        import serial.tools.list_ports
        self._wiz_port_combo.clear()
        for p in serial.tools.list_ports.comports():
            self._wiz_port_combo.addItem(f"{p.device} — {p.description}", p.device)

    def _update_nav(self) -> None:
        idx = self._stack.currentIndex()
        total = self._stack.count()
        self._back_btn.setEnabled(idx > 0)
        is_last = idx == total - 1
        self._next_btn.setText("Finish" if is_last else "Next →")
        self._progress.setText(f"Step {idx + 1} of {total}")

    def _go_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
            self._update_nav()
            # Auto-populate ports when reaching the connect page
            if idx + 1 == 1:
                self._refresh_wiz_ports()
        else:
            self._finish()

    def _go_back(self) -> None:
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._update_nav()

    def _finish(self) -> None:
        if hasattr(self, "_dont_show") and self._dont_show.isChecked():
            settings = QSettings()
            settings.setValue(_SETTINGS_KEY, True)
        self.accept()
