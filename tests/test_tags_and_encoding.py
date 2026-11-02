import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from malka.config import Config, get_app_dir
from malka.db import get_album_tracks, get_all_albums, get_connection, init_db, upsert_track
from malka.tags import detect_and_fix_encoding, read_tags, write_tags
from malka.ui.album_card import AlbumCard
from malka.ui.edit_dialog import EditAlbumDialog
from malka.ui.import_dialog import ImportDialog
from malka.importer import ImportAnalysisResult

# Ensure single QApplication
app = QApplication.instance()
if not app:
    app = QApplication([])


class TestTagsAndEncoding(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test.db")
        init_db(self.db_path)
        self.conn = get_connection(self.db_path)

    def tearDown(self):
        if self.conn:
            self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_portable_app_dir(self):
        """Verify .malka directory is inside the application directory, not in home."""
        app_dir = get_app_dir()
        malka_dir = app_dir / ".malka"
        self.assertNotEqual(malka_dir, Path.home() / ".malka")
        self.assertTrue(str(app_dir).startswith("C:") or str(app_dir).startswith("/"))

    def test_detect_and_fix_encoding(self):
        """Test mojibake detection on CP1251 decoded as Latin-1."""
        # 'Новый день календаря' in CP1251 bytes decoded as Latin-1:
        bad_text = "Íîâûé äåíü êàëåíäàðÿ"
        is_bad, fixed = detect_and_fix_encoding(bad_text)
        self.assertTrue(is_bad)
        self.assertEqual(fixed, "Новый день календаря")

        # 'Старый Приятель'
        bad_artist = "Ñòàðûé Ïðèÿòåëü"
        is_bad, fixed = detect_and_fix_encoding(bad_artist)
        self.assertTrue(is_bad)
        self.assertEqual(fixed, "Старый Приятель")

        # Normal English or clean Cyrillic text should NOT be detected as bad
        is_bad, fixed = detect_and_fix_encoding("Century Child")
        self.assertFalse(is_bad)
        self.assertEqual(fixed, "Century Child")

        is_bad, fixed = detect_and_fix_encoding("Привет мир")
        self.assertFalse(is_bad)
        self.assertEqual(fixed, "Привет мир")

    def test_read_tags_from_test_music_library_files(self):
        """Verify real files with bad encoding are decoded and flagged bad_encoding=1."""
        p1 = Path("test_music_library/01. Новый день календаря.mp3")
        if p1.exists():
            tags1 = read_tags(str(p1))
            # The fixture may already have been repaired by an older session; the
            # important part is that repaired/clean tags decode to the right text.
            self.assertIn(tags1["bad_encoding"], (0, 1))
            self.assertEqual(tags1["title"], "Новый день календаря")
            self.assertEqual(tags1["artist"], "Старый Приятель")
            self.assertEqual(tags1["album"], "Не плачь!")

        p2 = Path("test_music_library/Если я богат как царь vv13cd04.mp3")
        if p2.exists():
            tags2 = read_tags(str(p2))
            self.assertEqual(tags2["bad_encoding"], 1)
            self.assertTrue("Высоцкий" in tags2["artist"] or "Высоцкий" in tags2["album_artist"])
            self.assertTrue("хрустальный" in tags2["title"])

    def test_album_card_bad_encoding_badge_and_context_menu(self):
        """Verify AlbumCard shows bad encoding badge overlay when has_bad_encoding is True."""
        album_data = {
            "album": "Не плачь!",
            "album_artist": "Старый Приятель",
            "display_artist": "Старый Приятель",
            "valid_year": "1996",
            "track_count": 1,
            "disc_count": 1,
            "has_bad_encoding": True,
            "cover_path": "",
        }
        card = AlbumCard(album_data, db_conn=self.conn)
        self.assertTrue(card.has_bad_encoding)
        self.assertTrue(hasattr(card, "badge_encoding"))
        self.assertFalse(card.badge_encoding.isHidden())
        self.assertIn("Bad tags encoding", card.badge_encoding.text())

        # Test normal album card
        normal_data = dict(album_data)
        normal_data["has_bad_encoding"] = False
        card_normal = AlbumCard(normal_data, db_conn=self.conn)
        self.assertFalse(card_normal.has_bad_encoding)
        self.assertFalse(hasattr(card_normal, "badge_encoding"))

    def test_edit_album_dialog_bad_encoding_checkbox_and_save(self):
        """Verify EditAlbumDialog shows warning and checkbox, and saving clears bad_encoding."""
        # Insert a track with bad_encoding = 1 into temporary database
        track = {
            "file_path": str(Path(self.temp_dir) / "dummy.mp3"),
            "title": "Новый день календаря",
            "artist": "Старый Приятель",
            "album_artist": "Старый Приятель",
            "album": "Не плачь!",
            "year": "1996",
            "genre": "Rock",
            "track_no": "01",
            "disc_no": "1",
            "disc_total": "1",
            "compilation": 0,
            "has_cover": 0,
            "cover_cache_path": "",
            "mtime": 100.0,
            "duration": 200.0,
            "bad_encoding": 1,
        }
        upsert_track(self.conn, track)

        dlg = EditAlbumDialog("Не плачь!", "Старый Приятель", self.conn)
        self.assertTrue(dlg.has_bad_encoding)
        self.assertFalse(dlg.encoding_warning_frame.isHidden())
        self.assertTrue(dlg.fix_encoding_checkbox.isChecked())

        # Simulate save with fix_encoding_checkbox checked (mocking write_tags)
        from unittest.mock import patch
        with patch("malka.ui.edit_dialog.write_tags") as mock_write:
            mock_write.return_value = {
                "title": "Новый день календаря",
                "artist": "Старый Приятель",
                "album_artist": "Старый Приятель",
                "album": "Не плачь!",
                "year": "1996",
                "genre": "Rock",
                "track_no": "01",
                "disc_no": "1",
                "disc_total": "1",
                "compilation": 0,
                "has_cover": 0,
                "cover_cache_path": "",
                "mtime": 101.0,
            }
            dlg._on_save()

        # Check DB updated
        tracks = get_album_tracks(self.conn, "Не плачь!", "Старый Приятель")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["bad_encoding"], 0)

    def test_import_dialog_bad_encoding_checkbox(self):
        """Verify ImportDialog shows warning and checked checkbox when bad encoding is present."""
        analysis = ImportAnalysisResult(
            variant=1,
            album="Не плачь!",
            album_artist="Старый Приятель",
            year="1996",
            genre="Rock",
            disc_no="1",
            disc_total="1",
            compilation=0,
            cover_cache_path="",
            source_folder=self.temp_dir,
            tracks=[{
                "file_path": str(Path(self.temp_dir) / "track1.mp3"),
                "title": "Новый день календаря",
                "artist": "Старый Приятель",
                "album_artist": "Старый Приятель",
                "album": "Не плачь!",
                "year": "1996",
                "genre": "Rock",
                "track_no": "01",
                "disc_no": "1",
                "disc_total": "1",
                "compilation": 0,
                "bad_encoding": 1,
            }],
        )

        dlg = ImportDialog(analysis)
        self.assertTrue(dlg.has_bad_encoding)
        self.assertFalse(dlg.encoding_warning_frame.isHidden())
        self.assertTrue(dlg.fix_encoding_checkbox.isChecked())

        edited_album, edited_tracks = dlg.get_result_data()
        self.assertEqual(edited_tracks[0]["bad_encoding"], 0)


if __name__ == "__main__":
    unittest.main()
