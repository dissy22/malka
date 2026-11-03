from typing import Iterable, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class RescanLibrariesDialog(QDialog):
    """Choose which configured library roots to rescan."""

    def __init__(self, paths: Iterable[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rescan Libraries")
        self.resize(640, 420)
        self._checks: List[QCheckBox] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel("Select the library folders you want to rescan:")
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 6)
        body_layout.setSpacing(4)
        for path in paths:
            check = QCheckBox(path)
            check.setChecked(True)
            check.setToolTip(path)
            body_layout.addWidget(check)
            self._checks.append(check)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        select_row = QHBoxLayout()
        btn_all = QPushButton("Select All")
        btn_none = QPushButton("Deselect All")
        btn_all.clicked.connect(lambda: [c.setChecked(True) for c in self._checks])
        btn_none.clicked.connect(lambda: [c.setChecked(False) for c in self._checks])
        select_row.addWidget(btn_all)
        select_row.addWidget(btn_none)
        select_row.addStretch(1)
        layout.addLayout(select_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        scan = QPushButton("Rescan Selected")
        scan.setDefault(True)
        scan.clicked.connect(self._accept_if_any)
        buttons.addWidget(cancel)
        buttons.addWidget(scan)
        layout.addLayout(buttons)

    def _accept_if_any(self):
        if self.selected_paths():
            self.accept()

    def selected_paths(self) -> List[str]:
        return [c.text() for c in self._checks if c.isChecked()]
