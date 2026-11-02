import shutil
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QFrame

from malka.db import (
    get_album_decade_statistics,
    get_album_statistics,
    get_artist_statistics,
    get_connection,
    get_genre_statistics,
    init_db,
    upsert_track,
)
from malka.ui.main_window import MainWindow
from malka.ui.statistics_view import DecadePieChart, StatBarRow, StatisticsView

app = QApplication.instance()
if not app:
    app = QApplication([])


class TestStatistics(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test_stats.db")
        init_db(self.db_path)
        self.conn = get_connection(self.db_path)

        # Populate a variety of tracks across different artists, albums, years, and genres
        # Decades covered: 1970s, 1980s, 1990s, 2000s, 2010s
        sample_data = [
            # Artist 1: Queen - 4 tracks, 2 albums (1975, 1986)
            ("queen1.mp3", "Bohemian Rhapsody", "Queen", "Queen", "A Night at the Opera", "1975", "Rock"),
            ("queen2.mp3", "Love of My Life", "Queen", "Queen", "A Night at the Opera", "1975", "Rock"),
            ("queen3.mp3", "A Kind of Magic", "Queen", "Queen", "A Kind of Magic", "1986", "Rock"),
            ("queen4.mp3", "Princes of the Universe", "Queen", "Queen", "A Kind of Magic", "1986", "Rock"),

            # Artist 2: Nightwish - 6 tracks, 2 albums (2002, 2004)
            ("nw1.mp3", "Bless the Child", "Nightwish", "Nightwish", "Century Child", "2002", "Symphonic Metal"),
            ("nw2.mp3", "Ever Dream", "Nightwish", "Nightwish", "Century Child", "2002", "Symphonic Metal"),
            ("nw3.mp3", "End of All Hope", "Nightwish", "Nightwish", "Century Child", "2002", "Symphonic Metal"),
            ("nw4.mp3", "Nemo", "Nightwish", "Nightwish", "Once", "2004", "Symphonic Metal"),
            ("nw5.mp3", "Wish I Had an Angel", "Nightwish", "Nightwish", "Once", "2004", "Symphonic Metal"),
            ("nw6.mp3", "Ghost Love Score", "Nightwish", "Nightwish", "Once", "2004", "Symphonic Metal"),

            # Artist 3: Miles Davis - 2 tracks, 1 album (1959)
            ("md1.mp3", "So What", "Miles Davis", "Miles Davis", "Kind of Blue", "1959", "Jazz"),
            ("md2.mp3", "Blue in Green", "Miles Davis", "Miles Davis", "Kind of Blue", "1959", "Jazz"),

            # Artist 4: Daft Punk - 3 tracks, 1 album (2013)
            ("dp1.mp3", "Get Lucky", "Daft Punk", "Daft Punk", "Random Access Memories", "2013", "Electronic"),
            ("dp2.mp3", "Instant Crush", "Daft Punk", "Daft Punk", "Random Access Memories", "2013", "Electronic"),
            ("dp3.mp3", "Lose Yourself to Dance", "Daft Punk", "Daft Punk", "Random Access Memories", "2013", "Electronic"),

            # Artist 5: Nirvana - 2 tracks, 1 album (1991)
            ("nir1.mp3", "Smells Like Teen Spirit", "Nirvana", "Nirvana", "Nevermind", "1991", "Grunge"),
            ("nir2.mp3", "Come As You Are", "Nirvana", "Nirvana", "Nevermind", "1991", "Grunge"),
        ]

        for p, tit, art, alb_art, alb, yr, gen in sample_data:
            track = {
                "file_path": str(Path(self.temp_dir) / p),
                "title": tit,
                "artist": art,
                "album_artist": alb_art,
                "album": alb,
                "year": yr,
                "genre": gen,
                "track_no": "01",
                "disc_no": "1",
                "disc_total": "1",
                "compilation": 0,
                "has_cover": 0,
                "cover_cache_path": "",
                "mtime": 100.0,
                "duration": 200.0,
                "bad_encoding": 0,
            }
            upsert_track(self.conn, track)

    def tearDown(self):
        if self.conn:
            self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_artist_statistics_query(self):
        """Test get_artist_statistics sorted by tracks vs albums."""
        # By tracks
        by_tracks = get_artist_statistics(self.conn, sort_by="tracks")
        self.assertEqual(len(by_tracks), 5)
        self.assertEqual(by_tracks[0]["artist_name"], "Nightwish")
        self.assertEqual(by_tracks[0]["track_count"], 6)
        self.assertEqual(by_tracks[1]["artist_name"], "Queen")
        self.assertEqual(by_tracks[1]["track_count"], 4)

        # By albums
        by_albums = get_artist_statistics(self.conn, sort_by="albums")
        # Nightwish and Queen both have 2 albums, Nightwish has more tracks so comes first
        self.assertEqual(by_albums[0]["artist_name"], "Nightwish")
        self.assertEqual(by_albums[0]["album_count"], 2)
        self.assertEqual(by_albums[1]["artist_name"], "Queen")
        self.assertEqual(by_albums[1]["album_count"], 2)

    def test_album_statistics_query(self):
        """Test get_album_statistics returns albums ordered by track count."""
        albums = get_album_statistics(self.conn, sort_by="tracks")
        self.assertEqual(len(albums), 7)
        # Random Access Memories, Once, Century Child each have 3 tracks
        top3_names = {albums[0]["album"], albums[1]["album"], albums[2]["album"]}
        self.assertIn("Century Child", top3_names)
        self.assertIn("Once", top3_names)
        self.assertIn("Random Access Memories", top3_names)

    def test_album_decade_statistics_query(self):
        """Test 10-year decade buckets starting from 1900."""
        res = get_album_decade_statistics(self.conn)
        self.assertEqual(res["total_albums"], 7)
        decades = res["decades"]
        decade_map = {d["decade"]: d["album_count"] for d in decades}

        # 1950s: Kind of Blue (1959) -> 1
        self.assertEqual(decade_map.get("1950s"), 1)
        # 1970s: A Night at the Opera (1975) -> 1
        self.assertEqual(decade_map.get("1970s"), 1)
        # 1980s: A Kind of Magic (1986) -> 1
        self.assertEqual(decade_map.get("1980s"), 1)
        # 1990s: Nevermind (1991) -> 1
        self.assertEqual(decade_map.get("1990s"), 1)
        # 2000s: Century Child (2002), Once (2004) -> 2
        self.assertEqual(decade_map.get("2000s"), 2)
        # 2010s: Random Access Memories (2013) -> 1
        self.assertEqual(decade_map.get("2010s"), 1)

    def test_genre_statistics_query(self):
        """Test get_genre_statistics."""
        genres = get_genre_statistics(self.conn, sort_by="tracks")
        self.assertEqual(len(genres), 5)
        # Top genre should be Symphonic Metal (6 tracks)
        self.assertEqual(genres[0]["genre"], "Symphonic Metal")
        self.assertEqual(genres[0]["track_count"], 6)

    def test_statistics_view_switch_categories_and_modes(self):
        """Test StatisticsView switches between Artists, Albums, and Genres."""
        view = StatisticsView(self.conn, theme="dark")

        # Category: Artists
        view.set_category("artists")
        self.assertEqual(view.cat_stack.currentIndex(), 0)
        self.assertIn("Artists", view.title_lbl.text())
        self.assertEqual(len(view.artists_view.all_items), 5)

        # Switch to Most albums mode in Artists
        view._on_sub_2_clicked()
        self.assertEqual(view.artist_mode, "albums")

        # Category: Albums
        view.set_category("albums")
        self.assertEqual(view.cat_stack.currentIndex(), 1)
        self.assertIn("Albums", view.title_lbl.text())

        # Switch to Albums by decade in Albums
        view._on_sub_2_clicked()
        self.assertEqual(view.album_mode, "decades")
        self.assertEqual(view.albums_stack.currentIndex(), 1)
        self.assertEqual(view.albums_decade_view.total_albums, 7)

        # Category: Genres
        view.set_category("genres")
        self.assertEqual(view.cat_stack.currentIndex(), 2)
        self.assertIn("Genres", view.title_lbl.text())
        self.assertEqual(len(view.genres_view.all_items), 5)

    def test_pagination_and_pinning(self):
        """Test pagination and search pinning in StatRankView."""
        # Create a synthetic dataset of 25 artists to test top 10 + bottom 10 + pinning
        items = [
            {"artist_name": f"Artist {i:02d}", "track_count": 100 - i, "album_count": 1}
            for i in range(1, 26)
        ]
        view = StatisticsView(self.conn, theme="dark")
        rank_view = view.artists_view
        rank_view.set_items(items, val_unit="tracks")

        # With 25 items, initial top=10, bottom=10. Total 20 visible, 5 in middle.
        self.assertEqual(rank_view.top_container.count(), 10)
        self.assertEqual(rank_view.bottom_container.count(), 10)
        self.assertFalse(rank_view.btn_load_top.isHidden())
        self.assertFalse(rank_view.btn_load_bottom.isHidden())

        # Pin an item in the middle (index 14 -> "Artist 15")
        rank_view._on_completer_activated("Artist 15")
        self.assertEqual(rank_view.pinned_key, "Artist 15")
        self.assertFalse(rank_view.pinned_container.isHidden())
        self.assertEqual(rank_view.pinned_layout.count(), 1)
        pinned_row = rank_view.pinned_layout.itemAt(0).widget()
        self.assertIsInstance(pinned_row, StatBarRow)
        self.assertEqual(pinned_row.rank, 15)

        # Expand top
        rank_view._on_load_more_top()
        self.assertEqual(rank_view.top_count, 20)
        # Now 20 + 10 >= 25, all merged!
        self.assertTrue(rank_view.btn_load_top.isHidden())
        self.assertTrue(rank_view.btn_load_bottom.isHidden())
        self.assertEqual(rank_view.top_container.count(), 25)

    def test_statistics_dark_theme_is_transparent_and_borderless(self):
        view = StatisticsView(self.conn, theme="dark")
        view.set_category("albums")
        view._on_sub_2_clicked()  # decade view
        view.apply_theme("dark")

        # Scroll areas must not paint a stray white/opaque background.
        self.assertIn("transparent", view.albums_rank_view.scroll.styleSheet())
        self.assertIn("transparent", view.albums_decade_view.albums_scroll.styleSheet())
        self.assertFalse(view.albums_rank_view.scroll.viewport().autoFillBackground())

        # Statistics rows and panels are frameless.
        row = StatBarRow(
            {"artist_name": "Queen", "track_count": 3, "album_count": 1},
            rank=1, val=3, max_val=3, total_val=3, item_type="artist", theme="dark",
        )
        self.assertNotIn("1px solid", row.styleSheet())
        top_frame = view.albums_decade_view.findChild(QFrame, "pieTopFrame")
        self.assertNotIn("1px solid", top_frame.styleSheet())

    def test_statistics_thumbnail_uses_full_allocated_size(self):
        row = StatBarRow(
            {"album": "Album", "album_artist": "Artist", "track_count": 3},
            rank=1, val=3, max_val=3, total_val=3,
            item_type="album", theme="dark",
        )
        src = QPixmap(80, 80)
        src.fill(Qt.GlobalColor.red)
        src.setDevicePixelRatio(2.0)
        result = row._round_pixmap(src, 40, is_circle=False)
        self.assertEqual(result.devicePixelRatio(), 2.0)
        self.assertEqual(result.width(), 80)  # 40 logical px at 2x DPR
        self.assertEqual(result.height(), 80)

    def test_main_window_statistics_button_toggle_and_navigation(self):
        """Test clicking Statistics button in MainWindow toggles view and sidebar is preserved."""
        from unittest.mock import MagicMock
        mw = MainWindow(check_first_launch=False)

        # Initially stats mode is False
        self.assertFalse(mw.is_stats_mode)
        self.assertFalse(mw.btn_stats.isChecked())

        # Toggle Statistics ON
        mw.btn_stats.setChecked(True)
        self.assertTrue(mw.is_stats_mode)
        self.assertEqual(mw.main_stack.currentWidget(), mw.statistics_view)

        # Switch views (Artists, Albums, Genres) while in stats mode
        mw.set_view("artists")
        self.assertEqual(mw.statistics_view.current_category, "artists")
        self.assertEqual(mw.main_stack.currentWidget(), mw.statistics_view)

        mw.set_view("genres")
        self.assertEqual(mw.statistics_view.current_category, "genres")

        # Simulate clicking an artist in stats -> turns off stats and navigates to artist's albums
        mw._on_stat_artist_selected("Queen")
        self.assertFalse(mw.btn_stats.isChecked())
        self.assertFalse(mw.is_stats_mode)
        self.assertEqual(mw.artist_filter, "Queen")
        self.assertEqual(mw.current_view, "albums")

        mw.close()


if __name__ == "__main__":
    unittest.main()
