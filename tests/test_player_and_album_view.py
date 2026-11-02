import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Run Qt headlessly
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from malka.config import config
from malka.db import get_connection, init_db, upsert_track
from malka.player import PlayerController, format_time_ms, is_file_playable
from malka.ui.album_card import AlbumCard
from malka.ui.album_detail_view import AlbumDetailView, TrackRowWidget
from malka.ui.main_window import MainWindow
from malka.ui.player_sidebar import PlayerSidebar
from tests.test_core import create_dummy_image, create_dummy_mp3

# Ensure single QApplication instance
app = QApplication.instance() or QApplication([])


class TestPlayerAndAlbumView(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="malka_player_test_"))
        self.db_path = self.test_dir / "library.db"
        init_db(str(self.db_path))
        self.conn = get_connection(str(self.db_path))

        import malka.config
        self.orig_config_file = malka.config.CONFIG_FILE
        malka.config.CONFIG_FILE = self.test_dir / "config.json"

        config.library_path = str(self.test_dir)
        config.db_path = str(self.db_path)

        # Create audio files inside library
        self.mp3_track = self.test_dir / "track1.mp3"
        create_dummy_mp3(self.mp3_track)

        self.m4a_track = self.test_dir / "track2.m4a"
        self.m4a_track.write_bytes(b"dummy m4a content")

        self.flac_track = self.test_dir / "track3.flac"
        self.flac_track.write_bytes(b"dummy flac content")

        # Create an outside folder with an mp3
        self.outside_dir = Path(tempfile.mkdtemp(prefix="malka_outside_"))
        self.outside_mp3 = self.outside_dir / "outside.mp3"
        create_dummy_mp3(self.outside_mp3)

        # Insert album into DB
        upsert_track(self.conn, {
            "file_path": str(self.mp3_track),
            "title": "Alpha Track",
            "artist": "The Rockers",
            "album_artist": "The Rockers",
            "album": "Greatest Hits",
            "year": "2024",
            "genre": "Rock",
            "track_no": "1",
            "disc_no": "1",
            "has_cover": 0,
            "cover_cache_path": "",
            "mtime": 0,
        })
        upsert_track(self.conn, {
            "file_path": str(self.m4a_track),
            "title": "Beta Track",
            "artist": "The Rockers",
            "album_artist": "The Rockers",
            "album": "Greatest Hits",
            "year": "2024",
            "genre": "Rock",
            "track_no": "2",
            "disc_no": "1",
            "has_cover": 0,
            "cover_cache_path": "",
            "mtime": 0,
        })
        self.conn.commit()

    def tearDown(self):
        import malka.config
        malka.config.CONFIG_FILE = self.orig_config_file
        self.conn.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)
        shutil.rmtree(self.outside_dir, ignore_errors=True)

    def test_format_time_ms(self):
        self.assertEqual(format_time_ms(0), "00:00")
        self.assertEqual(format_time_ms(-50), "00:00")
        self.assertEqual(format_time_ms(45000), "00:45")
        self.assertEqual(format_time_ms(125000), "02:05")
        self.assertEqual(format_time_ms(3600000), "60:00")

    def test_is_file_playable(self):
        # 1. Valid MP3 inside library
        ok, msg = is_file_playable(str(self.mp3_track))
        self.assertTrue(ok)
        self.assertEqual(msg, "")

        # 2. Valid M4A inside library
        ok, msg = is_file_playable(str(self.m4a_track))
        self.assertTrue(ok)
        self.assertEqual(msg, "")

        # 3. FLAC is playable (decoded through FFmpeg)
        ok, msg = is_file_playable(str(self.flac_track))
        self.assertTrue(ok)
        self.assertEqual(msg, "")

        # 3b. Formats outside the library are rejected
        ape_file = self.test_dir / "track.ape"
        ape_file.write_bytes(b"dummy")
        ok, msg = is_file_playable(str(ape_file))
        self.assertFalse(ok)
        self.assertIn("Unsupported format", msg)

        # 4. Non-existent file
        ok, msg = is_file_playable(str(self.test_dir / "does_not_exist.mp3"))
        self.assertFalse(ok)
        self.assertIn("does not exist", msg)

        # 5. Outside library file
        ok, msg = is_file_playable(str(self.outside_mp3))
        self.assertFalse(ok)
        self.assertIn("outside the music library folder", msg)

    def test_player_controller_queue_and_controls(self):
        controller = PlayerController()
        album_data = {"album": "Greatest Hits", "album_artist": "The Rockers"}
        tracks = [
            {"file_path": str(self.mp3_track), "title": "Alpha Track"},
            {"file_path": str(self.m4a_track), "title": "Beta Track"},
            {"file_path": str(self.flac_track), "title": "FLAC Track"},
        ]

        # play_album filters out unsupported flac
        started_events = []
        controller.track_started.connect(lambda t, a: started_events.append((t, a)))

        ok = controller.play_album(album_data, tracks)
        self.assertTrue(ok)
        self.assertEqual(len(controller.playlist), 3)  # mp3, m4a and flac
        self.assertEqual(controller.current_index, 0)
        self.assertEqual(controller.current_track["title"], "Alpha Track")
        self.assertEqual(len(started_events), 1)

        # Volume control
        controller.set_volume(75)
        self.assertEqual(controller.get_volume(), 75)
        controller.set_volume(150)  # clamp to 100
        self.assertEqual(controller.get_volume(), 100)

        # Audio device management
        devices = controller.get_audio_devices()
        self.assertIsInstance(devices, list)
        current_dev = controller.get_current_audio_device()
        self.assertIsNotNone(current_dev)

        # Next track
        ok = controller.next_track()
        self.assertTrue(ok)
        self.assertEqual(controller.current_index, 1)
        self.assertEqual(controller.current_track["title"], "Beta Track")

        # Stop playback
        controller.stop()
        self.assertIsNone(controller.current_track)
        self.assertEqual(len(controller.playlist), 0)

    def test_album_detail_view_and_track_rows(self):
        controller = PlayerController()
        view = AlbumDetailView(controller, self.conn)

        album_data = {
            "album": "Greatest Hits",
            "album_artist": "The Rockers",
            "display_artist": "The Rockers",
            "year": "2024",
            "genre": "Rock",
            "cover_path": "",
            "disc_count": 1,
        }

        self.conn.execute(
            "UPDATE tracks SET comment = ? WHERE file_path = ?",
            ("Recorded live in 2024.", str(self.mp3_track)),
        )
        self.conn.commit()
        view.set_album(album_data)

        # Verify header labels and full-width single-line title box
        self.assertEqual(view.title_label.text(), "Greatest Hits")
        self.assertFalse(view.title_label.wordWrap())  # word-wrap disabled as requested
        self.assertEqual(view.artist_label.text(), "The Rockers")
        self.assertIn("2024", view.meta_label.text())
        self.assertIn("Rock", view.meta_label.text())
        self.assertIn("Commentary:", view.comment_label.text())
        self.assertIn("Recorded live in 2024.", view.comment_label.text())
        self.assertFalse(view.comment_label.isHidden())

        # Verify tracks rendered
        self.assertEqual(len(view.track_rows), 2)
        row0 = view.track_rows[0]
        self.assertEqual(row0.title_label.text(), "Alpha Track")
        self.assertEqual(row0.icon_label.text(), "01")

        # Verify no borders on track rows and play album button
        self.assertIn("border: none", row0.styleSheet())
        self.assertIn("border: none", view.btn_play_album.styleSheet())

        # Simulate hover event
        row0.enterEvent(None)
        self.assertIn("border: none", row0.styleSheet())
        self.assertFalse(row0.icon_label.pixmap().isNull())
        row0.leaveEvent(None)
        self.assertIn("border: none", row0.styleSheet())
        self.assertEqual(row0.icon_label.text(), "01")

        # Clicking track row emits track_play_requested
        played_tracks = []
        view.track_play_requested.connect(lambda t, a, all_t: played_tracks.append((t, a, len(all_t))))

        # Simulate track row click
        mouse_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(10.0, 10.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        row0.mouseReleaseEvent(mouse_ev)
        self.assertEqual(len(played_tracks), 1)
        self.assertEqual(played_tracks[0][0]["title"], "Alpha Track")
        self.assertEqual(played_tracks[0][2], 2)

        # Clicking "Play album" button emits first track
        view.btn_play_album.click()
        self.assertEqual(len(played_tracks), 2)
        self.assertEqual(played_tracks[1][0]["title"], "Alpha Track")

        # Right-click on a track offers "Open file location"
        from unittest.mock import patch

        class _FakeContextEvent:
            def globalPos(self):
                return QPoint(0, 0)

        located = []
        row0.location_requested.connect(located.append)
        with patch("PyQt6.QtWidgets.QMenu.exec", return_value=None):
            row0.contextMenuEvent(_FakeContextEvent())
        actions = {a.text(): a for a in row0.context_menu.actions()}
        self.assertIn("Open file location", actions)
        actions["Open file location"].trigger()
        self.assertEqual(located[0]["file_path"], str(self.mp3_track))

    def test_player_sidebar_behavior(self):
        controller = PlayerController()
        sidebar = PlayerSidebar(controller)

        # Initially placeholder values
        self.assertEqual(sidebar.title_label.text(), "No track playing")
        self.assertGreaterEqual(sidebar.device_combo.count(), 1)

        # Start track
        track = {"title": "Bohemian Rhapsody", "artist": "Queen"}
        album = {"album": "A Night at the Opera", "year": "1975"}
        controller.track_started.emit(track, album)

        self.assertEqual(sidebar.title_label.text(), "Bohemian Rhapsody")
        self.assertEqual(sidebar.artist_label.text(), "Queen")
        self.assertIn("A Night at the Opera", sidebar.album_label.text())
        self.assertIn("1975", sidebar.album_label.text())
        self.assertFalse(sidebar.btn_play_pause.icon().isNull())

        # Play/Pause toggle
        controller.state_changed.emit(False)
        self.assertFalse(sidebar.btn_play_pause.icon().isNull())

        controller.state_changed.emit(True)
        self.assertFalse(sidebar.btn_play_pause.icon().isNull())

        # Position updates
        controller.position_changed.emit(65000, 180000)
        self.assertEqual(sidebar.time_current_label.text(), "01:05")
        self.assertEqual(sidebar.time_total_label.text(), "03:00")

        # Clicking stop closes sidebar
        sidebar.show()
        self.assertTrue(sidebar.isVisible())
        sidebar.btn_stop.click()
        self.assertFalse(sidebar.isVisible())

    def test_main_window_audio_navigation(self):
        window = MainWindow()
        window.show()
        window.refresh_library_view()

        # Check album card exists in flow layout
        self.assertEqual(window.main_stack.currentIndex(), 0)  # Grid view

        album_data = {
            "album": "Greatest Hits",
            "album_artist": "The Rockers",
            "display_artist": "The Rockers",
            "year": "2024",
            "cover_path": "",
            "track_count": 2,
        }

        # 1. Clicking an album card opens album detail view
        window._on_album_clicked(album_data)
        self.assertEqual(window.main_stack.currentIndex(), 1)  # Album detail
        self.assertEqual(window.current_view, "album_detail")
        self.assertFalse(window.breadcrumb_bar.isHidden())

        # 2. Starting playback opens persistent sidebar
        self.assertTrue(window.player_sidebar.isHidden())
        window._on_track_play_requested(
            {"file_path": str(self.mp3_track), "title": "Alpha Track"},
            album_data,
            [{"file_path": str(self.mp3_track), "title": "Alpha Track"}],
        )
        self.assertFalse(window.player_sidebar.isHidden())

        # 3. Navigating back or switching views keeps sidebar open and playing
        window._on_back_clicked()
        self.assertEqual(window.main_stack.currentIndex(), 0)
        self.assertFalse(window.player_sidebar.isHidden())

        window.set_view("artists")
        self.assertFalse(window.player_sidebar.isHidden())

        window.set_view("genres")
        self.assertFalse(window.player_sidebar.isHidden())

        # 4. Stopping playback in sidebar closes it
        window.player_sidebar.btn_stop.click()
        self.assertTrue(window.player_sidebar.isHidden())

        # 5. Verify custom title bar and frameless window flags
        self.assertIsNotNone(window.title_bar)
        self.assertEqual(window.title_bar.title_label.text(), "Malka")
        self.assertTrue(bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint))

        # 6. Verify scrollbars are enabled by default (ScrollBarAsNeeded) and can be toggled off (ScrollBarAlwaysOff)
        self.assertEqual(window.scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.assertEqual(window.scroll_area.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(window.album_detail_view.scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        config.show_scrollbars = False
        window.update_scrollbars()
        self.assertEqual(window.scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(window.album_detail_view.scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        config.show_scrollbars = True
        window.update_scrollbars()
        self.assertEqual(window.scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.assertEqual(window.album_detail_view.scroll_area.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 7. Verify segmented view switcher (centered separate row, flush spacing, no borders)
        self.assertIsNotNone(window.view_switcher_frame)
        self.assertEqual(window.view_switcher_frame.layout().spacing(), 0)
        self.assertIn("border: none", window.btn_view_albums.styleSheet())
        self.assertIn("border: none", window.btn_view_artists.styleSheet())
        self.assertIn("border: none", window.btn_view_genres.styleSheet())

        # 8. Verify breadcrumb_bar and view_switcher_frame share the same navigation row layout
        self.assertEqual(window.breadcrumb_bar.parentWidget(), window.view_switcher_frame.parentWidget())

        # 9. Verify sidebar artist & album labels are clickable and navigate properly
        window.player_sidebar._current_artist_name = "The Rockers"
        window.player_sidebar._current_album_name = "Greatest Hits"
        window.player_sidebar._current_album_artist = "The Rockers"
        window.player_sidebar._current_album_data = album_data

        # Click artist in sidebar
        window.player_sidebar.artist_label.mouseReleaseEvent(
            QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        )
        self.assertEqual(window.artist_filter, "The Rockers")
        self.assertEqual(window.current_view, "albums")

        # Click album in sidebar
        window.player_sidebar.album_label.mouseReleaseEvent(
            QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        )
        self.assertEqual(window.current_view, "album_detail")
        self.assertEqual(window.main_stack.currentIndex(), 1)

        window.close()

    def test_view_switcher_permanent_centering(self):
        window = MainWindow()
        window.resize(1000, 700)
        window.show()
        nav_row = window.nav_row_widget
        nav_row.resize(968, 34)
        nav_row.update_positions()

        sw_w = window.view_switcher_frame.width()
        expected_cx = (968 - sw_w) // 2

        # 1. When breadcrumb_bar is hidden
        window.breadcrumb_bar.hide()
        nav_row.update_positions()
        pos_hidden = window.view_switcher_frame.x()
        self.assertEqual(pos_hidden, expected_cx)
        self.assertTrue(window.btn_sort.isVisible())
        self.assertTrue(window.btn_sort.x() > expected_cx + sw_w)

        # 2. When breadcrumb_bar is shown
        window.breadcrumb_bar.set_path([
            ("All albums", lambda: None),
            ("Very Long Artist Name Breadcrumb", None),
        ])
        window.breadcrumb_bar.show()
        nav_row.update_positions()
        pos_shown = window.view_switcher_frame.x()
        self.assertEqual(pos_shown, expected_cx)
        self.assertEqual(pos_hidden, pos_shown)

        # 3. On resize
        nav_row.resize(1200, 34)
        nav_row.update_positions()
        expected_new_cx = (1200 - sw_w) // 2
        self.assertEqual(window.view_switcher_frame.x(), expected_new_cx)
        self.assertTrue(window.btn_sort.x() > expected_new_cx + sw_w)

        # 4. Hidden on album detail view
        window._on_album_clicked({"album": "Test", "album_artist": "Artist", "year": "2020"})
        self.assertTrue(window.btn_sort.isHidden())

        # 5. Restored on back
        window._on_back_clicked()
        self.assertFalse(window.btn_sort.isHidden())

        window.close()

    def test_sidebar_album_navigation_correct_artist_link(self):
        window = MainWindow()
        window.show()

        album_a = {
            "album": "Album Alpha",
            "album_artist": "Artist Alpha",
            "display_artist": "Artist Alpha",
            "year": "2020",
            "cover_path": "",
            "track_count": 5,
        }
        album_b = {
            "album": "Album Beta",
            "album_artist": "Artist Beta",
            "display_artist": "Artist Beta",
            "year": "2022",
            "cover_path": "",
            "track_count": 8,
        }
        window.all_albums_cache = [album_a, album_b]

        # User is viewing Album Beta by Artist Beta
        window.artist_filter = "Artist Beta"
        window._on_album_clicked(album_b)
        self.assertEqual(
            window.breadcrumb_bar.plain_text(),
            "All albums / Artist Beta / Album Beta /",
        )

        # While Album Alpha is playing, user clicks Album Alpha in sidebar
        window._on_sidebar_album_clicked(album_a, "Album Alpha", "Artist Alpha")

        # Now viewing Album Alpha; the breadcrumb path MUST point to Artist Alpha, NOT Artist Beta!
        self.assertEqual(window.current_view, "album_detail")
        self.assertEqual(window.artist_filter, "Artist Alpha")
        self.assertEqual(
            window.breadcrumb_bar.plain_text(),
            "All albums / Artist Alpha / Album Alpha /",
        )

        # Clicking back returns to Artist Alpha's albums
        window._on_back_clicked()
        self.assertEqual(window.current_view, "albums")
        self.assertEqual(window.artist_filter, "Artist Alpha")
        self.assertEqual(window.breadcrumb_bar.plain_text(), "All albums / Artist Alpha /")

        window.close()

    def test_light_theme_and_playback_controls_border(self):
        window = MainWindow()
        window.show()

        # 1. Apply light theme
        window.apply_theme("light")
        self.assertEqual(window.theme, "light")
        self.assertEqual(window.player_sidebar.theme, "light")

        # Light theme controls must have NO border
        sidebar_style_light = window.player_sidebar.styleSheet()
        self.assertIn("QPushButton.controlBtn", sidebar_style_light)
        self.assertIn("QPushButton#sidebarCloseBtn", sidebar_style_light)
        self.assertNotIn("border: 1.5px solid", sidebar_style_light)

        # 2. In Play album button: in light theme icon is white, in dark theme icon is dark
        from malka.ui.image_utils import get_resource_icon
        # Light theme -> white icon
        window.album_detail_view.apply_theme("light")
        # Dark theme -> dark icon
        window.album_detail_view.apply_theme("dark")

        # 3. Apply dark theme
        window.apply_theme("dark")
        self.assertEqual(window.theme, "dark")
        self.assertEqual(window.player_sidebar.theme, "dark")

        # Dark theme controls must have no border
        sidebar_style_dark = window.player_sidebar.styleSheet()
        self.assertIn("QPushButton.controlBtn", sidebar_style_dark)
        self.assertIn("border: none", sidebar_style_dark)
        self.assertIn("border-radius: 19px", sidebar_style_dark)

        # 4. SettingsDialog text color in dark theme is light gray #c9d1d9
        from malka.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(window)
        dlg.apply_theme("dark")
        self.assertIn("color: #c9d1d9;", dlg.styleSheet())
        self.assertEqual(dlg.theme_combo.palette().text().color().name().lower(), "#c9d1d9")

        window.close()

    def test_album_sorting_ascending_by_year(self):
        from malka.db import album_sort_key, parse_year_int, get_all_albums, get_albums_by_artist, get_albums_by_genre
        self.assertEqual(parse_year_int("1993"), 1993)
        self.assertEqual(parse_year_int(2005), 2005)
        self.assertEqual(parse_year_int("2011-04-12"), 2011)
        self.assertEqual(parse_year_int(""), 999999)
        self.assertEqual(parse_year_int(None), 999999)
        self.assertEqual(parse_year_int("NO_DATA"), 999999)

        # Insert multiple albums with varying years
        test_albums = [
            ("Album 2021", "Test Artist", "2021", "SortGenre"),
            ("Album 1993", "Test Artist", "1993", "SortGenre"),
            ("Album 1997", "Test Artist", "1997", "SortGenre"),
            ("Album NoYear", "Test Artist", "", "SortGenre"),
            ("Album 2004", "Test Artist", "2004", "SortGenre"),
        ]
        for alb, art, yr, gn in test_albums:
            track_file = self.test_dir / f"{alb}.mp3"
            create_dummy_mp3(track_file)
            upsert_track(self.conn, {
                "file_path": str(track_file),
                "title": "Track 1",
                "artist": art,
                "album_artist": art,
                "album": alb,
                "year": yr,
                "genre": gn,
                "track_no": "1",
                "disc_no": "1",
                "disc_total": "1",
                "compilation": 0,
                "has_cover": 0,
                "cover_cache_path": "",
                "mtime": 1000.0,
                "duration": 180.0,
            })
        self.conn.commit()

        # 1. Standard mode (artist_year):
        # Sorted by Artist ASC, then Year ASC, then Title ASC.
        # "Test Artist" comes before "The Rockers". Within "Test Artist", sorted by Year ASC.
        all_albums_default = get_all_albums(self.conn)
        album_names_default = [a["album"] for a in all_albums_default]
        expected_default = ["Album 1993", "Album 1997", "Album 2004", "Album 2021", "Album NoYear", "Greatest Hits"]
        self.assertEqual(album_names_default, expected_default)

        # 2. Pure Year ASC mode:
        # Valid years ascending (1993, 1997, 2004, 2021, 2024), missing year last.
        all_albums_year_asc = get_all_albums(self.conn, sort_mode="year_asc")
        expected_year_asc = ["Album 1993", "Album 1997", "Album 2004", "Album 2021", "Greatest Hits", "Album NoYear"]
        self.assertEqual([a["album"] for a in all_albums_year_asc], expected_year_asc)

        # 3. Pure Year DESC mode:
        # Valid years descending (2024, 2021, 2004, 1997, 1993), missing year last.
        all_albums_year_desc = get_all_albums(self.conn, sort_mode="year_desc")
        expected_year_desc = ["Greatest Hits", "Album 2021", "Album 2004", "Album 1997", "Album 1993", "Album NoYear"]
        self.assertEqual([a["album"] for a in all_albums_year_desc], expected_year_desc)

        # 4. Title ASC mode:
        all_albums_title_asc = get_all_albums(self.conn, sort_mode="title_asc")
        expected_title_asc = ["Album 1993", "Album 1997", "Album 2004", "Album 2021", "Album NoYear", "Greatest Hits"]
        self.assertEqual([a["album"] for a in all_albums_title_asc], expected_title_asc)

        # 5. Title DESC mode:
        all_albums_title_desc = get_all_albums(self.conn, sort_mode="title_desc")
        expected_title_desc = ["Greatest Hits", "Album NoYear", "Album 2021", "Album 2004", "Album 1997", "Album 1993"]
        self.assertEqual([a["album"] for a in all_albums_title_desc], expected_title_desc)

        # 6. get_albums_by_artist inherits album sort mode
        expected_artist = ["Album 1993", "Album 1997", "Album 2004", "Album 2021", "Album NoYear"]
        artist_albums = get_albums_by_artist(self.conn, "Test Artist")
        self.assertEqual([a["album"] for a in artist_albums], expected_artist)

        # In year_desc for artist:
        expected_artist_desc = ["Album 2021", "Album 2004", "Album 1997", "Album 1993", "Album NoYear"]
        artist_albums_desc = get_albums_by_artist(self.conn, "Test Artist", sort_mode="year_desc")
        self.assertEqual([a["album"] for a in artist_albums_desc], expected_artist_desc)

        # 7. get_albums_by_genre inherits album sort mode
        genre_albums = get_albums_by_genre(self.conn, "SortGenre")
        self.assertEqual([a["album"] for a in genre_albums], expected_artist)

    def test_categorize_album_ep_and_single(self):
        from malka.db import categorize_album
        # EPs
        self.assertEqual(categorize_album("Debut - EP"), "ep")
        self.assertEqual(categorize_album("Debut - EP 1"), "ep")
        self.assertEqual(categorize_album("Debut - EP 12"), "ep")
        self.assertEqual(categorize_album("Debut - Deluxe EP"), "ep")
        self.assertEqual(categorize_album("Debut - Deluxe EP 2"), "ep")
        self.assertEqual(categorize_album("Debut – Deluxe EP 2"), "ep")
        self.assertEqual(categorize_album("Debut — Deluxe EP 2"), "ep")
        self.assertEqual(categorize_album("Debut - Deluxe Ep"), "ep")
        self.assertEqual(categorize_album("Debut - ep"), "ep")

        # Singles
        self.assertEqual(categorize_album("Human Behaviour - Single"), "single")
        self.assertEqual(categorize_album("Human Behaviour - Single 1"), "single")
        self.assertEqual(categorize_album("Human Behaviour - Deluxe Single"), "single")
        self.assertEqual(categorize_album("Human Behaviour - Deluxe Single 3"), "single")
        self.assertEqual(categorize_album("Human Behaviour – Single 2"), "single")
        self.assertEqual(categorize_album("Human Behaviour — Single 2"), "single")
        self.assertEqual(categorize_album("Human Behaviour - single"), "single")

        # Regular Albums
        self.assertEqual(categorize_album("Homogenic"), "album")
        self.assertEqual(categorize_album("Post"), "album")
        self.assertEqual(categorize_album("Epica"), "album")
        self.assertEqual(categorize_album("Single Ladies"), "album")
        self.assertEqual(categorize_album("The Best of - Live"), "album")

    def test_artist_view_subcategories_and_sorting(self):
        from malka.ui.section_header import SectionHeaderWidget

        # Insert discography with regular albums, EPs, and singles
        artist = "SubcatArtist"
        items = [
            ("Studio Two", artist, "2005"),
            ("Studio One", artist, "1998"),
            ("Summer EP - Deluxe EP 1", artist, "2007"),
            ("Spring EP - EP", artist, "2002"),
            ("Lead Single - Deluxe Single", artist, "2010"),
            ("Promo - Single 1", artist, "2001"),
        ]
        for alb, art, yr in items:
            track_file = self.test_dir / f"{alb}.mp3"
            create_dummy_mp3(track_file)
            upsert_track(self.conn, {
                "file_path": str(track_file),
                "title": "Track 1",
                "artist": art,
                "album_artist": art,
                "album": alb,
                "year": yr,
                "genre": "Pop",
                "track_no": "1",
                "disc_no": "1",
                "disc_total": "1",
                "compilation": 0,
                "has_cover": 0,
                "cover_cache_path": "",
                "mtime": 1000.0,
                "duration": 180.0,
            })
        self.conn.commit()

        window = MainWindow()
        window.db_conn = self.conn
        window.refresh_library_view()

        # Switch to artist view
        window._on_artist_clicked(artist)

        # Inspect layout items
        headers = []
        albums_by_header = {}
        current_header = None

        for i in range(window.flow_layout.count()):
            item = window.flow_layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, SectionHeaderWidget):
                current_header = w.title_text
                headers.append(current_header)
                albums_by_header[current_header] = []
            elif isinstance(w, AlbumCard):
                if current_header:
                    albums_by_header[current_header].append(w.album_data["album"])

        # Should have 3 subcategory sections: Albums, EPs, Singles
        self.assertEqual(headers, ["Albums", "EPs", "Singles"])

        # Regular albums sorted year ASC: Studio One (1998), Studio Two (2005)
        self.assertEqual(albums_by_header["Albums"], ["Studio One", "Studio Two"])

        # EPs sorted year ASC: Spring EP - EP (2002), Summer EP - Deluxe EP 1 (2007)
        self.assertEqual(albums_by_header["EPs"], ["Spring EP - EP", "Summer EP - Deluxe EP 1"])

        # Singles sorted year ASC: Promo - Single 1 (2001), Lead Single - Deluxe Single (2010)
        self.assertEqual(albums_by_header["Singles"], ["Promo - Single 1", "Lead Single - Deluxe Single"])

        # Test artist with ONLY regular albums (no EPs, no singles) -> no section headers
        artist2 = "OnlyAlbumsArtist"
        for alb, yr in [("Album B", "2015"), ("Album A", "2010")]:
            track_file = self.test_dir / f"{alb}.mp3"
            create_dummy_mp3(track_file)
            upsert_track(self.conn, {
                "file_path": str(track_file),
                "title": "Track 1",
                "artist": artist2,
                "album_artist": artist2,
                "album": alb,
                "year": yr,
                "genre": "Pop",
                "track_no": "1",
                "disc_no": "1",
                "disc_total": "1",
                "compilation": 0,
                "has_cover": 0,
                "cover_cache_path": "",
                "mtime": 1000.0,
                "duration": 180.0,
            })
        self.conn.commit()
        window.refresh_library_view()
        window._on_artist_clicked(artist2)

        # Inspect layout items for artist with only regular albums
        sec_headers = [
            window.flow_layout.itemAt(i).widget()
            for i in range(window.flow_layout.count())
            if isinstance(window.flow_layout.itemAt(i).widget(), SectionHeaderWidget)
        ]
        self.assertEqual(len(sec_headers), 0)

        rendered_albums = [
            window.flow_layout.itemAt(i).widget().album_data["album"]
            for i in range(window.flow_layout.count())
            if isinstance(window.flow_layout.itemAt(i).widget(), AlbumCard)
        ]
        self.assertEqual(rendered_albums, ["Album A", "Album B"])

        window.close()

    def test_playback_volume_is_restored_from_config(self):
        original = getattr(config, "volume", 100)
        try:
            config.volume = 34
            controller = PlayerController()
            self.assertEqual(controller.get_volume(), 34)

            controller.set_volume(71)
            self.assertEqual(config.volume, 71)
            self.assertEqual(controller.get_volume(), 71)
            controller.stop()
        finally:
            config.volume = original

    def test_file_operation_suspends_and_resumes_at_new_path(self):
        controller = PlayerController()
        old_path = str(self.mp3_track)
        controller.playlist = [{"file_path": old_path, "title": "Alpha Track"}]
        controller.current_album = {"album": "Greatest Hits", "album_artist": "The Rockers"}
        controller.current_index = 0
        controller.current_track = controller.playlist[0]

        token = controller.suspend_for_file_operation([old_path])
        self.assertIsNotNone(token)
        self.assertTrue(token["suspended"])
        self.assertTrue(controller._operation_suspended)

        # Simulate the organizer moving the file while playback is released.
        new_path = self.test_dir / "moved" / "01. Alpha Track.mp3"
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(old_path, new_path)

        controller.resume_after_file_operation(token, {old_path: str(new_path)})
        self.assertFalse(controller._operation_suspended)
        self.assertEqual(controller.current_track["file_path"], str(new_path))
        self.assertEqual(controller.playlist[0]["file_path"], str(new_path))
        self.assertEqual(controller.current_index, 0)
        controller.stop()

    def test_restore_playback_state_paused_at_position(self):
        controller = PlayerController()
        track = {
            "file_path": str(self.mp3_track),
            "title": "Alpha Track",
            "artist": "The Rockers",
            "album_artist": "The Rockers",
            "album": "Greatest Hits",
            "year": "2024",
            "genre": "Rock",
            "track_no": "1",
            "disc_no": "1",
            "disc_total": "1",
            "duration": 180.0,
            "comment": "",
        }
        state = {
            "file_path": str(self.mp3_track),
            "position_ms": 1234,
            "index": 0,
            "album": {"album": "Greatest Hits", "album_artist": "The Rockers"},
            "tracks": [track],
            "volume": 60,
        }
        self.assertTrue(controller.restore_playback_state(state))
        self.assertEqual(controller.current_track["title"], "Alpha Track")
        self.assertEqual(controller.position_ms(), 1234)
        self.assertFalse(controller.is_playing())  # must not auto-play
        self.assertEqual(controller.get_playback_state()["position_ms"], 1234)
        controller.stop()

    def test_sort_button_and_inheritance(self):
        from malka.config import config
        window = MainWindow()
        window.db_conn = self.conn
        window.show()
        window.refresh_library_view()

        # 1. Default modes
        self.assertEqual(window.album_sort_mode, "artist_year")
        self.assertEqual(window.artist_sort_mode, "name_asc")
        self.assertEqual(window.genre_sort_mode, "name_asc")
        self.assertTrue(window.btn_sort.isVisible())

        # 2. Test sorting options in albums view
        window.set_view("albums")
        window._on_sort_selected("album", "year_desc")
        self.assertEqual(window.album_sort_mode, "year_desc")
        self.assertEqual(config.album_sort_mode, "year_desc")

        # 3. Test sorting in artists view
        window.set_view("artists")
        window._on_sort_selected("artist", "name_desc")
        self.assertEqual(window.artist_sort_mode, "name_desc")
        self.assertEqual(config.artist_sort_mode, "name_desc")

        # 4. Test sorting in genres view
        window.set_view("genres")
        window._on_sort_selected("genre", "name_desc")
        self.assertEqual(window.genre_sort_mode, "name_desc")
        self.assertEqual(config.genre_sort_mode, "name_desc")

        # 5. Inheritance: when drilled down into an artist, sorting mode is inherited from Albums view
        window._on_artist_clicked("The Rockers")
        self.assertEqual(window.current_view, "albums")
        self.assertEqual(window.album_sort_mode, "year_desc")
        self.assertTrue(window.btn_sort.isVisible())

        # Changing sort while inside artist updates album_sort_mode
        window._on_sort_selected("album", "title_asc")
        self.assertEqual(window.album_sort_mode, "title_asc")
        self.assertEqual(config.album_sort_mode, "title_asc")

        # Returning to all albums retains title_asc
        window._on_back_clicked()
        self.assertEqual(window.album_sort_mode, "title_asc")

        # 6. Inheritance in genre drill-down
        window.set_view("genres")
        window._on_genre_clicked("Rock")
        self.assertEqual(window.current_view, "albums")
        self.assertEqual(window.album_sort_mode, "title_asc")

        window.close()


if __name__ == "__main__":
    unittest.main()
