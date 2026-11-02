import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from malka.config import config
from malka.db import get_all_albums, get_connection, init_db
from malka.player import is_file_playable
from malka.scanner import LibraryScanner
from malka.tags import write_tags
from tests.test_core import create_dummy_mp3

app = QApplication.instance() or QApplication([])


class TestMultipleLibraries(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="malka_multilib_test_"))
        self.lib_one = self.temp_dir / "Library One"
        self.lib_two = self.temp_dir / "Library Two"
        self.lib_one.mkdir()
        self.lib_two.mkdir()

        self.db_path = str(self.temp_dir / "library.db")
        init_db(self.db_path)
        self.conn = get_connection(self.db_path)

        import malka.config
        self.orig_config_file = malka.config.CONFIG_FILE
        malka.config.CONFIG_FILE = self.temp_dir / "config.json"
        self.orig_paths = list(getattr(config, "library_paths", []))
        self.orig_db_path = config.db_path
        config.db_path = self.db_path
        config.set_library_paths([str(self.lib_one), str(self.lib_two)])

        self.track_one = self.lib_one / "01. First.mp3"
        self.track_two = self.lib_two / "01. Second.mp3"
        create_dummy_mp3(self.track_one)
        create_dummy_mp3(self.track_two)
        write_tags(
            str(self.track_one),
            title="First", artist="Artist One", album_artist="Artist One",
            album="Album One", year="2001", genre="Rock", track_no="1",
        )
        write_tags(
            str(self.track_two),
            title="Second", artist="Artist Two", album_artist="Artist Two",
            album="Album Two", year="2002", genre="Pop", track_no="1",
        )

    def tearDown(self):
        import malka.config
        malka.config.CONFIG_FILE = self.orig_config_file
        config.set_library_paths(self.orig_paths)
        config.db_path = self.orig_db_path
        self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_config_helpers(self):
        self.assertEqual(len(config.library_paths), 2)
        self.assertTrue(config.is_path_in_library(str(self.track_one)))
        self.assertTrue(config.is_path_in_library(str(self.track_two)))
        self.assertEqual(
            config.library_root_for_path(str(self.track_one)),
            str(self.lib_one.resolve()),
        )
        self.assertEqual(
            config.library_root_for_path(str(self.track_two)),
            str(self.lib_two.resolve()),
        )

    def test_scanner_scans_every_library_folder(self):
        scanner = LibraryScanner(config.library_paths, self.db_path)
        scanner.run()
        albums = {a["album"] for a in get_all_albums(self.conn)}
        self.assertIn("Album One", albums)
        self.assertIn("Album Two", albums)

    def test_both_folders_are_playable(self):
        for path in (self.track_one, self.track_two):
            ok, msg = is_file_playable(str(path))
            self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()
