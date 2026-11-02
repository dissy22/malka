import sys
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from malka.ui.main_window import MainWindow


def main():
    # Enable high DPI scaling
    app = QApplication(sys.argv)
    app.setApplicationName("Malka")
    app.setOrganizationName("MalkaMusic")

    # Set default modern font
    font = QFont("Segoe UI", 9)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
