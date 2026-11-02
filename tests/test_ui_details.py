import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from malka.db import get_connection, init_db, upsert_track
from malka.player import PlayerController
from malka.ui.album_detail_view import AlbumDetailView

app = QApplication.instance() or QApplication([])


def make_track(path: Path, *, title="Song", artist="Artist", album="Album",
               year="2020", genre="Rock") -> dict:
    return {
        "file_path": str(path),
        "title": title,
        "artist": artist,
        "album_artist": artist,
        "album": album,
        "year": year,
        "genre": genre,
        "track_no": "01",
        "disc_no": "1",
        "disc_total": "1",
        "compilation": 0,
        "has_cover": 0,
        "cover_cache_path": "",
        "mtime": 0.0,
        "duration": 10.0,
        "comment": "",
    }


class TestAlbumDetailLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="malka_links_"))
        self.db = self.tmp / "db.sqlite"
        init_db(str(self.db))
        self.conn = get_connection(str(self.db))
        upsert_track(self.conn, make_track(self.tmp / "01. song.flac"))
        self.conn.commit()
        self.album = {
            "album": "Album",
            "album_artist": "Artist",
            "display_artist": "Artist",
            "year": "2020",
            "track_count": 1,
            "disc_count": 1,
        }
        self.view = AlbumDetailView(PlayerController(), self.conn)
        self.view.set_album(self.album)

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_artist_is_clickable(self):
        captured = []
        self.view.artist_clicked.connect(captured.append)
        self.view.artist_label.clicked.emit()
        self.assertEqual(captured, ["Artist"])

    def test_year_link_opens_year_search(self):
        captured = []
        self.view.year_clicked.connect(captured.append)
        self.view._on_meta_link("year:2020")
        self.assertEqual(captured, ["2020"])

    def test_genre_link_opens_genre(self):
        captured = []
        self.view.genre_clicked.connect(captured.append)
        self.view._on_meta_link("genre:Rock")
        self.assertEqual(captured, ["Rock"])

    def test_meta_label_contains_year_and_genre_links(self):
        html = self.view.meta_label.text()
        self.assertIn('href="year:2020"', html)
        self.assertIn('href="genre:Rock"', html)

    def test_second_click_on_current_track_toggles_pause(self):
        track = self.view.tracks[0]
        self.view.controller.current_track = track
        self.view.controller.toggle_play_pause = MagicMock()

        played = []
        self.view.track_play_requested.connect(lambda *args: played.append(args))
        self.view._on_track_clicked(track)

        self.view.controller.toggle_play_pause.assert_called_once()
        self.assertEqual(played, [])

    def test_other_track_still_plays(self):
        other = dict(self.view.tracks[0], file_path=str(self.tmp / "02. other.flac"))
        self.view.controller.current_track = self.view.tracks[0]
        self.view.controller.toggle_play_pause = MagicMock()

        played = []
        self.view.track_play_requested.connect(lambda *args: played.append(args))
        self.view._on_track_clicked(other)

        self.view.controller.toggle_play_pause.assert_not_called()
        self.assertEqual(len(played), 1)


class TestIcons(unittest.TestCase):
    def test_toolbar_icons_are_tinted_per_theme(self):
        from malka.ui.image_utils import get_tinted_icon

        for theme in ("dark", "light"):
            icon = get_tinted_icon("add_library_path.png", size=20, theme=theme)
            self.assertFalse(icon.isNull())
            pix = icon.pixmap(20, 20).toImage()
            opaque = [
                pix.pixelColor(x, y)
                for x in range(pix.width())
                for y in range(pix.height())
                if pix.pixelColor(x, y).alpha() > 200
            ]
            self.assertTrue(opaque)
            color = opaque[0]
            expected = (139, 148, 158) if theme == "dark" else (101, 109, 118)
            self.assertEqual((color.red(), color.green(), color.blue()), expected)

    def test_emoji_window_icon(self):
        from malka.ui.image_utils import emoji_icon

        icon = emoji_icon("🎵")
        self.assertFalse(icon.isNull())
        self.assertIn(256, [size.width() for size in icon.availableSizes()])


class TestAboutDialog(unittest.TestCase):
    def test_about_contains_contacts_site_and_license(self):
        from malka.ui.about_dialog import AboutDialog, SUPPORT_URL

        dlg = AboutDialog()
        text = " ".join(
            label.text() for label in dlg.findChildren(QLabel)
        )
        self.assertIn("Pavel Distrianov", text)
        self.assertIn("gml.paul93@gmail.com", text)
        self.assertIn("t.me/paveldistrianov", text)
        self.assertIn("dps.com.ru/malka", text)
        self.assertIn("GPLv2", text)
        self.assertTrue(dlg.btn_support.text())
        self.assertEqual(dlg.btn_support.toolTip(), SUPPORT_URL)


class TestTopFade(unittest.TestCase):
    def test_fade_strength_follows_scroll(self):
        from malka.ui.main_window import MainWindow

        class Fake:
            value = -1

            def set_strength(self, value):
                self.value = value

        fade = Fake()
        MainWindow._update_top_fade(fade, 0)
        self.assertEqual(fade.value, 0.0)
        MainWindow._update_top_fade(fade, 20)
        self.assertAlmostEqual(fade.value, 0.5, places=2)
        MainWindow._update_top_fade(fade, 999)
        self.assertEqual(fade.value, 1.0)


class TestStatusBar(unittest.TestCase):
    def test_status_bar_has_no_library_location(self):
        harness = MainWindowStub()
        harness._update_status_bar_info()
        text = harness.status_info_label.text()
        self.assertIn("Albums:", text)
        self.assertIn("Tracks:", text)
        self.assertNotIn("/tmp", text)
        self.assertNotIn("Folder", text)


class MainWindowStub:
    """Minimal object exposing what _update_status_bar_info needs."""

    def __init__(self):
        from malka.ui.main_window import MainWindow

        self._update_status_bar_info = MainWindow._update_status_bar_info.__get__(self)
        self._now_playing_text = MainWindow._now_playing_text.__get__(self)
        self._current_track_bitrate = MainWindow._current_track_bitrate.__get__(self)
        self.all_albums_cache = [{"album": "A", "track_count": 2}]
        self.status_info_label = QLabel()
        self.player_controller = type("C", (), {"current_track": None, "position_ms": lambda self: 0})()
        self._track_info = None
        self._track_bitrates = None


if __name__ == "__main__":
    unittest.main()
