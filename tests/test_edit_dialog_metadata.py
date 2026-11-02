import os
import subprocess
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import imageio_ffmpeg
from PyQt6.QtWidgets import QApplication

from malka.db import get_all_albums, get_connection, init_db, upsert_track
from malka.tags import read_tags
from malka.ui.edit_dialog import EditAlbumDialog

app = QApplication.instance() or QApplication([])


def _make_audio(path: Path, fmt: str) -> Path:
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-ac", "2",
    ]
    cmd += ["-c:a", "flac"] if fmt == "flac" else ["-c:a", "aac", "-b:a", "192k"]
    cmd += [
        "-metadata", "title=Original Title",
        "-metadata", "artist=Original Artist",
        "-metadata", "album_artist=Original Artist",
        "-metadata", "album=Original Album",
        "-metadata", "date=2001",
        "-metadata", "genre=Rock",
        "-metadata", "track=1",
        str(path),
    ]
    subprocess.run(cmd, check=True)
    return path


class TestEditDialogMetadata(unittest.TestCase):
    """Metadata edits must reach the audio files on disk, for every format."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="malka_edit_"))
        self.db = self.tmp / "db.sqlite"
        init_db(str(self.db))
        self.conn = get_connection(str(self.db))

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_album(self, fmt: str, count: int = 2):
        paths = []
        for i in range(1, count + 1):
            ext = ".flac" if fmt == "flac" else ".m4a"
            path = _make_audio(self.tmp / f"{i:02d}. track{ext}", fmt=fmt)
            upsert_track(self.conn, read_tags(str(path)))
            paths.append(path)
        self.conn.commit()
        return paths

    def test_album_edit_updates_every_flac_file(self):
        paths = self._add_album("flac")
        dlg = EditAlbumDialog("Original Album", "Original Artist", self.conn)
        dlg.show()
        dlg.album_edit.setText("New Album")
        dlg.album_artist_edit.setText("New Album Artist")
        dlg.year_edit.setText("1999")
        dlg.genre_edit.setText("Jazz")
        dlg.btn_save.click()

        self.assertEqual(dlg.result(), dlg.DialogCode.Accepted)
        for path in paths:
            tags = read_tags(str(path))
            self.assertEqual(tags["album"], "New Album")
            self.assertEqual(tags["album_artist"], "New Album Artist")
            self.assertEqual(tags["year"], "1999")
            self.assertEqual(tags["genre"], "Jazz")
        self.assertEqual(get_all_albums(self.conn)[0]["album"], "New Album")

    def test_single_track_edit_updates_flac_file(self):
        paths = self._add_album("flac")
        dlg = EditAlbumDialog("Original Album", "Original Artist", self.conn)
        dlg.show()
        dlg.tabs.setCurrentIndex(1)
        dlg.track_list.setCurrentRow(0)
        dlg.st_title.setText("Edited Title")
        dlg.st_year.setText("1971")
        dlg.st_genre.setText("Blues")
        dlg.st_artist.setText("Solo Artist")
        dlg.st_album.setText("Solo Album")
        dlg.st_album_artist.setText("Solo Album Artist")
        dlg.btn_save.click()

        tags = read_tags(str(paths[0]))
        self.assertEqual(tags["title"], "Edited Title")
        self.assertEqual(tags["year"], "1971")
        self.assertEqual(tags["genre"], "Blues")
        self.assertEqual(tags["artist"], "Solo Artist")
        self.assertEqual(tags["album"], "Solo Album")
        self.assertEqual(tags["album_artist"], "Solo Album Artist")

        # The track that was not edited keeps its album-level values.
        other = read_tags(str(paths[1]))
        self.assertEqual(other["album"], "Original Album")
        self.assertEqual(other["year"], "2001")
        self.assertEqual(other["genre"], "Rock")

    def test_single_track_edit_updates_m4a_file(self):
        paths = self._add_album("aac", count=1)
        dlg = EditAlbumDialog("Original Album", "Original Artist", self.conn)
        dlg.show()
        dlg.tabs.setCurrentIndex(1)
        dlg.track_list.setCurrentRow(0)
        dlg.st_title.setText("Edited Title")
        dlg.st_year.setText("1971")
        dlg.st_genre.setText("Blues")
        dlg.btn_save.click()

        tags = read_tags(str(paths[0]))
        self.assertEqual(tags["title"], "Edited Title")
        self.assertEqual(tags["year"], "1971")
        self.assertEqual(tags["genre"], "Blues")

    def test_import_dialog_keeps_per_track_edits(self):
        from malka.importer import analyze_import_folder
        from malka.ui.import_dialog import ImportDialog

        make_dir = self.tmp / "incoming"
        make_dir.mkdir()
        _make_audio(make_dir / "01. track.flac", fmt="flac")

        analysis = analyze_import_folder(str(make_dir), self.conn)
        dlg = ImportDialog(analysis)
        dlg.show()
        dlg.tabs.setCurrentIndex(1)
        dlg.track_list.setCurrentRow(0)
        dlg.st_year.setText("1971")
        dlg.st_genre.setText("Blues")
        dlg.st_album.setText("Per-track Album")
        dlg.st_cover_widget.action = "keep"

        album_data, tracks = dlg.get_result_data()
        self.assertEqual(tracks[0]["year"], "1971")
        self.assertEqual(tracks[0]["genre"], "Blues")
        self.assertEqual(tracks[0]["album"], "Per-track Album")
        # Album-level fields of the visible album tab are not forced over it.
        self.assertEqual(album_data["album"], analysis.album)

    def test_compilation_flag_round_trips_for_flac(self):
        paths = self._add_album("flac", count=1)
        dlg = EditAlbumDialog("Original Album", "Original Artist", self.conn)
        dlg.show()
        dlg.album_artist_edit.setText("")
        dlg.compilation_checkbox.setChecked(True)
        dlg.btn_save.click()

        tags = read_tags(str(paths[0]))
        self.assertEqual(tags["compilation"], 1)
        # An empty album artist becomes "Various Artists" for compilations.
        self.assertEqual(tags["album_artist"], "Various Artists")


if __name__ == "__main__":
    unittest.main()
