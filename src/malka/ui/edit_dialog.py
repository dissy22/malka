from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from malka.config import NO_DATA, config
from malka.db import get_album_tracks, update_track
from malka.organizer import is_album_ready_to_organize
from malka.tags import write_tags
from malka.ui.image_utils import checkbox_checkmark_qss

COMMON_DARK_STYLESHEET = """
    QDialog {
        background-color: #0d1117;
        color: #e6edf3;
    }
    QWidget {
        color: #e6edf3;
    }
    QLabel {
        color: #e6edf3;
    }
    QCheckBox {
        color: #e6edf3;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #30363d;
        border-radius: 3px;
        background-color: #161b22;
    }
    QCheckBox::indicator:checked {
        background-color: #238636;
        border-color: #2ea043;
    }
    QTabWidget::pane {
        border: 1px solid #30363d;
        background: #161b22;
        border-radius: 6px;
    }
    QTabBar::tab {
        background: #0d1117;
        color: #8b949e;
        padding: 8px 18px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
        font-weight: 500;
    }
    QTabBar::tab:selected {
        background: #161b22;
        color: #ffffff;
        border-bottom: 2px solid #58a6ff;
    }
    QTabBar::tab:hover:!selected {
        color: #c9d1d9;
        background: #1a1e24;
    }
    QLineEdit {
        background-color: #0d1117;
        border: 1px solid #30363d;
        border-radius: 5px;
        padding: 6px 10px;
        color: #ffffff;
    }
    QLineEdit:focus {
        border: 1px solid #58a6ff;
        background-color: #0d1117;
    }
    QPushButton {
        background-color: #21262d;
        border: 1px solid #30363d;
        border-radius: 5px;
        color: #e6edf3;
        padding: 7px 16px;
        min-width: 90px;
        font-weight: 500;
    }
    QPushButton:hover {
        background-color: #30363d;
        border-color: #8b949e;
        color: #ffffff;
    }
    QPushButton:pressed {
        background-color: #161b22;
    }
    QPushButton#saveBtn, QPushButton#importBtn {
        background-color: #238636;
        border: 1px solid #2ea043;
        color: #ffffff;
        font-weight: bold;
    }
    QPushButton#saveBtn:hover, QPushButton#importBtn:hover {
        background-color: #2ea043;
        border-color: #3fb950;
    }
    QPushButton:disabled {
        background-color: #161b22;
        border-color: #30363d;
        color: #6e7681;
    }
    QListWidget {
        background-color: #0d1117;
        border: 1px solid #30363d;
        border-radius: 5px;
        color: #ffffff;
    }
    QListWidget::item {
        padding: 6px 8px;
        border-bottom: 1px solid #161b22;
        color: #e6edf3;
    }
    QListWidget::item:selected {
        background-color: #1f6feb;
        color: #ffffff;
        border-radius: 4px;
    }
    QListWidget::item:hover:!selected {
        background-color: #161b22;
        color: #ffffff;
    }
    QSplitter::handle {
        background-color: #30363d;
    }
"""

COMMON_LIGHT_STYLESHEET = """
    QDialog {
        background-color: #f6f8fa;
        color: #1f2328;
    }
    QWidget {
        color: #1f2328;
    }
    QLabel {
        color: #1f2328;
    }
    QCheckBox {
        color: #1f2328;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #d0d7de;
        border-radius: 3px;
        background-color: #ffffff;
    }
    QCheckBox::indicator:checked {
        background-color: #1f883d;
        border-color: #1f883d;
    }
    QTabWidget::pane {
        border: 1px solid #d0d7de;
        background: #ffffff;
        border-radius: 6px;
    }
    QTabBar::tab {
        background: #eaeef2;
        color: #656d76;
        padding: 8px 18px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
        font-weight: 500;
    }
    QTabBar::tab:selected {
        background: #ffffff;
        color: #1f2328;
        border-bottom: 2px solid #0969da;
    }
    QTabBar::tab:hover:!selected {
        color: #1f2328;
        background: #f0f3f6;
    }
    QLineEdit {
        background-color: #ffffff;
        border: 1px solid #d0d7de;
        border-radius: 5px;
        padding: 6px 10px;
        color: #1f2328;
    }
    QLineEdit:focus {
        border: 1px solid #0969da;
        background-color: #ffffff;
    }
    QPushButton {
        background-color: #f6f8fa;
        border: 1px solid #d0d7de;
        border-radius: 5px;
        color: #1f2328;
        padding: 7px 16px;
        min-width: 90px;
        font-weight: 500;
    }
    QPushButton:hover {
        background-color: #eaeef2;
        border-color: #b0b8c1;
        color: #1f2328;
    }
    QPushButton:pressed {
        background-color: #dbe0e6;
    }
    QPushButton#saveBtn, QPushButton#importBtn {
        background-color: #1f883d;
        border: 1px solid #1a7f37;
        color: #ffffff;
        font-weight: bold;
    }
    QPushButton#saveBtn:hover, QPushButton#importBtn:hover {
        background-color: #1a7f37;
        border-color: #116329;
    }
    QPushButton:disabled {
        background-color: #f6f8fa;
        border-color: #d0d7de;
        color: #8c959f;
    }
    QListWidget {
        background-color: #ffffff;
        border: 1px solid #d0d7de;
        border-radius: 5px;
        color: #1f2328;
    }
    QListWidget::item {
        padding: 6px 8px;
        border-bottom: 1px solid #f0f2f5;
        color: #1f2328;
    }
    QListWidget::item:selected {
        background-color: #0969da;
        color: #ffffff;
        border-radius: 4px;
    }
    QListWidget::item:hover:!selected {
        background-color: #f3f4f6;
        color: #1f2328;
    }
    QSplitter::handle {
        background-color: #d0d7de;
    }
"""


