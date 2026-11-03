import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import malka.config as config_module
from malka.config import NO_DATA, config
from malka.db import (
    album_sort_key,
    categorize_album,
    delete_tracks_by_paths,
    delete_tracks_under_root,
    get_album_tracks,
    get_albums_by_artist,
    get_albums_by_genre,
    get_all_albums,
    get_all_artists,
    get_all_genres,
    get_connection,
    init_db,
    parse_year_int,
    set_artist_image,
    sort_albums,
    sort_artists,
    sort_genres,
)
from malka.formats import IMPORT_SOURCE_EXTS
from malka.importer import analyze_import_folder, execute_import
from malka.organizer import (
    apply_organization_plan,
    find_containing_root,
    is_album_ready_to_organize,
    is_track_organized,
    refresh_organization_flags,
)
from malka.player import PlayerController
from malka.scanner import LibraryScanner
from malka.ui.about_dialog import AboutDialog
from malka.ui.album_card import AlbumCard
from malka.ui.audio_info import request_audio_info
from malka.ui.album_detail_view import AlbumDetailView
from malka.ui.artist_card import ArtistCard
from malka.ui.breadcrumb_bar import BreadcrumbBar
from malka.ui.edit_dialog import EditAlbumDialog, EditTrackDialog
from malka.ui.file_utils import move_to_recycle_bin, open_folder, reveal_file
from malka.ui.flow_layout import FlowLayout
from malka.ui.genre_card import GenreCard
from malka.ui.image_utils import emoji_icon, get_resource_path, get_tinted_icon
from malka.ui.import_dialog import ImportDialog
from malka.ui.import_progress_dialog import ImportProgressDialog
from malka.ui.library_dialogs import RescanLibrariesDialog
from malka.ui.player_sidebar import PlayerSidebar
from malka.ui.section_header import SectionHeaderWidget
from malka.ui.organize_dialog import OrganizeDialog
from malka.ui.settings_dialog import SettingsDialog
from malka.ui.statistics_view import StatisticsView
from malka.ui.title_bar import CustomTitleBar

#: Everything the import workflow accepts when dropped on the window.
IMPORT_DROP_EXTS = IMPORT_SOURCE_EXTS | {".cue", ".m3u", ".m3u8"}


def album_page_marker(album: Dict[str, Any], sort_mode: str) -> str:
    """Short label describing where a page starts/ends under the current sort.

    * title sorting  -> first letter of the album title;
    * year sorting   -> the year (e.g. ``1970``);
    * artist/year    -> first three letters of the artist name.
    """
    if sort_mode in ("title_asc", "title_desc"):
        name = str(album.get("album", "")).strip()
        if not name:
            return "#"
        ch = name[0].upper()
        return ch if ch.isalnum() else "#"

    if sort_mode in ("year_asc", "year_desc"):
        year = str(album.get("year", "") or "").strip()
        match = re.search(r"\b(19|20)\d{2}\b", year)
        return match.group(0) if match else "#"

    # Default: artist/year sorting.
    artist = str(album.get("display_artist") or album.get("album_artist") or "").strip()
    if not artist:
        return "#"
    return artist[:3].upper()


def format_page_label(first: str, last: str) -> str:
    return first if first == last else f"{first}-{last}"


class SegmentButton(QPushButton):
    """A flat segment whose rounded fill is painted edge-to-edge inside an island."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._segment_fill = QColor(0, 0, 0, 0)
        self._segment_hover = QColor(0, 0, 0, 0)
        self._segment_radius = "none"
        self._segment_divider = QColor(0, 0, 0, 0)
        self._segment_divider_visible = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_segment_style(self, fill: str, hover: str, radius: str, divider: str, show_divider: bool):
        def _color(value: str) -> QColor:
            color = QColor(value)
            return color if color.isValid() else QColor(0, 0, 0, 0)

        self._segment_fill = _color(fill)
        self._segment_hover = _color(hover)
        self._segment_radius = radius
        self._segment_divider = _color(divider)
        self._segment_divider_visible = show_divider
        self.update()

    def _shape_path(self) -> QPainterPath:
        w, h = self.width(), self.height()
        r = 7.0
        left = self._segment_radius in ("left", "both")
        right = self._segment_radius in ("right", "both")
        path = QPainterPath()
        path.moveTo(r if left else 0, 0)
        path.lineTo(w - r if right else w, 0)
        if right:
            path.quadTo(w, 0, w, r)
            path.lineTo(w, h - r)
            path.quadTo(w, h, w - r, h)
        else:
            path.lineTo(w, h)
        path.lineTo(r if left else 0, h)
        if left:
            path.quadTo(0, h, 0, h - r)
            path.lineTo(0, r)
            path.quadTo(0, 0, r, 0)
        else:
            path.lineTo(0, 0)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = self._shape_path()
        painter.setClipPath(path)
        fill = self._segment_hover if self.underMouse() and self.isEnabled() else self._segment_fill
        if fill.alpha() > 0:
            painter.fillPath(path, fill)
        if self._segment_divider_visible:
            painter.setPen(self._segment_divider)
            painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        painter.end()
        super().paintEvent(event)


def _rounded_rect_mask(width: int, height: int, radius: int):
    """Raster mask used to clip segmented islands to their rounded corners."""
    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(0, 0, width, height, radius, radius)
    painter.end()
    return pix.mask()


class NavRowWidget(QWidget):
    """
    Navigation row widget that keeps the View Switcher (Artists | Albums | Genres)
    strictly and mathematically centered at (width - switcher_width) // 2 at all times,
    while accommodating the breadcrumb / back button on the left and Sort button on the right
    without shifting the switcher.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.breadcrumb_bar: Optional[QWidget] = None
        self.view_switcher_frame: Optional[QWidget] = None
        self.mode_island: Optional[QWidget] = None
        self.sort_button: Optional[QWidget] = None
        self.setFixedHeight(36)

    def set_widgets(
        self,
        breadcrumb_bar: QWidget,
        view_switcher_frame: QWidget,
        sort_button: Optional[QWidget] = None,
        mode_island: Optional[QWidget] = None,
    ):
        self.breadcrumb_bar = breadcrumb_bar
        self.view_switcher_frame = view_switcher_frame
        self.sort_button = sort_button
        self.mode_island = mode_island

        self.breadcrumb_bar.setParent(self)
        self.view_switcher_frame.setParent(self)
        self.breadcrumb_bar.installEventFilter(self)

        if self.sort_button:
            self.sort_button.setParent(self)
            self.sort_button.installEventFilter(self)
        if self.mode_island:
            self.mode_island.setParent(self)
            self.mode_island.installEventFilter(self)

        self.update_positions()

    def eventFilter(self, obj, event):
        if obj in (self.breadcrumb_bar, self.sort_button, self.mode_island) and event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.update_positions()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_positions()

    def update_positions(self):
        w = self.width()
        h = self.height()
        if not self.view_switcher_frame:
            return

        sw_w = 252
        sw_h = 32
        cx = (w - sw_w) // 2
        cy = (h - sw_h) // 2
        self.view_switcher_frame.setGeometry(cx, cy, sw_w, sw_h)

        if self.breadcrumb_bar and self.breadcrumb_bar.isVisible():
            max_bc_w = max(0, cx - 12)
            self.breadcrumb_bar.setGeometry(0, 0, max_bc_w, h)

        right_x = w - 4
        if self.mode_island and self.mode_island.isVisible():
            mi_w = 72
            mi_h = 32
            mi_x = right_x - mi_w
            mi_y = (h - mi_h) // 2
            self.mode_island.setGeometry(mi_x, mi_y, mi_w, mi_h)
            right_x = mi_x - 8

        if self.sort_button and self.sort_button.isVisible():
            sb_w = 34
            sb_h = 30
            sb_x = right_x - sb_w
            sb_y = (h - sb_h) // 2
            self.sort_button.setGeometry(sb_x, sb_y, sb_w, sb_h)


