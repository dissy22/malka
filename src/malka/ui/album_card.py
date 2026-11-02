from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)


class CoverLabel(QWidget):
    """Paints a pixmap without changing size hints or invalidating the layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self.setAutoFillBackground(False)

    def setPixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update()

    def pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    def clear(self):
        self._pixmap = None
        self.update()

    def setAlignment(self, *_args, **_kwargs):
        # Compatibility with the previous QLabel implementation.
        pass

    def paintEvent(self, event):
        if self._pixmap is None or self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()

from malka.config import NO_DATA, config
from malka.ui.image_utils import (
    create_square_placeholder,
    get_cached_square_pixmap,
    request_async_square_pixmap,
)


class AlbumCard(QFrame):
    album_clicked = pyqtSignal(dict)  # emits album_data
    edit_requested = pyqtSignal(str, str)  # album, album_artist
    fix_encoding_requested = pyqtSignal(str, str)  # album, album_artist
    organize_requested = pyqtSignal(str, str)  # album, album_artist
    open_folder_requested = pyqtSignal(str, str)

    def __init__(
        self,
        album_data: Dict[str, Any],
        is_organize_ready: Optional[bool] = None,
        organize_tooltip: str = "",
        parent=None,
        db_conn=None,
        defer_cover: bool = False,
    ):
        super().__init__(parent)
        self.album_data = album_data
        self.album = album_data["album"]
        self.album_artist = album_data["album_artist"]
        self.display_artist = album_data.get("display_artist", album_data["album_artist"])
        self.year = album_data.get("year", NO_DATA)
        self.cover_path = album_data.get("cover_path", "")
        self.track_count = album_data.get("track_count", 0)
        self.disc_count = album_data.get("disc_count", 1)
        self.has_bad_encoding = bool(album_data.get("has_bad_encoding", False))
        # Album is "organized" when every track already sits at its canonical path.
        self.is_organized = bool(album_data.get("is_organized", True))
        self.is_organize_ready = is_organize_ready
        self.organize_tooltip = organize_tooltip
        self.db_conn = db_conn
        self.defer_cover = defer_cover
        self._cover_loaded = False
        self._cover_loading = False

        self.setFixedSize(170, 230)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("albumCard")

        self.init_ui()
        from malka.config import config
        if self.defer_cover:
            # Cards in the main grid are styled once by MainWindow's stylesheet;
            # avoiding per-card setStyleSheet() makes creating 5000 tiles much
            # faster.
            self.theme = getattr(config, "theme", "dark")
        else:
            self.apply_theme(getattr(config, "theme", "dark"))

    def apply_theme(self, theme: str):
        self.theme = theme
        if getattr(self, "defer_cover", False):
            return
        if theme == "light":
            self.setStyleSheet("""
                QFrame#albumCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#albumCard:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                    border: none;
                    border-radius: 8px;
                }
                QLabel {
                    background: transparent;
                }
            """)
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #1f2328;")
            if hasattr(self, "info_label"):
                self.info_label.setStyleSheet("color: #656d76;")
        else:
            self.setStyleSheet("""
                QFrame#albumCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#albumCard:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: none;
                    border-radius: 8px;
                }
                QLabel {
                    background: transparent;
                }
            """)
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #ffffff;")
            if hasattr(self, "info_label"):
                self.info_label.setStyleSheet("color: #8b949e;")

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Frameless edge-to-edge square cover (170x170)
        self.cover_label = CoverLabel(self)
        self.cover_label.setFixedSize(170, 170)
        if self.defer_cover:
            self._set_blank_cover()
        else:
            self.set_cover_pixmap()
        layout.addWidget(self.cover_label)

        # Bad encoding warning badge overlay on cover. Deliberately understated:
        # this is a metadata issue, not an audio/encoder problem.
        if self.has_bad_encoding and getattr(config, "show_encoding_badge", True):
            self.badge_encoding = QLabel(self.cover_label)
            self.badge_encoding.setText("Bad tags encoding")
            self.badge_encoding.setStyleSheet("""
                QLabel {
                    background-color: rgba(13, 17, 23, 0.78);
                    color: #d29922;
                    font-size: 7pt;
                    font-weight: 600;
                    border: none;
                    border-radius: 4px;
                    padding: 1px 5px;
                }
            """)
            self.badge_encoding.setToolTip(
                "The text in this album's tags was decoded with the wrong character encoding (mojibake).\n"
                "The audio itself is fine. Right-click the album to fix the tags encoding."
            )
            self.badge_encoding.adjustSize()
            self.badge_encoding.move(6, 6)
            self.badge_encoding.show()

        # "Files need to be organized" badge, bottom-left so both can coexist.
        if not self.is_organized and getattr(config, "show_organize_badge", True):
            self.badge_organize = QLabel(self.cover_label)
            self.badge_organize.setText("Files need to be organized")
            self.badge_organize.setStyleSheet("""
                QLabel {
                    background-color: rgba(13, 17, 23, 0.82);
                    color: #e3b341;
                    font-size: 6.5pt;
                    font-weight: 600;
                    border: none;
                    border-radius: 4px;
                    padding: 1px 5px;
                }
            """)
            self.badge_organize.setToolTip(
                "These files are not in the library layout "
                "(<Album artist>/<Year> - <Album>/<template>).\n"
                "Right-click the album and choose \"Organize album files\"."
            )
            self.badge_organize.adjustSize()
            self.badge_organize.move(6, 170 - self.badge_organize.height() - 6)
            self.badge_organize.show()

        # Title Label
        self.title_label = QLabel()
        self.title_label.setObjectName("albumCardTitle")
        self.title_label.setContentsMargins(8, 0, 8, 0)
        self.title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        if not self.defer_cover:
            self.title_label.setStyleSheet("color: #ffffff;")
        disp_title = self.album if self.album != NO_DATA else "Untitled Album"
        elided = self.title_label.fontMetrics().elidedText(disp_title, Qt.TextElideMode.ElideRight, 154)
        self.title_label.setText(elided)
        self.title_label.setToolTip(disp_title)
        layout.addWidget(self.title_label)

        # Artist & Year Label
        self.info_label = QLabel()
        self.info_label.setObjectName("albumCardInfo")
        self.info_label.setContentsMargins(8, 0, 8, 0)
        self.info_label.setFont(QFont("Segoe UI", 8))
        if not self.defer_cover:
            self.info_label.setStyleSheet("color: #8b949e;")
        disp_artist = self.display_artist if self.display_artist != NO_DATA else "Unknown Artist"
        disp_year = f" ({self.year})" if self.year != NO_DATA else ""
        cd_info = f" • {self.disc_count} CDs" if self.disc_count > 1 else ""
        info_text = f"{disp_artist}{disp_year}{cd_info}"
        elided_info = self.info_label.fontMetrics().elidedText(info_text, Qt.TextElideMode.ElideRight, 154)
        self.info_label.setText(elided_info)
        self.info_label.setToolTip(f"{disp_artist}{disp_year} ({self.track_count} tracks{cd_info})")
        layout.addWidget(self.info_label)

        layout.addStretch()

    def _set_blank_cover(self):
        """Empty tile fill shown until this album's cover is loaded."""
        placeholder = create_square_placeholder(
            size=170,
            text_or_icon="",
            radius_top=8,
            bg_color="#1c2128",
            fg_color="#6e7681",
        )
        self.cover_label.setPixmap(placeholder)

    def load_cover(self, callback=None):
        """
        Loads one cover into an already-rendered tile.

        Called sequentially by MainWindow: the whole grid appears immediately
        with blank cover areas, and artwork is then filled in one album at a time.
        """
        if self._cover_loaded or self._cover_loading:
            if callback:
                callback()
            return

        if not self.cover_path or not Path(self.cover_path).exists():
            self._set_blank_cover()
            self._cover_loaded = True
            if callback:
                callback()
            return

        cached = get_cached_square_pixmap(self.cover_path, size=170, radius_top=8)
        if cached:
            self.cover_label.setPixmap(cached)
            self._cover_loaded = True
            if callback:
                callback()
            return

        self._cover_loading = True
        self._set_blank_cover()

        def _done(path: str, pixmap: QPixmap):
            self._cover_loading = False
            self._cover_loaded = True
            self._on_cover_loaded(path, pixmap)
            if callback:
                callback()

        request_async_square_pixmap(
            self.cover_path,
            size=170,
            radius_top=8,
            callback=_done,
        )

    def set_cover_pixmap(self):
        size = 170
        if not self.cover_path or not Path(self.cover_path).exists():
            placeholder = create_square_placeholder(
                size=size,
                text_or_icon="🎵",
                radius_top=8,
                bg_color="#1c2128",
                fg_color="#6e7681",
            )
            self.cover_label.setPixmap(placeholder)
            return

        # 1. Instant cache check (0ms)
        cached_pix = get_cached_square_pixmap(self.cover_path, size=size, radius_top=8)
        if cached_pix:
            self.cover_label.setPixmap(cached_pix)
            return

        # 2. Show lightweight placeholder immediately so UI never lags
        placeholder = create_square_placeholder(
            size=size,
            text_or_icon="🎵",
            radius_top=8,
            bg_color="#1c2128",
            fg_color="#6e7681",
        )
        self.cover_label.setPixmap(placeholder)

        # 3. Asynchronously generate & load thumbnail in background thread pool
        request_async_square_pixmap(
            self.cover_path,
            size=size,
            radius_top=8,
            callback=self._on_cover_loaded,
        )

    def _on_cover_loaded(self, path: str, pixmap: QPixmap):
        if self.cover_path and Path(self.cover_path).resolve() == Path(path).resolve():
            if not pixmap.isNull():
                self.cover_label.setPixmap(pixmap)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.album_clicked.emit(self.album_data)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.edit_requested.emit(self.album, self.album_artist)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = self.build_context_menu()
        menu.exec(event.globalPos())

    def build_context_menu(self) -> QMenu:
        """Builds (but does not show) the album context menu."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        self.context_menu = menu
        menu.setStyleSheet("""
            QMenu {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #3c3c3c;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #383838;
            }
            QMenu::item:disabled {
                color: #6e7681;
                background-color: transparent;
            }
            QMenu::separator {
                height: 1px;
                background: #3c3c3c;
                margin: 4px 0px;
            }
        """)

        edit_action = QAction("Edit album tags...", self)
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self.album, self.album_artist))
        menu.addAction(edit_action)

        fix_encoding_action = QAction("Fix tags encoding", self)
        fix_encoding_action.setEnabled(self.has_bad_encoding)
        if self.has_bad_encoding:
            fix_encoding_action.setToolTip("Rewrite this album's tags using the detected source character encoding.")
        else:
            fix_encoding_action.setToolTip("No tags encoding problems were detected for this album.")
        fix_encoding_action.triggered.connect(lambda: self.fix_encoding_requested.emit(self.album, self.album_artist))
        self.fix_encoding_action = fix_encoding_action
        menu.addAction(fix_encoding_action)

        # Lazy check readiness on demand only when right-click menu is opened
        ready = self.is_organize_ready
        tooltip = self.organize_tooltip
        if ready is None and self.db_conn:
            from malka.db import get_album_tracks
            from malka.organizer import is_album_ready_to_organize
            tracks = get_album_tracks(self.db_conn, self.album, self.album_artist)
            ready, tooltip = is_album_ready_to_organize(tracks)
            self.is_organize_ready = ready
            self.organize_tooltip = tooltip
        elif ready is None:
            ready = True

        organize_action = QAction("Organize album files", self)
        if self.is_organized:
            ready = False
            tooltip = "All files are already in the library layout"
        organize_action.setEnabled(ready)
        if not ready and tooltip:
            organize_action.setToolTip(tooltip)
        organize_action.triggered.connect(lambda: self.organize_requested.emit(self.album, self.album_artist))
        self.organize_action = organize_action
        menu.addAction(organize_action)

        menu.addSeparator()

        open_folder_action = QAction("Open folder in file manager", self)
        open_folder_action.triggered.connect(lambda: self.open_folder_requested.emit(self.album, self.album_artist))
        menu.addAction(open_folder_action)

        return menu
