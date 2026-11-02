"""
Custom window title bar for Malka.
Provides:
- Window icon and title
- Window drag to move
- Double-click to maximize/restore
- Minimize, Maximize/Restore, and Close buttons styled to match the dark theme
"""
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from malka.config import config


class CustomTitleBar(QWidget):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.window = parent_window
        self.setFixedHeight(34)
        self.setObjectName("customTitleBar")

        self.apply_theme(getattr(config, "theme", "dark"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(6)

        # App Icon & Title
        self.icon_label = QLabel("🎵")
        self.icon_label.setStyleSheet("font-size: 11pt; background: transparent;")
        layout.addWidget(self.icon_label)

        self.title_label = QLabel("Malka")
        self.title_label.setObjectName("titleText")
        layout.addWidget(self.title_label)

        layout.addStretch()

        # Minimize Button
        self.btn_min = QPushButton("─")
        self.btn_min.setProperty("class", "captionBtn")
        self.btn_min.setToolTip("Minimize")
        self.btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_min.clicked.connect(self.window.showMinimized)
        layout.addWidget(self.btn_min)

        # Maximize / Restore Button
        self.btn_max = QPushButton("□")
        self.btn_max.setProperty("class", "captionBtn")
        self.btn_max.setToolTip("Maximize")
        self.btn_max.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_max.clicked.connect(self._toggle_max_restore)
        layout.addWidget(self.btn_max)

        # Close Button
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("closeCaptionBtn")
        self.btn_close.setProperty("class", "captionBtn")
        self.btn_close.setToolTip("Close")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.window.close)
        layout.addWidget(self.btn_close)

        self._drag_pos = QPoint()

    def apply_theme(self, theme: str):
        if theme == "light":
            self.setStyleSheet("""
                QWidget#customTitleBar {
                    background-color: #ffffff;
                    border-bottom: 1px solid #d0d7de;
                }
                QLabel#titleText {
                    color: #1f2328;
                    font-size: 9pt;
                    font-weight: 600;
                    background: transparent;
                }
                QPushButton.captionBtn {
                    background-color: transparent;
                    border: none;
                    color: #656d76;
                    font-size: 10pt;
                    border-radius: 4px;
                    min-width: 44px;
                    max-width: 44px;
                    min-height: 28px;
                    max-height: 28px;
                }
                QPushButton.captionBtn:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                    border: none;
                    color: #1f2328;
                }
                QPushButton.captionBtn:pressed {
                    background-color: rgba(0, 0, 0, 0.12);
                    border: none;
                }
                QPushButton#closeCaptionBtn:hover {
                    background-color: #e81123;
                    border: none;
                    color: #ffffff;
                }
                QPushButton#closeCaptionBtn:pressed {
                    background-color: #c40e1e;
                    border: none;
                }
            """)
        else:
            self.setStyleSheet("""
                QWidget#customTitleBar {
                    background-color: #0f1318;
                    border-bottom: 1px solid #21262d;
                }
                QLabel#titleText {
                    color: #c9d1d9;
                    font-size: 9pt;
                    font-weight: 600;
                    background: transparent;
                }
                QPushButton.captionBtn {
                    background-color: transparent;
                    border: none;
                    color: #8b949e;
                    font-size: 10pt;
                    border-radius: 4px;
                    min-width: 44px;
                    max-width: 44px;
                    min-height: 28px;
                    max-height: 28px;
                }
                QPushButton.captionBtn:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: none;
                    color: #ffffff;
                }
                QPushButton.captionBtn:pressed {
                    background-color: rgba(255, 255, 255, 0.15);
                    border: none;
                }
                QPushButton#closeCaptionBtn:hover {
                    background-color: #e81123;
                    border: none;
                    color: #ffffff;
                }
                QPushButton#closeCaptionBtn:pressed {
                    background-color: #c40e1e;
                    border: none;
                }
            """)

    def update_max_restore_button(self, is_maximized: bool):
        if is_maximized:
            self.btn_max.setText("❐")
            self.btn_max.setToolTip("Restore")
        else:
            self.btn_max.setText("□")
            self.btn_max.setToolTip("Maximize")

    def _toggle_max_restore(self):
        if self.window.isMaximized():
            self.window.showNormal()
            self.update_max_restore_button(False)
        else:
            self.window.showMaximized()
            self.update_max_restore_button(True)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window.windowHandle()
            if handle:
                handle.startSystemMove()
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_max_restore()
            event.accept()
        super().mouseDoubleClickEvent(event)