class _TopFade(QWidget):
    """Content fades into the window background as it scrolls under the header."""

    def __init__(self, parent=None, height: int = 44):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._color = QColor("#0e1116")
        self._strength = 0.0
        self.setFixedHeight(height)

    def set_theme(self, theme: str):
        self._color = QColor("#f6f8fa" if theme == "light" else "#0e1116")
        self.update()

    def set_strength(self, strength: float):
        """0 = fully transparent (content at the top), 1 = solid at the top edge."""
        strength = max(0.0, min(1.0, float(strength)))
        if abs(strength - self._strength) < 0.01:
            return
        self._strength = strength
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QLinearGradient

        painter = QPainter(self)
        if self._strength <= 0.0:
            return
        gradient = QLinearGradient(0, 0, 0, self.height())
        top = QColor(self._color)
        top.setAlpha(int(255 * self._strength))
        bottom = QColor(self._color)
        bottom.setAlpha(0)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(0.55, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillRect(self.rect(), gradient)
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self, check_first_launch: bool = True):
        super().__init__()
        self.setWindowTitle("Malka — Music Library Organizer")
        self.setWindowIcon(emoji_icon("🎵"))
        self.resize(1050, 750)
        self.setMinimumSize(800, 550)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setMouseTracking(True)
        self.theme: str = getattr(config, "theme", "dark")

        # Database connection & state
        init_db(config.db_path)
        self.db_conn = get_connection(config.db_path)
        self.scanner_thread: Optional[LibraryScanner] = None
        self.all_albums_cache: List[Dict[str, Any]] = []
        self.all_artists_cache: List[Dict[str, Any]] = []
        self.all_genres_cache: List[Dict[str, Any]] = []
        # Keep rendered grid widgets alive so switching Artists/Albums/Genres is
        # instant instead of destroying and re-creating hundreds of cards.
        self._view_caches: Dict[str, Dict[str, Any]] = {}
        self._data_revision: int = 0
        self._cover_queue: List[AlbumCard] = []
        self._cover_queue_index: int = 0
        self._cover_queue_token: int = 0
        self._cover_queue_active: bool = False
        self._album_build_depth: int = 0
        self._album_refresh_pending: bool = False
        self._incremental_albums: Optional[Dict[str, Any]] = None
        self._album_render_token: int = 0
        self.album_page: int = 0
        self.album_page_size: int = 300
        self._cover_scroll_timer = QTimer(self)
        self._cover_scroll_timer.setSingleShot(True)
        self._cover_scroll_timer.setInterval(30)
        self._cover_scroll_timer.timeout.connect(self._load_visible_covers)
        self.current_view: str = "albums"  # "artists", "albums", "genres", "album_detail"
        self.prev_view: str = "albums"
        self._closing: bool = False
        self._config_target = getattr(config_module, "CONFIG_FILE", None)
        self.artist_filter: Optional[str] = None
        self.genre_filter: Optional[str] = None
        self.is_stats_mode: bool = False
        self.album_sort_mode: str = getattr(config, "album_sort_mode", "artist_year")
        self.artist_sort_mode: str = getattr(config, "artist_sort_mode", "name_asc")
        self.genre_sort_mode: str = getattr(config, "genre_sort_mode", "name_asc")
        self.view_mode: str = getattr(config, "view_mode", "tiles")
        self._table_sort: Dict[str, tuple] = {}

        # Audio player controller
        self.player_controller = PlayerController(self)
        self.player_controller.error_occurred.connect(self._on_player_error)
        self.player_controller.track_started.connect(self._on_track_started_quality)
        self._track_info_path: str = ""
        self._track_info = None
        self._track_bitrates = None
        self.player_controller.playback_stopped.connect(self._on_playback_stopped)

        # Search debounce timer (150ms)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.refresh_current_view)

        # Refreshes the bottom bar once a second so the "now playing" quality
        # and bitrate stay current.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._update_status_bar_info)
        self._status_timer.start()

        self.init_ui()
        self.apply_theme(self.theme)

        # Handle first launch check
        if check_first_launch:
            QTimer.singleShot(100, self._check_first_launch)

        # Restore the previous playback session (paused, without auto-play).
        if getattr(config, "playback_state", None):
            QTimer.singleShot(250, self._restore_playback_session)

    def init_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Custom Title Bar
        self.title_bar = CustomTitleBar(self)
        root_layout.addWidget(self.title_bar)

        content_widget = QWidget()
        content_widget.setObjectName("contentWidget")
        content_widget.setMouseTracking(True)
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(16, 10, 16, 8)
        main_layout.setSpacing(12)

        # Top Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        def _toolbar_button(tooltip: str) -> QPushButton:
            button = QPushButton("")
            button.setProperty("class", "topBtn")
            button.setToolTip(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(36, 30)
            button.setIconSize(QSize(20, 20))
            return button

        self.btn_select_dir = _toolbar_button("Add Library Folder")
        self.btn_select_dir.clicked.connect(self._on_select_directory)
        top_bar.addWidget(self.btn_select_dir)

        self.btn_import = _toolbar_button("Import Album")
        self.btn_import.clicked.connect(self._on_click_import)
        top_bar.addWidget(self.btn_import)

        self.btn_rescan = _toolbar_button("Rescan Library")
        self.btn_rescan.clicked.connect(self._on_rescan_clicked)
        top_bar.addWidget(self.btn_rescan)

        self.btn_settings = _toolbar_button("Settings")
        self.btn_settings.clicked.connect(self._on_open_settings)
        top_bar.addWidget(self.btn_settings)

        self.btn_stats = _toolbar_button("Statistics")
        self.btn_stats.setObjectName("btnStats")
        self.btn_stats.setCheckable(True)
        self.btn_stats.toggled.connect(self._on_toggle_statistics)
        top_bar.addWidget(self.btn_stats)

        self.btn_about = _toolbar_button("About Malka")
        self.btn_about.clicked.connect(self._on_show_about)
        top_bar.addWidget(self.btn_about)

        top_bar.addStretch()

        # Search field
        self.search_tracks_check = QCheckBox("Search tracks")
        self.search_tracks_check.setObjectName("searchTracksCheck")
        self.search_tracks_check.setFont(QFont("Segoe UI", 9))
        self.search_tracks_check.setToolTip(
            "Search inside track titles and file names. Results are albums that contain a matching track."
        )
        self.search_tracks_check.toggled.connect(self._on_search_tracks_toggled)
        top_bar.addWidget(self.search_tracks_check)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchEdit")
        self._update_search_placeholder()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textEdited.connect(self._on_search_text_edited)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        top_bar.addWidget(self.search_edit)



        main_layout.addLayout(top_bar)

        # Navigation & View Switcher Row (single line: clickable library path on the left,
        # view switcher permanently centered, sort button on the right).
        self.breadcrumb_bar = BreadcrumbBar(content_widget)
        self.breadcrumb_bar.hide()

        # Center: Segmented View Switcher (Artists | Albums | Genres)
        self.view_switcher_frame = QFrame()
        self.view_switcher_frame.setObjectName("viewSwitcherFrame")
        self.view_switcher_frame.setFixedHeight(32)
        self.view_switcher_frame.setStyleSheet("""
            QFrame#viewSwitcherFrame {
                background-color: #1a1e24;
                border: none;
                border-radius: 7px;
            }
        """)

        self.view_switcher_frame.setFixedSize(252, 32)
        self.view_switcher_frame.setMask(_rounded_rect_mask(252, 32, 7))
        view_switcher_layout = QHBoxLayout(self.view_switcher_frame)
        view_switcher_layout.setContentsMargins(0, 0, 0, 0)
        view_switcher_layout.setSpacing(0)

        self.btn_view_artists = SegmentButton("Artists")
        self.btn_view_albums = SegmentButton("Albums")
        self.btn_view_genres = SegmentButton("Genres")

        for btn in (self.btn_view_artists, self.btn_view_albums, self.btn_view_genres):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(84, 32)

        self.btn_view_artists.clicked.connect(lambda: self.set_view("artists"))
        self.btn_view_albums.clicked.connect(lambda: self.set_view("albums"))
        self.btn_view_genres.clicked.connect(lambda: self.set_view("genres"))

        view_switcher_layout.addWidget(self.btn_view_artists)
        view_switcher_layout.addWidget(self.btn_view_albums)
        view_switcher_layout.addWidget(self.btn_view_genres)

        # Separate Tiles/Table island, placed to the left of Sort.
        self.mode_island_frame = QFrame()
        self.mode_island_frame.setObjectName("modeIsland")
        self.mode_island_frame.setFixedSize(72, 32)
        self.mode_island_frame.setMask(_rounded_rect_mask(72, 32, 7))
        mode_layout = QHBoxLayout(self.mode_island_frame)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(0)

        self.btn_mode_tiles = SegmentButton()
        self.btn_mode_table = SegmentButton()
        for _btn, _tip in (
            (self.btn_mode_tiles, "Tiles view"),
            (self.btn_mode_table, "Table view"),
        ):
            _btn.setCheckable(True)
            _btn.setAutoExclusive(True)
            _btn.setCursor(Qt.CursorShape.PointingHandCursor)
            _btn.setToolTip(_tip)
            _btn.setFixedSize(36, 32)
            _btn.setIconSize(QSize(20, 20))
            _btn.setObjectName("viewModeBtn")
            mode_layout.addWidget(_btn)
        self.btn_mode_tiles.setIcon(get_tinted_icon("tiles_view.png", 20, self.theme))
        self.btn_mode_table.setIcon(get_tinted_icon("table_view.png", 20, self.theme))
        self.btn_mode_tiles.clicked.connect(lambda: self._set_view_mode("tiles"))
        self.btn_mode_table.clicked.connect(lambda: self._set_view_mode("table"))

        # Right: Sort button (opens context menu with sorting options)
        self.btn_sort = QPushButton("")
        self.btn_sort.setObjectName("btnSort")
        self.btn_sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort.setToolTip("Sort")
        self.btn_sort.setFixedSize(34, 30)
        self.btn_sort.setIcon(get_tinted_icon("Sort_button.png", 17, self.theme))
        self.btn_sort.setIconSize(QSize(17, 17))
        self.btn_sort.clicked.connect(self._show_sort_menu)

        self.nav_row_widget = NavRowWidget(content_widget)
        self.nav_row_widget.set_widgets(
            self.breadcrumb_bar,
            self.view_switcher_frame,
            self.btn_sort,
            self.mode_island_frame,
        )
        main_layout.addWidget(self.nav_row_widget)

        self._update_view_buttons_style()

        # Center Body Area: Split horizontally into (Main Content Stack | Player Sidebar)
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)

        # Main Stack: Index 0 = Grid Scroll Area, Index 1 = Album Detail View
        self.main_stack = QStackedWidget()

        # Page 0: Catalog pages. Each view keeps its own scroll container and
        # FlowLayout, so switching between Artists/Albums/Genres never has to
        # detach and re-add thousands of album tiles.
        (
            self._albums_page,
            self._albums_scroll_area,
            self._albums_pager_header,
            self._albums_pager_layout,
        ) = self._make_catalog_page()
        (
            self._artists_page,
            self._artists_scroll_area,
            self._artists_pager_header,
            self._artists_pager_layout,
        ) = self._make_catalog_page()
        (
            self._genres_page,
            self._genres_scroll_area,
            self._genres_pager_header,
            self._genres_pager_layout,
        ) = self._make_catalog_page()

        self._albums_container_widget = self._albums_scroll_area.widget()
        self._artists_container_widget = self._artists_scroll_area.widget()
        self._genres_container_widget = self._genres_scroll_area.widget()
        self._albums_flow_layout = self._albums_container_widget.layout()
        self._artists_flow_layout = self._artists_container_widget.layout()
        self._genres_flow_layout = self._genres_container_widget.layout()
        self._albums_table = self._albums_page._catalog_table
        self._artists_table = self._artists_page._catalog_table
        self._genres_table = self._genres_page._catalog_table
        for _table in (self._albums_table, self._artists_table, self._genres_table):
            _table.horizontalHeader().sectionClicked.connect(self._on_table_header_clicked)
            _table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
            _table.cellClicked.connect(self._on_table_cell_clicked)
            _table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            _table.customContextMenuRequested.connect(
                lambda pos, t=_table: self._on_table_context_menu(t, pos)
            )

        self.catalog_stack = QStackedWidget()
        self.catalog_stack.addWidget(self._albums_page)
        self.catalog_stack.addWidget(self._artists_page)
        self.catalog_stack.addWidget(self._genres_page)
        self.catalog_stack.setCurrentWidget(self._albums_page)
        for _sa in (self._albums_scroll_area, self._artists_scroll_area, self._genres_scroll_area):
            _sa.verticalScrollBar().valueChanged.connect(self._schedule_visible_covers)
            _sa.viewport().installEventFilter(self)
        self.main_stack.addWidget(self.catalog_stack)

        # Page 1: Album Detail View
        self.album_detail_view = AlbumDetailView(self.player_controller, self.db_conn)
        self.album_detail_view.track_play_requested.connect(self._on_track_play_requested)
        self.album_detail_view.artist_clicked.connect(self._go_to_artist)
        self.album_detail_view.genre_clicked.connect(self._go_to_genre)
        self.album_detail_view.year_clicked.connect(self._search_year)
        self.album_detail_view.track_location_requested.connect(self._on_track_location_requested)
        self.album_detail_view.track_edit_requested.connect(self._on_edit_track)
        self.album_detail_view.track_remove_requested.connect(self._on_remove_track)
        self.main_stack.addWidget(self.album_detail_view)

        # Page 2: Statistics View
        self.statistics_view = StatisticsView(self.db_conn, theme=self.theme)
        self.statistics_view.artist_selected.connect(self._on_stat_artist_selected)
        self.statistics_view.album_selected.connect(self._on_stat_album_selected)
        self.statistics_view.genre_selected.connect(self._on_stat_genre_selected)
        self.main_stack.addWidget(self.statistics_view)

        # Albums/artists/genres/album page scroll under a fade instead of being
        # clipped by a hard edge below the navigation.
        self._scroll_fades = {}
        for viewport in (
            self._albums_scroll_area.viewport(),
            self._artists_scroll_area.viewport(),
            self._genres_scroll_area.viewport(),
            self.album_detail_view.scroll_area.viewport(),
        ):
            fade = _TopFade(viewport)
            fade.setGeometry(0, 0, viewport.width(), fade.height())
            fade.raise_()
            fade.show()
            self._scroll_fades[viewport] = fade
            viewport.installEventFilter(self)

        def _bind_scroll(scroll_area, fade):
            bar = scroll_area.verticalScrollBar()
            bar.valueChanged.connect(lambda value, f=fade: self._update_top_fade(f, value))
            self._update_top_fade(fade, bar.value())

        _bind_scroll(self._albums_scroll_area, self._scroll_fades[self._albums_scroll_area.viewport()])
        _bind_scroll(self._artists_scroll_area, self._scroll_fades[self._artists_scroll_area.viewport()])
        _bind_scroll(self._genres_scroll_area, self._scroll_fades[self._genres_scroll_area.viewport()])
        _bind_scroll(self.album_detail_view.scroll_area, self._scroll_fades[self.album_detail_view.scroll_area.viewport()])

        body_layout.addWidget(self.main_stack, 1)

        # Persistent Player Sidebar on the right (hidden until playback starts)
        self.player_sidebar = PlayerSidebar(self.player_controller)
        self.player_sidebar.artist_clicked.connect(self._on_sidebar_artist_clicked)
        self.player_sidebar.album_clicked.connect(self._on_sidebar_album_clicked)
        self.player_sidebar.hide()
        body_layout.addWidget(self.player_sidebar)

        main_layout.addLayout(body_layout, 1)
        root_layout.addWidget(content_widget, 1)

        # Enable Drag-and-Drop
        self.setAcceptDrops(True)

        # Empty state message labels (one per catalog page)
        self.empty_label = QLabel(self._albums_container_widget)
        self._artists_empty_label = QLabel(self._artists_container_widget)
        self._genres_empty_label = QLabel(self._genres_container_widget)
        for lbl in (self.empty_label, self._artists_empty_label, self._genres_empty_label):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet("color: #666666; padding: 40px;")
            lbl.setText("Music library is empty. Select a library folder or drag and drop an album folder here to import.")
            lbl.hide()

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_info_label = QLabel("Ready")
        self.status_info_label.setStyleSheet("color: #aaaaaa; margin-left: 8px;")
        self.status_bar.addWidget(self.status_info_label, 1)

        self.scan_status_label = QLabel("")
        self.scan_status_label.setStyleSheet("color: #888888; margin-right: 8px;")
        self.status_bar.addPermanentWidget(self.scan_status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self._apply_view_mode_visibility()

    def _check_first_launch(self):
        if getattr(self, "_closing", False):
            return
        try:
            self.db_conn.execute("SELECT 1")
        except Exception:
            return
        existing = [p for p in config.library_paths if Path(p).exists()]
        if not existing:
            msg = QMessageBox(self)
            msg.setWindowTitle("Welcome to Malka")
            msg.setText("Please select your music library folder to get started.")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            self._on_select_directory()
        else:
            try:
                refresh_organization_flags(
                    self.db_conn,
                    list(config.library_paths),
                    config.track_naming_format,
                )
            except Exception:
                pass
            self.refresh_library_view()
            if not self.all_albums_cache:
                self.start_scanning(force=False)

    def _make_catalog_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        header = QWidget(page)
        header.setObjectName("catalogPager")
        header.hide()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 10, 8, 10)
        header_layout.setSpacing(6)
        header_layout.addStretch(1)
        header_layout.addStretch(1)
        page_layout.addWidget(header)

        scroll = QScrollArea()
        # The flow layout computes its own height; letting QScrollArea resize
        # the widget as well creates a width/height feedback loop on big grids.
        scroll.setWidgetResizable(False)
        scroll.setAcceptDrops(False)
        container = QWidget()
        container.setObjectName("scrollContainer")
        container.setAcceptDrops(False)
        layout = FlowLayout(container, margin=10, h_spacing=18, v_spacing=18)
        container.setLayout(layout)
        scroll.setWidget(container)

        table = QTableWidget(page)
        table.setObjectName("catalogTable")
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setSectionsClickable(True)
        table.hide()

        page_layout.addWidget(scroll, 1)
        page_layout.addWidget(table, 1)
        page._catalog_table = table
        return page, scroll, header, header_layout

    def _catalog_page_index(self, view_name: Optional[str] = None) -> int:
        view = view_name or self.current_view
        if view == "artists":
            return 1
        if view == "genres":
            return 2
        return 0

    @property
    def flow_layout(self) -> FlowLayout:
        if self.current_view == "artists":
            return self._artists_flow_layout
        if self.current_view == "genres":
            return self._genres_flow_layout
        return self._albums_flow_layout

    @property
    def container_widget(self) -> QWidget:
        if self.current_view == "artists":
            return self._artists_container_widget
        if self.current_view == "genres":
            return self._genres_container_widget
        return self._albums_container_widget

    @property
    def scroll_area(self) -> QScrollArea:
        if self.current_view == "artists":
            return self._artists_scroll_area
        if self.current_view == "genres":
            return self._genres_scroll_area
        return self._albums_scroll_area

    def _active_empty_label(self) -> QLabel:
        if self.current_view == "artists":
            return self._artists_empty_label
        if self.current_view == "genres":
            return self._genres_empty_label
        return self.empty_label

    def _set_catalog_page(self, view_name: str):
        self.catalog_stack.setCurrentIndex(self._catalog_page_index(view_name))

    def _restore_playback_session(self):
        if getattr(self, "_closing", False):
            return
        state = getattr(config, "playback_state", None)
        if not isinstance(state, dict):
            return
        try:
            restored = self.player_controller.restore_playback_state(state)
        except Exception:
            restored = False
        if restored:
            self.player_sidebar.show()
        else:
            config.playback_state = None

    def _on_select_directory(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Add Music Library Folder",
            config.library_path or str(Path.home()),
        )
        if directory:
            added = config.add_library_path(directory)
            config.save()
            if added:
                self.status_info_label.setText(f"Added library folder: {directory}")
                # Only scan the newly added root; the other libraries stay untouched.
                self.start_scanning(force=False, paths=[directory], delete_scope=[directory])

    def _on_show_about(self):
        dlg = AboutDialog(self, theme=self.theme)
        dlg.exec()

    def _on_open_settings(self):
        dlg = SettingsDialog(self)
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.libraries_added.connect(self._on_libraries_added)
        dlg.libraries_removed.connect(self._on_libraries_removed)
        dlg.exec()

    def _on_settings_saved(self):
        self.apply_theme(getattr(config, "theme", "dark"))
        self.update_scrollbars()
        self.refresh_library_view()

    def _on_libraries_added(self, paths):
        if paths:
            self.start_scanning(force=False, paths=list(paths), delete_scope=list(paths))

    def _on_libraries_removed(self, items):
        cover_candidates: set[str] = set()
        for path, delete_cache in items:
            try:
                root = Path(path).expanduser().resolve()
                rows = self.db_conn.execute("SELECT file_path, cover_cache_path FROM tracks").fetchall()
                for row in rows:
                    try:
                        Path(row["file_path"]).resolve().relative_to(root)
                    except Exception:
                        continue
                    if row["cover_cache_path"]:
                        cover_candidates.add(row["cover_cache_path"])
            except Exception:
                pass
            delete_tracks_under_root(self.db_conn, path)
            if delete_cache and cover_candidates:
                remaining = {
                    row["cover_cache_path"]
                    for row in self.db_conn.execute(
                        "SELECT cover_cache_path FROM tracks WHERE cover_cache_path IS NOT NULL"
                    ).fetchall()
                    if row["cover_cache_path"]
                }
                cache_root = Path(getattr(config_module, "CACHE_DIR", ""))
                for cover in cover_candidates - remaining:
                    try:
                        cover_path = Path(cover)
                        cover_path.relative_to(cache_root)
                        cover_path.unlink(missing_ok=True)
                    except Exception:
                        continue
                cover_candidates.clear()
        self.refresh_library_view()

    def update_scrollbars(self):
        show = getattr(config, "show_scrollbars", True)
        policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if show else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        for sa in (self._albums_scroll_area, self._artists_scroll_area, self._genres_scroll_area):
            sa.setVerticalScrollBarPolicy(policy)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if hasattr(self, "album_detail_view") and hasattr(self.album_detail_view, "update_scrollbars"):
            self.album_detail_view.update_scrollbars()
        if hasattr(self, "statistics_view") and hasattr(self.statistics_view, "update_scrollbars"):
            self.statistics_view.update_scrollbars()

    def _on_rescan_clicked(self):
        paths = list(getattr(config, "library_paths", []))
        if not paths:
            QMessageBox.warning(self, "Warning", "Please select a valid library folder first.")
            return
        if len(paths) == 1:
            self.start_scanning(force=True, paths=paths, delete_scope=paths)
            return
        dialog = RescanLibrariesDialog(paths, self)
        if dialog.exec():
            selected = dialog.selected_paths()
            if selected:
                self.start_scanning(force=True, paths=selected, delete_scope=selected)

    def start_scanning(self, force: bool = False, paths=None, delete_scope=None):
        scan_paths = list(paths) if paths is not None else list(config.library_paths)
        existing_roots = [p for p in scan_paths if Path(p).exists()]
        if not existing_roots:
            QMessageBox.warning(self, "Warning", "Please select a valid library folder first.")
            return

        if self.scanner_thread and self.scanner_thread.isRunning():
            return

        self.btn_rescan.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.scan_status_label.setText("Preparing to scan...")

        self.scanner_thread = LibraryScanner(
            scan_paths,
            config.db_path,
            force_rescan=force,
            naming_format=config.track_naming_format,
            delete_scope=delete_scope if delete_scope is not None else scan_paths,
        )
        self.scanner_thread.progress.connect(self._on_scan_progress)
        self.scanner_thread.status_text.connect(self._on_scan_status_text)
        self.scanner_thread.finished_scan.connect(self._on_scan_finished)
        self.scanner_thread.error.connect(self._on_scan_error)
        self.scanner_thread.start()

    def _on_scan_progress(self, current: int, total: int, filename: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        disp_name = filename if len(filename) < 30 else filename[:27] + "..."
        self.scan_status_label.setText(f"{current}/{total}: {disp_name}")

    def _on_scan_status_text(self, text: str):
        self.scan_status_label.setText(text)

    def _on_scan_finished(self, total: int, deleted: int):
        self.progress_bar.setVisible(False)
        self.scan_status_label.setText(f"Scan completed: {total} files")
        self.btn_rescan.setEnabled(True)
        self.refresh_library_view()

    def _on_scan_error(self, err_msg: str):
        self.progress_bar.setVisible(False)
        self.btn_rescan.setEnabled(True)
        QMessageBox.critical(self, "Scan Error", err_msg)

    def set_view(self, view_name: str):
        if view_name not in ("artists", "albums", "genres"):
            return
        if getattr(self, "search_tracks_check", None) and self.search_tracks_check.isChecked() and view_name != "albums":
            return
        self.current_view = view_name
        self.prev_view = view_name
        if hasattr(self, "album_page"):
            self.album_page = 0
        self.artist_filter = None
        self.genre_filter = None
        self._update_view_buttons_style()

        if getattr(self, "is_stats_mode", False):
            if hasattr(self, "btn_sort"):
                self.btn_sort.hide()
            if hasattr(self, "breadcrumb_bar"):
                self.breadcrumb_bar.hide()
            if hasattr(self, "statistics_view"):
                self.main_stack.setCurrentWidget(self.statistics_view)
                self.statistics_view.set_category(view_name)
            return

        if hasattr(self, "main_stack") and self.main_stack.currentIndex() != 0:
            self.main_stack.setCurrentIndex(0)
        if hasattr(self, "catalog_stack"):
            self._set_catalog_page(view_name)
        if hasattr(self, "btn_mode_tiles"):
            self._apply_view_mode_visibility()
        if hasattr(self, "btn_sort"):
            self.btn_sort.setVisible(self.view_mode != "table" and not self.is_stats_mode)

        self._update_search_placeholder()
        self._update_breadcrumb()
        self.refresh_current_view()

    def _on_toggle_statistics(self, checked: bool):
        self.is_stats_mode = checked
        if checked:
            if hasattr(self, "btn_sort"):
                self.btn_sort.hide()
            if hasattr(self, "breadcrumb_bar"):
                self.breadcrumb_bar.hide()
            if hasattr(self, "mode_island_frame"):
                self.mode_island_frame.hide()
            self.main_stack.setCurrentWidget(self.statistics_view)
            self.statistics_view.set_category(self.current_view if self.current_view in ("artists", "albums", "genres") else "albums")
        else:
            if hasattr(self, "mode_island_frame"):
                self.mode_island_frame.show()
            if hasattr(self, "btn_sort"):
                self.btn_sort.setVisible(self.current_view == "albums" and not self.artist_filter and not self.genre_filter)
            if self.current_view == "album_detail":
                self.main_stack.setCurrentWidget(self.album_detail_view)
            else:
                self._set_catalog_page(self.current_view)
                self.main_stack.setCurrentWidget(self.catalog_stack)
            self._update_breadcrumb()
            if self.current_view != "album_detail":
                self.refresh_current_view()
                self._update_status_bar_info()

    def _on_stat_artist_selected(self, artist_name: str):
        self.btn_stats.setChecked(False)
        self.set_view("artists")
        self._on_artist_clicked(artist_name)

    def _on_stat_album_selected(self, album_name: str, album_artist: str):
        self.btn_stats.setChecked(False)
        target_alb = album_name.strip().lower()
        target_art = album_artist.strip().lower()
        match = next(
            (a for a in self.all_albums_cache 
             if a["album"].strip().lower() == target_alb and 
                (not target_art or a["album_artist"].strip().lower() == target_art or a.get("display_artist", "").strip().lower() == target_art)),
            None
        )
        if match:
            self._on_album_clicked(match)
        else:
            album_data = {
                "album": album_name,
                "album_artist": album_artist,
                "display_artist": album_artist,
            }
            self._on_album_clicked(album_data)

    def _on_stat_genre_selected(self, genre_name: str):
        self.btn_stats.setChecked(False)
        self.set_view("genres")
        self._on_genre_clicked(genre_name)

    def _update_view_buttons_style(self):
        is_light = getattr(self, "theme", "dark") == "light"
        fill = "#ffffff" if is_light else "#0b0d10"
        active_text = "#1f2328" if is_light else "#ffffff"
        inactive_text = "#656d76" if is_light else "#8b949e"
        hover = "rgba(0,0,0,0.05)" if is_light else "rgba(255,255,255,0.08)"
        disabled_text = "#4b5563" if is_light else "#6e7681"
        divider = "rgba(127,127,127,0.28)"
        track_search = bool(
            getattr(self, "search_tracks_check", None) and self.search_tracks_check.isChecked()
        )

        segments = (
            (self.btn_view_artists, "artists", "left"),
            (self.btn_view_albums, "albums", "none"),
            (self.btn_view_genres, "genres", "right"),
        )
        for index, (button, view, radius) in enumerate(segments):
            if button is None:
                continue
            active = self.current_view == view
            disabled = track_search and view != "albums"
            text_color = disabled_text if disabled else (active_text if active else inactive_text)
            weight = 600 if active and not disabled else 500
            button.setStyleSheet(
                "QPushButton {"
                f" background:transparent; color:{text_color};"
                f" font-weight:{weight}; font-size:8.5pt; padding:0px;"
                " border: none; min-height:32px; max-height:32px;"
                "}"
            )
            segment_fill = fill if active and not disabled else "transparent"
            segment_hover = (
                hover if not active and not disabled else "transparent"
            )
            button.set_segment_style(
                segment_fill, segment_hover, radius, divider, index < 2
            )

    # ------------------------------------------------------------------
    # Breadcrumb navigation
    # ------------------------------------------------------------------
    def _go_all_albums(self):
        self.set_view("albums")

    def _go_to_artist(self, artist_name: str):
        if not artist_name:
            return
        if getattr(self, "is_stats_mode", False):
            self.btn_stats.setChecked(False)
        self.current_view = "albums"
        self.prev_view = "albums"
        self.album_page = 0
        self.artist_filter = artist_name
        self.genre_filter = None
        self.main_stack.setCurrentIndex(0)
        self._set_catalog_page("albums")
        if hasattr(self, "btn_sort"):
            self.btn_sort.show()
        self._update_view_buttons_style()
        self._update_search_placeholder()
        self._update_breadcrumb()
        self.refresh_current_view()

    def _search_year(self, year: str):
        """Shows all albums of a given year by filling the search box."""
        year = (year or "").strip()
        if not year:
            return
        if getattr(self, "is_stats_mode", False):
            self.btn_stats.setChecked(False)
        self.current_view = "albums"
        self.prev_view = "albums"
        self.album_page = 0
        self.artist_filter = None
        self.genre_filter = None
        self.main_stack.setCurrentIndex(0)
        self._set_catalog_page("albums")
        if hasattr(self, "btn_sort"):
            self.btn_sort.show()
        self._update_view_buttons_style()
        self.search_edit.setText(year)
        self._update_breadcrumb()
        self.refresh_current_view()

    def _go_to_genre(self, genre_name: str):
        if not genre_name:
            return
        if getattr(self, "is_stats_mode", False):
            self.btn_stats.setChecked(False)
        self.current_view = "albums"
        self.prev_view = "albums"
        self.album_page = 0
        self.genre_filter = genre_name
        self.artist_filter = None
        self.main_stack.setCurrentIndex(0)
        self._set_catalog_page("albums")
        if hasattr(self, "btn_sort"):
            self.btn_sort.show()
        self._update_view_buttons_style()
        self._update_search_placeholder()
        self._update_breadcrumb()
        self.refresh_current_view()

    def _album_artist_for_breadcrumb(self) -> str:
        if self.current_view != "album_detail":
            return ""
        if hasattr(self, "album_detail_view"):
            data = self.album_detail_view.album_data or {}
            artist = (data.get("display_artist") or data.get("album_artist") or "").strip()
            if artist and artist != NO_DATA:
                return artist
        if self.artist_filter:
            return self.artist_filter
        return ""

    def _album_title_for_breadcrumb(self) -> str:
        if self.current_view != "album_detail":
            return ""
        if hasattr(self, "album_detail_view"):
            data = self.album_detail_view.album_data or {}
            title = (data.get("album") or "").strip()
            if title and title != NO_DATA:
                return title
        return ""

    def _update_breadcrumb(self):
        """
        Builds the clickable library path shown left of the view switcher:
        ``All albums / Artist / Album /``.
        """
        if not hasattr(self, "breadcrumb_bar"):
            return

        if getattr(self, "is_stats_mode", False):
            self.breadcrumb_bar.hide()
            return

        segments = []
        if self.current_view == "album_detail":
            segments.append(("All albums", self._go_all_albums))
            artist = self._album_artist_for_breadcrumb()
            if artist:
                segments.append((artist, lambda name=artist: self._go_to_artist(name)))
            title = self._album_title_for_breadcrumb()
            if title:
                segments.append((title, None))
        elif self.current_view == "albums" and self.artist_filter:
            segments.append(("All albums", self._go_all_albums))
            segments.append((self.artist_filter, None))
        elif self.current_view == "albums" and self.genre_filter:
            segments.append(("All albums", self._go_all_albums))
            segments.append((self.genre_filter, None))

        if not segments:
            self.breadcrumb_bar.hide()
            return

        self.breadcrumb_bar.set_path(segments)
        self.breadcrumb_bar.show()
        if hasattr(self, "nav_row_widget"):
            self.nav_row_widget.update_positions()

    def _on_back_clicked(self):
        """Programmatic "go up one level" (keyboard/backward-compatible helper)."""
        if self.current_view == "album_detail":
            artist = self._album_artist_for_breadcrumb()
            if artist:
                self._go_to_artist(artist)
            else:
                self._go_all_albums()
            return
        if self.artist_filter:
            self._go_all_albums()
        elif self.genre_filter:
            self._go_all_albums()
        else:
            self.set_view("albums")

    def _on_album_clicked(self, album_data: Dict[str, Any]):
        if self.current_view != "album_detail":
            self.prev_view = self.current_view
        self.current_view = "album_detail"
        if hasattr(self, "btn_sort"):
            self.btn_sort.hide()
        self._update_view_buttons_style()

        self.album_detail_view.set_album(album_data)
        self.main_stack.setCurrentIndex(1)

        alb_artist = (album_data.get("display_artist") or album_data.get("album_artist", "")).strip()
        alb_genre = (album_data.get("genre") or "").strip()

        if alb_artist and alb_artist != NO_DATA:
            self.artist_filter = alb_artist
        else:
            self.artist_filter = None
        if self.genre_filter:
            if not (alb_genre and alb_genre.lower() == self.genre_filter.lower()):
                self.genre_filter = None

        self._update_breadcrumb()

    def _on_track_play_requested(self, track: Dict[str, Any], album_data: Dict[str, Any], all_tracks: List[Dict[str, Any]]):
        if track and track.get("file_path"):
            ok = self.player_controller.play_track(track, album_data, all_tracks)
        else:
            ok = self.player_controller.play_album(album_data, all_tracks)

        if ok:
            self.player_sidebar.show()

    def _on_player_error(self, message: str):
        self.status_bar.showMessage(f"Playback Notice: {message}", 5000)

    def _on_playback_stopped(self):
        if getattr(self, "_closing", False):
            return
        # Stop was explicit (or the album ended): do not restore this session
        # on the next launch.  Persist the removal only when the config target
        # is still the one this window was created with.
        config.playback_state = None
        try:
            current_target = getattr(config_module, "CONFIG_FILE", None)
            if current_target == getattr(self, "_config_target", current_target):
                config.save_runtime_state()
        except Exception:
            pass

    def _on_sidebar_artist_clicked(self, artist_name: str):
        if not artist_name:
            return
        if hasattr(self, "main_stack") and self.main_stack.currentIndex() != 0:
            self.main_stack.setCurrentIndex(0)
        self._on_artist_clicked(artist_name)

    def _on_sidebar_album_clicked(self, album_data: Dict[str, Any], album_name: str, album_artist: str):
        if not album_data or not album_data.get("album"):
            if not album_name:
                return
            match = None
            for a in self.all_albums_cache:
                if a.get("album", "").strip().lower() == album_name.strip().lower():
                    if not album_artist or a.get("album_artist", "").strip().lower() == album_artist.strip().lower():
                        match = a
                        break
                    if match is None:
                        match = a
            album_data = match

        if not album_data:
            return

        alb_artist = (album_data.get("display_artist") or album_data.get("album_artist", "")).strip()
        if self.artist_filter and alb_artist:
            self.artist_filter = alb_artist
        elif self.artist_filter and not alb_artist:
            self.artist_filter = None

        if self.genre_filter:
            alb_genre = (album_data.get("genre") or "").strip()
            if alb_genre.lower() != self.genre_filter.lower():
                self.genre_filter = None

        self._on_album_clicked(album_data)

    def _on_artist_clicked(self, artist_name: str):
        self.artist_filter = artist_name
        self.genre_filter = None
        self.current_view = "albums"
        self.prev_view = "artists"
        self.album_page = 0
        if hasattr(self, "main_stack"):
            self.main_stack.setCurrentIndex(0)
        if hasattr(self, "catalog_stack"):
            self._set_catalog_page("albums")
        if hasattr(self, "btn_sort"):
            self.btn_sort.show()
        self._update_view_buttons_style()
        self._update_breadcrumb()
        self.refresh_current_view()

    def _on_artist_image_updated(self, artist_name: str, new_path: str):
        # Keep the in-memory artist cache in sync. Without this, navigating away
        # from the Artists view and back re-rendered a stale entry (no image)
        # until the application was restarted.
        cache = getattr(self, "all_artists_cache", None)
        if cache is None:
            return
        for artist in cache:
            if artist.get("name") == artist_name:
                artist["image_path"] = new_path
                break
        if getattr(self, "is_stats_mode", False) and hasattr(self, "statistics_view"):
            self.statistics_view.refresh_current()

    def _on_genre_clicked(self, genre_name: str):
        self.genre_filter = genre_name
        self.artist_filter = None
        self.current_view = "albums"
        self.prev_view = "genres"
        self.album_page = 0
        if hasattr(self, "main_stack"):
            self.main_stack.setCurrentIndex(0)
        if hasattr(self, "catalog_stack"):
            self._set_catalog_page("albums")
        if hasattr(self, "btn_sort"):
            self.btn_sort.show()
        self._update_view_buttons_style()
        self._update_breadcrumb()
        self.refresh_current_view()

    def refresh_library_view(self):
        # Data changed: drop rendered views and rebuild lazily on next activation.
        self._data_revision += 1
        self._invalidate_view_caches()
        # Reload albums, artists, genres from DB
        self.all_albums_cache = get_all_albums(self.db_conn)
        self.all_artists_cache = get_all_artists(self.db_conn)
        self.all_genres_cache = get_all_genres(self.db_conn)
        if hasattr(self, "statistics_view"):
            self.statistics_view.invalidate_cache()
        if getattr(self, "is_stats_mode", False) and hasattr(self, "statistics_view"):
            self.statistics_view.refresh_current()
        self.refresh_current_view()
        self._update_status_bar_info()
        # Load artist photos into the RAM thumbnail cache in the background so
        # the first Artists navigation is already warm.
        QTimer.singleShot(250, self._prewarm_artist_thumbnails)

    def _prewarm_artist_thumbnails(self):
        if getattr(self, "_closing", False):
            return
        from malka.ui.image_utils import request_async_square_pixmap
        for artist in getattr(self, "all_artists_cache", []):
            image_path = artist.get("image_path")
            if image_path:
                request_async_square_pixmap(
                    image_path,
                    size=170,
                    radius_top=8,
                    callback=lambda *_: None,
                )

    def _library_display_text(self) -> str:
        paths = list(getattr(config, "library_paths", []))
        if not paths:
            return "Not selected"
        if len(paths) == 1:
            return paths[0]
        return f"{paths[0]} (+{len(paths) - 1} more)"

    def _on_track_started_quality(self, track, album_data):
        """Load stream info + per-second bitrate profile for the new track."""
        file_path = (track or {}).get("file_path", "")
        self._track_info_path = file_path
        self._track_info = None
        self._track_bitrates = None
        if not file_path:
            return

        def _ready(path, info, profile):
            if path != self._track_info_path:
                return
            self._track_info = info
            self._track_bitrates = profile
            self._update_status_bar_info()

        request_audio_info(file_path, _ready)

    def _current_track_bitrate(self) -> int:
        from malka.bitrate import bitrate_at

        info = self._track_info or {}
        return bitrate_at(
            self._track_bitrates,
            int(info.get("bitrate") or 0),
            int(self.player_controller.position_ms()),
        )

    def _now_playing_text(self) -> str:
        """Sample rate / bit depth / bitrate of the second being played."""
        track = getattr(self.player_controller, "current_track", None)
        info = self._track_info
        if not track or not info:
            return ""

        parts = []
        sample_rate = int(info.get("sample_rate") or 0)
        bit_depth = int(info.get("bits_per_sample") or 0)
        channels = int(info.get("channels") or 0)
        if sample_rate:
            parts.append(f"{sample_rate / 1000:g} kHz")
        if bit_depth:
            parts.append(f"{bit_depth}-bit")
        if channels:
            parts.append(f"{channels} ch")
        bitrate = self._current_track_bitrate()
        if bitrate:
            parts.append(f"≈{bitrate} kbps")
        return f"  |  ♪ {' · '.join(parts)}" if parts else ""

    def _update_status_bar_info(self):
        total_albums = len(self.all_albums_cache)
        total_tracks = sum(a.get("track_count", 0) for a in self.all_albums_cache)
        self.status_info_label.setText(
            f"Albums: {total_albums}  |  Tracks: {total_tracks}" + self._now_playing_text()
        )

    def _on_search_text_edited(self, text: str):
        self.album_page = 0
        if hasattr(self, "scroll_area"):
            self.scroll_area.verticalScrollBar().setValue(0)
        if hasattr(self, "search_timer"):
            self.search_timer.start()

    def _on_search_text_changed(self, text: str):
        if getattr(self, "search_tracks_check", None) and self.search_tracks_check.isChecked() and text.strip():
            self._prepare_track_search_mode()
        if not text:
            self.album_page = 0
            if hasattr(self, "search_timer"):
                self.search_timer.stop()
            self.refresh_current_view()
        elif hasattr(self, "search_timer") and not self.search_timer.isActive():
            self.refresh_current_view()

    def _prepare_track_search_mode(self):
        """Track search is albums-only and tiles-only, without re-rendering."""
        if self.current_view != "albums" or self.artist_filter or self.genre_filter:
            self.current_view = "albums"
            self.artist_filter = None
            self.genre_filter = None
            self.prev_view = "albums"
            if hasattr(self, "main_stack"):
                self.main_stack.setCurrentIndex(0)
            if hasattr(self, "catalog_stack"):
                self._set_catalog_page("albums")
            self._update_view_buttons_style()
        if self.view_mode != "tiles":
            self.view_mode = "tiles"
            config.view_mode = "tiles"
            config.save()
            self._apply_view_mode_visibility()

    def _update_search_placeholder(self):
        if getattr(self, "search_tracks_check", None) and self.search_tracks_check.isChecked():
            self.search_edit.setPlaceholderText("🔍 Search inside track titles and file names.")
        elif self.current_view == "artists":
            self.search_edit.setPlaceholderText("🔍 Search artists...")
        elif self.current_view == "genres":
            self.search_edit.setPlaceholderText("🔍 Search genres...")
        else:
            self.search_edit.setPlaceholderText("🔍 Search by album, artist, year...")

    def _track_search_active(self, query: Optional[str] = None) -> bool:
        if not getattr(self, "search_tracks_check", None) or not self.search_tracks_check.isChecked():
            return False
        text = (query if query is not None else self.search_edit.text()).strip()
        return len(text) >= 2

    def _update_track_search_navigation(self):
        enabled = not self.search_tracks_check.isChecked()
        if hasattr(self, "btn_view_artists"):
            self.btn_view_artists.setEnabled(enabled)
            self.btn_view_genres.setEnabled(enabled)
            if hasattr(self, "btn_view_albums"):
                self._update_view_buttons_style()

    def _on_search_tracks_toggled(self, checked: bool):
        self._update_track_search_navigation()
        self._update_search_placeholder()
        query = self.search_edit.text().strip()
        # Toggling the mode with an empty search box changes only the box
        # placeholder and navigation state. Re-rendering the library here
        # would produce a pointless visible flicker.
        if not query:
            return
        self.album_page = 0
        self._invalidate_view_caches()
        if checked:
            self._prepare_track_search_mode()
        self.refresh_current_view()

    def _set_view_mode(self, mode: str):
        if mode not in ("tiles", "table"):
            return
        if mode == "table" and self._track_search_active():
            if hasattr(self, "btn_mode_tiles"):
                self.btn_mode_tiles.setChecked(True)
            QMessageBox.information(
                self, "Track search",
                "Track search results are shown as tiles only. Turn off “Search tracks” to use the table view.",
            )
            return
        self.view_mode = mode
        config.view_mode = mode
        config.save()
        self._apply_view_mode_visibility()
        self.refresh_current_view()

    def _toggle_view_mode(self):
        self._set_view_mode("table" if self.view_mode == "tiles" else "tiles")

    def _apply_view_mode_visibility(self):
        table_mode = self.view_mode == "table" and not self._track_search_active()
        for page, scroll, table in (
            (self._albums_page, self._albums_scroll_area, self._albums_table),
            (self._artists_page, self._artists_scroll_area, self._artists_table),
            (self._genres_page, self._genres_scroll_area, self._genres_table),
        ):
            scroll.setVisible(not table_mode)
            table.setVisible(table_mode)
        if hasattr(self, "btn_mode_tiles"):
            self.btn_mode_tiles.setChecked(not table_mode)
            self.btn_mode_table.setChecked(table_mode)
            is_light = getattr(self, "theme", "dark") == "light"
            active_color = (0, 0, 0) if is_light else (255, 255, 255)
            fill = "#ffffff" if is_light else "#0b0d10"
            hover = "rgba(0,0,0,0.06)" if is_light else "rgba(255,255,255,0.08)"
            mode_qss = "QPushButton { background:transparent; border:none; padding:0px; }"
            self.btn_mode_tiles.setStyleSheet(mode_qss)
            self.btn_mode_table.setStyleSheet(mode_qss)
            self.btn_mode_tiles.set_segment_style(
                fill if not table_mode else "transparent",
                hover if table_mode else "transparent",
                "left",
                "rgba(127,127,127,0.28)",
                True,
            )
            self.btn_mode_table.set_segment_style(
                fill if table_mode else "transparent",
                hover if not table_mode else "transparent",
                "right",
                "rgba(127,127,127,0.28)",
                False,
            )
            self.btn_mode_tiles.setIcon(get_tinted_icon(
                "tiles_view.png", 20, self.theme, active_color if not table_mode else None
            ))
            self.btn_mode_table.setIcon(get_tinted_icon(
                "table_view.png", 20, self.theme, active_color if table_mode else None
            ))
        if hasattr(self, "btn_sort"):
            self.btn_sort.setVisible(not table_mode and not self.is_stats_mode)
        if table_mode:
            for header in (self._albums_pager_header, self._artists_pager_header, self._genres_pager_header):
                header.hide()
        else:
            self.container_widget.show()
            if self._albums_pager_layout.count() > 2:
                self._albums_pager_header.show()

    def _render_catalog_table(self, query: str = ""):
        self._empty_state_active = False
        self._cancel_incremental_album_render()
        self._apply_view_mode_visibility()
        view = self.current_view
        table = self._table_for_view(view)
        if table is None:
            return
        table.setUpdatesEnabled(False)
        try:
            table.clear()
            table.clearSpans()
            table.setSortingEnabled(False)
            if view == "albums":
                headers = ["Album", "Artist", "Year", "Tracks"]
                rows = self._table_album_rows(query)
                key_fn = lambda r, c: (
                    str(r.get("album", "")).casefold() if c == 0 else
                    str(r.get("display_artist") or r.get("album_artist", "")).casefold() if c == 1 else
                    parse_year_int(r.get("year")) if c == 2 else
                    int(r.get("track_count", 0))
                )
            elif view == "artists":
                headers = ["Artist", "Albums", "Tracks"]
                rows = self._table_artist_rows(query)
                key_fn = lambda r, c: (
                    str(r.get("name", "")).casefold() if c == 0 else
                    int(r.get("album_count", 0)) if c == 1 else
                    int(r.get("track_count", 0))
                )
            else:
                headers = ["Genre", "Albums", "Tracks"]
                rows = self._table_genre_rows(query)
                key_fn = lambda r, c: (
                    str(r.get("genre", "")).casefold() if c == 0 else
                    int(r.get("album_count", 0)) if c == 1 else
                    int(r.get("track_count", 0))
                )

            column, ascending = self._table_sort.get(view, (0, True))
            column = min(column, len(headers) - 1)
            rows.sort(key=lambda r: key_fn(r, column), reverse=not ascending)
            if not rows:
                table.setColumnCount(len(headers))
                table.setHorizontalHeaderLabels(headers)
                table.setRowCount(1)
                empty_item = QTableWidgetItem("No matching items found.")
                empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
                table.setItem(0, 0, empty_item)
                table.setSpan(0, 0, 1, len(headers))
                table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
                self._active_empty_label().hide()
                self.container_widget.hide()
                table.show()
                return
            arrow = " ▲" if ascending else " ▼"
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(
                [h + (arrow if i == column else "") for i, h in enumerate(headers)]
            )
            table.setRowCount(len(rows))
            for row_idx, data in enumerate(rows):
                values = (
                    [data.get("album", ""), data.get("display_artist") or data.get("album_artist", ""),
                     str(data.get("year", "")), str(data.get("track_count", 0))]
                    if view == "albums" else
                    [data.get("name", ""), str(data.get("album_count", 0)), str(data.get("track_count", 0))]
                    if view == "artists" else
                    [data.get("genre", ""), str(data.get("album_count", 0)), str(data.get("track_count", 0))]
                )
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, data)
                    table.setItem(row_idx, col, item)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.resizeRowsToContents()
            self._active_empty_label().hide()
            self.container_widget.hide()
            table.show()
        finally:
            table.setUpdatesEnabled(True)

    def _style_tables(self):
        light = getattr(self, "theme", "dark") == "light"
        if light:
            style = (
                "QTableWidget#catalogTable { background:#ffffff; color:#1f2328; border:none;"
                " alternate-background-color:#ffffff; selection-background-color:#eaeef2;"
                " selection-color:#0969da; }"
                "QTableWidget#catalogTable::item { padding:6px 8px; border-bottom:1px solid #eaeef2; }"
                "QHeaderView::section { background:#f6f8fa; color:#57606a; border:none;"
                " border-bottom:1px solid #d0d7de; padding:8px; font-weight:600; }"
            )
        else:
            style = (
                "QTableWidget#catalogTable { background:#0d1117; color:#e6edf3; border:none;"
                " alternate-background-color:#0d1117; selection-background-color:#1c2430;"
                " selection-color:#58a6ff; }"
                "QTableWidget#catalogTable::item { padding:6px 8px; border-bottom:1px solid #21262d; }"
                "QHeaderView::section { background:#161b22; color:#8b949e; border:none;"
                " border-bottom:1px solid #30363d; padding:8px; font-weight:600; }"
            )
        for table in (self._albums_table, self._artists_table, self._genres_table):
            table.setStyleSheet(style)
            table.verticalHeader().setDefaultSectionSize(34)

    def _table_for_view(self, view: Optional[str] = None) -> Optional[QTableWidget]:
        view = view or self.current_view
        if view == "artists":
            return self._artists_table
        if view == "genres":
            return self._genres_table
        return self._albums_table

    def _table_album_rows(self, query: str) -> List[Dict[str, Any]]:
        if self.artist_filter:
            source = get_albums_by_artist(self.db_conn, self.artist_filter, sort_mode=self.album_sort_mode)
        elif self.genre_filter:
            source = get_albums_by_genre(self.db_conn, self.genre_filter, sort_mode=self.album_sort_mode)
        else:
            source = self.all_albums_cache
        if not query:
            return list(source)
        return [
            a for a in source
            if query in a["album"].lower()
            or query in a["display_artist"].lower()
            or query in a["album_artist"].lower()
            or query in str(a.get("year", "")).lower()
        ]

    def _table_artist_rows(self, query: str) -> List[Dict[str, Any]]:
        return [a for a in self.all_artists_cache if not query or query in a["name"].lower()]

    def _table_genre_rows(self, query: str) -> List[Dict[str, Any]]:
        return [g for g in self.all_genres_cache if not query or query in g["genre"].lower()]

    def _on_table_header_clicked(self, section: int):
        view = self.current_view
        column, ascending = self._table_sort.get(view, (-1, True))
        if column == section:
            ascending = not ascending
        else:
            ascending = True
        self._table_sort[view] = (section, ascending)
        self.refresh_current_view()

    def _on_table_cell_clicked(self, row: int, _column: int):
        # Single click selects; double click opens. Kept separate so selecting
        # a row does not navigate away unexpectedly.
        pass

    def _table_context_style(self) -> str:
        if getattr(self, "theme", "dark") == "light":
            return """
                QMenu { background:#ffffff; color:#1f2328; border:1px solid #d0d7de; border-radius:6px; padding:4px; }
                QMenu::item { padding:6px 18px; border-radius:4px; }
                QMenu::item:selected { background:#f3f4f6; color:#0969da; }
                QMenu::separator { height:1px; background:#d0d7de; margin:4px 2px; }
            """
        return """
            QMenu { background:#1a1e24; color:#e6edf3; border:1px solid #30363d; border-radius:6px; padding:4px; }
            QMenu::item { padding:6px 18px; border-radius:4px; }
            QMenu::item:selected { background:#262c36; color:#58a6ff; }
            QMenu::separator { height:1px; background:#30363d; margin:4px 2px; }
        """

    def _on_table_context_menu(self, table: QTableWidget, pos):
        row = table.rowAt(pos.y())
        if row < 0:
            return
        item = table.item(row, 0)
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        global_pos = table.viewport().mapToGlobal(pos)
        if self.current_view == "albums":
            self._show_album_table_menu(data, global_pos)
        elif self.current_view == "artists":
            self._show_artist_table_menu(data, global_pos)

    def _show_album_table_menu(self, album: Dict[str, Any], global_pos):
        menu = QMenu(self)
        name = album.get("album", "")
        artist = album.get("album_artist", "")
        edit = QAction(get_tinted_icon("context_menu_edit_tags.png", 20, self.theme), "Edit album tags...", menu)
        edit.triggered.connect(lambda: self._on_edit_album(name, artist))
        menu.addAction(edit)
        fix = QAction(get_tinted_icon("context_menu_fix_encoding.png", 20, self.theme), "Fix tags encoding", menu)
        fix.setEnabled(bool(album.get("has_bad_encoding", False)))
        fix.triggered.connect(lambda: self._on_fix_album_encoding(name, artist))
        menu.addAction(fix)
        organize = QAction(get_tinted_icon("context_menu_organize.png", 20, self.theme), "Organize album files", menu)
        try:
            from malka.organizer import is_album_ready_to_organize
            ready, _ = is_album_ready_to_organize(get_album_tracks(self.db_conn, name, artist))
            organize.setEnabled(bool(ready) and not bool(album.get("is_organized", False)))
        except Exception:
            organize.setEnabled(False)
        organize.triggered.connect(lambda: self._on_organize_album(name, artist))
        menu.addAction(organize)
        menu.addSeparator()
        open_folder = QAction(
            get_tinted_icon("context_menu_fix_open_in_file_manager.png", 20, self.theme),
            "Open folder in file manager", menu,
        )
        open_folder.triggered.connect(lambda: self._on_open_album_folder(name, artist))
        menu.addAction(open_folder)
        menu.addSeparator()
        remove = QAction(get_tinted_icon("context_menu_delete.png", 20, self.theme), "Remove album", menu)
        remove.triggered.connect(lambda: self._on_remove_album(name, artist))
        menu.addAction(remove)
        menu.exec(global_pos)

    def _show_artist_table_menu(self, artist: Dict[str, Any], global_pos):
        menu = QMenu(self)
        name = artist.get("name", "")
        add_image = QAction(
            get_tinted_icon("context_menu_edit_tags.png", 20, self.theme),
            "Change artist image...", menu,
        )
        add_image.triggered.connect(lambda: self._table_change_artist_image(artist))
        menu.addAction(add_image)
        if artist.get("image_path"):
            remove_image = QAction(
                get_tinted_icon("context_menu_delete.png", 20, self.theme),
                "Remove artist image", menu,
            )
            remove_image.triggered.connect(lambda: self._table_remove_artist_image(name))
            menu.addAction(remove_image)
        menu.exec(global_pos)

    def _table_change_artist_image(self, artist: Dict[str, Any]):
        card = ArtistCard(artist, self.db_conn, self)
        card.image_updated.connect(self._on_artist_image_updated)
        card._add_artist_image()
        card.deleteLater()
        self.refresh_current_view()

    def _table_remove_artist_image(self, artist_name: str):
        set_artist_image(self.db_conn, artist_name, None)
        for art in self.all_artists_cache:
            if art.get("name") == artist_name:
                art["image_path"] = ""
                break
        self.refresh_current_view()

    def _on_table_cell_double_clicked(self, row: int, _column: int):
        table = self._table_for_view()
        item = table.item(row, 0) if table else None
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        if self.current_view == "albums":
            self._on_album_clicked(data)
        elif self.current_view == "artists":
            self._on_artist_clicked(data.get("name", ""))
        elif self.current_view == "genres":
            self._on_genre_clicked(data.get("genre", ""))

    def _show_sort_menu(self):
        menu = QMenu(self)
        menu.setObjectName("sortMenu")

        # If in Albums view or drilled into an artist or genre (which displays albums)
        if self.current_view == "albums" or self.artist_filter or self.genre_filter:
            options = [
                ("artist_year", "Artist + Year"),
                ("year_asc", "Year ↑"),
                ("year_desc", "Year ↓"),
                ("title_asc", "Title ↑"),
                ("title_desc", "Title ↓"),
            ]
            active_mode = self.album_sort_mode
            category = "album"
        elif self.current_view == "artists":
            options = [
                ("name_asc", "Name ↑"),
                ("name_desc", "Name ↓"),
            ]
            active_mode = self.artist_sort_mode
            category = "artist"
        elif self.current_view == "genres":
            options = [
                ("name_asc", "Name ↑"),
                ("name_desc", "Name ↓"),
            ]
            active_mode = self.genre_sort_mode
            category = "genre"
        else:
            return

        action_group = QActionGroup(menu)
        action_group.setExclusive(True)

        for mode_id, label in options:
            action = QAction(label, menu)
            action.setCheckable(True)
            if mode_id == active_mode:
                action.setChecked(True)
            action.triggered.connect(lambda checked, m=mode_id, cat=category: self._on_sort_selected(cat, m))
            action_group.addAction(action)
            menu.addAction(action)

        btn_rect = self.btn_sort.rect()
        pos = self.btn_sort.mapToGlobal(btn_rect.bottomLeft())
        menu.exec(pos)

    def _on_sort_selected(self, category: str, mode_id: str):
        if category == "album":
            self.album_sort_mode = mode_id
            config.album_sort_mode = mode_id
        elif category == "artist":
            self.artist_sort_mode = mode_id
            config.artist_sort_mode = mode_id
        elif category == "genre":
            self.genre_sort_mode = mode_id
            config.genre_sort_mode = mode_id
        config.save()
        self.refresh_current_view()

    def refresh_current_view(self):
        if getattr(self, "_album_build_depth", 0) > 0:
            # processEvents() during a large grid build may fire the search
            # debounce timer; defer it until the current render is finished.
            self._album_refresh_pending = True
            return
        if getattr(self, "is_stats_mode", False):
            if hasattr(self, "statistics_view"):
                self.statistics_view.refresh_current()
            return

        query = self.search_edit.text().strip().lower()
        if self.current_view == "album_detail":
            if hasattr(self, "btn_sort"):
                self.btn_sort.hide()
            if query:
                self.current_view = "albums"
                self.artist_filter = None
                self.genre_filter = None
                if hasattr(self, "main_stack"):
                    self.main_stack.setCurrentIndex(0)
                if hasattr(self, "catalog_stack"):
                    self._set_catalog_page("albums")
                self._update_view_buttons_style()
                if hasattr(self, "btn_sort"):
                    self.btn_sort.show()
            else:
                self._update_breadcrumb()
                return
        else:
            if hasattr(self, "btn_sort"):
                self.btn_sort.show()

        self._update_breadcrumb()

        if self._track_search_active(query) and self.view_mode != "tiles":
            self.view_mode = "tiles"
            config.view_mode = "tiles"
            config.save()
            self._apply_view_mode_visibility()

        if self.view_mode == "table" and not self._track_search_active(query):
            self._render_catalog_table(query)
            return

        if self.current_view == "artists":
            self._render_artists(query)
        elif self.current_view == "genres":
            self._render_genres(query)
        else:  # "albums"
            self._render_albums(query)

    # ------------------------------------------------------------------
    # Rendered-view cache
    # ------------------------------------------------------------------
    def _detach_layout_widgets(self):
        """Removes widgets from the grid layout without deleting them."""
        while self.flow_layout.count() > 0:
            item = self.flow_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()

    def _cancel_cover_loading(self):
        self._cover_queue_token += 1
        self._cover_queue = []
        self._cover_queue_index = 0
        self._cover_queue_active = False

    def _cancel_incremental_album_render(self):
        state = self._incremental_albums
        if not state:
            return
        self._incremental_albums = None
        self._album_render_token += 1
        widgets = set(state.get("widgets", []))
        for i in range(self.flow_layout.count() - 1, -1, -1):
            item = self.flow_layout.itemAt(i)
            widget = item.widget() if item else None
            if widget in widgets:
                self.flow_layout.takeAt(i)
                widget.hide()
                widget.deleteLater()
        for widget in state.get("pending", []):
            widget.hide()
            widget.deleteLater()
        self.flow_layout.setEnabled(True)
        self._cancel_cover_loading()

    def _begin_view_render(self, view_name: str, cache_key: tuple) -> bool:
        """Reuses a previously rendered view when its data/filter key matches."""
        self._cancel_incremental_album_render()
        cache = self._view_caches.get(view_name)
        if cache and cache.get("key") == cache_key:
            cached_widgets = cache.get("widgets", [])
            self._active_empty_label().hide()
            # Dedicated per-view layouts keep their widgets in place; if the
            # layout already holds this view's tiles, switching back is O(1).
            if self.flow_layout.count() != len(cached_widgets):
                self._detach_layout_widgets()
                self.flow_layout.setEnabled(False)
                for widget in cached_widgets:
                    self.flow_layout.addWidget(widget)
                self.flow_layout.setEnabled(True)
                self.flow_layout.invalidate()
                self._update_container_height()
            return True

        if view_name == "albums":
            # Old tiles are about to be replaced; stop feeding them covers.
            self._cancel_cover_loading()
        self._detach_layout_widgets()
        if cache:
            for widget in cache.get("widgets", []):
                widget.hide()
                widget.deleteLater()
            self._view_caches.pop(view_name, None)
        return False

    def _store_view_cache(self, view_name: str, cache_key: tuple):
        widgets = []
        for i in range(self.flow_layout.count()):
            item = self.flow_layout.itemAt(i)
            widget = item.widget() if item else None
            if widget is not None:
                widgets.append(widget)
        if widgets:
            self._view_caches[view_name] = {"key": cache_key, "widgets": widgets}
        else:
            self._view_caches.pop(view_name, None)

    def _invalidate_view_caches(self):
        self._cancel_incremental_album_render()
        self._cancel_cover_loading()
        for layout in (self._albums_flow_layout, self._artists_flow_layout, self._genres_flow_layout):
            while layout.count() > 0:
                item = layout.takeAt(0)
                widget = item.widget() if item else None
                if widget is not None:
                    widget.hide()
                    widget.deleteLater()
        for cache in list(self._view_caches.values()):
            for widget in cache.get("widgets", []):
                widget.hide()
                widget.deleteLater()
        self._view_caches.clear()

    def _render_artists(self, filter_text: str = ""):
        cache_key = (filter_text, self.artist_sort_mode, self._data_revision)
        self.container_widget.setUpdatesEnabled(False)
        self.container_widget.hide()
        if self._begin_view_render("artists", cache_key):
            self.container_widget.show()
            self.container_widget.setUpdatesEnabled(True)
            return

        self._empty_state_active = False
        self.flow_layout.setEnabled(False)
        try:
            self.flow_layout.clear()
            if not self.all_artists_cache:
                self.all_artists_cache = get_all_artists(self.db_conn)
            artists = sort_artists(self.all_artists_cache, self.artist_sort_mode)

            filtered = []
            for art in artists:
                if not filter_text or filter_text in art["name"].lower():
                    filtered.append(art)

            if not filtered:
                self._show_empty_message(
                    "No artists found in the library."
                    if not artists
                    else "No artists found matching the search query."
                )
                return

            self._active_empty_label().hide()

            for art in filtered:
                card = ArtistCard(art, self.db_conn)
                card.artist_clicked.connect(self._on_artist_clicked)
                card.image_updated.connect(self._on_artist_image_updated)
                self.flow_layout.addWidget(card)

        finally:
            # Re-enable layout only after the whole batch has been inserted;
            # otherwise every addWidget() triggers an O(n) relayout of the grid.
            self.flow_layout.setEnabled(True)
            self.flow_layout.invalidate()
            if not getattr(self, "_empty_state_active", False):
                self._update_container_height()
                self._store_view_cache("artists", cache_key)
            self.container_widget.show()
            self.container_widget.setUpdatesEnabled(True)

    def _render_genres(self, filter_text: str = ""):
        cache_key = (filter_text, self.genre_sort_mode, self._data_revision)
        self.container_widget.setUpdatesEnabled(False)
        self.container_widget.hide()
        if self._begin_view_render("genres", cache_key):
            self.container_widget.show()
            self.container_widget.setUpdatesEnabled(True)
            return

        self._empty_state_active = False
        self.flow_layout.setEnabled(False)
        try:
            self.flow_layout.clear()
            if not self.all_genres_cache:
                self.all_genres_cache = get_all_genres(self.db_conn)
            genres = sort_genres(self.all_genres_cache, self.genre_sort_mode)

            filtered = []
            for g in genres:
                if not filter_text or filter_text in g["genre"].lower():
                    filtered.append(g)

            if not filtered:
                self._show_empty_message(
                    "No genres found in the library."
                    if not genres
                    else "No genres found matching the search query."
                )
                return

            self._active_empty_label().hide()

            for g in filtered:
                card = GenreCard(g)
                card.genre_clicked.connect(self._on_genre_clicked)
                self.flow_layout.addWidget(card)

        finally:
            # Re-enable layout only after the whole batch has been inserted;
            # otherwise every addWidget() triggers an O(n) relayout of the grid.
            self.flow_layout.setEnabled(True)
            self.flow_layout.invalidate()
            if not getattr(self, "_empty_state_active", False):
                self._update_container_height()
                self._store_view_cache("genres", cache_key)
            self.container_widget.show()
            self.container_widget.setUpdatesEnabled(True)

    def _create_album_card(self, album: Dict[str, Any], defer_cover: bool = False) -> AlbumCard:
        card = AlbumCard(album, db_conn=self.db_conn, defer_cover=defer_cover)
        card.album_clicked.connect(self._on_album_clicked)
        card.edit_requested.connect(self._on_edit_album)
        card.fix_encoding_requested.connect(self._on_fix_album_encoding)
        card.organize_requested.connect(self._on_organize_album)
        card.open_folder_requested.connect(self._on_open_album_folder)
        card.remove_requested.connect(self._on_remove_album)
        return card

    def _build_album_render_items(self, filtered: List[Dict[str, Any]]) -> List[tuple]:
        """Returns a flat ordered list of ('album', dict) / ('header', title, count)."""
        items: List[tuple] = []
        if self.artist_filter:
            regular_albums = []
            eps = []
            singles = []
            for alb in filtered:
                cat = categorize_album(alb.get("album", ""))
                if cat == "ep":
                    eps.append(alb)
                elif cat == "single":
                    singles.append(alb)
                else:
                    regular_albums.append(alb)

            regular_albums = sort_albums(regular_albums, self.album_sort_mode)
            eps = sort_albums(eps, self.album_sort_mode)
            singles = sort_albums(singles, self.album_sort_mode)

            has_subcategories = bool(eps or singles)
            if has_subcategories:
                sections = []
                if regular_albums:
                    sections.append(("Albums", regular_albums))
                if eps:
                    sections.append(("EPs", eps))
                if singles:
                    sections.append(("Singles", singles))
                for title, albums in sections:
                    items.append(("header", title, len(albums)))
                    items.extend(("album", alb) for alb in albums)
                return items
        items.extend(("album", alb) for alb in filtered)
        return items

    def _page_marker(self, album: Dict[str, Any]) -> str:
        return album_page_marker(album, self.album_sort_mode)

    def _update_album_pager(self, page_count: int, items: List[tuple]):
        layout = self._albums_pager_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if page_count <= 1:
            self._albums_pager_header.hide()
            return

        if getattr(self, "theme", "dark") == "light":
            style = (
                "QPushButton#pagerButton { color:#1f2328; background:#ffffff; border:1px solid #d0d7de;"
                " border-radius:6px; padding:5px 10px; }"
                "QPushButton#pagerButton:checked { background:#0969da; color:#ffffff; border-color:#0969da; }"
            )
        else:
            style = (
                "QPushButton#pagerButton { color:#c9d1d9; background:#21262d; border:1px solid #30363d;"
                " border-radius:6px; padding:5px 10px; }"
                "QPushButton#pagerButton:checked { background:#1f6feb; color:#ffffff; border-color:#1f6feb; }"
            )

        page_chunks = []
        for page in range(page_count):
            chunk = items[page * self.album_page_size:(page + 1) * self.album_page_size]
            albums = [item[1] for item in chunk if item[0] == "album"]
            if albums:
                first = self._page_marker(albums[0])
                last = self._page_marker(albums[-1])
                page_chunks.append((page, first, last, albums))
        labels = [format_page_label(first, last) for _, first, last, _ in page_chunks]
        duplicate_labels = len(set(labels)) < len(labels)

        layout.addStretch(1)
        for idx, (page, first, last, albums) in enumerate(page_chunks):
            label = labels[idx]
            if duplicate_labels:
                label = f"{label} · {page + 1}"
            btn = QPushButton(label)
            btn.setObjectName("pagerButton")
            btn.setStyleSheet(style)
            btn.setCheckable(True)
            btn.setChecked(page == self.album_page)
            btn.setToolTip(f"{albums[0].get('album', '')} … {albums[-1].get('album', '')}")
            btn.clicked.connect(lambda _checked=False, p=page: self._goto_album_page(p))
            layout.addWidget(btn)
        layout.addStretch(1)
        self._albums_pager_header.show()

    def _sync_pager_selection(self):
        buttons = [
            self._albums_pager_layout.itemAt(i).widget()
            for i in range(self._albums_pager_layout.count())
            if self._albums_pager_layout.itemAt(i).widget() is not None
        ]
        for page, btn in enumerate(buttons):
            btn.setChecked(page == self.album_page)

    def _goto_album_page(self, page: int):
        if page < 0 or page == self.album_page:
            return
        self.album_page = page
        self._albums_scroll_area.verticalScrollBar().setValue(0)
        self.refresh_current_view()

    def _render_album_item(self, item: tuple, covers_to_load: List[AlbumCard]):
        if item[0] == "header":
            header = SectionHeaderWidget(
                title=item[1],
                count=item[2],
                is_first=not covers_to_load,
                theme=self.theme,
            )
            self.flow_layout.addWidget(header)
            return
        card = self._create_album_card(item[1], defer_cover=True)
        covers_to_load.append(card)
        self.flow_layout.addWidget(card)

    def _begin_incremental_album_render(self, items: List[tuple], cache_key: tuple):
        """Renders an empty page first, then feeds tiles in event-loop batches."""
        self._cancel_incremental_album_render()
        self.flow_layout.setEnabled(False)
        self._album_render_token += 1
        token = self._album_render_token
        self._incremental_albums = {
            "items": items,
            "index": 0,
            "cache_key": cache_key,
            "token": token,
            "widgets": [],
            "album_cards": [],
            "pending": [],
            "revision": self._data_revision,
            "sort_mode": self.album_sort_mode,
            "filter_text": self.search_edit.text().strip().lower(),
            "batches_since_paint": 0,
        }
        QTimer.singleShot(0, lambda: self._add_incremental_album_batch(token))

    def _add_incremental_album_batch(self, token: int):
        if getattr(self, "_closing", False):
            self._cancel_incremental_album_render()
            return
        state = self._incremental_albums
        if not state or state.get("token") != token:
            return
        if (
            self._data_revision != state.get("revision")
            or self.album_sort_mode != state.get("sort_mode")
            or self.search_edit.text().strip().lower() != state.get("filter_text")
        ):
            self._cancel_incremental_album_render()
            QTimer.singleShot(0, self.refresh_current_view)
            return

        items = state["items"]
        start = state["index"]
        is_first_batch = (start == 0)
        batch = items[start:start + 60]
        if not batch:
            self._store_view_cache("albums", state["cache_key"])
            self._incremental_albums = None
            self._schedule_visible_covers()
            return

        pending = state.setdefault("pending", [])
        if is_first_batch:
            # Paint the very first batch straight away, then keep building the
            # rest of the widgets *without* parenting them so the visible page
            # doesn't pay a per-tile show/relayout cost.
            self.flow_layout.setEnabled(False)
            self.container_widget.setUpdatesEnabled(False)
            for item in batch:
                widget = self._make_album_render_widget(item, state)
                self.flow_layout.addWidget(widget)
                widget.show()
            state["index"] = start + len(batch)
            self.flow_layout.setEnabled(True)
            self.flow_layout.invalidate()
            self._update_container_height()
            self.container_widget.show()
            self.container_widget.setUpdatesEnabled(True)
            QTimer.singleShot(0, lambda: self._add_incremental_album_batch(token))
            return

        # Subsequent batches: create widgets cheaply, parent them to the layout
        # in one go at the end.
        for item in batch:
            widget = self._make_album_render_widget(item, state)
            pending.append(widget)
        state["index"] = start + len(batch)

        if state["index"] >= len(items):
            self.flow_layout.setEnabled(False)
            self.container_widget.setUpdatesEnabled(False)
            for widget in pending:
                self.flow_layout.addWidget(widget)
                widget.show()
            pending.clear()
            self._update_container_height()
            self.flow_layout.setEnabled(False)
            self.container_widget.setUpdatesEnabled(True)
            self._store_view_cache("albums", state["cache_key"])
            self._incremental_albums = None
            self._schedule_visible_covers()
        else:
            QTimer.singleShot(0, lambda: self._add_incremental_album_batch(token))

    def _make_album_render_widget(self, item: tuple, state: Dict[str, Any]):
        if item[0] == "header":
            widget = SectionHeaderWidget(
                title=item[1],
                count=item[2],
                is_first=(state["index"] == 0),
                theme=self.theme,
            )
        else:
            widget = self._create_album_card(item[1], defer_cover=True)
            state["album_cards"].append(widget)
        # Parent immediately and keep hidden. Creating hundreds of parentless
        # QWidgets creates top-level native windows and freezes the app.
        widget.setParent(self.container_widget)
        widget.hide()
        state["widgets"].append(widget)
        return widget

    def _schedule_visible_covers(self):
        if getattr(self, "_closing", False):
            return
        self._cover_scroll_timer.start()

    def _load_visible_covers(self):
        if getattr(self, "_closing", False):
            return
        if self.current_view != "albums" or self._incremental_albums is not None:
            return
        if hasattr(self, "main_stack") and self.main_stack.currentIndex() != 0:
            return
        scroll = self._albums_scroll_area
        layout = self._albums_flow_layout
        if scroll is None or layout is None:
            return
        y0 = scroll.verticalScrollBar().value() - 300
        y1 = y0 + scroll.viewport().height() + 600
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, AlbumCard):
                top = widget.y()
                if top + widget.height() >= y0 and top <= y1:
                    widget.load_cover()

    def _start_cover_loading(self, cards: List[AlbumCard]):
        """Fills already-rendered tiles with artwork, strictly one at a time."""
        self._cancel_cover_loading()
        self._cover_queue = list(cards)
        self._cover_queue_index = 0
        self._cover_queue_active = True
        # Loading covers must not invalidate and re-run the 2500-item flow
        # layout for every single pixmap change.
        self.flow_layout.setEnabled(False)
        token = self._cover_queue_token
        QTimer.singleShot(0, lambda: self._load_next_cover(token))

    def _load_next_cover(self, token: int):
        if token != self._cover_queue_token or getattr(self, "_closing", False):
            return
        if self._cover_queue_index >= len(self._cover_queue):
            self._cover_queue = []
            self._cover_queue_index = 0
            self._cover_queue_active = False
            self.flow_layout.setEnabled(True)
            return

        card = self._cover_queue[self._cover_queue_index]
        self._cover_queue_index += 1

        def _advance():
            # A zero-delay timer per cover starves every other timer (the UI
            # looks frozen while 2500 covers are processed). One millisecond
            # still fills the grid quickly but keeps the event loop responsive.
            QTimer.singleShot(1, lambda: self._load_next_cover(token))

        try:
            card.load_cover(callback=_advance)
        except RuntimeError:
            # Card was deleted by a refresh between queue steps.
            _advance()

    def _show_empty_message(self, text: str):
        """Clears stale tiles/cache and shows a single empty-state message."""
        self._empty_state_active = True
        self._cancel_incremental_album_render()
        self._cancel_cover_loading()
        if hasattr(self, "flow_layout"):
            self.flow_layout.clear()
        if hasattr(self, "_view_caches"):
            self._view_caches.pop(self.current_view, None)
        if self.current_view == "albums" and hasattr(self, "_update_album_pager"):
            self._update_album_pager(1, [])
        label = self._active_empty_label()
        label.setText(text)
        viewport = self.scroll_area.viewport()
        w = max(1, viewport.width())
        h = max(1, viewport.height())
        self.container_widget.setFixedSize(w, h)
        label.setGeometry(0, 0, w, h)
        label.show()
        label.raise_()
        self.container_widget.show()
        self.container_widget.setUpdatesEnabled(True)
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(0)
        fade = getattr(self, "_scroll_fades", {}).get(self.scroll_area.viewport())
        if fade is not None:
            fade.set_strength(0.0)

    def _track_search_albums(self, query: str, album_source: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        q = query.casefold()
        album_map: Dict[tuple, Dict[str, Any]] = {}
        for album in album_source:
            key = (str(album.get("album", "")).casefold(), str(album.get("album_artist", "")).casefold())
            album_map[key] = dict(album)
        matches: Dict[tuple, List[str]] = {}
        try:
            rows = self.db_conn.execute(
                "SELECT album, album_artist, title, file_path FROM tracks"
            ).fetchall()
        except Exception:
            return []
        for row in rows:
            key = (str(row["album"]).casefold(), str(row["album_artist"]).casefold())
            if key not in album_map:
                continue
            title = str(row["title"] or "")
            filename = Path(str(row["file_path"] or "")).name
            if q in title.casefold():
                display = title
            elif q in filename.casefold():
                display = filename
            else:
                continue
            bucket = matches.setdefault(key, [])
            if display not in bucket:
                bucket.append(display)
        result = []
        for key, names in matches.items():
            album = album_map[key]
            album["_track_matches"] = names[:8]
            album["_track_query"] = query
            result.append(album)
        return sort_albums(result, self.album_sort_mode)

    def _render_albums(self, filter_text: str = ""):
        cache_key = (
            filter_text,
            self.artist_filter,
            self.genre_filter,
            self.album_sort_mode,
            self._data_revision,
            self.album_page,
            self.search_tracks_check.isChecked(),
        )
        self.container_widget.setUpdatesEnabled(False)
        if self._begin_view_render("albums", cache_key):
            self.container_widget.setUpdatesEnabled(True)
            self._sync_pager_selection()
            self._schedule_visible_covers()
            return
        self.container_widget.hide()
        self._empty_state_active = False

        incremental_started = False
        covers_to_load: List[AlbumCard] = []
        self.flow_layout.setEnabled(False)
        try:
            self.flow_layout.clear()

            # If filtered by artist or genre
            if self.artist_filter:
                album_source = get_albums_by_artist(self.db_conn, self.artist_filter, sort_mode=self.album_sort_mode)
            elif self.genre_filter:
                album_source = get_albums_by_genre(self.db_conn, self.genre_filter, sort_mode=self.album_sort_mode)
            else:
                album_source = self.all_albums_cache

            tracks_mode = self.search_tracks_check.isChecked()
            raw_query = self.search_edit.text().strip()
            if tracks_mode and raw_query and len(raw_query) < 2:
                self._show_empty_message(
                    "Type at least 2 characters to search tracks."
                )
                return
            if tracks_mode and len(raw_query) >= 2:
                filtered = self._track_search_albums(raw_query, album_source)
                if not filtered:
                    self._show_empty_message("No tracks found matching the search query.")
                    return
                self.empty_label.hide()
                page_count = max(1, (len(filtered) + self.album_page_size - 1) // self.album_page_size)
                if self.album_page >= page_count:
                    self.album_page = page_count - 1
                all_items = [("album", alb) for alb in filtered]
                page_start = self.album_page * self.album_page_size
                render_items = all_items[page_start:page_start + self.album_page_size]
                self._update_album_pager(page_count, all_items)
                incremental_started = True
                self._begin_incremental_album_render(render_items, cache_key)
                return

            filtered = []
            for alb in album_source:
                if not filter_text:
                    filtered.append(alb)
                    continue
                name_match = filter_text in alb["album"].lower()
                artist_match = filter_text in alb["display_artist"].lower()
                album_artist_match = filter_text in alb["album_artist"].lower()
                year_match = filter_text in str(alb["year"]).lower()
                if name_match or artist_match or album_artist_match or year_match:
                    filtered.append(alb)

            if not filtered:
                self._show_empty_message(
                    "No albums found in this category."
                    if not album_source
                    else "No albums found matching the search query."
                )
                return

            self.empty_label.hide()
            filtered = sort_albums(filtered, self.album_sort_mode)

            # Any large album list (All albums, an artist, a genre, a search
            # result) opens empty first and fills in background batches.
            render_items = self._build_album_render_items(filtered)
            page_count = max(1, (len(render_items) + self.album_page_size - 1) // self.album_page_size)
            if self.album_page >= page_count:
                self.album_page = page_count - 1
            self._update_album_pager(page_count, render_items)
            if page_count > 1:
                page_start = self.album_page * self.album_page_size
                render_items = render_items[page_start:page_start + self.album_page_size]

            if len(render_items) > 120:
                incremental_started = True
                self._begin_incremental_album_render(render_items, cache_key)
                return

            for item in render_items:
                self._render_album_item(item, covers_to_load)

        finally:
            # Re-enable layout only after the whole batch has been inserted;
            # otherwise every addWidget() triggers an O(n) relayout of the grid.
            if not incremental_started:
                self.flow_layout.setEnabled(True)
                self.flow_layout.invalidate()
                if not getattr(self, "_empty_state_active", False):
                    self._update_container_height()
                    self._store_view_cache("albums", cache_key)
                self.container_widget.show()
                self.container_widget.setUpdatesEnabled(True)
                self._schedule_visible_covers()
            # Incremental mode keeps the page hidden and update-disabled until
            # the batch build finishes; the grid then appears all at once.
            if self._album_refresh_pending:
                self._album_refresh_pending = False
                QTimer.singleShot(0, self.refresh_current_view)

    def _update_container_height(self):
        self._resize_catalog_page(self.scroll_area)

    @staticmethod
    def _update_top_fade(fade, scroll_value: int):
        # Ramp in over the first 40 px of scrolling so the resting grid stays clean.
        fade.set_strength(min(1.0, max(0, int(scroll_value)) / 40.0))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            fade = getattr(self, "_scroll_fades", {}).get(obj)
            if fade is not None:
                fade.setGeometry(0, 0, obj.width(), fade.height())
                fade.raise_()
            for sa in (
                getattr(self, "_albums_scroll_area", None),
                getattr(self, "_artists_scroll_area", None),
                getattr(self, "_genres_scroll_area", None),
            ):
                if sa is not None and obj is sa.viewport():
                    QTimer.singleShot(0, lambda s=sa: self._resize_catalog_page(s))
                    break
        return super().eventFilter(obj, event)

    def _resize_catalog_page(self, scroll: QScrollArea):
        if getattr(self, "_empty_state_active", False):
            return
        if getattr(self, "_catalog_resize_guard", False):
            return
        container = scroll.widget()
        layout = container.layout() if container is not None else None
        if container is None or layout is None:
            return
        w = scroll.viewport().width()
        if w <= 0:
            return
        self._catalog_resize_guard = True
        try:
            h = layout.heightForWidth(w)
            container.setFixedSize(w, h)
            layout.setGeometry(container.rect())
        finally:
            self._catalog_resize_guard = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "nav_row_widget"):
            self.nav_row_widget.update_positions()
        if hasattr(self, "flow_layout") and hasattr(self, "scroll_area") and hasattr(self, "container_widget"):
            self._update_container_height()

    def _apply_toolbar_icons(self, theme: str):
        icons = {
            self.btn_select_dir: ("add_library_path.png", 20),
            self.btn_import: ("import_album.png", 20),
            self.btn_rescan: ("rescan_library.webp", 20),
            self.btn_settings: ("settings.png", 20),
            self.btn_stats: ("statistics.png", 20),
            self.btn_about: ("about.png", 20),
        }
        for button, (filename, size) in icons.items():
            button.setIcon(get_tinted_icon(filename, size=size, theme=theme))
            button.setIconSize(QSize(size, size))

    def apply_theme(self, theme: str):
        self.theme = theme
        config.theme = theme
        if hasattr(self, "btn_stats"):
            self._apply_toolbar_icons(theme)
        for fade in getattr(self, "_scroll_fades", {}).values():
            fade.set_theme(theme)
        if theme == "light":
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #f6f8fa;
                }
                QWidget#centralWidget {
                    background-color: #f6f8fa;
                }
                QWidget#contentWidget {
                    background-color: #f6f8fa;
                }
                QScrollArea {
                    background-color: #f6f8fa;
                    border: none;
                }
                QWidget#scrollContainer {
                    background-color: #f6f8fa;
                }
                QFrame#albumCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#albumCard:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                }
                QLabel#albumCardTitle {
                    color: #1f2328;
                    background: transparent;
                }
                QLabel#albumCardInfo {
                    color: #656d76;
                    background: transparent;
                }
                QStackedWidget {
                    background-color: #f6f8fa;
                }
                QScrollBar:vertical {
                    background: transparent;
                    width: 6px;
                    margin: 0px;
                    border: none;
                }
                QScrollBar::handle:vertical {
                    background: rgba(0, 0, 0, 0.18);
                    min-height: 24px;
                    border-radius: 3px;
                }
                QScrollBar::handle:vertical:hover {
                    background: rgba(0, 0, 0, 0.32);
                }
                QScrollBar::handle:vertical:pressed {
                    background: rgba(0, 0, 0, 0.45);
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                    background: transparent;
                    border: none;
                }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: transparent;
                }
                QScrollBar:horizontal {
                    background: transparent;
                    height: 6px;
                    margin: 0px;
                    border: none;
                }
                QScrollBar::handle:horizontal {
                    background: rgba(0, 0, 0, 0.18);
                    min-width: 24px;
                    border-radius: 3px;
                }
                QScrollBar::handle:horizontal:hover {
                    background: rgba(0, 0, 0, 0.32);
                }
                QScrollBar::handle:horizontal:pressed {
                    background: rgba(0, 0, 0, 0.45);
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0px;
                    background: transparent;
                    border: none;
                }
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                    background: transparent;
                }
                QLineEdit#searchEdit {
                    background-color: #ffffff;
                    border: 1px solid #d0d7de;
                    border-radius: 16px;
                    padding: 6px 14px;
                    color: #1f2328;
                    font-size: 9pt;
                    min-width: 250px;
                }
                QLineEdit#searchEdit:hover {
                    border: 1px solid #b0b8c1;
                }
                QLineEdit#searchEdit:focus {
                    background-color: #ffffff;
                    border: 1px solid #0969da;
                }
                QPushButton.topBtn {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                    color: #57606a;
                    padding: 6px 14px;
                    font-weight: 500;
                }
                QPushButton.topBtn:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                    border: none;
                    color: #1f2328;
                }
                QPushButton.topBtn:pressed {
                    background-color: rgba(0, 0, 0, 0.12);
                    border: none;
                }
                QPushButton.topBtn:checked, QPushButton#btnStats:checked {
                    background-color: #ddf4ff;
                    color: #0969da;
                    border: 1px solid #54aeff;
                    font-weight: bold;
                }
                QStatusBar {
                    background-color: #ffffff;
                    color: #656d76;
                    border-top: 1px solid #d0d7de;
                }
                QProgressBar {
                    background-color: #eaeef2;
                    border: 1px solid #d0d7de;
                    border-radius: 4px;
                    text-align: center;
                    color: #1f2328;
                    max-height: 14px;
                    min-width: 180px;
                }
                QProgressBar::chunk {
                    background-color: #0969da;
                    border-radius: 3px;
                }
            """)
            if hasattr(self, "view_switcher_frame"):
                self.view_switcher_frame.setStyleSheet("""
                    QFrame#viewSwitcherFrame {
                        background-color: #eaeef2;
                        border: none;
                        border-radius: 7px;
                    }
                """)
            if hasattr(self, "mode_island_frame"):
                self.mode_island_frame.setStyleSheet("""
                    QFrame#modeIsland {
                        background-color: #eaeef2;
                        border: none;
                        border-radius: 7px;
                    }
                """)
            if hasattr(self, "btn_sort"):
                self.btn_sort.setIcon(get_tinted_icon("Sort_button.png", 17, "light"))
                self.btn_sort.setStyleSheet("""
                    QPushButton#btnSort {
                        background-color: #eaeef2;
                        border: 1px solid #d0d7de;
                        border-radius: 7px;
                        color: #57606a;
                        font-size: 8.5pt;
                        font-weight: 500;
                        padding: 4px 12px;
                    }
                    QPushButton#btnSort:hover {
                        background-color: #dfe4e9;
                        border: 1px solid #afb8c1;
                        color: #1f2328;
                    }
                    QPushButton#btnSort:pressed {
                        background-color: #d0d7de;
                    }
                """)
            if hasattr(self, "status_info_label"):
                self.status_info_label.setStyleSheet("color: #656d76; margin-left: 8px;")
            if hasattr(self, "scan_status_label"):
                self.scan_status_label.setStyleSheet("color: #656d76; margin-right: 8px;")
            if hasattr(self, "empty_label"):
                self.empty_label.setStyleSheet("color: #656d76; padding: 40px;")
        else:
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #0e1116;
                }
                QWidget#centralWidget {
                    background-color: #0e1116;
                }
                QWidget#contentWidget {
                    background-color: #0e1116;
                }
                QScrollArea {
                    background-color: #0e1116;
                    border: none;
                }
                QWidget#scrollContainer {
                    background-color: #0e1116;
                }
                QFrame#albumCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#albumCard:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                }
                QLabel#albumCardTitle {
                    color: #ffffff;
                    background: transparent;
                }
                QLabel#albumCardInfo {
                    color: #8b949e;
                    background: transparent;
                }
                QStackedWidget {
                    background-color: #0e1116;
                }
                QScrollBar:vertical {
                    background: transparent;
                    width: 6px;
                    margin: 0px;
                    border: none;
                }
                QScrollBar::handle:vertical {
                    background: rgba(255, 255, 255, 0.22);
                    min-height: 24px;
                    border-radius: 3px;
                }
                QScrollBar::handle:vertical:hover {
                    background: rgba(255, 255, 255, 0.40);
                }
                QScrollBar::handle:vertical:pressed {
                    background: rgba(255, 255, 255, 0.55);
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                    background: transparent;
                    border: none;
                }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: transparent;
                }
                QScrollBar:horizontal {
                    background: transparent;
                    height: 6px;
                    margin: 0px;
                    border: none;
                }
                QScrollBar::handle:horizontal {
                    background: rgba(255, 255, 255, 0.22);
                    min-width: 24px;
                    border-radius: 3px;
                }
                QScrollBar::handle:horizontal:hover {
                    background: rgba(255, 255, 255, 0.40);
                }
                QScrollBar::handle:horizontal:pressed {
                    background: rgba(255, 255, 255, 0.55);
                }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                    width: 0px;
                    background: transparent;
                    border: none;
                }
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                    background: transparent;
                }
                QLineEdit#searchEdit {
                    background-color: rgba(255, 255, 255, 0.05);
                    border: none;
                    border-radius: 16px;
                    padding: 6px 14px;
                    color: #ffffff;
                    font-size: 9pt;
                    min-width: 250px;
                }
                QLineEdit#searchEdit:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: none;
                }
                QLineEdit#searchEdit:focus {
                    background-color: rgba(255, 255, 255, 0.1);
                    border: none;
                }
                QPushButton.topBtn {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                    color: #c9d1d9;
                    padding: 6px 14px;
                    font-weight: 500;
                }
                QPushButton.topBtn:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: none;
                    color: #ffffff;
                }
                QPushButton.topBtn:pressed {
                    background-color: rgba(255, 255, 255, 0.14);
                    border: none;
                }
                QPushButton.topBtn:checked, QPushButton#btnStats:checked {
                    background-color: #1f6feb;
                    color: #ffffff;
                    border: 1px solid #388bfd;
                    font-weight: bold;
                }
                QStatusBar {
                    background-color: #1a1a1a;
                    color: #888888;
                    border-top: 1px solid #282828;
                }
                QProgressBar {
                    background-color: #222222;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    text-align: center;
                    color: #ffffff;
                    max-height: 14px;
                    min-width: 180px;
                }
                QProgressBar::chunk {
                    background-color: #007acc;
                    border-radius: 3px;
                }
            """)
            if hasattr(self, "view_switcher_frame"):
                self.view_switcher_frame.setStyleSheet("""
                    QFrame#viewSwitcherFrame {
                        background-color: #1a1e24;
                        border: none;
                        border-radius: 7px;
                    }
                """)
            if hasattr(self, "mode_island_frame"):
                self.mode_island_frame.setStyleSheet("""
                    QFrame#modeIsland {
                        background-color: #1a1e24;
                        border: none;
                        border-radius: 7px;
                    }
                """)
            if hasattr(self, "btn_sort"):
                self.btn_sort.setIcon(get_tinted_icon("Sort_button.png", 17, "dark"))
                self.btn_sort.setStyleSheet("""
                    QPushButton#btnSort {
                        background-color: #1a1e24;
                        border: 1px solid #282e38;
                        border-radius: 7px;
                        color: #c9d1d9;
                        font-size: 8.5pt;
                        font-weight: 500;
                        padding: 4px 12px;
                    }
                    QPushButton#btnSort:hover {
                        background-color: #242931;
                        border: 1px solid #3d4450;
                        color: #ffffff;
                    }
                    QPushButton#btnSort:pressed {
                        background-color: #161a20;
                    }
                """)
            if hasattr(self, "status_info_label"):
                self.status_info_label.setStyleSheet("color: #aaaaaa; margin-left: 8px;")
            if hasattr(self, "scan_status_label"):
                self.scan_status_label.setStyleSheet("color: #888888; margin-right: 8px;")
            if hasattr(self, "empty_label"):
                self.empty_label.setStyleSheet("color: #666666; padding: 40px;")

        if hasattr(self, "title_bar"):
            self.title_bar.apply_theme(theme)
        if hasattr(self, "player_sidebar"):
            self.player_sidebar.apply_theme(theme)
        if hasattr(self, "breadcrumb_bar"):
            self.breadcrumb_bar.apply_theme(theme)
        if hasattr(self, "album_detail_view"):
            self.album_detail_view.apply_theme(theme)
        if hasattr(self, "statistics_view"):
            self.statistics_view.apply_theme(theme)
        if hasattr(self, "btn_view_artists"):
            self._update_view_buttons_style()
        if hasattr(self, "flow_layout"):
            for i in range(self.flow_layout.count()):
                item = self.flow_layout.itemAt(i)
                if item and item.widget():
                    w = item.widget()
                    if hasattr(w, "apply_theme"):
                        w.apply_theme(theme)
        # Cached (currently hidden) views must follow theme changes too.
        for cache in getattr(self, "_view_caches", {}).values():
            for widget in cache.get("widgets", []):
                if hasattr(widget, "apply_theme"):
                    widget.apply_theme(theme)
        if hasattr(self, "btn_mode_tiles"):
            self._apply_view_mode_visibility()
        if hasattr(self, "search_tracks_check"):
            text_col = "#57606a" if theme == "light" else "#c9d1d9"
            accent = "#0969da" if theme == "light" else "#1f6feb"
            self.search_tracks_check.setStyleSheet(
                f"QCheckBox#searchTracksCheck {{ color:{text_col}; font-size:8.5pt; spacing:5px; }}"
                f"QCheckBox#searchTracksCheck::indicator {{ width:14px; height:14px; }}"
                f"QCheckBox#searchTracksCheck::indicator:checked {{ background:{accent}; border-color:{accent}; }}"
            )
        self.update_scrollbars()
        self._style_tables()

        check_path = get_resource_path("checkmark.png").replace("\\", "/")
        menu_bg = "#ffffff" if theme == "light" else "#1a1e24"
        menu_fg = "#1f2328" if theme == "light" else "#e6edf3"
        menu_border = "#d0d7de" if theme == "light" else "#30363d"
        menu_hover = "#f3f4f6" if theme == "light" else "#262c36"
        menu_accent = "#0969da" if theme == "light" else "#58a6ff"
        menu_disabled = "#8c959f" if theme == "light" else "#6e7681"
        check_border = "#d0d7de" if theme == "light" else "#3c3c3c"
        check_bg = "#ffffff" if theme == "light" else "#1e1e1e"
        check_accent = "#0969da" if theme == "light" else "#1f6feb"
        extra = f"""
            QMenu {{
                background-color: {menu_bg};
                color: {menu_fg};
                border: 1px solid {menu_border};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{
                padding: 7px 26px 7px 36px;
                border-radius: 6px;
            }}
            QMenu::icon {{
                left: 9px;
                width: 20px;
                height: 20px;
            }}
            QMenu::item:selected {{
                background-color: {menu_hover};
                color: {menu_accent};
            }}
            QMenu::item:disabled {{
                color: {menu_disabled};
            }}
            QMenu#sortMenu::item {{
                padding-left: 8px;
            }}
            QMenu#sortMenu::indicator {{
                width: 14px;
                height: 14px;
            }}
            QMenu::separator {{
                height: 1px;
                background: {menu_border};
                margin: 5px 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {check_border};
                border-radius: 4px;
                background-color: {check_bg};
            }}
            QCheckBox::indicator:hover {{
                border-color: {check_accent};
            }}
            QCheckBox::indicator:checked {{
                background-color: {check_accent};
                border-color: {check_accent};
                image: url("{check_path}");
                image-position: center;
            }}
        """
        self.setStyleSheet(self.styleSheet() + extra)

    def _on_edit_album(self, album_name: str, album_artist: str):
        tracks = get_album_tracks(self.db_conn, album_name, album_artist)
        file_paths = [t.get("file_path", "") for t in tracks]
        suspend_state: Dict[str, Any] = {"token": None}

        def on_operation_started():
            # Pause only when Save is actually pressed, not while browsing the dialog.
            if suspend_state["token"] is None:
                suspend_state["token"] = self.player_controller.suspend_for_file_operation(file_paths)

        def on_operation_finished(success: bool):
            token = suspend_state.pop("token", None)
            if token:
                self.player_controller.resume_after_file_operation(token)

        dlg = EditAlbumDialog(album_name, album_artist, self.db_conn, parent=self, theme=self.theme)
        dlg.operation_about_to_start.connect(on_operation_started)
        dlg.operation_finished.connect(on_operation_finished)
        try:
            if dlg.exec():
                self.refresh_library_view()
        finally:
            token = suspend_state.pop("token", None)
            if token:
                self.player_controller.resume_after_file_operation(token)

    def _remove_files_to_trash(self, file_paths: List[str]) -> tuple[list[str], list[str]]:
        removed, failed = [], []
        for file_path in file_paths:
            if not file_path:
                continue
            if move_to_recycle_bin(file_path):
                removed.append(file_path)
            else:
                failed.append(file_path)
        return removed, failed

    def _on_remove_album(self, album_name: str, album_artist: str):
        tracks = get_album_tracks(self.db_conn, album_name, album_artist)
        if not tracks:
            return
        answer = QMessageBox.question(
            self,
            "Remove Album",
            f"Remove album “{album_name}” by {album_artist}?\n\n"
            f"{len(tracks)} audio file(s) will be moved to the Recycle Bin and their database records deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        file_paths = [t.get("file_path", "") for t in tracks if t.get("file_path")]
        token = self.player_controller.suspend_for_file_operation(file_paths)
        try:
            removed, failed = self._remove_files_to_trash(file_paths)
            if removed:
                delete_tracks_by_paths(self.db_conn, removed)
            if failed:
                QMessageBox.warning(
                    self, "Remove Album",
                    "Some files could not be moved to the Recycle Bin and were kept:\n" + "\n".join(failed[:8]),
                )
            self.refresh_library_view()
            if self.current_view == "album_detail":
                self._go_all_albums()
        finally:
            if token:
                self.player_controller.resume_after_file_operation(token)

    def _on_remove_track(self, track: Dict[str, Any]):
        file_path = track.get("file_path", "")
        title = track.get("title", Path(file_path).name)
        answer = QMessageBox.question(
            self,
            "Remove Track",
            f"Remove track “{title}”?\n\n"
            "The audio file will be moved to the Recycle Bin and its database record deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        token = self.player_controller.suspend_for_file_operation([file_path] if file_path else [])
        try:
            removed, failed = self._remove_files_to_trash([file_path] if file_path else [])
            if removed:
                delete_tracks_by_paths(self.db_conn, removed)
            if failed:
                QMessageBox.warning(self, "Remove Track", "The file could not be moved to the Recycle Bin.")
                return
            album_data = dict(self.album_detail_view.album_data or {})
            self.refresh_library_view()
            if self.current_view == "album_detail" and album_data.get("album"):
                remaining = get_album_tracks(self.db_conn, album_data.get("album", ""), album_data.get("album_artist", ""))
                if remaining:
                    self._on_album_clicked(album_data)
                else:
                    self._go_all_albums()
        finally:
            if token:
                self.player_controller.resume_after_file_operation(token)

    def _on_edit_track(self, track: Dict[str, Any]):
        file_path = track.get("file_path", "")
        if not file_path:
            return
        token = None

        def on_started():
            nonlocal token
            if token is None:
                token = self.player_controller.suspend_for_file_operation([file_path])

        def on_finished(success: bool):
            nonlocal token
            if token:
                self.player_controller.resume_after_file_operation(token)
                token = None

        dlg = EditTrackDialog(track, self.db_conn, parent=self, theme=self.theme)
        dlg.operation_about_to_start.connect(on_started)
        dlg.operation_finished.connect(on_finished)
        try:
            if dlg.exec():
                album_data = dict(self.album_detail_view.album_data or {})
                self.refresh_library_view()
                if self.current_view == "album_detail" and album_data.get("album"):
                    self._on_album_clicked(album_data)
        finally:
            if token:
                self.player_controller.resume_after_file_operation(token)

    def _on_fix_album_encoding(self, album_name: str, album_artist: str):
        from malka.db import get_album_tracks, upsert_track
        from malka.tags import detect_and_fix_encoding, read_tags, write_tags

        tracks = get_album_tracks(self.db_conn, album_name, album_artist)
        if not tracks:
            return

        token = self.player_controller.suspend_for_file_operation(
            [t.get("file_path", "") for t in tracks]
        )
        fixed_count = 0
        try:
            fixed_count = self._fix_album_encoding_files(tracks, detect_and_fix_encoding, read_tags, write_tags, upsert_track)
        finally:
            if token:
                self.player_controller.resume_after_file_operation(token)

        self.db_conn.commit()
        self.refresh_library_view()
        QMessageBox.information(
            self,
            "Encoding Fixed",
            f"Successfully fixed tags character encoding for {fixed_count} tracks in '{album_name}'.\n"
            f"Tags were rewritten in standard UTF-8.",
        )

    def _fix_album_encoding_files(self, tracks, detect_and_fix_encoding, read_tags, write_tags, upsert_track) -> int:
        fixed_count = 0
        for t in tracks:
            file_p = t.get("file_path")
            if not file_p or not Path(file_p).exists():
                continue

            raw_tags = read_tags(file_p)

            title = t.get("title") or raw_tags.get("title")
            artist = t.get("artist") or raw_tags.get("artist")
            alb_art = t.get("album_artist") or raw_tags.get("album_artist")
            album = t.get("album") or raw_tags.get("album")
            genre = t.get("genre") or raw_tags.get("genre")
            year = t.get("year") or raw_tags.get("year")
            track_no = t.get("track_no") or raw_tags.get("track_no")
            disc_no = t.get("disc_no") or raw_tags.get("disc_no", "1")
            disc_total = t.get("disc_total") or raw_tags.get("disc_total", "1")
            compilation = t.get("compilation") or raw_tags.get("compilation", 0)

            # Ensure text is decoded properly if it had mojibake
            _, title = detect_and_fix_encoding(title)
            _, artist = detect_and_fix_encoding(artist)
            _, alb_art = detect_and_fix_encoding(alb_art)
            _, album = detect_and_fix_encoding(album)
            _, genre = detect_and_fix_encoding(genre)

            write_tags(
                file_path=file_p,
                title=title,
                artist=artist,
                album_artist=alb_art,
                album=album,
                year=year,
                genre=genre,
                track_no=track_no,
                disc_no=disc_no,
                disc_total=disc_total,
                compilation=compilation,
            )

            updated = dict(t)
            updated["title"] = title
            updated["artist"] = artist
            updated["album_artist"] = alb_art
            updated["album"] = album
            updated["genre"] = genre
            updated["bad_encoding"] = 0
            updated["is_organized"] = 1 if is_track_organized(
                updated, list(config.library_paths), config.track_naming_format
            ) else 0
            upsert_track(self.db_conn, updated)
            fixed_count += 1

        return fixed_count

    def _on_organize_album(self, album_name: str, album_artist: str):
        tracks = get_album_tracks(self.db_conn, album_name, album_artist)
        if not tracks:
            return
        ready, reason = is_album_ready_to_organize(tracks)
        if not ready:
            QMessageBox.warning(self, "Organization Unavailable", reason)
            return

        roots = [p for p in config.library_paths if Path(p).exists()]
        if not roots:
            QMessageBox.warning(
                self,
                "Organization Unavailable",
                "The library folder that contains this album is not available.",
            )
            return

        default_root = find_containing_root(tracks[0].get("file_path", ""), roots) or roots[0]
        dlg = OrganizeDialog(
            tracks,
            roots,
            default_root,
            config.track_naming_format,
            parent=self,
            theme=self.theme,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        library_root = dlg.chosen_library()
        plan = dlg.plan()
        if not plan:
            return

        token = self.player_controller.suspend_for_file_operation(
            [t.get("file_path", "") for t in tracks]
        )
        updated = tracks
        try:
            success, msg, updated = apply_organization_plan(
                plan,
                library_root,
                self.db_conn,
                config.track_naming_format,
            )
        finally:
            if token:
                path_map = {}
                for old, new_track in zip(tracks, updated):
                    old_path = old.get("file_path", "")
                    new_path = new_track.get("file_path", "")
                    if old_path and new_path:
                        path_map[old_path] = new_path
                self.player_controller.resume_after_file_operation(token, path_map=path_map)

        if success:
            self.refresh_library_view()
            self._update_status_bar_info()
            self.status_info_label.setText(f"✔ Organized album '{album_name}'")
            QMessageBox.information(self, "Success", msg)
        else:
            QMessageBox.critical(self, "Organization Error", msg)

    def _on_open_album_folder(self, album_name: str, album_artist: str):
        tracks = get_album_tracks(self.db_conn, album_name, album_artist)
        if not tracks:
            return

        folder = Path(tracks[0]["file_path"]).parent
        if not open_folder(str(folder)):
            QMessageBox.warning(self, "Folder Not Found", f"Folder does not exist:\n{folder}")

    def _on_track_location_requested(self, track: Dict[str, Any]):
        file_path = (track or {}).get("file_path", "")
        if not file_path:
            return
        if not reveal_file(file_path):
            QMessageBox.warning(
                self,
                "File Not Found",
                f"Could not open the file location:\n{file_path}",
            )

    # ------------------ Drag and Drop Support ------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = Path(url.toLocalFile())
                if p.is_dir() or p.suffix.lower() in IMPORT_DROP_EXTS:
                    event.acceptProposedAction()
                    self.status_info_label.setText("Drop album folder here to import...")
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._update_status_bar_info()
        event.accept()

    def dropEvent(self, event):
        self._update_status_bar_info()
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            event.ignore()
            return

        event.acceptProposedAction()
        target_folder = paths[0] if paths[0].is_dir() else paths[0].parent
        self.start_import_workflow(str(target_folder))

    # ------------------ Import Workflow ------------------
    def _on_click_import(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Album Folder to Import",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self.start_import_workflow(folder)

    def start_import_workflow(self, folder_path: str):
        existing_roots = [p for p in config.library_paths if Path(p).exists()]
        if not existing_roots:
            QMessageBox.warning(
                self,
                "No Library Set",
                "Please configure your library folder before importing albums.",
            )
            self._on_select_directory()
            existing_roots = [p for p in config.library_paths if Path(p).exists()]
            if not existing_roots:
                return

        self.status_info_label.setText(f"Analyzing folder '{Path(folder_path).name}'...")
        QApplication.processEvents()

        try:
            analysis = analyze_import_folder(folder_path, self.db_conn)
        except Exception as e:
            self._update_status_bar_info()
            QMessageBox.critical(
                self,
                "Import Analysis Error",
                f"Could not analyze folder for import:\n{e}",
            )
            return

        dlg = ImportDialog(analysis, self, theme=self.theme)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            edited_album, edited_tracks = dlg.get_result_data()

            # Remember the chosen quality settings for this kind of import and
            # use them for the actual conversion run.
            import_settings = {
                "mode": edited_album.get("import_mode") or analysis.mode,
                "format": edited_album.get("import_format") or analysis.output_format,
                "rate": edited_album.get("import_rate") or analysis.target_rate,
            }
            analysis.mode = import_settings["mode"]
            analysis.output_format = import_settings["format"]
            analysis.target_rate = int(import_settings["rate"])
            try:
                config.set_import_settings(analysis.source_kind, import_settings)
                config.save()
            except Exception:
                pass

            destination = existing_roots[0]
            if hasattr(dlg, "get_destination_library"):
                destination = dlg.get_destination_library() or destination

            progress_dlg = ImportProgressDialog(
                analysis=analysis,
                edited_album=edited_album,
                edited_tracks=edited_tracks,
                library_path=destination,
                naming_format=config.track_naming_format,
                db_path=config.db_path,
                parent=self,
                theme=self.theme,
            )
            progress_dlg.exec()

            if progress_dlg.result_success:
                # Add/refresh the imported album smoothly without full disk rescan
                self.refresh_library_view()
                self.status_info_label.setText(
                    f"✔ Imported '{edited_album['album']}' ({len(progress_dlg.result_imported)} tracks)"
                )
                QMessageBox.information(
                    self,
                    "Import Complete",
                    f"Album '{edited_album['album']}' was successfully imported into your library with {len(progress_dlg.result_imported)} tracks.",
                )
            else:
                self._update_status_bar_info()
                msg = progress_dlg.result_msg or "Import was cancelled or failed."
                if "cancelled" in msg.lower():
                    self.status_info_label.setText("⚠ Import cancelled.")
                else:
                    QMessageBox.critical(self, "Import Failed", f"Failed to import album:\n{msg}")
        else:
            self._update_status_bar_info()

    # ------------------ Frameless Window Resizing & State ------------------
    def _get_resize_edge(self, pos: QPoint):
        if self.isMaximized():
            return None
        m = 6
        edge = None
        if pos.x() <= m:
            edge = Qt.Edge.LeftEdge if edge is None else (edge | Qt.Edge.LeftEdge)
        elif pos.x() >= self.width() - m:
            edge = Qt.Edge.RightEdge if edge is None else (edge | Qt.Edge.RightEdge)
        if pos.y() <= m:
            edge = Qt.Edge.TopEdge if edge is None else (edge | Qt.Edge.TopEdge)
        elif pos.y() >= self.height() - m:
            edge = Qt.Edge.BottomEdge if edge is None else (edge | Qt.Edge.BottomEdge)
        return edge

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._get_resize_edge(event.pos())
            if edge and self.windowHandle():
                self.windowHandle().startSystemResize(edge)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        edge = self._get_resize_edge(event.pos())
        if edge == Qt.Edge.LeftEdge or edge == Qt.Edge.RightEdge:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == Qt.Edge.TopEdge or edge == Qt.Edge.BottomEdge:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge) or edge == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge == (Qt.Edge.TopEdge | Qt.Edge.RightEdge) or edge == (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "title_bar") and self.title_bar:
            self.title_bar.update_max_restore_button(self.isMaximized())

    def closeEvent(self, event):
        self._closing = True
        self._cancel_cover_loading()
        try:
            from malka.ui.image_utils import clear_thumbnail_queue
            clear_thumbnail_queue()
        except Exception:
            pass
        if hasattr(self, "player_controller"):
            try:
                config.volume = self.player_controller.get_volume()
                state = self.player_controller.get_playback_state()
                if state:
                    config.playback_state = state
                    config.save_runtime_state()
                else:
                    config.save_volume()
            except Exception:
                pass
            self.player_controller.stop()
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.cancel()
            self.scanner_thread.wait(2000)
        self.db_conn.close()
        super().closeEvent(event)
