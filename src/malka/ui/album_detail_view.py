"""
Album Detail View for Malka.
Displays a dedicated album page with:
- Large album cover artwork
- Album title, artist, year, genre, and tracks count
- 'Play album' button
- Interactive tracklist with hover highlight and Play icon
- Plays tracks via PlayerController
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from mutagen import File
from PyQt6.QtCore import QEvent, QObject, QPoint, QRectF, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from malka.config import NO_DATA, config
from malka.db import get_album_tracks
from malka.player import PlayerController, format_time_ms, is_file_playable
from malka.ui.image_utils import (
    create_square_placeholder,
    get_cached_square_pixmap,
    get_resource_icon,
    get_resource_pixmap,
    request_async_square_pixmap,
)


_TRACK_DURATION_CACHE: Dict[str, str] = {}


class _DurationSignals(QObject):
    duration_ready = pyqtSignal(str, str)  # (file_path, duration_str)


_DURATION_SIGNALS = _DurationSignals()


class _DurationWorker(QRunnable):
    def __init__(self, file_path: str, db_conn=None):
        super().__init__()
        self.file_path = file_path
        self.db_conn = db_conn

    def run(self):
        try:
            if self.file_path and Path(self.file_path).exists():
                audio = File(self.file_path)
                if audio and audio.info and hasattr(audio.info, "length"):
                    length_sec = float(audio.info.length)
                    dur_str = format_time_ms(int(length_sec * 1000))
                    _TRACK_DURATION_CACHE[self.file_path] = dur_str
                    _DURATION_SIGNALS.duration_ready.emit(self.file_path, dur_str)
                    if self.db_conn:
                        from malka.db import update_track_duration
                        update_track_duration(self.db_conn, self.file_path, length_sec)
        except Exception:
            pass


def _get_initial_duration_str(track: Dict[str, Any]) -> str:
    dur = track.get("duration", 0.0)
    try:
        dur_val = float(dur)
        if dur_val > 0:
            return format_time_ms(int(dur_val * 1000))
    except Exception:
        pass
    fp = track.get("file_path", "")
    return _TRACK_DURATION_CACHE.get(fp, "")


class TrackRowWidget(QFrame):
    """
    Interactive track row with Spotify-style hover:
    Shows track number normally; on hover, shows '▶' play icon and highlights the row.
    """

    track_clicked = pyqtSignal(dict)  # emits track dict
    location_requested = pyqtSignal(dict)  # right-click -> reveal file in file manager

    def __init__(self, track: Dict[str, Any], album_artist: str, is_active: bool = False, is_playing: bool = False, db_conn=None, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.track = track
        self.album_artist = album_artist
        self.is_active = is_active
        self.is_playing = is_playing
        self.db_conn = db_conn
        self.theme = theme

        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("trackRow")

        self._is_hovered = False
        self._init_ui()
        self._update_style()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 16, 0)
        layout.setSpacing(12)

        # Left Number / Play Indicator (fixed 32px width)
        self.icon_label = QLabel()
        self.icon_label.setFixedWidth(28)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        layout.addWidget(self.icon_label)

        # Title & Artist
        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel()
        self.title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet("color: #ffffff;")
        disp_title = self.track.get("title", "Untitled Track")
        self.title_label.setText(disp_title)
        self.title_label.setToolTip(disp_title)
        text_layout.addWidget(self.title_label)

        track_artist = self.track.get("artist", "")
        if track_artist and track_artist != NO_DATA and track_artist != self.album_artist:
            self.sub_label = QLabel(track_artist)
            self.sub_label.setFont(QFont("Segoe UI", 7))
            self.sub_label.setStyleSheet("color: #8b949e;")
            text_layout.addWidget(self.sub_label)

        layout.addLayout(text_layout, 1)

        # Audio Format label (plain text, no badge pill / visual highlight)
        ext = self.track.get("file_path", "").rsplit(".", 1)[-1].lower()
        if ext in ("m4a", "mp3", "flac", "wv", "ape"):
            fmt_lbl = QLabel(ext.upper())
            fmt_lbl.setFont(QFont("Segoe UI", 7))
            fmt_lbl.setStyleSheet("color: #6e7681; background: transparent; border: none;")
            layout.addWidget(fmt_lbl)

        # Duration label
        dur_str = _get_initial_duration_str(self.track)
        self.duration_label = QLabel(dur_str)
        self.duration_label.setFont(QFont("Segoe UI", 8))
        self.duration_label.setStyleSheet("color: #8b949e;")
        self.duration_label.setFixedWidth(45)
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.duration_label)

        # If duration was missing from DB/cache, load asynchronously in background thread
        if not dur_str and self.track.get("file_path"):
            _DURATION_SIGNALS.duration_ready.connect(self._on_duration_ready)
            QThreadPool.globalInstance().start(_DurationWorker(self.track.get("file_path"), self.db_conn))

    def _on_duration_ready(self, file_path: str, duration_str: str):
        if self.track.get("file_path") == file_path:
            self.duration_label.setText(duration_str)

    def _update_style(self):
        is_light = (self.theme == "light")
        accent_color = "#0969da" if is_light else "#58a6ff"
        text_color = "#1f2328" if is_light else "#ffffff"
        muted_color = "#656d76" if is_light else "#8b949e"

        if self.is_active:
            bg = "rgba(9, 105, 218, 0.12)" if is_light else "rgba(88, 166, 255, 0.15)"
            self.setStyleSheet(f"""
                QFrame#trackRow {{
                    background-color: {bg};
                    border: none;
                    border-radius: 6px;
                }}
            """)
            self.title_label.setStyleSheet(f"color: {accent_color}; font-weight: bold;")
            pix = get_resource_pixmap("pause.png" if self.is_playing else "play.png", 14, 14, theme=self.theme)
            if not pix.isNull():
                self.icon_label.setPixmap(pix)
            else:
                self.icon_label.setText("⏸" if self.is_playing else "▶")
                self.icon_label.setStyleSheet(f"color: {accent_color};")
        elif self._is_hovered:
            bg = "rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.08)"
            self.setStyleSheet(f"""
                QFrame#trackRow {{
                    background-color: {bg};
                    border: none;
                    border-radius: 6px;
                }}
            """)
            self.title_label.setStyleSheet(f"color: {text_color}; font-weight: bold;")
            pix = get_resource_pixmap("play.png", 14, 14, theme=self.theme)
            if not pix.isNull():
                self.icon_label.setPixmap(pix)
            else:
                self.icon_label.setText("▶")
                self.icon_label.setStyleSheet(f"color: {text_color}; font-size: 11px;")
        else:
            self.setStyleSheet("""
                QFrame#trackRow {
                    background-color: transparent;
                    border: none;
                    border-radius: 6px;
                }
            """)
            self.title_label.setStyleSheet(f"color: {text_color};")
            self.icon_label.clear()
            # Show track number
            raw_no = self.track.get("track_no", "01")
            try:
                num = int(str(raw_no).split("/")[0])
                disp_num = f"{num:02d}"
            except Exception:
                disp_num = str(raw_no)
            self.icon_label.setText(disp_num)
            self.icon_label.setStyleSheet(f"color: {muted_color}; font-size: 9pt;")

    def enterEvent(self, event):
        self._is_hovered = True
        self._update_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self._update_style()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.track_clicked.emit(self.track)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self.context_menu = menu
        is_light = (self.theme == "light")
        if is_light:
            menu.setStyleSheet("""
                QMenu {
                    background-color: #ffffff;
                    color: #1f2328;
                    border: 1px solid #d0d7de;
                    border-radius: 8px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 18px;
                    border-radius: 5px;
                }
                QMenu::item:selected {
                    background-color: #f3f4f6;
                    color: #0969da;
                }
            """)
        else:
            menu.setStyleSheet("""
                QMenu {
                    background-color: #1a1e24;
                    color: #e6edf3;
                    border: 1px solid #30363d;
                    border-radius: 8px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 18px;
                    border-radius: 5px;
                }
                QMenu::item:selected {
                    background-color: #262c36;
                    color: #58a6ff;
                }
            """)

        open_location_action = QAction("Open file location", menu)
        open_location_action.triggered.connect(lambda: self.location_requested.emit(self.track))
        menu.addAction(open_location_action)
        menu.exec(event.globalPos())

    def set_active_state(self, is_active: bool, is_playing: bool):
        self.is_active = is_active
        self.is_playing = is_playing
        self._update_style()


class AlbumDetailView(QWidget):
    """
    Dedicated Album Detail page showing artwork, metadata, Play Album button, and tracks.
    """

    back_requested = pyqtSignal()
    track_play_requested = pyqtSignal(dict, dict, list)  # (track, album_data, all_tracks)
    track_location_requested = pyqtSignal(dict)  # reveal the track file in the file manager

    def __init__(self, controller: PlayerController, db_conn, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.db_conn = db_conn
        self.theme = getattr(config, "theme", "dark")

        self.album_data: Dict[str, Any] = {}
        self.tracks: List[Dict[str, Any]] = []
        self.track_rows: List[TrackRowWidget] = []

        self._init_ui()
        self.apply_theme(self.theme)

        # Connect controller track changes to highlight active track
        self.controller.track_started.connect(self._on_track_started)
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.playback_stopped.connect(self._on_playback_stopped)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 20)
        main_layout.setSpacing(20)

        # Scroll Area for album details & track list
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.update_scrollbars()
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 20)
        self.content_layout.setSpacing(24)

        # 1. Full-width Album Title Section (Spans entire window width, no word-wrap)
        self.title_frame = QFrame()
        self.title_frame.setStyleSheet("background: transparent; border: none;")
        self.title_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_layout = QVBoxLayout(self.title_frame)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)

        # Category tag
        self.category_label = QLabel("ALBUM")
        self.category_label.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.category_label.setStyleSheet("color: #8b949e; letter-spacing: 1px;")
        title_layout.addWidget(self.category_label)

        # Album Title (Full width of the window, single line, no word-wrap)
        self.title_label = QLabel("Album Title")
        self.title_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #ffffff;")
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_layout.addWidget(self.title_label)

        self.content_layout.addWidget(self.title_frame)

        # 2. Main Body Split: Left Column (Cover + Info + Play) and Right Column (Tracks)
        body_widget = QWidget()
        body_widget.setStyleSheet("background: transparent; border: none;")
        body_layout = QHBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(28)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Left Column: Cover, Info, Play Button (220px width)
        left_widget = QWidget()
        left_widget.setFixedWidth(220)
        left_widget.setStyleSheet("background: transparent; border: none;")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Large Album Cover (220x220)
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(220, 220)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.cover_label)

        # Album Information (Artist, Metadata) under the cover
        meta_container = QVBoxLayout()
        meta_container.setSpacing(4)
        meta_container.setContentsMargins(0, 0, 0, 0)

        # Artist
        self.artist_label = QLabel("Artist Name")
        self.artist_label.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self.artist_label.setStyleSheet("color: #58a6ff;")
        self.artist_label.setWordWrap(True)
        meta_container.addWidget(self.artist_label)

        # Secondary Metadata (Year • Genre • Track count • Discs)
        self.meta_label = QLabel("2020 • Rock • 12 tracks")
        self.meta_label.setFont(QFont("Segoe UI", 9))
        self.meta_label.setStyleSheet("color: #8b949e;")
        self.meta_label.setWordWrap(True)
        meta_container.addWidget(self.meta_label)

        left_layout.addLayout(meta_container)

        left_layout.addSpacing(6)

        # "Play album" Button under information (borderless)
        self.btn_play_album = QPushButton("  Play album")
        self.btn_play_album.setIcon(get_resource_icon("play.png"))
        self.btn_play_album.setIconSize(QSize(16, 16))
        self.btn_play_album.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_album.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #0d1117;
                font-weight: 700;
                font-size: 13px;
                border-radius: 18px;
                border: none;
                padding: 8px 24px;
                min-height: 20px;
                max-width: 220px;
            }
            QPushButton:hover {
                background-color: #f3f4f6;
                border: none;
            }
            QPushButton:pressed {
                background-color: #d0d7de;
                border: none;
            }
        """)
        self.btn_play_album.clicked.connect(self._on_play_album_clicked)
        left_layout.addWidget(self.btn_play_album)

        # Album comment tag (shown right below "Play album")
        self.comment_label = QLabel("")
        self.comment_label.setObjectName("albumComment")
        self.comment_label.setFont(QFont("Segoe UI", 8))
        self.comment_label.setWordWrap(True)
        self.comment_label.setStyleSheet("color: #8b949e;")
        self.comment_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.comment_label.hide()
        left_layout.addWidget(self.comment_label)

        left_layout.addStretch()

        self.header_frame = left_widget  # Maintain attribute reference
        body_layout.addWidget(left_widget, 0, Qt.AlignmentFlag.AlignTop)

        # Right Column: Tracklist directly to the right of the cover & info
        self.tracks_container = QVBoxLayout()
        self.tracks_container.setSpacing(4)
        self.tracks_container.setContentsMargins(0, 0, 0, 0)
        self.tracks_container.setAlignment(Qt.AlignmentFlag.AlignTop)

        right_widget = QWidget()
        right_widget.setStyleSheet("background: transparent; border: none;")
        right_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        right_widget.setLayout(self.tracks_container)

        body_layout.addWidget(right_widget, 1)

        self.content_layout.addWidget(body_widget, 1)

        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)

    def set_album(self, album_data: Dict[str, Any]):
        self.album_data = album_data
        album_name = album_data["album"]
        album_artist = album_data["album_artist"]

        # Fetch tracks
        self.tracks = get_album_tracks(self.db_conn, album_name, album_artist)

        # Update metadata
        disp_title = album_name if album_name != NO_DATA else "Untitled Album"
        self.title_label.setText(disp_title)
        self.title_label.setToolTip(disp_title)

        disp_artist = album_data.get("display_artist") or album_artist
        if not disp_artist or disp_artist == NO_DATA:
            disp_artist = "Unknown Artist"
        self.artist_label.setText(disp_artist)

        is_comp = album_data.get("is_compilation", False)
        self.category_label.setText("COMPILATION" if is_comp else "ALBUM")

        year = album_data.get("year", "")
        year_str = f"{year}" if year and year != NO_DATA else ""
        genre = album_data.get("genre", "")
        if not genre and self.tracks:
            genre = self.tracks[0].get("genre", "")
        genre_str = f"{genre}" if genre and genre != NO_DATA else ""

        tr_count = len(self.tracks)
        tr_str = f"{tr_count} {'track' if tr_count == 1 else 'tracks'}"

        disc_count = album_data.get("disc_count", 1)
        disc_str = f" • {disc_count} CDs" if disc_count > 1 else ""

        meta_parts = [p for p in (year_str, genre_str, tr_str) if p]
        self.meta_label.setText(" • ".join(meta_parts) + disc_str)

        # Comment tag (use the first non-empty track comment of the album)
        comment = ""
        for track in self.tracks:
            candidate = (track.get("comment") or "").strip()
            if candidate and candidate != NO_DATA:
                comment = candidate
                break
        if not comment and self.tracks:
            # Albums scanned by older versions do not have the comment column
            # populated yet; read it directly once instead of forcing a rescan.
            try:
                from malka.tags import read_tags
                first_path = self.tracks[0].get("file_path", "")
                if first_path:
                    candidate = (read_tags(first_path).get("comment") or "").strip()
                    if candidate and candidate != NO_DATA:
                        comment = candidate
            except Exception:
                pass
        if comment:
            self.comment_label.setText(comment)
            self.comment_label.setToolTip(comment)
            self.comment_label.show()
        else:
            self.comment_label.clear()
            self.comment_label.hide()

        # Cover image (non-blocking)
        cover_path = album_data.get("cover_path", "")
        if cover_path:
            cached = get_cached_square_pixmap(cover_path, size=220, radius_top=8)
            if cached:
                self.cover_label.setPixmap(cached)
            else:
                placeholder = create_square_placeholder(size=220, text_or_icon="🎵", radius_top=8)
                self.cover_label.setPixmap(placeholder)
                request_async_square_pixmap(cover_path, size=220, radius_top=8, callback=self._on_cover_loaded)
        else:
            placeholder = create_square_placeholder(size=220, text_or_icon="🎵", radius_top=8)
            self.cover_label.setPixmap(placeholder)

        # Render track rows
        self._render_tracks()

    def _on_cover_loaded(self, path: str, pixmap: QPixmap):
        curr_cover = self.album_data.get("cover_path", "")
        if curr_cover and Path(curr_cover).resolve() == Path(path).resolve():
            if not pixmap.isNull():
                self.cover_label.setPixmap(pixmap)

    def _render_tracks(self):
        self.setUpdatesEnabled(False)
        try:
            # Clear existing track rows
            for row in self.track_rows:
                row.setParent(None)
                row.deleteLater()
            self.track_rows.clear()

            # Remove existing widgets in tracks container
            while self.tracks_container.count() > 0:
                item = self.tracks_container.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

            if not self.tracks:
                empty_lbl = QLabel("No tracks found in this album.")
                empty_lbl.setStyleSheet("color: #8b949e; padding: 20px;")
                self.tracks_container.addWidget(empty_lbl)
                return

            # Check multi-disc grouping
            distinct_discs = sorted(list({t.get("disc_no", "1") for t in self.tracks}), key=lambda d: int(d) if str(d).isdigit() else 1)
            is_multi_disc = len(distinct_discs) > 1

            curr_track = self.controller.current_track
            curr_fp = curr_track.get("file_path") if curr_track else None
            is_playing = self.controller.is_playing()

            for disc in distinct_discs:
                if is_multi_disc:
                    disc_header = QLabel(f"CD {disc}")
                    disc_header.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                    disc_header.setStyleSheet("color: #8b949e; padding: 14px 10px 4px 10px;")
                    self.tracks_container.addWidget(disc_header)

                disc_tracks = [t for t in self.tracks if t.get("disc_no", "1") == disc]
                for t in disc_tracks:
                    active = (curr_fp is not None and t.get("file_path") == curr_fp)
                    row = TrackRowWidget(
                        track=t,
                        album_artist=self.album_data.get("album_artist", ""),
                        is_active=active,
                        is_playing=(active and is_playing),
                        db_conn=self.db_conn,
                        theme=self.theme,
                    )
                    row.track_clicked.connect(self._on_track_clicked)
                    row.location_requested.connect(self.track_location_requested.emit)
                    self.track_rows.append(row)
                    self.tracks_container.addWidget(row)
        finally:
            self.setUpdatesEnabled(True)

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")
        if is_light:
            if hasattr(self, "category_label"):
                self.category_label.setStyleSheet("color: #656d76; letter-spacing: 1px;")
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #1f2328;")
            if hasattr(self, "artist_label"):
                self.artist_label.setStyleSheet("color: #0969da;")
            if hasattr(self, "meta_label"):
                self.meta_label.setStyleSheet("color: #656d76;")
            if hasattr(self, "comment_label"):
                self.comment_label.setStyleSheet("color: #656d76; font-size: 8pt;")
            if hasattr(self, "btn_play_album"):
                self.btn_play_album.setStyleSheet("""
                    QPushButton {
                        background-color: #1f2328;
                        color: #ffffff;
                        font-weight: 700;
                        font-size: 13px;
                        border-radius: 18px;
                        border: none;
                        padding: 8px 24px;
                        min-height: 20px;
                        max-width: 220px;
                    }
                    QPushButton:hover {
                        background-color: #32383f;
                        border: none;
                    }
                    QPushButton:pressed {
                        background-color: #424a53;
                        border: none;
                    }
                """)
        else:
            if hasattr(self, "category_label"):
                self.category_label.setStyleSheet("color: #8b949e; letter-spacing: 1px;")
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #ffffff;")
            if hasattr(self, "artist_label"):
                self.artist_label.setStyleSheet("color: #58a6ff;")
            if hasattr(self, "meta_label"):
                self.meta_label.setStyleSheet("color: #8b949e;")
            if hasattr(self, "comment_label"):
                self.comment_label.setStyleSheet("color: #8b949e; font-size: 8pt;")
            if hasattr(self, "btn_play_album"):
                self.btn_play_album.setStyleSheet("""
                    QPushButton {
                        background-color: #ffffff;
                        color: #0d1117;
                        font-weight: 700;
                        font-size: 13px;
                        border-radius: 18px;
                        border: none;
                        padding: 8px 24px;
                        min-height: 20px;
                        max-width: 220px;
                    }
                    QPushButton:hover {
                        background-color: #f3f4f6;
                        border: none;
                    }
                    QPushButton:pressed {
                        background-color: #d0d7de;
                        border: none;
                    }
                """)

        if hasattr(self, "btn_play_album"):
            # Play album button has inverted background: dark button (#1f2328) with white icon in light theme,
            # and white button (#ffffff) with dark icon in dark theme.
            btn_icon_theme = "dark" if theme == "light" else "light"
            self.btn_play_album.setIcon(get_resource_icon("play.png", theme=btn_icon_theme))

        for row in self.track_rows:
            row.theme = theme
            row._update_style()

        self.update_scrollbars()

    def update_scrollbars(self):
        policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if getattr(config, "show_scrollbars", True) else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        if hasattr(self, "scroll_area"):
            self.scroll_area.setVerticalScrollBarPolicy(policy)
            self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _on_play_album_clicked(self):
        self.track_play_requested.emit(self.tracks[0] if self.tracks else {}, self.album_data, self.tracks)

    def _on_track_clicked(self, track: Dict[str, Any]):
        self.track_play_requested.emit(track, self.album_data, self.tracks)

    def _on_track_started(self, track: Dict[str, Any], album_data: Dict[str, Any]):
        fp = track.get("file_path")
        is_playing = self.controller.is_playing()
        for row in self.track_rows:
            is_active = (row.track.get("file_path") == fp)
            row.set_active_state(is_active, is_active and is_playing)

    def _on_state_changed(self, is_playing: bool):
        curr_fp = self.controller.current_track.get("file_path") if self.controller.current_track else None
        for row in self.track_rows:
            is_active = (row.track.get("file_path") == curr_fp)
            row.set_active_state(is_active, is_active and is_playing)

    def _on_playback_stopped(self):
        for row in self.track_rows:
            row.set_active_state(False, False)
