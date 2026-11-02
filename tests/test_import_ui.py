import os
import tempfile
import unittest
from pathlib import Path

# Headless Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QMimeData, QPoint, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent
from PyQt6.QtWidgets import QApplication, QLabel

from malka.config import config
from malka.db import get_connection, init_db
from malka.importer import ImportAnalysisResult
from malka.ui.import_dialog import ImportDialog
from malka.ui.import_progress_dialog import ImportProgressDialog, ImportWorker
from malka.ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestImportUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="malka_ui_test_"))
        self.db_path = self.temp_dir / "ui_test.db"
        init_db(str(self.db_path))
        self.conn = get_connection(str(self.db_path))

    def tearDown(self):
        self.conn.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_import_dialog_variant_1_and_tab_syncing(self):
        analysis = ImportAnalysisResult(
            variant=1,
            album="Test Album",
            album_artist="Test Artist",
            year="2021",
            genre="Rock",
            disc_no="1",
            disc_total="1",
            compilation=0,
            cover_cache_path="",
            source_folder=str(self.temp_dir),
            tracks=[
                {
                    "title": "Track One",
                    "artist": "Test Artist",
                    "album_artist": "Test Artist",
                    "album": "Test Album",
                    "year": "2021",
                    "genre": "Rock",
                    "track_no": "01",
                    "disc_no": "1",
                    "disc_total": "1",
                },
                {
                    "title": "Track Two",
                    "artist": "Test Artist",
                    "album_artist": "Test Artist",
                    "album": "Test Album",
                    "year": "2021",
                    "genre": "Rock",
                    "track_no": "02",
                    "disc_no": "1",
                    "disc_total": "1",
                },
            ],
        )

        dlg = ImportDialog(analysis)
        dlg.show()

        # Check album fields
        self.assertEqual(dlg.album_edit.text(), "Test Album")
        self.assertEqual(dlg.album_artist_edit.text(), "Test Artist")
        self.assertEqual(dlg.year_edit.text(), "2021")
        self.assertEqual(dlg.genre_edit.text(), "Rock")

        # Check tracks
        self.assertEqual(dlg.track_list.count(), 2)
        self.assertIn("01. Track One", dlg.track_list.item(0).text())
        self.assertIn("02. Track Two", dlg.track_list.item(1).text())

        # Check validation is enabled
        self.assertTrue(dlg.btn_import.isEnabled())

        # Test editing album title updates tracks
        dlg.album_edit.setText("Updated Album")
        album_data, tracks_data = dlg.get_result_data()
        self.assertEqual(album_data["album"], "Updated Album")
        self.assertEqual(tracks_data[0]["album"], "Updated Album")

        # Invalidate required field
        dlg.year_edit.setText("")
        dlg._validate_readiness()
        self.assertFalse(dlg.btn_import.isEnabled())

        dlg.year_edit.setText("2022")
        dlg._validate_readiness()
        self.assertTrue(dlg.btn_import.isEnabled())

        dlg.reject()

    def test_import_dialog_hi_res_image_settings_and_summary(self):
        analysis = ImportAnalysisResult(
            variant=2,
            album="CUE Journey",
            album_artist="Explorer",
            year="2020",
            genre="Electronic",
            sample_rate=96000,
            bits_per_sample=24,
            source_flac_path="album.flac",
            tracks=[
                {"title": "One", "artist": "Explorer", "album_artist": "Explorer",
                 "album": "CUE Journey", "year": "2020", "genre": "Electronic",
                 "track_no": "01", "disc_no": "1", "disc_total": "1", "index01": "00:00:00"},
            ],
        )
        dlg = ImportDialog(analysis)
        dlg.show()

        # Hi-Res image: lossy / lossless-resample / keep Hi-Res, all with splitting.
        modes = [dlg.mode_combo.itemData(i) for i in range(dlg.mode_combo.count())]
        self.assertEqual(modes, ["lossy", "lossless_resample", "copy"])
        self.assertIn("Split into 1 track", dlg.summary_body_lbl.text())

        # Lossy mode exposes MP3/M4A plus the resampling ceiling.
        dlg.mode_combo.setCurrentIndex(modes.index("lossy"))
        self.assertEqual(
            [dlg.format_combo.itemData(i) for i in range(dlg.format_combo.count())],
            ["mp3", "m4a"],
        )
        self.assertTrue(dlg.rate_combo.isVisible())
        self.assertTrue(dlg.rate_combo.itemData(0) == 44100)

        # Lossless resample exposes FLAC/ALAC.
        dlg.mode_combo.setCurrentIndex(modes.index("lossless_resample"))
        self.assertEqual(
            [dlg.format_combo.itemData(i) for i in range(dlg.format_combo.count())],
            ["flac", "alac"],
        )

        # Keep original: format is fixed to the source and the rate picker is hidden.
        dlg.mode_combo.setCurrentIndex(modes.index("copy"))
        self.assertFalse(dlg.format_combo.isEnabled())
        self.assertIn("FLAC", dlg.format_combo.currentText())
        self.assertFalse(dlg.rate_combo.isVisible())

        # Summary always shows album, artist, year and the destination path.
        summary = dlg.summary_body_lbl.text()
        title = dlg.summary_title_lbl.text()
        self.assertIn("CUE Journey", title)
        self.assertIn("Explorer", title)
        self.assertIn("2020", title)
        self.assertIn("Destination:", summary)
        self.assertIn("Explorer", summary)

        # Destination selector exists and follows the configured library roots.
        self.assertIsNotNone(dlg.destination_combo)
        self.assertEqual(dlg.destination_combo.count(), max(1, len(config.library_paths)))

        dlg.reject()

    def test_import_dialog_mp3_tracks_have_no_conversion_choice(self):
        analysis = ImportAnalysisResult(
            variant=1,
            album="Lossy Album",
            album_artist="Lossy Artist",
            year="2022",
            genre="Pop",
            sample_rate=44100,
            bits_per_sample=16,
            tracks=[
                {"title": "One", "artist": "Lossy Artist", "album_artist": "Lossy Artist",
                 "album": "Lossy Album", "year": "2022", "genre": "Pop",
                 "track_no": "01", "disc_no": "1", "disc_total": "1"},
            ],
        )
        dlg = ImportDialog(analysis)
        dlg.show()
        self.assertEqual(
            [dlg.mode_combo.itemData(i) for i in range(dlg.mode_combo.count())],
            ["copy"],
        )
        self.assertFalse(dlg.format_combo.isEnabled())
        self.assertIn("no re-encoding", dlg.mode_combo.currentText())
        self.assertFalse(dlg.rate_combo.isVisible())
        dlg.reject()

    def test_main_window_drag_drop_accepts_folder(self):
        win = MainWindow(check_first_launch=False)
        win.show()

        # Create drag enter event with a directory URL
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.temp_dir))])

        event = QDragEnterEvent(
            QPoint(100, 100),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        win.dragEnterEvent(event)
        self.assertTrue(event.isAccepted())

        # Create drag enter event with an invalid non-audio file
        txt_file = self.temp_dir / "notes.txt"
        txt_file.write_text("hello")
        mime_bad = QMimeData()
        mime_bad.setUrls([QUrl.fromLocalFile(str(txt_file))])
        event_bad = QDragEnterEvent(
            QPoint(100, 100),
            Qt.DropAction.CopyAction,
            mime_bad,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        win.dragEnterEvent(event_bad)
        self.assertFalse(event_bad.isAccepted())

        win.close()

    def test_import_progress_dialog_updates(self):
        analysis = ImportAnalysisResult(
            variant=1,
            album="Test Progress Album",
            album_artist="Test Artist",
            year="2023",
            genre="Rock",
            source_folder=str(self.temp_dir),
            tracks=[{"title": "Track 1"}, {"title": "Track 2"}],
        )
        edited_album = {
            "album": "Test Progress Album",
            "album_artist": "Test Artist",
            "year": "2023",
            "genre": "Rock",
            "compilation": 0,
            "cover_cache_path": "",
            "remove_cover": False,
        }

        # Subclass or instantiate without auto-running worker
        dlg = ImportProgressDialog(
            analysis=analysis,
            edited_album=edited_album,
            edited_tracks=analysis.tracks,
            library_path=str(self.temp_dir),
            naming_format="<track_no>. <title>",
            db_path=str(self.db_path),
            auto_start=False,
        )
        dlg.show()

        # Test UI progress update slots
        dlg._on_progress_update(1, 2, "Encoding track 1/2: Track 1", "[50.0%] 1:00/2:00 (52x), ETA 0:01", 42)
        self.assertEqual(dlg.phase_lbl.text(), "Encoding track 1/2: Track 1")
        self.assertIn("ETA 0:01", dlg.detail_lbl.text())
        self.assertEqual(dlg.counter_lbl.text(), "Track 1 of 2")
        self.assertEqual(dlg.progress_bar.value(), 42)

        # Test finish slot
        dlg._on_finished_import(True, "Success", ["file1.m4a", "file2.m4a"])
        self.assertTrue(dlg.result_success)
        self.assertEqual(len(dlg.result_imported), 2)
        dlg.accept()

    def test_dialogs_theme_switching_light_and_dark(self):
        from malka.ui.edit_dialog import EditAlbumDialog, BaseAlbumEditDialog

        analysis = ImportAnalysisResult(
            variant=1,
            album="Theme Album",
            album_artist="Theme Artist",
            year="2024",
            genre="Ambient",
            tracks=[{"title": "Track 1"}],
        )

        # 1. ImportDialog light & dark
        import_dlg = ImportDialog(analysis, theme="light")
        self.assertEqual(import_dlg.theme, "light")
        self.assertIn("#f6f8fa", import_dlg.styleSheet())
        self.assertIn("#ffffff", import_dlg.banner.styleSheet())
        self.assertEqual(import_dlg.album_cover_widget.theme, "light")

        import_dlg.apply_theme("dark")
        self.assertEqual(import_dlg.theme, "dark")
        self.assertIn("#0d1117", import_dlg.styleSheet())
        self.assertIn("#161b22", import_dlg.banner.styleSheet())
        self.assertEqual(import_dlg.album_cover_widget.theme, "dark")
        import_dlg.close()

        # 2. BaseAlbumEditDialog / EditAlbumDialog light & dark
        edit_dlg = BaseAlbumEditDialog(tracks=analysis.tracks, theme="light")
        self.assertEqual(edit_dlg.theme, "light")
        self.assertIn("#f6f8fa", edit_dlg.styleSheet())
        self.assertEqual(edit_dlg.album_cover_widget.theme, "light")

        edit_dlg.apply_theme("dark")
        self.assertEqual(edit_dlg.theme, "dark")
        self.assertIn("#0d1117", edit_dlg.styleSheet())
        self.assertEqual(edit_dlg.album_cover_widget.theme, "dark")
        edit_dlg.close()

        # 3. ImportProgressDialog light & dark
        progress_dlg = ImportProgressDialog(
            analysis=analysis,
            edited_album={"album": "Theme Album", "album_artist": "Theme Artist"},
            edited_tracks=analysis.tracks,
            library_path=str(self.temp_dir),
            naming_format="<track_no>. <title>",
            db_path=str(self.db_path),
            auto_start=False,
            theme="light",
        )
        self.assertEqual(progress_dlg.theme, "light")
        self.assertIn("#f6f8fa", progress_dlg.styleSheet())

        progress_dlg.apply_theme("dark")
        self.assertEqual(progress_dlg.theme, "dark")
        self.assertIn("#0d1117", progress_dlg.styleSheet())
        progress_dlg.close()


if __name__ == "__main__":
    unittest.main()