class CoverPreviewWidget(QWidget):
    cover_changed = pyqtSignal(str)  # "new", "delete", "keep"
    search_requested = pyqtSignal()

    def __init__(self, size: int = 120, parent=None, theme: str = "dark"):
        super().__init__(parent)
        self.preview_size = size
        self.theme = theme
        self.action = "keep"  # keep, new, delete
        self.new_image_path: Optional[str] = None
        self.original_image_path: Optional[str] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(size, size)
        self.preview_label.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.preview_label)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_add = QPushButton("Add Cover")
        self.btn_add.clicked.connect(self._on_add_cover)
        btn_layout.addWidget(self.btn_add)

        self.btn_search = QPushButton("Search for cover art online")
        self.btn_search.setObjectName("searchCoverBtn")
        self.btn_search.setToolTip("Search Discogs using the Album, Artist and Year fields")
        self.btn_search.clicked.connect(self.search_requested.emit)
        btn_layout.addWidget(self.btn_search)

        self.btn_delete = QPushButton("Delete Cover")
        self.btn_delete.clicked.connect(self._on_delete_cover)
        btn_layout.addWidget(self.btn_delete)

        layout.addLayout(btn_layout)
        layout.addStretch()

        self._update_preview()

    def apply_theme(self, theme: str):
        self.theme = theme
        if theme == "light":
            self.btn_search.setStyleSheet(
                "QPushButton { background:#0969da; border:1px solid #0969da;"
                " color:#ffffff; font-weight:600; padding:7px 12px; border-radius:5px; }"
                "QPushButton:hover { background:#0860ca; }"
            )
        else:
            self.btn_search.setStyleSheet(
                "QPushButton { background:#1f6feb; border:1px solid #388bfd;"
                " color:#ffffff; font-weight:600; padding:7px 12px; border-radius:5px; }"
                "QPushButton:hover { background:#388bfd; }"
            )
        self._update_preview()

    def set_controls_enabled(self, loaded: bool, search_enabled: bool):
        self.btn_add.setEnabled(loaded)
        self.btn_search.setEnabled(loaded and search_enabled)
        self.btn_delete.setEnabled(
            loaded and (bool(self.original_image_path) or self.action == "new")
        )

    def set_original_cover(self, path: Optional[str]):
        self.original_image_path = path if path and Path(path).exists() else None
        self.action = "keep"
        self.new_image_path = None
        self._update_preview()

    def _on_add_cover(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cover Image",
            "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)",
        )
        if file_path:
            self.action = "new"
            self.new_image_path = file_path
            self._update_preview()
            self.cover_changed.emit("new")

    def _on_delete_cover(self):
        self.action = "delete"
        self.new_image_path = None
        self._update_preview()
        self.cover_changed.emit("delete")

    def _update_preview(self):
        if self.action == "delete":
            self.preview_label.setPixmap(self._create_placeholder())
        elif self.action == "new" and self.new_image_path:
            pix = QPixmap(self.new_image_path)
            if not pix.isNull():
                self.preview_label.setPixmap(self._scale_pixmap(pix))
            else:
                self.preview_label.setPixmap(self._create_placeholder())
        elif self.original_image_path:
            pix = QPixmap(self.original_image_path)
            if not pix.isNull():
                self.preview_label.setPixmap(self._scale_pixmap(pix))
            else:
                self.preview_label.setPixmap(self._create_placeholder())
        else:
            self.preview_label.setPixmap(self._create_placeholder())

    def _scale_pixmap(self, pix: QPixmap) -> QPixmap:
        s = self.preview_size
        scaled = pix.scaled(
            s, s,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cropped = scaled.copy(
            (scaled.width() - s) // 2,
            (scaled.height() - s) // 2,
            s, s,
        )
        return self._round_corners(cropped, 6)

    def _create_placeholder(self) -> QPixmap:
        s = self.preview_size
        pix = QPixmap(s, s)
        is_light = (self.theme == "light")
        bg_col = QColor("#ffffff" if is_light else "#161b22")
        border_col = QColor("#d0d7de" if is_light else "#30363d")
        icon_col = QColor("#8c959f" if is_light else "#6e7681")

        pix.fill(bg_col)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(border_col)
        painter.drawRoundedRect(1, 1, s - 2, s - 2, 6, 6)
        font = QFont("Segoe UI Symbol", max(16, s // 4))
        painter.setFont(font)
        painter.setPen(icon_col)
        painter.drawText(0, 0, s, s, Qt.AlignmentFlag.AlignCenter, "🖼️")
        painter.end()
        return self._round_corners(pix, 6)

    def _round_corners(self, pixmap: QPixmap, radius: int) -> QPixmap:
        rounded = QPixmap(pixmap.size())
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return rounded


class SaveProgressDialog(QDialog):
    """Modal progress dialog shown while tag/artwork changes are written."""

    def __init__(self, total: int, parent=None, theme: str = "dark"):
        super().__init__(parent)
        self.setWindowTitle("Saving changes")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setFixedSize(560, 160)
        self.setStyleSheet(
            "QDialog { background-color:#ffffff; color:#1f2328; }"
            "QLabel { color:#1f2328; font-size:12px; }"
            "QLabel#saveTitle { font-size:14px; font-weight:700; }"
            "QProgressBar { border:1px solid #d0d7de; border-radius:5px;"
            " background:#f6f8fa; height:16px; text-align:center; }"
            "QProgressBar::chunk { background:#0969da; border-radius:4px; }"
            if theme == "light" else
            "QDialog { background-color:#0d1117; color:#e6edf3; }"
            "QLabel { color:#e6edf3; font-size:12px; }"
            "QLabel#saveTitle { font-size:14px; font-weight:700; }"
            "QProgressBar { border:1px solid #30363d; border-radius:5px;"
            " background:#161b22; height:16px; text-align:center; }"
            "QProgressBar::chunk { background:#1f6feb; border-radius:4px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        title = QLabel("Saving changes")
        title.setObjectName("saveTitle")
        layout.addWidget(title)
        self.operation_label = QLabel("Preparing files…")
        self.operation_label.setWordWrap(True)
        layout.addWidget(self.operation_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m")
        layout.addWidget(self.progress)
        layout.addStretch(1)

    def set_operation(self, text: str, value: int):
        self.operation_label.setText(text)
        self.progress.setValue(max(0, min(value, self.progress.maximum())))
        QApplication.processEvents()

    def finish(self):
        self.progress.setValue(self.progress.maximum())
        QApplication.processEvents()
        self.accept()


class BaseAlbumEditDialog(QDialog):
    """
    Unified base dialog for album and single-track metadata editing.
    Ensures 100% identical layout, control hierarchy, tab synchronization, and theme styling.
    """

    def __init__(self, tracks: List[Dict[str, Any]], parent=None, theme: Optional[str] = None):
        super().__init__(parent)
        self.tracks = [dict(t) for t in tracks]
        self._initial_tracks = [dict(t) for t in tracks]
        self.current_single_track_idx = -1
        self.require_complete_tags = bool(getattr(self, "require_complete_tags", False))
        self._lookup_buttons: List[QPushButton] = []
        self._field_buttons: Dict[str, List[QPushButton]] = {}
        self._search_worker = None
        self._search_dialog = None
        self._search_canceled = False
        self._metadata_worker = None
        self._metadata_dialog = None
        self._metadata_canceled = False
        self._metadata_target_field = ""
        self._metadata_single = False
        self._metadata_candidate = None
        self._search_single = False

        if theme is not None:
            self.theme = theme
        elif hasattr(parent, "theme"):
            self.theme = parent.theme
        else:
            self.theme = getattr(config, "theme", "dark")

        # Multi-disc check
        discs = {str(t.get("disc_no", "1")).strip() for t in self.tracks if t.get("disc_no")}
        self.is_multi_disc = len(discs) > 1 or any(d not in ("1", "", NO_DATA) for d in discs)

        # Bad encoding check
        self.has_bad_encoding = any(t.get("bad_encoding") == 1 for t in self.tracks)
        if not self.has_bad_encoding:
            from malka.tags import detect_and_fix_encoding
            for t in self.tracks:
                for k in ("title", "artist", "album_artist", "album", "genre"):
                    val = t.get(k)
                    if val and val != NO_DATA:
                        bad, _ = detect_and_fix_encoding(str(val))
                        if bad:
                            self.has_bad_encoding = True
                            t["bad_encoding"] = 1
                            break
                if self.has_bad_encoding:
                    break

        self.resize(1200, 720)
        self.setMinimumSize(1040, 640)

        self._build_ui()
        if self.has_bad_encoding:
            self.encoding_warning_frame.setVisible(True)
            self.fix_encoding_checkbox.setChecked(True)
        else:
            self.encoding_warning_frame.setVisible(False)
            self.fix_encoding_checkbox.setChecked(False)

        self.apply_theme(self.theme)
        self._populate_initial_data()

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")
        self.setStyleSheet(COMMON_LIGHT_STYLESHEET if is_light else COMMON_DARK_STYLESHEET)
        panel_qss = (
            "QFrame#editPanel { background:#ffffff; border:1px solid #d0d7de;"
            " border-radius:8px; }"
            "QLabel#editSectionTitle { font-size:14px; font-weight:700; color:#1f2328; }"
            "QLabel#editSubtle { color:#656d76; font-size:11px; }"
            if is_light else
            "QFrame#editPanel { background:#161b22; border:1px solid #30363d;"
            " border-radius:8px; }"
            "QLabel#editSectionTitle { font-size:14px; font-weight:700; color:#ffffff; }"
            "QLabel#editSubtle { color:#8b949e; font-size:11px; }"
        )
        self.setStyleSheet(self.styleSheet() + panel_qss + checkbox_checkmark_qss())

        if hasattr(self, "album_cover_widget"):
            self.album_cover_widget.apply_theme(theme)
        if hasattr(self, "st_cover_widget"):
            self.st_cover_widget.apply_theme(theme)

        if is_light:
            lookup_qss = (
                "QPushButton { background:#f6f8fa; border:1px solid #d0d7de;"
                " border-radius:5px; color:#1f2328; padding:0; min-width:28px;"
                " max-width:28px; min-height:28px; max-height:28px; }"
                "QPushButton:hover { background:#eaeef2; border-color:#0969da; }"
            )
        else:
            lookup_qss = (
                "QPushButton { background:#21262d; border:1px solid #30363d;"
                " border-radius:5px; color:#e6edf3; padding:0; min-width:28px;"
                " max-width:28px; min-height:28px; max-height:28px; }"
                "QPushButton:hover { background:#30363d; border-color:#58a6ff; }"
            )
        icon_color = "#656d76" if is_light else "#8b949e"
        for button in self._lookup_buttons:
            button.setStyleSheet(lookup_qss)
            button.setIcon(self._search_icon(14, icon_color))

        title_col = "#57606a" if is_light else "#8b949e"
        if hasattr(self, "left_title"):
            self.left_title.setStyleSheet(f"font-weight: bold; color: {title_col};")
        if hasattr(self, "right_title"):
            self.right_title.setStyleSheet(f"font-weight: bold; color: {title_col};")

        if hasattr(self, "encoding_warning_frame"):
            if is_light:
                self.encoding_warning_frame.setStyleSheet("""
                    QFrame#encodingWarningFrame {
                        background-color: #fff8f2;
                        border: 1px solid #d46b08;
                        border-radius: 6px;
                    }
                    QLabel#encodingWarningLabel {
                        color: #b24d00;
                        font-size: 12px;
                        font-weight: 500;
                    }
                    QCheckBox#fixEncodingCheckbox {
                        color: #1f2328;
                        font-weight: 600;
                    }
                """)
            else:
                self.encoding_warning_frame.setStyleSheet("""
                    QFrame#encodingWarningFrame {
                        background-color: #2b1d0c;
                        border: 1px solid #9e4a15;
                        border-radius: 6px;
                    }
                    QLabel#encodingWarningLabel {
                        color: #ff9b57;
                        font-size: 12px;
                        font-weight: 500;
                    }
                    QCheckBox#fixEncodingCheckbox {
                        color: #f0f6fc;
                        font-weight: 600;
                    }
                """)

        self._validate_readiness()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 14, 16, 14)
        self.main_layout.setSpacing(12)

        # Top banner container (used by import mode and warnings)
        self.top_banner_container = QVBoxLayout()
        self.top_banner_container.setContentsMargins(0, 0, 0, 0)
        self.top_banner_container.setSpacing(8)
        self.main_layout.addLayout(self.top_banner_container)

        # Encoding warning banner
        self.encoding_warning_frame = QFrame()
        self.encoding_warning_frame.setObjectName("encodingWarningFrame")
        encoding_layout = QHBoxLayout(self.encoding_warning_frame)
        encoding_layout.setContentsMargins(12, 8, 12, 8)
        encoding_layout.setSpacing(12)

        self.encoding_warning_lbl = QLabel("⚠️ Improper character encoding detected in tags (mojibake).")
        self.encoding_warning_lbl.setObjectName("encodingWarningLabel")
        encoding_layout.addWidget(self.encoding_warning_lbl)

        encoding_layout.addStretch()

        self.fix_encoding_checkbox = QCheckBox("Fix tags encoding")
        self.fix_encoding_checkbox.setObjectName("fixEncodingCheckbox")
        encoding_layout.addWidget(self.fix_encoding_checkbox)

        self.top_banner_container.addWidget(self.encoding_warning_frame)

        # Tabs
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # Tab 1: Album edit
        self.tab_album = QWidget()
        self._setup_album_tab()
        self.tabs.addTab(self.tab_album, "Album edit")

        # Tab 2: Single track edit
        self.tab_tracks = QWidget()
        self._setup_single_track_tab()
        self.tabs.addTab(self.tab_tracks, "Single track edit")

        # Bottom Bar
        bottom_layout = QHBoxLayout()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
        bottom_layout.addWidget(self.status_lbl)
        bottom_layout.addStretch()

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setToolTip("Discard edits and reload the tag values")
        self.btn_reload.clicked.connect(self._on_reload)
        bottom_layout.addWidget(self.btn_reload)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(self.btn_cancel)

        self.btn_action = QPushButton("Save Changes")
        self.btn_action.setObjectName("saveBtn")
        bottom_layout.addWidget(self.btn_action)

        self.main_layout.addLayout(bottom_layout)

        # Connect tab switching
        self.tabs.currentChanged.connect(self._on_tab_changed)

    @staticmethod
    def _search_icon(size: int = 14, color: str = "#e6edf3") -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(2, 2, size - 7, size - 7)
        painter.drawLine(size - 5, size - 5, size - 1, size - 1)
        painter.end()
        return QIcon(pix)

    def _lookup_button(self, field: str, tip: str) -> QPushButton:
        button = QPushButton()
        button.setIcon(self._search_icon(14))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(28, 28)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._on_field_lookup(field))
        self._lookup_buttons.append(button)
        self._field_buttons.setdefault(field, []).append(button)
        return button

    def _with_lookup(self, edit: QLineEdit, field: str, tip: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(edit, 1)
        layout.addWidget(self._lookup_button(field, tip))
        return widget

    def _setup_album_tab(self):
        layout = QHBoxLayout(self.tab_album)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        form_panel = QFrame()
        form_panel.setObjectName("editPanel")
        form_panel_layout = QVBoxLayout(form_panel)
        form_panel_layout.setContentsMargins(16, 14, 16, 14)
        form_panel_layout.setSpacing(10)

        tags_title = QLabel("Tags")
        tags_title.setObjectName("editSectionTitle")
        form_panel_layout.addWidget(tags_title)
        tags_hint = QLabel("Values are read from the files and written back on save.")
        tags_hint.setObjectName("editSubtle")
        tags_hint.setWordWrap(True)
        form_panel_layout.addWidget(tags_hint)

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.album_edit = QLineEdit()
        self.album_edit.setPlaceholderText("Album title")
        self.album_edit.setClearButtonEnabled(True)
        form.addRow(
            "Album:",
            self._with_lookup(self.album_edit, "album", "Find Album on Discogs using Artist + Year"),
        )

        self.album_artist_edit = QLineEdit()
        self.album_artist_edit.setPlaceholderText("Album artist")
        self.album_artist_edit.setClearButtonEnabled(True)
        form.addRow(
            "Album artist:",
            self._with_lookup(
                self.album_artist_edit,
                "album_artist",
                "Fill Album artist from the selected Discogs release (needs Artist, Album and Year)",
            ),
        )

        artist_widget = QWidget()
        artist_layout = QVBoxLayout(artist_widget)
        artist_layout.setContentsMargins(0, 0, 0, 0)
        artist_layout.setSpacing(4)
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("Track artist")
        self.artist_edit.setClearButtonEnabled(True)
        artist_layout.addWidget(
            self._with_lookup(self.artist_edit, "artist", "Find Artist on Discogs using Album + Year")
        )
        self.artist_same_checkbox = QCheckBox("Apply this Artist to all tracks in album")
        self.artist_same_checkbox.setChecked(True)
        self.artist_same_checkbox.toggled.connect(self._on_album_fields_changed)
        artist_layout.addWidget(self.artist_same_checkbox)
        form.addRow("Artist:", artist_widget)

        year_genre_box = QWidget()
        year_genre_layout = QHBoxLayout(year_genre_box)
        year_genre_layout.setContentsMargins(0, 0, 0, 0)
        year_genre_layout.setSpacing(6)
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("e.g. 2005")
        self.year_edit.setFixedWidth(100)
        year_genre_layout.addWidget(self.year_edit)
        year_genre_layout.addWidget(
            self._lookup_button("year", "Find Year on Discogs using Artist + Album")
        )
        year_genre_layout.addSpacing(6)
        year_genre_layout.addWidget(QLabel("Genre:"))
        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("Genre")
        self.genre_edit.setClearButtonEnabled(True)
        year_genre_layout.addWidget(self.genre_edit, 1)
        year_genre_layout.addWidget(
            self._lookup_button(
                "genre",
                "Fill Genre from the selected Discogs release (needs Artist, Album and Year)",
            )
        )
        form.addRow("Year / Genre:", year_genre_box)

        self.disc_total_edit = QLineEdit("1")
        self.disc_total_edit.setPlaceholderText("1")
        self.disc_total_edit.setFixedWidth(70)
        form.addRow("Total Discs:", self.disc_total_edit)

        self.compilation_checkbox = QCheckBox("Compilation (Various Artists album)")
        self.compilation_checkbox.toggled.connect(self._on_compilation_toggled)
        self.compilation_checkbox.toggled.connect(self._on_album_fields_changed)
        form.addRow("Compilation:", self.compilation_checkbox)

        form_panel_layout.addLayout(form)
        form_panel_layout.addStretch(1)
        layout.addWidget(form_panel, 1)

        cover_panel = QFrame()
        cover_panel.setObjectName("editPanel")
        cover_panel.setFixedWidth(430)
        cover_layout = QVBoxLayout(cover_panel)
        cover_layout.setContentsMargins(16, 14, 16, 14)
        cover_layout.setSpacing(10)
        cover_title = QLabel("Cover art")
        cover_title.setObjectName("editSectionTitle")
        cover_layout.addWidget(cover_title)
        cover_hint = QLabel("Embedded artwork. Search online or pick a local image.")
        cover_hint.setObjectName("editSubtle")
        cover_hint.setWordWrap(True)
        cover_layout.addWidget(cover_hint)
        self.album_cover_widget = CoverPreviewWidget(size=140, theme=self.theme)
        self.album_cover_widget.search_requested.connect(lambda: self._on_search_cover(False))
        self.album_cover_widget.cover_changed.connect(lambda _action: self._update_cover_source(False))
        cover_layout.addWidget(self.album_cover_widget)
        self.album_cover_source = QLabel("No artwork loaded.")
        self.album_cover_source.setObjectName("editSubtle")
        self.album_cover_source.setWordWrap(True)
        cover_layout.addWidget(self.album_cover_source)
        cover_layout.addStretch(1)
        note = QLabel("Searches Discogs. Uses Album, Artist and Year as anchors.")
        note.setObjectName("editSubtle")
        note.setWordWrap(True)
        cover_layout.addWidget(note)
        layout.addWidget(cover_panel, 0)

        self.album_edit.textChanged.connect(self._on_album_fields_changed)
        self.album_artist_edit.textChanged.connect(self._on_album_fields_changed)
        self.artist_edit.textChanged.connect(self._on_album_fields_changed)
        self.year_edit.textChanged.connect(self._on_album_fields_changed)
        self.genre_edit.textChanged.connect(self._on_album_fields_changed)
        self.disc_total_edit.textChanged.connect(self._on_album_fields_changed)
        for editor in (
            self.album_edit,
            self.album_artist_edit,
            self.artist_edit,
            self.year_edit,
            self.genre_edit,
        ):
            editor.textChanged.connect(self._update_field_search_buttons)

    def _setup_single_track_tab(self):
        layout = QHBoxLayout(self.tab_tracks)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: track list
        left_panel = QFrame()
        left_panel.setObjectName("editPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        self.left_title = QLabel("Album Tracks")
        self.left_title.setObjectName("editSectionTitle")
        left_layout.addWidget(self.left_title)
        self.track_list = QListWidget()
        self.track_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.track_list.currentRowChanged.connect(self._on_track_selected)
        left_layout.addWidget(self.track_list, 1)
        splitter.addWidget(left_panel)

        # Middle: reference-style tag form
        form_panel = QFrame()
        form_panel.setObjectName("editPanel")
        form_panel_layout = QVBoxLayout(form_panel)
        form_panel_layout.setContentsMargins(16, 14, 16, 14)
        form_panel_layout.setSpacing(10)
        self.right_title = QLabel("Tags")
        self.right_title.setObjectName("editSectionTitle")
        form_panel_layout.addWidget(self.right_title)
        self.st_hint = QLabel("Values are read from the file and written back on save.")
        self.st_hint.setObjectName("editSubtle")
        self.st_hint.setWordWrap(True)
        form_panel_layout.addWidget(self.st_hint)

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.st_title = QLineEdit()
        self.st_title.setPlaceholderText("Track title")
        form.addRow(
            "Title:",
            self._with_lookup(
                self.st_title,
                "title",
                "Fill the track title from Discogs (needs Artist, Album, Year; uses Track number or the file name)",
            ),
        )

        self.st_artist = QLineEdit()
        self.st_artist.setPlaceholderText("Track artist")
        form.addRow(
            "Artist:",
            self._with_lookup(self.st_artist, "artist", "Find Artist on Discogs using Album + Year"),
        )

        self.st_album = QLineEdit()
        self.st_album.setPlaceholderText("Album title")
        form.addRow(
            "Album:",
            self._with_lookup(self.st_album, "album", "Find Album on Discogs using Artist + Year"),
        )

        self.st_album_artist = QLineEdit()
        self.st_album_artist.setPlaceholderText("Album artist")
        form.addRow(
            "Album artist:",
            self._with_lookup(
                self.st_album_artist,
                "album_artist",
                "Fill Album artist from the selected Discogs release",
            ),
        )

        year_genre_box = QWidget()
        year_genre_layout = QHBoxLayout(year_genre_box)
        year_genre_layout.setContentsMargins(0, 0, 0, 0)
        year_genre_layout.setSpacing(6)
        self.st_year = QLineEdit()
        self.st_year.setPlaceholderText("e.g. 2005")
        self.st_year.setFixedWidth(100)
        year_genre_layout.addWidget(self.st_year)
        year_genre_layout.addWidget(
            self._lookup_button("year", "Find Year on Discogs using Artist + Album")
        )
        year_genre_layout.addSpacing(6)
        year_genre_layout.addWidget(QLabel("Genre:"))
        self.st_genre = QLineEdit()
        self.st_genre.setPlaceholderText("Genre")
        year_genre_layout.addWidget(self.st_genre, 1)
        year_genre_layout.addWidget(
            self._lookup_button("genre", "Fill Genre from the selected Discogs release")
        )
        form.addRow("Year / Genre:", year_genre_box)

        track_disc_box = QWidget()
        track_disc_layout = QHBoxLayout(track_disc_box)
        track_disc_layout.setContentsMargins(0, 0, 0, 0)
        track_disc_layout.setSpacing(6)
        self.st_track_no = QLineEdit()
        self.st_track_no.setPlaceholderText("e.g. 01")
        self.st_track_no.setFixedWidth(80)
        track_disc_layout.addWidget(self.st_track_no)
        track_disc_layout.addSpacing(8)
        track_disc_layout.addWidget(QLabel("Disc:"))
        self.st_disc_no = QLineEdit()
        self.st_disc_no.setPlaceholderText("1")
        self.st_disc_no.setFixedWidth(50)
        track_disc_layout.addWidget(self.st_disc_no)
        track_disc_layout.addWidget(QLabel("of"))
        self.st_disc_total = QLineEdit()
        self.st_disc_total.setPlaceholderText("1")
        self.st_disc_total.setFixedWidth(50)
        track_disc_layout.addWidget(self.st_disc_total)
        track_disc_layout.addWidget(
            self._lookup_button(
                "track",
                "Find Track and Disc number from the tagged Title (needs Artist, Album, Year and Title)",
            )
        )
        track_disc_layout.addStretch(1)
        form.addRow("Track / Disc:", track_disc_box)

        self.st_compilation = QCheckBox("Compilation (Various Artists album)")
        self.st_compilation.toggled.connect(self._on_single_track_field_changed)
        form.addRow("Compilation:", self.st_compilation)

        form_panel_layout.addLayout(form)
        form_panel_layout.addStretch(1)
        splitter.addWidget(form_panel)

        # Right: cover panel
        cover_panel = QFrame()
        cover_panel.setObjectName("editPanel")
        cover_panel.setFixedWidth(410)
        cover_layout = QVBoxLayout(cover_panel)
        cover_layout.setContentsMargins(14, 14, 14, 14)
        cover_layout.setSpacing(10)
        cover_title = QLabel("Cover art")
        cover_title.setObjectName("editSectionTitle")
        cover_layout.addWidget(cover_title)
        cover_hint = QLabel("Artwork embedded in this track.")
        cover_hint.setObjectName("editSubtle")
        cover_hint.setWordWrap(True)
        cover_layout.addWidget(cover_hint)
        self.st_cover_widget = CoverPreviewWidget(size=140, theme=self.theme)
        self.st_cover_widget.search_requested.connect(lambda: self._on_search_cover(True))
        self.st_cover_widget.cover_changed.connect(lambda _action: self._update_cover_source(True))
        cover_layout.addWidget(self.st_cover_widget)
        self.st_cover_source = QLabel("No artwork loaded.")
        self.st_cover_source.setObjectName("editSubtle")
        self.st_cover_source.setWordWrap(True)
        cover_layout.addWidget(self.st_cover_source)
        cover_layout.addStretch(1)
        note = QLabel("Searches Discogs. Uses Album, Artist and Year as anchors.")
        note.setObjectName("editSubtle")
        note.setWordWrap(True)
        cover_layout.addWidget(note)
        splitter.addWidget(cover_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 530, 410])

        for editor in (
            self.st_disc_no,
            self.st_disc_total,
            self.st_track_no,
            self.st_title,
            self.st_artist,
            self.st_album,
            self.st_album_artist,
            self.st_year,
            self.st_genre,
        ):
            editor.textChanged.connect(self._on_single_track_field_changed)
            editor.textChanged.connect(self._update_field_search_buttons)

    def _populate_initial_data(self):
        if not self.tracks:
            return

        # Infer album-level values from tracks
        first_t = self.tracks[0]
        init_album = ""
        init_album_artist = ""
        init_artist = ""
        init_year = ""
        init_genre = ""
        sample_cover = None
        max_disc = 1

        for t in self.tracks:
            if not init_album and t.get("album") and t["album"] != NO_DATA:
                init_album = t["album"]
            if not init_album_artist and t.get("album_artist") and t["album_artist"] != NO_DATA:
                init_album_artist = t["album_artist"]
            if not init_artist and t.get("artist") and t["artist"] != NO_DATA:
                init_artist = t["artist"]
            if not init_year and t.get("year") and t["year"] != NO_DATA:
                init_year = t["year"]
            if not init_genre and t.get("genre") and t["genre"] != NO_DATA:
                init_genre = t["genre"]
            if not sample_cover and t.get("cover_cache_path"):
                sample_cover = t["cover_cache_path"]
            try:
                d = int(t.get("disc_no", 1))
                tot = int(t.get("disc_total", 1))
                max_disc = max(max_disc, d, tot)
            except Exception:
                pass

        is_comp = any(t.get("compilation") == 1 for t in self.tracks) or (init_album_artist == "Various Artists")

        self.album_edit.setText(init_album)
        self.album_artist_edit.setText(init_album_artist)
        self.artist_edit.setText(init_artist)
        self.year_edit.setText(init_year)
        self.genre_edit.setText(init_genre)
        self.disc_total_edit.setText(str(max_disc))
        self.compilation_checkbox.setChecked(is_comp)
        self.artist_same_checkbox.setChecked(not is_comp)

        if sample_cover and Path(sample_cover).exists():
            self.album_cover_widget.set_original_cover(sample_cover)
        self._update_cover_source(False)

        # Populate track list
        self._refresh_track_list()
        if self.tracks:
            self.track_list.setCurrentRow(0)
        self._update_field_search_buttons()

    def _refresh_track_list(self):
        curr_row = self.track_list.currentRow()
        self.track_list.blockSignals(True)
        self.track_list.clear()

        discs = {str(t.get("disc_no", "1")).strip() for t in self.tracks if t.get("disc_no")}
        has_multi = len(discs) > 1 or any(d not in ("1", "", NO_DATA) for d in discs)

        for i, t in enumerate(self.tracks):
            tr_num = t.get("track_no", f"{i + 1:02d}")
            title = t.get("title", f"Track {i + 1}")
            disc_num = t.get("disc_no", "1")
            prefix = f"[CD {disc_num}] " if has_multi else ""
            item_text = f"{prefix}{tr_num}. {title}"
            self.track_list.addItem(QListWidgetItem(item_text))

        self.track_list.blockSignals(False)
        if 0 <= curr_row < len(self.tracks):
            self.track_list.setCurrentRow(curr_row)

    def _update_cover_source(self, single: bool = False):
        widget = self.st_cover_widget if single else getattr(self, "album_cover_widget", None)
        label = self.st_cover_source if single else getattr(self, "album_cover_source", None)
        if widget is None or label is None:
            return
        if widget.action == "delete":
            label.setText("Artwork will be removed on save.")
        elif widget.action == "new":
            label.setText("New artwork selected — it will be embedded on save.")
        elif widget.original_image_path:
            label.setText("Artwork embedded in the file.")
        else:
            label.setText("No artwork loaded.")

    def _on_compilation_toggled(self, checked: bool):
        if checked:
            if not self.album_artist_edit.text().strip() or self.album_artist_edit.text() == NO_DATA:
                self.album_artist_edit.setText("Various Artists")
            self.artist_same_checkbox.setChecked(False)

    def _on_album_fields_changed(self):
        new_album = self.album_edit.text().strip()
        new_album_artist = self.album_artist_edit.text().strip()
        new_artist = self.artist_edit.text().strip()
        new_year = self.year_edit.text().strip()
        new_genre = self.genre_edit.text().strip()
        new_disc_total = self.disc_total_edit.text().strip()
        apply_artist = self.artist_same_checkbox.isChecked()
        is_comp = 1 if self.compilation_checkbox.isChecked() else 0

        for t in self.tracks:
            t["compilation"] = is_comp
            t["album"] = new_album or NO_DATA
            t["album_artist"] = new_album_artist or NO_DATA
            if apply_artist:
                t["artist"] = new_artist or NO_DATA
            t["year"] = new_year or NO_DATA
            t["genre"] = new_genre or NO_DATA
            if new_disc_total:
                t["disc_total"] = new_disc_total

        # If single track form is currently visible, update its fields
        row = self.track_list.currentRow()
        if 0 <= row < len(self.tracks):
            t = self.tracks[row]
            widgets = [self.st_album, self.st_album_artist, self.st_year, self.st_genre, self.st_disc_total]
            if apply_artist:
                widgets.append(self.st_artist)
            for w in widgets:
                w.blockSignals(True)
            self.st_album.setText(t.get("album", "") if t.get("album") != NO_DATA else "")
            self.st_album_artist.setText(t.get("album_artist", "") if t.get("album_artist") != NO_DATA else "")
            if apply_artist:
                self.st_artist.setText(t.get("artist", "") if t.get("artist") != NO_DATA else "")
            self.st_year.setText(t.get("year", "") if t.get("year") != NO_DATA else "")
            self.st_genre.setText(t.get("genre", "") if t.get("genre") != NO_DATA else "")
            self.st_disc_total.setText(str(t.get("disc_total", "1")))
            self.st_compilation.blockSignals(True)
            self.st_compilation.setChecked(int(t.get("compilation") or 0) == 1)
            self.st_compilation.blockSignals(False)
            for w in widgets:
                w.blockSignals(False)

        self._update_field_search_buttons()
        self._validate_readiness()

    def _on_tab_changed(self, new_index: int):
        if new_index == 1:
            # Switched to single track edit: save any album tab changes into tracks
            self._on_album_fields_changed()
            if self.current_single_track_idx >= 0:
                self._load_single_track(self.current_single_track_idx)
        else:
            # Switched to album edit: save any single track edits
            self._save_current_single_track_form()
        self._update_field_search_buttons()

    def _on_track_selected(self, index: int):
        if index < 0 or index >= len(self.tracks):
            return
        self._save_current_single_track_form()
        self.current_single_track_idx = index
        self._load_single_track(index)

    def _load_single_track(self, index: int):
        if index < 0 or index >= len(self.tracks):
            return
        t = self.tracks[index]

        # Block signals to avoid feedback loops
        widgets = [
            self.st_disc_no, self.st_disc_total, self.st_track_no, self.st_title,
            self.st_artist, self.st_album_artist, self.st_album, self.st_year, self.st_genre,
            self.st_compilation,
        ]
        for w in widgets:
            w.blockSignals(True)

        self.st_disc_no.setText(str(t.get("disc_no", "1")))
        self.st_disc_total.setText(str(t.get("disc_total", "1")))
        self.st_track_no.setText(t.get("track_no", "") if t.get("track_no") != NO_DATA else "")
        self.st_title.setText(t.get("title", "") if t.get("title") != NO_DATA else "")
        self.st_artist.setText(t.get("artist", "") if t.get("artist") != NO_DATA else "")
        self.st_album_artist.setText(t.get("album_artist", "") if t.get("album_artist") != NO_DATA else "")
        self.st_album.setText(t.get("album", "") if t.get("album") != NO_DATA else "")
        self.st_year.setText(t.get("year", "") if t.get("year") != NO_DATA else "")
        self.st_genre.setText(t.get("genre", "") if t.get("genre") != NO_DATA else "")
        self.st_compilation.setChecked(int(t.get("compilation") or 0) == 1)

        for w in widgets:
            w.blockSignals(False)

        # Track cover art preview
        cover_path = t.get("cover_cache_path")
        self.st_cover_widget.set_original_cover(cover_path)
        if t.get("_cover_action") == "new" and t.get("_new_cover_path"):
            self.st_cover_widget.action = "new"
            self.st_cover_widget.new_image_path = t["_new_cover_path"]
            self.st_cover_widget._update_preview()
        elif t.get("_cover_action") == "delete":
            self.st_cover_widget.action = "delete"
            self.st_cover_widget._update_preview()
        self._update_cover_source(True)

    def _on_single_track_field_changed(self):
        row = self.current_single_track_idx
        if row < 0 or row >= len(self.tracks):
            return

        t = self.tracks[row]
        t["disc_no"] = self.st_disc_no.text().strip() or "1"
        t["disc_total"] = self.st_disc_total.text().strip() or "1"
        t["track_no"] = self.st_track_no.text().strip() or NO_DATA
        t["title"] = self.st_title.text().strip() or NO_DATA
        t["artist"] = self.st_artist.text().strip() or NO_DATA
        t["album_artist"] = self.st_album_artist.text().strip() or NO_DATA
        t["album"] = self.st_album.text().strip() or NO_DATA
        t["year"] = self.st_year.text().strip() or NO_DATA
        t["genre"] = self.st_genre.text().strip() or NO_DATA
        t["compilation"] = 1 if self.st_compilation.isChecked() else 0

        # Update left list item
        discs = {str(item.get("disc_no", "1")).strip() for item in self.tracks if item.get("disc_no")}
        has_multi = len(discs) > 1 or any(d not in ("1", "", NO_DATA) for d in discs)
        prefix = f"[CD {t['disc_no']}] " if has_multi else ""
        item = self.track_list.item(row)
        if item:
            item.setText(f"{prefix}{t['track_no']}. {t['title']}")

        self._update_field_search_buttons()
        self._validate_readiness()

    def _save_current_single_track_form(self):
        row = self.current_single_track_idx
        if 0 <= row < len(self.tracks):
            t = self.tracks[row]
            t["disc_no"] = self.st_disc_no.text().strip() or "1"
            t["disc_total"] = self.st_disc_total.text().strip() or "1"
            t["track_no"] = self.st_track_no.text().strip() or NO_DATA
            t["title"] = self.st_title.text().strip() or NO_DATA
            t["artist"] = self.st_artist.text().strip() or NO_DATA
            t["album_artist"] = self.st_album_artist.text().strip() or NO_DATA
            t["album"] = self.st_album.text().strip() or NO_DATA
            t["year"] = self.st_year.text().strip() or NO_DATA
            t["genre"] = self.st_genre.text().strip() or NO_DATA
            t["compilation"] = 1 if self.st_compilation.isChecked() else 0

            # Cover changes
            t["_cover_action"] = self.st_cover_widget.action
            t["_new_cover_path"] = self.st_cover_widget.new_image_path

    # ------------------------------------------------------------------
    # Discogs metadata lookup (one field at a time, as in CoverArtTagger)
    # ------------------------------------------------------------------
    METADATA_LABELS = {
        "artist": "Artist",
        "album": "Album",
        "year": "Year",
        "title": "Title",
        "genre": "Genre",
        "album_artist": "Album artist",
        "track": "Track number",
    }

    def _is_single(self) -> bool:
        return self.tabs.currentIndex() == 1

    def _context_values(self, single: bool) -> Dict[str, str]:
        if single:
            return {
                "album": self.st_album.text().strip(),
                "album_artist": self.st_album_artist.text().strip(),
                "artist": self.st_artist.text().strip(),
                "year": self.st_year.text().strip(),
                "genre": self.st_genre.text().strip(),
                "title": self.st_title.text().strip(),
            }
        return {
            "album": self.album_edit.text().strip(),
            "album_artist": self.album_artist_edit.text().strip(),
            "artist": self.artist_edit.text().strip(),
            "year": self.year_edit.text().strip(),
            "genre": self.genre_edit.text().strip(),
        }

    def _field_edit(self, field: str, single: bool):
        if single:
            return {
                "artist": self.st_artist,
                "album": self.st_album,
                "year": self.st_year,
                "title": self.st_title,
                "genre": self.st_genre,
                "album_artist": self.st_album_artist,
            }.get(field)
        return {
            "artist": self.artist_edit,
            "album": self.album_edit,
            "year": self.year_edit,
            "genre": self.genre_edit,
            "album_artist": self.album_artist_edit,
        }.get(field)

    def _metadata_requirement(self, field: str, single: bool) -> str:
        ctx = self._context_values(single)
        artist, album, year = bool(ctx["artist"]), bool(ctx["album"]), bool(ctx["year"])
        if field == "artist":
            return "" if album and year else "Fill Album and Year first."
        if field == "album":
            return "" if artist and year else "Fill Artist and Year first."
        if field == "year":
            return "" if artist and album else "Fill Artist and Album first."
        if field in ("title", "genre", "album_artist", "track"):
            if not (artist and album and year):
                return "Fill Artist, Album and Year first."
            if field == "track" and not ctx.get("title", ""):
                return "Fill Title first."
            return ""
        return "Unknown field."

    def _update_field_search_buttons(self, *args):
        single = self._is_single()
        busy = bool(self._metadata_worker and self._metadata_worker.isRunning())
        for field, buttons in self._field_buttons.items():
            requirement = self._metadata_requirement(field, single)
            for button in buttons:
                button.setEnabled(not requirement and not busy)
        ctx = self._context_values(single)
        if hasattr(self, "album_cover_widget"):
            self.album_cover_widget.set_controls_enabled(True, bool(ctx["album"]))
        if hasattr(self, "st_cover_widget"):
            self.st_cover_widget.set_controls_enabled(True, bool(ctx["album"]))

    @staticmethod
    def _norm_meta(value: str) -> str:
        return " ".join(str(value or "").split()).casefold()

    def _matching_metadata_candidate(self, single: bool):
        candidate = self._metadata_candidate
        if candidate is None:
            return None
        ctx = self._context_values(single)
        if self._norm_meta(candidate.artist) != self._norm_meta(ctx["artist"]):
            return None
        if self._norm_meta(candidate.title) != self._norm_meta(ctx["album"]):
            return None
        if self._norm_meta(candidate.year) != self._norm_meta(ctx["year"]):
            return None
        return candidate

    def _set_status(self, text: str, kind: str = "info"):
        light = self.theme == "light"
        colors = {
            "info": "#656d76" if light else "#8b949e",
            "ok": "#1a7f37" if light else "#3fb950",
            "warn": "#9a6700" if light else "#d29922",
            "error": "#cf222e" if light else "#f85149",
        }
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(
            f"color:{colors.get(kind, colors['info'])}; font-size:12px; font-weight:500;"
        )

    def _on_field_lookup(self, field: str):
        single = self._is_single()
        requirement = self._metadata_requirement(field, single)
        if requirement:
            QMessageBox.information(self, "Not enough information", requirement)
            return
        if self._metadata_worker is not None and self._metadata_worker.isRunning():
            return

        ctx = self._context_values(single)
        if field in ("title", "genre", "album_artist", "track"):
            candidate = self._matching_metadata_candidate(single)
            if candidate is not None:
                self._apply_metadata_value(field, candidate, single)
                return

        from malka.ui.discogs_dialogs import DiscogsBusyDialog
        from malka.ui.discogs_workers import DiscogsMetadataWorker

        self._metadata_target_field = field
        self._metadata_single = single
        self._metadata_canceled = False
        worker = DiscogsMetadataWorker(ctx["artist"], ctx["album"], ctx["year"], self)
        worker.progress.connect(self._on_metadata_progress)
        worker.succeeded.connect(self._on_metadata_succeeded)
        worker.failed.connect(self._on_metadata_failed)
        worker.finished.connect(self._on_metadata_finished)
        self._metadata_worker = worker
        self._metadata_dialog = DiscogsBusyDialog(
            "Looking up metadata",
            f'Searching Discogs for “{ctx["album"] or ctx["artist"]}”…',
            self,
            theme=self.theme,
        )
        self._metadata_dialog.canceled.connect(self._cancel_metadata_lookup)
        self._metadata_dialog.show()
        worker.start()
        self._update_field_search_buttons()
        self._set_status("Looking up release metadata on Discogs…", "info")

    def _on_metadata_progress(self, message: str):
        if self._metadata_dialog is not None:
            self._metadata_dialog.set_message(message)
        self._set_status(message[:110], "info")

    def _on_metadata_succeeded(self, candidates):
        if self._metadata_canceled:
            return
        self._close_metadata_dialog()
        if not candidates:
            self._set_status("No matching Discogs releases found.", "warn")
            QMessageBox.information(
                self,
                "Nothing found",
                "Discogs did not return a matching release. Check Artist, Album and Year — "
                "or add a Discogs token in Settings if the API is rate-limiting.",
            )
            return
        selected = candidates[0] if len(candidates) == 1 else self._pick_release(candidates)
        if selected is None:
            self._set_status("Metadata lookup cancelled.", "info")
            return
        self._metadata_candidate = selected
        self._apply_metadata_value(
            self._metadata_target_field, selected, self._metadata_single
        )
        self._update_field_search_buttons()

    def _on_metadata_failed(self, message: str):
        if self._metadata_canceled:
            return
        self._close_metadata_dialog()
        self._set_status("Metadata lookup failed.", "error")
        QMessageBox.warning(self, "Lookup failed", message)

    def _cancel_metadata_lookup(self):
        if self._metadata_worker is None:
            return
        self._metadata_canceled = True
        self._metadata_worker.requestInterruption()
        if self._metadata_dialog is not None:
            self._metadata_dialog.set_message("Cancelling the lookup…")
            self._metadata_dialog.btn_cancel.setEnabled(False)
        self._set_status("Cancelling metadata lookup…", "info")

    def _on_metadata_finished(self):
        self._close_metadata_dialog()
        worker = self._metadata_worker
        self._metadata_worker = None
        if worker is not None:
            worker.deleteLater()
        self._update_field_search_buttons()
        if self._metadata_canceled:
            self._set_status("Metadata lookup cancelled.", "info")

    def _close_metadata_dialog(self):
        if self._metadata_dialog is not None:
            dialog = self._metadata_dialog
            self._metadata_dialog = None
            dialog.accept()
            dialog.deleteLater()

    def _pick_release(self, candidates):
        from malka.ui.discogs_dialogs import DiscogsChoiceDialog

        entries = []
        for candidate in candidates:
            display = candidate.display_title
            if candidate.display_detail:
                display += f" · {candidate.display_detail}"
            entries.append((display, candidate.tooltip, candidate))
        dialog = DiscogsChoiceDialog(
            "Choose release",
            "Several Discogs releases match. Pick the release to use.",
            entries,
            self,
            theme=self.theme,
            select_label="Use this release",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = dialog.selected_value()
            return value if value is not None else None
        return None

    def _pick_track(self, tracks, subtitle: str):
        from malka.ui.discogs_dialogs import DiscogsChoiceDialog

        entries = [(track.display, track.tooltip, track) for track in tracks]
        dialog = DiscogsChoiceDialog(
            "Choose track",
            subtitle,
            entries,
            self,
            theme=self.theme,
            select_label="Use this track",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_value()
        return None

    def _pick_value(self, title: str, values: List[str]):
        from malka.ui.discogs_dialogs import DiscogsChoiceDialog

        entries = [(value, value, value) for value in values]
        dialog = DiscogsChoiceDialog(
            title,
            "Discogs lists several values. Pick the one to use.",
            entries,
            self,
            theme=self.theme,
            select_label="Use this value",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            value = dialog.selected_value()
            return str(value) if value else None
        return None

    def _apply_metadata_value(self, field: str, candidate, single: bool):
        label = self.METADATA_LABELS.get(field, field.title())
        value = ""
        status_extra = ""
        if field == "track":
            self._apply_track_number(candidate, single)
            return
        if field == "artist":
            value = candidate.artist
        elif field == "album":
            value = candidate.title
        elif field == "year":
            value = candidate.year
        elif field == "album_artist":
            value = candidate.artist
        elif field == "genre":
            genres = candidate.genre_values
            if not genres:
                QMessageBox.information(
                    self,
                    "No genre found",
                    "Discogs did not provide a genre or style for this release.",
                )
                return
            if len(genres) == 1:
                value = genres[0]
            else:
                selected = self._pick_value("Choose genre", genres)
                if selected is None:
                    return
                value = selected
        elif field == "title":
            track = self._resolve_track(candidate, single)
            if track is None:
                return
            value = track.title
            if track.position:
                status_extra = f" (track {track.position})"
        else:
            return
        if not value:
            QMessageBox.information(
                self,
                "No value found",
                f"Discogs did not provide a value for {label}.",
            )
            return
        edit = self._field_edit(field, single)
        if edit is None:
            return
        edit.setText(value)
        edit.setFocus()
        self._set_status(
            f"{label} filled from Discogs: “{value[:80]}”{status_extra}.", "ok"
        )
        self._update_field_search_buttons()

    def _apply_track_number(self, candidate, single: bool):
        track = self._resolve_track_by_title(candidate, single)
        if track is None:
            return
        track_no = track.track_no.strip()
        if not track_no:
            QMessageBox.information(
                self,
                "No track number",
                f'Discogs position “{track.position}” does not contain a numeric track number.',
            )
            return
        if single:
            self.st_track_no.setText(track_no)
            if track.disc_no:
                self.st_disc_no.setText(track.disc_no)
        else:
            # Album-level dialog has no track number field; this lookup is only
            # exposed on the single-track tab.
            return
        disc_text = f", disc {track.disc_no}" if track.disc_no else ""
        self._set_status(
            f"Track number filled from Discogs: {track_no}{disc_text} — "
            f"“{track.title[:60]}”.",
            "ok",
        )
        self._update_field_search_buttons()

    def _resolve_track_by_title(self, candidate, single: bool):
        from malka.discogs_metadata import rank_tracks_by_title

        if not candidate.tracks:
            QMessageBox.information(
                self, "No tracklist", "Discogs did not return a tracklist for this release."
            )
            return None
        title = self.st_title.text().strip() if single else ""
        ranked = rank_tracks_by_title(candidate, title)
        if not ranked:
            QMessageBox.information(
                self,
                "Track not found",
                f"Could not find “{title}” in the Discogs tracklist.",
            )
            return None
        best_score, best_track = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if len(ranked) == 1 or (
            best_score >= 0.82 and best_score - second_score >= 0.08
        ):
            return best_track
        choices = [track for score, track in ranked if score >= 0.45][:12]
        if not choices:
            choices = candidate.tracks
        return self._pick_track(
            choices,
            f"Could not match “{title}” unambiguously. Pick the track:",
        )

    def _resolve_track(self, candidate, single: bool):
        from malka.discogs_metadata import (
            rank_tracks_by_filename,
            rank_tracks_by_title,
            tracks_by_number,
        )

        if not candidate.tracks:
            QMessageBox.information(
                self, "No tracklist", "Discogs did not return a tracklist for this release."
            )
            return None
        if not single:
            return None
        track_no = self.st_track_no.text().strip()
        disc_no = self.st_disc_no.text().strip()
        if track_no:
            matches = tracks_by_number(candidate, track_no, disc_no)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                return self._pick_track(
                    matches,
                    "Several tracks have this number. Pick the right one.",
                )
        row = self.current_single_track_idx
        file_path = (
            self.tracks[row].get("file_path", "")
            if 0 <= row < len(self.tracks)
            else ""
        )
        if file_path:
            ranked = rank_tracks_by_filename(
                candidate,
                Path(file_path).name,
                self.st_artist.text().strip(),
                self.st_album.text().strip(),
            )
            if ranked:
                best_score, best_track = ranked[0]
                second_score = ranked[1][0] if len(ranked) > 1 else 0.0
                if best_score >= 0.60 and (
                    len(ranked) == 1 or best_score - second_score >= 0.08
                ):
                    return best_track
                choices = [track for score, track in ranked if score > 0][:12]
                if not choices:
                    choices = candidate.tracks
                return self._pick_track(
                    choices,
                    "Could not determine the track unambiguously from the file name. "
                    "Pick the track:",
                )
        return self._pick_track(
            candidate.tracks,
            f"Pick the track for {candidate.display_title}:",
        )

    # ------------------------------------------------------------------
    # Discogs cover search (separate from metadata lookup)
    # ------------------------------------------------------------------
    def _on_search_cover(self, single: bool):
        ctx = self._context_values(single)
        album = ctx["album"]
        if not album:
            QMessageBox.information(
                self,
                "Album title required",
                "Fill in the Album field first — the cover search uses it as its query.",
            )
            (self.st_album if single else self.album_edit).setFocus()
            return
        if self._search_worker is not None and self._search_worker.isRunning():
            return
        artist = ctx["album_artist"] or ctx["artist"]
        if artist.lower() in ("various artists", "va") and ctx["artist"]:
            artist = ctx["artist"]
        year = ctx["year"]
        self._search_canceled = False
        from malka.ui.discogs_dialogs import DiscogsBusyDialog
        from malka.ui.discogs_workers import DiscogsCoverWorker

        worker = DiscogsCoverWorker(album, artist, year, self)
        worker.progress.connect(self._on_search_progress)
        worker.succeeded.connect(self._on_search_succeeded)
        worker.failed.connect(self._on_search_failed)
        worker.finished.connect(self._on_search_finished)
        self._search_worker = worker
        self._search_single = single
        self._search_dialog = DiscogsBusyDialog(
            "Searching for cover art",
            f'Looking for “{album}” on Discogs…',
            self,
            theme=self.theme,
        )
        self._search_dialog.canceled.connect(self._cancel_search)
        self._search_dialog.show()
        worker.start()
        self._set_status(f'Searching cover art for “{album[:60]}”…', "info")

    def _on_search_progress(self, message: str):
        if self._search_dialog is not None:
            self._search_dialog.set_message(message)
        self._set_status(message[:110], "info")

    def _on_search_succeeded(self, result):
        if self._search_canceled:
            return
        self._close_search_dialog()
        if not result.images:
            self._set_status("No cover art found.", "warn")
            QMessageBox.information(
                self,
                "No cover art found",
                f'No cover images were found for “{result.album}”.\n\n'
                "Check the Album field or add the album artist for a more precise match.",
            )
            return
        from malka.ui.discogs_dialogs import DiscogsGalleryDialog

        self._set_status(
            f"Found {len(result.images)} cover image(s). Choose one.", "info"
        )
        gallery = DiscogsGalleryDialog(
            result.images, result.album, result.artist, self.theme, self
        )
        if gallery.exec() == QDialog.DialogCode.Accepted:
            image = gallery.selected_image()
            if image is not None:
                self._apply_artwork(
                    image, gallery.selected_resize_size(), self._search_single
                )
        else:
            self._set_status("No artwork selected.", "info")

    def _on_search_failed(self, message: str):
        if self._search_canceled:
            return
        self._close_search_dialog()
        self._set_status("Cover search failed.", "error")
        QMessageBox.warning(self, "Search failed", message)

    def _cancel_search(self):
        if self._search_worker is None:
            return
        self._search_canceled = True
        self._search_worker.requestInterruption()
        if self._search_dialog is not None:
            self._search_dialog.set_message("Cancelling the search…")
            self._search_dialog.btn_cancel.setEnabled(False)
        self._set_status("Cancelling search…", "info")

    def _on_search_finished(self):
        self._close_search_dialog()
        worker = self._search_worker
        self._search_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._search_canceled:
            self._set_status("Cover search cancelled.", "info")

    def _close_search_dialog(self):
        if self._search_dialog is not None:
            dialog = self._search_dialog
            self._search_dialog = None
            dialog.accept()
            dialog.deleteLater()

    def _apply_artwork(self, image, target_size: Optional[int], single: bool):
        if not image.thumbnail:
            QMessageBox.warning(
                self, "Artwork unavailable", "This image has no downloaded preview."
            )
            return
        from malka.discogs_imaging import prepare_artwork
        from malka.tags import save_cover_cache

        try:
            prepared = prepare_artwork(image.thumbnail, target_size)
            path = save_cover_cache(prepared.data, prepared.extension)
        except Exception as exc:
            QMessageBox.warning(
                self, "Could not prepare artwork", f"Failed to prepare the image:\n{exc}"
            )
            return
        if not path:
            QMessageBox.warning(self, "Could not cache artwork", "Failed to save the image.")
            return
        widget = self.st_cover_widget if single else self.album_cover_widget
        widget.action = "new"
        widget.new_image_path = path
        widget._update_preview()
        widget.btn_delete.setEnabled(True)
        widget.cover_changed.emit("new")
        self._update_cover_source(single)
        self._set_status("Cover art selected. It will be embedded on save.", "ok")

    def _on_reload(self):
        reply = QMessageBox.question(
            self,
            "Reload tags",
            "Discard all edits and reload the original tag values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.tracks = [dict(t) for t in self._initial_tracks]
        self.current_single_track_idx = -1
        self._populate_initial_data()
        self._set_status("Tags reloaded from the editor snapshot.", "info")

    def _show_saved_message(self, text: str):
        """Non-blocking completion message with an OK button."""
        box = QMessageBox(None)
        box.setWindowTitle("Changes saved")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        box.setWindowModality(Qt.WindowModality.NonModal)
        box.setStyleSheet(self.styleSheet())
        self._saved_message_box = box
        box.open()

    def _validate_readiness(self) -> bool:
        # Check readiness for organization / import
        ready, msg = is_album_ready_to_organize(self.tracks)
        is_light = (getattr(self, "theme", "dark") == "light")
        if ready:
            self.btn_action.setEnabled(True)
            self.status_lbl.setText("✔ All required tags filled.")
            col = "#1a7f37" if is_light else "#3fb950"
            self.status_lbl.setStyleSheet(f"color: {col}; font-size: 12px; font-weight: 500;")
        else:
            # Editing/cover-only saves must remain possible even if the album is
            # not ready for automatic organization. ImportDialog explicitly
            # opts into the stricter behaviour.
            self.btn_action.setEnabled(not self.require_complete_tags)
            self.status_lbl.setText(f"⚠ {msg}")
            col = "#9a6700" if is_light else "#d29922"
            self.status_lbl.setStyleSheet(f"color: {col}; font-size: 12px; font-weight: 500;")
        return ready


class EditAlbumDialog(BaseAlbumEditDialog):
    """
    Dialog for editing an album already present in the library.
    Writes changes directly to audio files and updates SQLite.
    """

    # Emitted around the actual file-writing phase so playback can release the
    # files and resume at the same position afterwards.
    operation_about_to_start = pyqtSignal()
    operation_finished = pyqtSignal(bool)

    def __init__(self, album_name: str, album_artist: str, db_conn, parent=None, theme: Optional[str] = None):
        self.album_name = album_name
        self.album_artist = album_artist
        self.db_conn = db_conn

        raw_tracks = get_album_tracks(self.db_conn, album_name, album_artist)
        tracks = [dict(t) for t in raw_tracks]

        super().__init__(tracks=tracks, parent=parent, theme=theme)
        self.setWindowTitle(f"Edit Album: {album_name}")

        self.btn_action.setText("Save Changes")
        self.btn_action.setObjectName("saveBtn")
        self.btn_save = self.btn_action  # alias for tests
        self.btn_action.clicked.connect(self._on_save)

    def _on_save(self):
        # Album-tab edits are propagated live by the field signals; only the
        # visible single-track form still has to be flushed. Calling
        # _on_album_fields_changed() here would overwrite per-track edits
        # (Year / Album / Album artist / Genre / Artist) with the album values.
        self._save_current_single_track_form()

        album_cover_action = self.album_cover_widget.action
        album_new_cover = self.album_cover_widget.new_image_path
        fix_enc = self.fix_encoding_checkbox.isChecked()

        success = False
        total = len(self.tracks)
        progress = SaveProgressDialog(total, self, theme=self.theme)
        progress.show()
        self.operation_about_to_start.emit()
        try:
            for index, t in enumerate(self.tracks, start=1):
                file_path = t["file_path"]
                progress.set_operation(
                    f"Writing tags: {Path(file_path).name} ({index}/{total})…",
                    index - 1,
                )

                if fix_enc:
                    from malka.tags import detect_and_fix_encoding
                    for k in ("title", "artist", "album_artist", "album", "genre"):
                        v = t.get(k)
                        if v and v != NO_DATA:
                            _, fixed_val = detect_and_fix_encoding(str(v))
                            t[k] = fixed_val

                if album_cover_action == "delete" and t.get("_cover_action") != "new":
                    t["_cover_action"] = "delete"
                    t["_new_cover_path"] = None
                elif album_cover_action == "new" and t.get("_cover_action") != "delete":
                    t["_cover_action"] = "new"
                    t["_new_cover_path"] = album_new_cover

                cover_action = t.get("_cover_action", "keep")
                remove_cov = (cover_action == "delete")
                new_cov = t.get("_new_cover_path") if cover_action == "new" else None

                updated_tags = write_tags(
                    file_path=file_path,
                    title=t.get("title"),
                    artist=t.get("artist"),
                    album_artist=t.get("album_artist"),
                    album=t.get("album"),
                    year=t.get("year"),
                    genre=t.get("genre"),
                    track_no=t.get("track_no"),
                    disc_no=t.get("disc_no"),
                    disc_total=t.get("disc_total"),
                    compilation=t.get("compilation"),
                    new_cover_path=new_cov,
                    remove_cover=remove_cov,
                )

                from malka.organizer import is_track_organized

                db_data = {
                    "title": updated_tags["title"],
                    "artist": updated_tags["artist"],
                    "album_artist": updated_tags["album_artist"],
                    "album": updated_tags["album"],
                    "year": updated_tags["year"],
                    "genre": updated_tags["genre"],
                    "track_no": updated_tags["track_no"],
                    "disc_no": updated_tags.get("disc_no", "1"),
                    "disc_total": updated_tags.get("disc_total", "1"),
                    "compilation": updated_tags.get("compilation", 0),
                    "has_cover": updated_tags["has_cover"],
                    "cover_cache_path": updated_tags["cover_cache_path"],
                    "mtime": updated_tags["mtime"],
                    "bad_encoding": 0 if fix_enc else int(t.get("bad_encoding", 0)),
                    "is_organized": 1 if is_track_organized(
                        updated_tags, list(config.library_paths), config.track_naming_format, self.is_multi_disc
                    ) else 0,
                }
                update_track(self.db_conn, t["id"], db_data)

            self.db_conn.commit()
            progress.set_operation("Updating the library database…", total)
            success = True
        except Exception as e:
            progress.accept()
            QMessageBox.critical(self, "Save Error", f"Failed to save changes to tags: {e}")
        finally:
            self.operation_finished.emit(success)
            if success:
                progress.finish()

        if success:
            self.accept()
            self._show_saved_message(
                f"Successfully saved changes to {total} file{'s' if total != 1 else ''}."
            )


class EditTrackDialog(BaseAlbumEditDialog):
    """Edit tags of one specific track (single-track tab only)."""

    operation_about_to_start = pyqtSignal()
    operation_finished = pyqtSignal(bool)

    def __init__(self, track: Dict[str, Any], db_conn, parent=None, theme: Optional[str] = None):
        self.db_conn = db_conn
        self.track = dict(track)
        super().__init__(tracks=[dict(track)], parent=parent, theme=theme)
        title = self.track.get("title", "Track")
        self.setWindowTitle(f"Edit Track Tags: {title}")
        self.tabs.setCurrentIndex(1)
        self.tabs.setTabEnabled(0, False)
        self.btn_action.setText("Save Changes")
        self.btn_action.clicked.connect(self._on_save)

    def _on_save(self):
        self._save_current_single_track_form()
        fix_enc = self.fix_encoding_checkbox.isChecked()
        success = False
        progress = SaveProgressDialog(1, self, theme=self.theme)
        progress.show()
        self.operation_about_to_start.emit()
        try:
            t = self.tracks[0]
            file_path = t["file_path"]
            progress.set_operation(f"Writing tags: {Path(file_path).name}…", 0)
            if fix_enc:
                from malka.tags import detect_and_fix_encoding
                for k in ("title", "artist", "album_artist", "album", "genre"):
                    v = t.get(k)
                    if v and v != NO_DATA:
                        _, fixed_val = detect_and_fix_encoding(str(v))
                        t[k] = fixed_val

            cover_action = self.st_cover_widget.action
            new_cover = (
                self.st_cover_widget.new_image_path
                if cover_action == "new"
                else None
            )
            updated_tags = write_tags(
                file_path=file_path,
                title=t.get("title"),
                artist=t.get("artist"),
                album_artist=t.get("album_artist"),
                album=t.get("album"),
                year=t.get("year"),
                genre=t.get("genre"),
                track_no=t.get("track_no"),
                disc_no=t.get("disc_no"),
                disc_total=t.get("disc_total"),
                compilation=t.get("compilation"),
                new_cover_path=new_cover,
                remove_cover=(cover_action == "delete"),
            )
            from malka.organizer import is_track_organized
            db_data = {
                "title": updated_tags["title"],
                "artist": updated_tags["artist"],
                "album_artist": updated_tags["album_artist"],
                "album": updated_tags["album"],
                "year": updated_tags["year"],
                "genre": updated_tags["genre"],
                "track_no": updated_tags["track_no"],
                "disc_no": updated_tags.get("disc_no", "1"),
                "disc_total": updated_tags.get("disc_total", "1"),
                "compilation": updated_tags.get("compilation", 0),
                "has_cover": updated_tags["has_cover"],
                "cover_cache_path": updated_tags["cover_cache_path"],
                "mtime": updated_tags["mtime"],
                "bad_encoding": 0 if fix_enc else int(t.get("bad_encoding", 0)),
                "is_organized": 1 if is_track_organized(
                    updated_tags, list(config.library_paths), config.track_naming_format, self.is_multi_disc
                ) else 0,
            }
            update_track(self.db_conn, t["id"], db_data)
            self.db_conn.commit()
            progress.set_operation("Updating the library database…", 1)
            success = True
        except Exception as e:
            progress.accept()
            QMessageBox.critical(self, "Save Error", f"Failed to save track tags: {e}")
        finally:
            self.operation_finished.emit(success)
            if success:
                progress.finish()
        if success:
            self.accept()
            self._show_saved_message("Track tags and artwork saved.")
