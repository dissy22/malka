import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Set headless Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from malka.config import config
from malka.db import get_album_tracks, get_all_albums, get_connection, init_db
from malka.organizer import is_album_ready_to_organize, organize_album
from malka.scanner import LibraryScanner
from malka.tags import read_tags
from malka.ui.edit_dialog import EditAlbumDialog
from malka.ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestLibraryOperations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="malka_real_test_"))
        self.test_lib_dir = self.temp_dir / "music"
        self.test_db_path = self.temp_dir / "library.db"

        # Copy real test_music_library if present
        if Path("test_music_library").exists():
            shutil.copytree("test_music_library", self.test_lib_dir)

        # Isolate config
        import malka.config
        self.orig_config_file = malka.config.CONFIG_FILE
        malka.config.CONFIG_FILE = self.temp_dir / "config.json"

        config.library_path = str(self.test_lib_dir)
        config.db_path = str(self.test_db_path)

        init_db(str(self.test_db_path))
        self.conn = get_connection(str(self.test_db_path))

    def tearDown(self):
        import malka.config
        malka.config.CONFIG_FILE = self.orig_config_file
        self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_library_scan_layout_edit_and_organize(self):
        if not self.test_lib_dir.exists():
            self.skipTest("test_music_library folder not found")

        # 1. Scan
        scanner = LibraryScanner(str(self.test_lib_dir), str(self.test_db_path), force_rescan=True)
        scanner.run()

        albums = get_all_albums(self.conn)
        self.assertGreaterEqual(len(albums), 1)

        # 2. MainWindow rendering and non-overlapping cards
        win = MainWindow(check_first_launch=False)
        win.resize(1000, 700)
        win.show()
        win.refresh_library_view()
        app.processEvents()

        self.assertEqual(win.flow_layout.count(), len(albums))
        positions = []
        for i in range(win.flow_layout.count()):
            w = win.flow_layout.itemAt(i).widget()
            positions.append((w.pos().x(), w.pos().y()))

        # Ensure no overlap
        self.assertEqual(len(set(positions)), len(albums))
        win.close()

        # 3. Edit Album
        dlg = EditAlbumDialog("(Oh), Common Life", "Fireworks", self.conn)
        dlg.album_edit.setText("(Oh), Common Life (Expanded)")
        dlg.year_edit.setText("2015")
        dlg.genre_edit.setText("Pop Punk")
        dlg.btn_save.click()

        updated_tracks = get_album_tracks(self.conn, "(Oh), Common Life (Expanded)", "Fireworks")
        self.assertEqual(len(updated_tracks), 11)
        self.assertEqual(updated_tracks[0]["album"], "(Oh), Common Life (Expanded)")
        self.assertEqual(updated_tracks[0]["year"], "2015")

        # 4. Organize
        ready, _ = is_album_ready_to_organize(updated_tracks)
        self.assertTrue(ready)

        success, msg, _ = organize_album(
            library_path=str(self.test_lib_dir),
            tracks=updated_tracks,
            template="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertTrue(success)

        expected_folder = self.test_lib_dir / "Fireworks" / "2015 - (Oh), Common Life (Expanded)"
        self.assertTrue(expected_folder.exists())
        self.assertEqual(len(list(expected_folder.glob("*.mp3"))), 11)
        self.assertTrue((expected_folder / "01. Glowing Crosses.mp3").exists())

    def test_the_beatles_white_album_multi_disc(self):
        beatles_src = Path("The Beatles (White Album)")
        if not beatles_src.exists():
            self.skipTest("The Beatles (White Album) folder not found")

        beatles_target = self.temp_dir / "Beatles_Lib"
        shutil.copytree(beatles_src, beatles_target / "The Beatles (White Album)")

        beatles_db = self.temp_dir / "beatles.db"
        init_db(str(beatles_db))
        conn = get_connection(str(beatles_db))

        # 1. Scan
        scanner = LibraryScanner(str(beatles_target), str(beatles_db), force_rescan=True)
        scanner.run()

        albums = get_all_albums(conn)
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["album"], "The Beatles (White Album)")
        self.assertEqual(albums[0]["track_count"], 30)
        self.assertEqual(albums[0]["disc_count"], 2)

        # 2. Tracks ordering
        tracks = get_album_tracks(conn, "The Beatles (White Album)", "The Beatles")
        self.assertEqual(len(tracks), 30)

        # Disc 1 Track 1
        self.assertEqual(tracks[0]["title"], "Back In the U.S.S.R.")
        self.assertEqual(tracks[0]["disc_no"], "1")
        self.assertEqual(tracks[0]["track_no"], "01")

        # Disc 1 Track 17 (last of Disc 1)
        self.assertEqual(tracks[16]["title"], "Julia")
        self.assertEqual(tracks[16]["disc_no"], "1")
        self.assertEqual(tracks[16]["track_no"], "17")

        # Disc 2 Track 1 (first of Disc 2)
        self.assertEqual(tracks[17]["title"], "Birthday")
        self.assertEqual(tracks[17]["disc_no"], "2")
        self.assertEqual(tracks[17]["track_no"], "01")

        # Disc 2 Track 13 (last of Disc 2)
        self.assertEqual(tracks[29]["title"], "Good Night")
        self.assertEqual(tracks[29]["disc_no"], "2")
        self.assertEqual(tracks[29]["track_no"], "13")

        # 3. Check Edit dialog displays CD labels in track list
        dlg = EditAlbumDialog("The Beatles (White Album)", "The Beatles", conn)
        item0 = dlg.track_list.item(0).text()
        item17 = dlg.track_list.item(17).text()
        self.assertIn("[CD 1]", item0)
        self.assertIn("01. Back In the U.S.S.R.", item0)
        self.assertIn("[CD 2]", item17)
        self.assertIn("01. Birthday", item17)
        dlg.reject()

        # 4. Organize multi-disc album
        ready, _ = is_album_ready_to_organize(tracks)
        self.assertTrue(ready)

        organized_lib = self.temp_dir / "Organized_Music"
        organized_lib.mkdir()

        success, msg, _ = organize_album(
            library_path=str(organized_lib),
            tracks=tracks,
            template="<track_no>. <title>",
            db_conn=conn,
        )
        self.assertTrue(success)

        # Ensure CD 1 and CD 2 subdirectories exist
        cd1_dir = organized_lib / "The Beatles" / "1968 - The Beatles (White Album)" / "CD 1"
        cd2_dir = organized_lib / "The Beatles" / "1968 - The Beatles (White Album)" / "CD 2"
        self.assertTrue(cd1_dir.exists())
        self.assertTrue(cd2_dir.exists())

        # Check track counts in each CD folder
        cd1_files = list(cd1_dir.glob("*.m4a"))
        cd2_files = list(cd2_dir.glob("*.m4a"))
        self.assertEqual(len(cd1_files), 17)
        self.assertEqual(len(cd2_files), 13)

        # Check that both track 1s exist in their respective CD folders without collision
        self.assertTrue((cd1_dir / "01. Back In the U.S.S.R.m4a").exists())
        self.assertTrue((cd2_dir / "01. Birthday.m4a").exists())

        conn.close()


if __name__ == "__main__":
    unittest.main()
