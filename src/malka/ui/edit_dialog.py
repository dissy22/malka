from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
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

        self.btn_delete = QPushButton("Delete Cover")
        self.btn_delete.clicked.connect(self._on_delete_cover)
        btn_layout.addWidget(self.btn_delete)

        layout.addLayout(btn_layout)
        layout.addStretch()

        self._update_preview()

    def apply_theme(self, theme: str):
        self.theme = theme
        self._update_preview()

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


class BaseAlbumEditDialog(QDialog):
    """
    Unified base dialog for album and single-track metadata editing.
    Ensures 100% identical layout, control hierarchy, tab synchronization, and theme styling.
    """

    def __init__(self, tracks: List[Dict[str, Any]], parent=None, theme: Optional[str] = None):
        super().__init__(parent)
        self.tracks = [dict(t) for t in tracks]
        self.current_single_track_idx = -1

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

        self.resize(800, 600)
        self.setMinimumSize(700, 520)

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
        self.setStyleSheet(self.styleSheet() + checkbox_checkmark_qss())

        if hasattr(self, "album_cover_widget"):
            self.album_cover_widget.apply_theme(theme)
        if hasattr(self, "st_cover_widget"):
            self.st_cover_widget.apply_theme(theme)

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

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(self.btn_cancel)

        self.btn_action = QPushButton("Save Changes")
        self.btn_action.setObjectName("saveBtn")
        bottom_layout.addWidget(self.btn_action)

        self.main_layout.addLayout(bottom_layout)

        # Connect tab switching
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _setup_album_tab(self):
        layout = QVBoxLayout(self.tab_album)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.album_edit = QLineEdit()
        form.addRow("Album:", self.album_edit)

        self.album_artist_edit = QLineEdit()
        form.addRow("Album artist:", self.album_artist_edit)

        # Compilation checkbox
        self.compilation_checkbox = QCheckBox("Compilation (Various Artists album)")
        self.compilation_checkbox.toggled.connect(self._on_compilation_toggled)
        # Checkboxes are album-level controls too: keep the tracks in sync.
        self.compilation_checkbox.toggled.connect(self._on_album_fields_changed)
        form.addRow("Compilation:", self.compilation_checkbox)

        # Artist row with Checkbox underneath
        artist_widget = QWidget()
        artist_layout = QVBoxLayout(artist_widget)
        artist_layout.setContentsMargins(0, 0, 0, 0)
        artist_layout.setSpacing(4)
        self.artist_edit = QLineEdit()
        artist_layout.addWidget(self.artist_edit)
        self.artist_same_checkbox = QCheckBox("Apply this Artist to all tracks in album")
        self.artist_same_checkbox.setChecked(True)
        self.artist_same_checkbox.toggled.connect(self._on_album_fields_changed)
        artist_layout.addWidget(self.artist_same_checkbox)
        form.addRow("Artist:", artist_widget)

        self.year_edit = QLineEdit()
        form.addRow("Year:", self.year_edit)

        self.genre_edit = QLineEdit()
        form.addRow("Genre:", self.genre_edit)

        self.disc_total_edit = QLineEdit("1")
        form.addRow("Total Discs (CDs):", self.disc_total_edit)

        # Cover Art row
        self.album_cover_widget = CoverPreviewWidget(size=120, theme=self.theme)
        form.addRow("Cover Art:", self.album_cover_widget)

        layout.addLayout(form)
        layout.addStretch()

        # Connect text changes to trigger validation & live tab sync
        self.album_edit.textChanged.connect(self._on_album_fields_changed)
        self.album_artist_edit.textChanged.connect(self._on_album_fields_changed)
        self.artist_edit.textChanged.connect(self._on_album_fields_changed)
        self.year_edit.textChanged.connect(self._on_album_fields_changed)
        self.genre_edit.textChanged.connect(self._on_album_fields_changed)
        self.disc_total_edit.textChanged.connect(self._on_album_fields_changed)

    def _setup_single_track_tab(self):
        layout = QHBoxLayout(self.tab_tracks)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Left: List of tracks
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.left_title = QLabel("Album Tracks:")
        title_col = "#57606a" if self.theme == "light" else "#8b949e"
        self.left_title.setStyleSheet(f"font-weight: bold; color: {title_col};")
        left_layout.addWidget(self.left_title)

        self.track_list = QListWidget()
        self.track_list.currentRowChanged.connect(self._on_track_selected)
        left_layout.addWidget(self.track_list)
        splitter.addWidget(left_widget)

        # Right: Single track edit form
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.right_title = QLabel("Edit Selected Track:")
        self.right_title.setStyleSheet(f"font-weight: bold; color: {title_col};")
        right_layout.addWidget(self.right_title)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Disc fields
        disc_layout = QHBoxLayout()
        disc_layout.setSpacing(6)
        self.st_disc_no = QLineEdit()
        self.st_disc_no.setPlaceholderText("1")
        self.st_disc_no.setFixedWidth(50)
        self.st_disc_total = QLineEdit()
        self.st_disc_total.setPlaceholderText("1")
        self.st_disc_total.setFixedWidth(50)
        disc_layout.addWidget(QLabel("Disc:"))
        disc_layout.addWidget(self.st_disc_no)
        disc_layout.addWidget(QLabel("of"))
        disc_layout.addWidget(self.st_disc_total)
        disc_layout.addStretch()
        form.addRow("Disc (CD):", disc_layout)

        self.st_track_no = QLineEdit()
        form.addRow("Track Number:", self.st_track_no)

        self.st_title = QLineEdit()
        form.addRow("Title:", self.st_title)

        self.st_artist = QLineEdit()
        form.addRow("Artist:", self.st_artist)

        self.st_album_artist = QLineEdit()
        form.addRow("Album artist:", self.st_album_artist)

        self.st_album = QLineEdit()
        form.addRow("Album:", self.st_album)

        self.st_year = QLineEdit()
        form.addRow("Year:", self.st_year)

        self.st_genre = QLineEdit()
        form.addRow("Genre:", self.st_genre)

        self.st_cover_widget = CoverPreviewWidget(size=100, theme=self.theme)
        form.addRow("Cover Art:", self.st_cover_widget)

        right_layout.addLayout(form)
        right_layout.addStretch()
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Connect live track changes
        self.st_disc_no.textChanged.connect(self._on_single_track_field_changed)
        self.st_disc_total.textChanged.connect(self._on_single_track_field_changed)
        self.st_track_no.textChanged.connect(self._on_single_track_field_changed)
        self.st_title.textChanged.connect(self._on_single_track_field_changed)
        self.st_artist.textChanged.connect(self._on_single_track_field_changed)
        self.st_album_artist.textChanged.connect(self._on_single_track_field_changed)
        self.st_album.textChanged.connect(self._on_single_track_field_changed)
        self.st_year.textChanged.connect(self._on_single_track_field_changed)
        self.st_genre.textChanged.connect(self._on_single_track_field_changed)

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

        # Populate track list
        self._refresh_track_list()
        if self.tracks:
            self.track_list.setCurrentRow(0)

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
            for w in widgets:
                w.blockSignals(False)

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
            self.st_artist, self.st_album_artist, self.st_album, self.st_year, self.st_genre
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

        # Update left list item
        discs = {str(item.get("disc_no", "1")).strip() for item in self.tracks if item.get("disc_no")}
        has_multi = len(discs) > 1 or any(d not in ("1", "", NO_DATA) for d in discs)
        prefix = f"[CD {t['disc_no']}] " if has_multi else ""
        item = self.track_list.item(row)
        if item:
            item.setText(f"{prefix}{t['track_no']}. {t['title']}")

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

            # Cover changes
            t["_cover_action"] = self.st_cover_widget.action
            t["_new_cover_path"] = self.st_cover_widget.new_image_path

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
            self.btn_action.setEnabled(False)
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
        self.operation_about_to_start.emit()
        try:
            for t in self.tracks:
                file_path = t["file_path"]

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
            success = True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save changes to tags: {e}")
        finally:
            self.operation_finished.emit(success)

        if success:
            self.accept()


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
        self.operation_about_to_start.emit()
        try:
            t = self.tracks[0]
            file_path = t["file_path"]
            if fix_enc:
                from malka.tags import detect_and_fix_encoding
                for k in ("title", "artist", "album_artist", "album", "genre"):
                    v = t.get(k)
                    if v and v != NO_DATA:
                        _, fixed_val = detect_and_fix_encoding(str(v))
                        t[k] = fixed_val

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
                new_cover_path=None,
                remove_cover=False,
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
            success = True
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save track tags: {e}")
        finally:
            self.operation_finished.emit(success)
        if success:
            self.accept()
