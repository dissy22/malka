from PyQt6.QtCore import QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


class SectionHeaderWidget(QWidget):
    is_section_header = True

    def __init__(
        self,
        title: str,
        count: int = 0,
        is_first: bool = False,
        theme: str = "dark",
        parent=None,
    ):
        super().__init__(parent)
        self.theme = theme
        self.is_first = is_first
        self.title_text = title
        self.count = count
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        top_margin = 4 if is_first else 22
        layout.setContentsMargins(0, top_margin, 0, 6)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))

        self.count_label = QLabel(f"({count})" if count > 0 else "")
        self.count_label.setFont(QFont("Segoe UI", 10))

        layout.addWidget(self.title_label)
        if count > 0:
            layout.addWidget(self.count_label)
        layout.addStretch()

        self.apply_theme(theme)

    def sizeHint(self) -> QSize:
        h = 36 if self.is_first else 54
        return QSize(200, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def apply_theme(self, theme: str):
        self.theme = theme
        if theme == "light":
            self.title_label.setStyleSheet("color: #1f2328; font-weight: bold; background: transparent; border: none;")
            self.count_label.setStyleSheet("color: #656d76; font-weight: 500; background: transparent; border: none;")
        else:
            self.title_label.setStyleSheet("color: #f0f6fc; font-weight: bold; background: transparent; border: none;")
            self.count_label.setStyleSheet("color: #8b949e; font-weight: 500; background: transparent; border: none;")
