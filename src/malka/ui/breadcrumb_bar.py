"""Clickable breadcrumb path used in the main navigation row."""
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

BreadcrumbItem = Tuple[str, Optional[Callable[[], None]]]


class BreadcrumbBar(QFrame):
    """
    Displays a library path such as ``All albums / Artist / Album /`` where every
    parent segment is clickable.  Long paths are elided segment by segment so the
    bar always fits the area reserved for it by the navigation row.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("breadcrumbBar")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._items: List[BreadcrumbItem] = []
        self._entries: List[dict] = []
        self._separators: List[QLabel] = []
        self._theme = "dark"

        self.apply_theme("dark")
        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_path(self, items: List[BreadcrumbItem]):
        self._items = list(items or [])
        self._rebuild()

    def plain_text(self) -> str:
        parts = [text for text, _ in self._items]
        if not parts:
            return ""
        return " / ".join(parts) + " /"

    def text(self) -> str:
        return self.plain_text()

    def segments(self) -> List[str]:
        return [text for text, _ in self._items]

    def apply_theme(self, theme: str):
        self._theme = theme
        is_light = (theme == "light")
        if is_light:
            link_col, hover_col = "#0969da", "#0550ae"
            current_col, sep_col = "#1f2328", "#8c959f"
        else:
            link_col, hover_col = "#58a6ff", "#79c0ff"
            current_col, sep_col = "#e6edf3", "#6e7681"

        self.setStyleSheet(f"""
            QFrame#breadcrumbBar {{
                background: transparent;
                border: none;
            }}
            QPushButton#breadcrumbSegment {{
                background: transparent;
                border: none;
                color: {link_col};
                font-size: 12px;
                font-weight: 500;
                padding: 0px;
                text-align: center;
            }}
            QPushButton#breadcrumbSegment:hover {{
                color: {hover_col};
                background: transparent;
            }}
            QLabel#breadcrumbCurrent {{
                color: {current_col};
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }}
            QLabel#breadcrumbSep {{
                color: {sep_col};
                font-size: 12px;
                background: transparent;
            }}
        """)
        self._apply_sizes()

    # ------------------------------------------------------------------
    # Internal UI construction
    # ------------------------------------------------------------------
    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._entries = []
        self._separators = []

    def _rebuild(self):
        self._clear()

        for index, (text, callback) in enumerate(self._items):
            if callback is not None:
                # Escape '&' for QPushButton: a single ampersand is interpreted as
                # a mnemonic marker and disappears from artist names such as
                # "Bill Brown & Jamie Christopherson".
                widget: QWidget = QPushButton(text.replace("&", "&&"))
                widget.setObjectName("breadcrumbSegment")
                widget.setCursor(Qt.CursorShape.PointingHandCursor)
                widget.setFlat(True)
                # QPushButton.clicked passes a bool; absorb it so lambdas with
                # default arguments are not accidentally called with the bool.
                widget.clicked.connect(lambda checked=False, cb=callback: cb())
            else:
                widget = QLabel(text)
                widget.setObjectName("breadcrumbCurrent")
                widget.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

            # Give widgets a concrete 12 px font so QFontMetrics used for
            # sizing/eliding matches the stylesheet-rendered text exactly.
            font = QFont(self.font())
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.DemiBold if callback is None else QFont.Weight.Medium)
            widget.setFont(font)

            widget.setToolTip(text)
            self._layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
            self._entries.append({"widget": widget, "text": text, "is_button": callback is not None})

            sep = QLabel("/")
            sep.setObjectName("breadcrumbSep")
            sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sep.setFixedWidth(12)
            self._layout.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
            self._separators.append(sep)

        self._layout.addStretch(1)
        # Re-apply the stylesheet after the widgets have been (re)created.
        self.apply_theme(self._theme)
        QTimer.singleShot(0, self._apply_sizes)

    def _apply_sizes(self):
        if not self._entries:
            return

        available = max(0, self.width() - 2)
        sep_total = len(self._separators) * 12
        content_available = max(0, available - sep_total)

        # Measure the full (unescaped) segment texts.  Never scale every segment
        # proportionally: short words like "All albums" or "Björk" must not be
        # chopped just because one artist name is very long.
        natural_widths = []
        for entry in self._entries:
            widget = entry["widget"]
            widget.setMinimumWidth(0)
            widget.setMaximumWidth(16777215)
            if entry["is_button"]:
                widget.setText(entry["text"].replace("&", "&&"))
            else:
                widget.setText(entry["text"])
            natural_widths.append(max(16, widget.sizeHint().width()))

        if sum(natural_widths) <= content_available or content_available <= 0:
            widths = list(natural_widths)
        else:
            widths = list(natural_widths)
            overflow = sum(widths) - content_available
            # First shrink only genuinely long segments (keep short words intact).
            for floor in (72, 36, 18):
                if overflow <= 0:
                    break
                order = sorted(range(len(widths)), key=lambda i: widths[i], reverse=True)
                for idx in order:
                    if overflow <= 0:
                        break
                    reducible = widths[idx] - floor
                    if reducible <= 0:
                        continue
                    reduction = min(overflow, reducible)
                    widths[idx] -= reduction
                    overflow -= reduction

        for idx, (entry, width) in enumerate(zip(self._entries, widths)):
            widget = entry["widget"]
            natural = natural_widths[idx]
            widget.setFixedWidth(max(16, width))
            if width < natural:
                fm: QFontMetrics = widget.fontMetrics()
                display_text = fm.elidedText(entry["text"], Qt.TextElideMode.ElideRight, max(4, width - 2))
                if entry["is_button"]:
                    widget.setText(display_text.replace("&", "&&"))
                else:
                    widget.setText(display_text)
            else:
                if entry["is_button"]:
                    widget.setText(entry["text"].replace("&", "&&"))
                else:
                    widget.setText(entry["text"])
            widget.setToolTip(entry["text"])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_sizes()
