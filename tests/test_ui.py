import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

# Run Qt headlessly
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QPushButton

from malka.config import config
from malka.db import (
    get_album_tracks,
    get_all_artists,
    get_all_genres,
    get_artist_image,
    get_connection,
    init_db,
    set_artist_image,
)
from malka.tags import write_tags
from malka.ui.album_card import AlbumCard
from malka.ui.artist_card import ArtistCard
from malka.ui.edit_dialog import EditAlbumDialog
from malka.ui.genre_card import GenreCard
from malka.ui.main_window import MainWindow
from malka.ui.settings_dialog import SettingsDialog
from tests.test_core import create_dummy_image, create_dummy_mp3

# Ensure single QApplication instance
app = QApplication.instance() or QApplication([])


class TestMalkaUI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="malka_ui_test_"))
        self.db_path = self.test_dir / "ui_library.db"
        init_db(str(self.db_path))
        self.conn = get_connection(str(self.db_path))

        # Isolate config file
        import malka.config
        self.orig_config_file = malka.config.CONFIG_FILE
        malka.config.CONFIG_FILE = self.test_dir / "config.json"

        config.library_path = str(self.test_dir)
        config.db_path = str(self.db_path)

        # Create 1 test album with 2 tracks
        self.audio_file1 = self.test_dir / "track1.mp3"
        self.audio_file2 = self.test_dir / "track2.mp3"
        create_dummy_mp3(self.audio_file1)
        create_dummy_mp3(self.audio_file2)

        self.cover_file = self.test_dir / "cover.jpg"
        create_dummy_image(self.cover_file)

        write_tags(
            str(self.audio_file1),
            title="Song A",
            artist="Artist X",
            album_artist="Artist X",
            album="Masterpiece",
            year="2020",
            genre="Pop",
            track_no="1",
            new_cover_path=str(self.cover_file),
        )
        write_tags(
            str(self.audio_file2),
            title="Song B",
            artist="Artist X",
            album_artist="Artist X",
            album="Masterpiece",
            year="2020",
            genre="Pop",
            track_no="2",
        )

    def tearDown(self):
        import malka.config
        malka.config.CONFIG_FILE = self.orig_config_file
        self.conn.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_settings_dialog(self):
        dlg = SettingsDialog()
        dlg.template_edit.setText("<track_no> - <title>")
        self.assertEqual(dlg.preview_label.text(), "01 - Bohemian Rhapsody.mp3")
        self.assertTrue(dlg.scrollbars_checkbox.isChecked())

        dlg.scrollbars_checkbox.setChecked(False)
        # Save
        dlg.btn_save.click()
        self.assertEqual(config.track_naming_format, "<track_no> - <title>")
        self.assertFalse(config.show_scrollbars)

        # Restore default
        config.show_scrollbars = True
        config.save()

    def test_album_card(self):
        album_data = {
            "album": "Masterpiece",
            "album_artist": "Artist X",
            "display_artist": "Artist X",
            "year": "2020",
            "track_count": 2,
            "cover_path": str(self.cover_file),
        }
        card = AlbumCard(album_data, is_organize_ready=True)
        self.assertEqual(card.album, "Masterpiece")
        self.assertEqual(card.year, "2020")
        self.assertTrue(card.is_organize_ready)

    def test_edit_dialog_album_tab(self):
        # Scan files into DB first
        from malka.scanner import LibraryScanner
        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        dlg = EditAlbumDialog("Masterpiece", "Artist X", self.conn)
        self.assertEqual(len(dlg.tracks), 2)
        self.assertEqual(dlg.album_edit.text(), "Masterpiece")
        self.assertEqual(dlg.artist_edit.text(), "Artist X")

        # Edit album name and year
        dlg.album_edit.setText("Masterpiece Remastered")
        dlg.year_edit.setText("2025")
        dlg.btn_save.click()

        # Verify DB updated
        tracks_after = get_album_tracks(self.conn, "Masterpiece Remastered", "Artist X")
        self.assertEqual(len(tracks_after), 2)
        self.assertEqual(tracks_after[0]["album"], "Masterpiece Remastered")
        self.assertEqual(tracks_after[0]["year"], "2025")

    def test_main_window_render(self):
        from malka.scanner import LibraryScanner
        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        win = MainWindow(check_first_launch=False)
        win.refresh_library_view()
        self.assertEqual(len(win.all_albums_cache), 1)
        self.assertIn("Masterpiece", win.all_albums_cache[0]["album"])

        # Test search filter
        win.search_edit.setText("NonExistent")
        self.assertEqual(win.flow_layout.count(), 0)

        win.search_edit.setText("Masterpiece")
        self.assertEqual(win.flow_layout.count(), 1)
        win.close()

    def test_artist_and_genre_cards(self):
        # Artist card
        art_data = {
            "name": "Queen",
            "album_count": 3,
            "track_count": 42,
            "image_path": "",
            "sample_cover": "",
        }
        art_card = ArtistCard(art_data, self.conn)
        self.assertEqual(art_card.artist_name, "Queen")
        self.assertEqual(art_card.avatar_label.width(), 170)
        self.assertEqual(art_card.avatar_label.height(), 170)
        self.assertFalse(art_card._has_image())

        # Genre card
        genre_data = {
            "genre": "Rock",
            "album_count": 5,
            "track_count": 60,
            "sample_cover": "",
        }
        genre_card = GenreCard(genre_data)
        self.assertEqual(genre_card.genre_name, "Rock")
        self.assertEqual(genre_card.banner_label.width(), 170)
        self.assertEqual(genre_card.banner_label.height(), 170)

    def test_view_switching_and_drill_down(self):
        from malka.scanner import LibraryScanner
        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        win = MainWindow(check_first_launch=False)
        win.refresh_library_view()

        # 1. Default view is albums
        self.assertEqual(win.current_view, "albums")
        self.assertEqual(win.flow_layout.count(), 1)
        self.assertTrue(win.breadcrumb_bar.isHidden())

        # 2. Switch to Artists view
        win.btn_view_artists.click()
        self.assertEqual(win.current_view, "artists")
        self.assertEqual(win.flow_layout.count(), 1)
        self.assertTrue(win.breadcrumb_bar.isHidden())

        # 3. Click artist tile -> Drill down into albums of this artist
        win._on_artist_clicked("Artist X")
        self.assertEqual(win.current_view, "albums")
        self.assertEqual(win.artist_filter, "Artist X")
        self.assertFalse(win.breadcrumb_bar.isHidden())
        self.assertEqual(win.breadcrumb_bar.plain_text(), "All albums / Artist X /")
        self.assertEqual(win.flow_layout.count(), 1)

        # 4. Click the "All albums" breadcrumb root -> all albums
        win._go_all_albums()
        self.assertEqual(win.current_view, "albums")
        self.assertIsNone(win.artist_filter)
        self.assertTrue(win.breadcrumb_bar.isHidden())

        # 5. Switch to Genres view
        win.btn_view_genres.click()
        self.assertEqual(win.current_view, "genres")
        self.assertEqual(win.flow_layout.count(), 1)

        # 6. Click genre tile -> Drill down into albums of this genre
        win._on_genre_clicked("Pop")
        self.assertEqual(win.current_view, "albums")
        self.assertEqual(win.genre_filter, "Pop")
        self.assertFalse(win.breadcrumb_bar.isHidden())
        self.assertEqual(win.breadcrumb_bar.plain_text(), "All albums / Pop /")
        self.assertEqual(win.flow_layout.count(), 1)

        # 7. Click the breadcrumb root -> all albums
        win._go_all_albums()
        self.assertEqual(win.current_view, "albums")
        self.assertIsNone(win.genre_filter)

        # 8. Switch back to Albums
        win.btn_view_albums.click()
        self.assertEqual(win.current_view, "albums")
        self.assertTrue(win.breadcrumb_bar.isHidden())

        win.close()

    def test_album_breadcrumb_path_is_clickable(self):
        win = MainWindow(check_first_launch=False)
        win.show()
        album = {
            "album": "Flowers for Vases",
            "album_artist": "Hayley Williams",
            "display_artist": "Hayley Williams",
            "year": "2021",
            "cover_path": "",
            "track_count": 1,
        }
        win._on_album_clicked(album)
        self.assertEqual(
            win.breadcrumb_bar.plain_text(),
            "All albums / Hayley Williams / Flowers for Vases /",
        )

        # Every parent segment is a real clickable button.
        buttons = {b.toolTip(): b for b in win.breadcrumb_bar.findChildren(QPushButton)}
        self.assertIn("All albums", buttons)
        self.assertIn("Hayley Williams", buttons)

        buttons["Hayley Williams"].click()
        self.assertEqual(win.current_view, "albums")
        self.assertEqual(win.artist_filter, "Hayley Williams")
        self.assertEqual(win.breadcrumb_bar.plain_text(), "All albums / Hayley Williams /")

        buttons = {b.toolTip(): b for b in win.breadcrumb_bar.findChildren(QPushButton)}
        buttons["All albums"].click()
        self.assertEqual(win.current_view, "albums")
        self.assertIsNone(win.artist_filter)
        self.assertTrue(win.breadcrumb_bar.isHidden())
        win.close()

    def test_artist_image_cache_updates_immediately(self):
        win = MainWindow(check_first_launch=False)
        win.all_artists_cache = [
            {"name": "Artist X", "image_path": "", "album_count": 1, "track_count": 2}
        ]
        win._on_artist_image_updated("Artist X", "/tmp/artist-x.jpg")
        self.assertEqual(win.all_artists_cache[0]["image_path"], "/tmp/artist-x.jpg")
        win.close()

    def test_album_card_encoding_badge_and_fix_action(self):
        from unittest.mock import patch

        album_data = {
            "album": "Не плачь!",
            "album_artist": "Старый Приятель",
            "display_artist": "Старый Приятель",
            "year": "1996",
            "track_count": 1,
            "disc_count": 1,
            "has_bad_encoding": True,
            "cover_path": "",
        }
        card = AlbumCard(album_data, db_conn=self.conn)
        self.assertEqual(card.badge_encoding.text(), "Bad tags encoding")

        class _FakeEvent:
            def globalPos(self):
                return QPoint(0, 0)

        with patch("PyQt6.QtWidgets.QMenu.exec", return_value=None):
            card.contextMenuEvent(_FakeEvent())
        actions = {a.text(): a for a in card.context_menu.actions()}
        self.assertTrue(actions["Fix tags encoding"].isEnabled())
        self.assertIn("item:disabled", card.context_menu.styleSheet())

        normal_data = dict(album_data)
        normal_data["has_bad_encoding"] = False
        normal_card = AlbumCard(normal_data, db_conn=self.conn)
        with patch("PyQt6.QtWidgets.QMenu.exec", return_value=None):
            normal_card.contextMenuEvent(_FakeEvent())
        normal_actions = {a.text(): a for a in normal_card.context_menu.actions()}
        self.assertFalse(normal_actions["Fix tags encoding"].isEnabled())

    def test_rendered_views_are_cached_between_switches(self):
        win = MainWindow(check_first_launch=False)
        win.show()
        win.all_albums_cache = [
            {
                "album": "Cached Album",
                "album_artist": "Artist X",
                "display_artist": "Artist X",
                "year": "2020",
                "cover_path": "",
                "track_count": 2,
            }
        ]
        win.current_view = "albums"
        win.refresh_current_view()

        first_card = win.flow_layout.itemAt(0).widget()
        win.set_view("artists")
        win.set_view("albums")
        second_card = win.flow_layout.itemAt(0).widget()
        self.assertIs(first_card, second_card)
        win.close()

    def test_breadcrumb_shows_ampersand_and_even_slash_spacing(self):
        win = MainWindow(check_first_launch=False)
        win.resize(1400, 760)
        win.show()
        album = {
            "album": "Lineage",
            "album_artist": "Bill Brown & Jamie Christopherson",
            "display_artist": "Bill Brown & Jamie Christopherson",
            "year": "2010",
            "cover_path": "",
            "track_count": 1,
        }
        win._on_album_clicked(album)
        self.assertEqual(
            win.breadcrumb_bar.plain_text(),
            "All albums / Bill Brown & Jamie Christopherson / Lineage /",
        )
        buttons = {b.toolTip(): b for b in win.breadcrumb_bar.findChildren(QPushButton)}
        self.assertIn("Bill Brown & Jamie Christopherson", buttons)
        # '&' must be escaped for QPushButton, otherwise Qt treats it as a mnemonic.
        artist_button = buttons["Bill Brown & Jamie Christopherson"]
        self.assertEqual(artist_button.toolTip(), "Bill Brown & Jamie Christopherson")
        self.assertIn("Bill Brown && Jamie", artist_button.text())
        self.assertEqual(win.breadcrumb_bar.layout().spacing(), 0)
        win.close()

    def test_large_album_grid_renders_all_tiles_immediately(self):
        win = MainWindow(check_first_launch=False)
        win.show()
        win.all_albums_cache = [
            {
                "album": f"Album {i}",
                "album_artist": f"Artist {i % 10}",
                "display_artist": f"Artist {i % 10}",
                "year": "2020",
                "cover_path": "",
                "track_count": 1,
            }
            for i in range(130)
        ]
        win.current_view = "albums"
        win.artist_filter = None
        win.genre_filter = None
        win.search_edit.clear()
        win.refresh_current_view()

        # The page opens empty; tiles are then generated incrementally.
        self.assertTrue(win._incremental_albums is not None)

        end = time.time() + 3.0
        while time.time() < end and win._incremental_albums is not None:
            QApplication.processEvents()
            time.sleep(0.005)
        self.assertEqual(win.flow_layout.count(), 130)
        self.assertIsNone(win._incremental_albums)
        win.close()

    def test_artist_image_is_resized_to_340(self):
        from malka.ui.image_utils import ARTIST_IMAGE_SIZE, save_square_artist_image

        src = self.test_dir / "large_artist.jpg"
        dest = self.test_dir / "artist_340.jpg"
        Image.new("RGB", (1200, 800), (30, 90, 150)).save(src)
        self.assertTrue(save_square_artist_image(src, dest, ARTIST_IMAGE_SIZE))
        with Image.open(dest) as img:
            self.assertEqual(img.size, (340, 340))

    def test_artist_image_db_operations(self):
        from malka.scanner import LibraryScanner
        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        set_artist_image(self.conn, "Artist X", "/path/to/artist.jpg")
        self.assertEqual(get_artist_image(self.conn, "Artist X"), "/path/to/artist.jpg")

        artists = get_all_artists(self.conn)
        self.assertEqual(len(artists), 1)
        self.assertEqual(artists[0]["image_path"], "/path/to/artist.jpg")

        # Remove image
        set_artist_image(self.conn, "Artist X", None)
        self.assertIsNone(get_artist_image(self.conn, "Artist X"))

    def test_image_caching_and_lazy_loading(self):
        from malka.ui.image_utils import (
            create_square_placeholder,
            get_cached_square_pixmap,
            load_high_quality_square_pixmap,
        )

        # 1. Test placeholder caching
        p1 = create_square_placeholder(size=170, text_or_icon="🎵", radius_top=8)
        p2 = create_square_placeholder(size=170, text_or_icon="🎵", radius_top=8)
        self.assertIs(p1, p2)

        # 2. Test high quality load & disk/RAM caching
        pix1 = load_high_quality_square_pixmap(self.cover_file, size=170, radius_top=8)
        self.assertIsNotNone(pix1)
        self.assertFalse(pix1.isNull())

        # Second call returns from RAM cache immediately
        pix2 = load_high_quality_square_pixmap(self.cover_file, size=170, radius_top=8)
        self.assertIs(pix1, pix2)

        # Fast cache check returns the pixmap
        cached = get_cached_square_pixmap(self.cover_file, size=170, radius_top=8)
        self.assertIs(cached, pix1)

        # Once cached, no stat()/realpath() filesystem round-trip is allowed.
        from unittest.mock import patch

        with patch("pathlib.Path.stat", side_effect=AssertionError("unexpected disk stat")):
            self.assertIs(
                get_cached_square_pixmap(self.cover_file, size=170, radius_top=8),
                pix1,
            )


if __name__ == "__main__":
    unittest.main()
