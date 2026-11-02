import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from malka.cue import cue_time_to_seconds
from malka.db import get_all_albums, get_connection, init_db
from malka.formats import MODE_COPY, MODE_LOSSLESS_RESAMPLE
from malka.importer import (
    ImportAnalysisResult,
    execute_import,
    find_ffmpeg_executable,
)


class TestEncoders(unittest.TestCase):
    def test_find_ffmpeg_finds_imageio_ffmpeg(self):
        with patch("shutil.which", return_value=None):
            ffmpeg_path = find_ffmpeg_executable()
        self.assertIsNotNone(ffmpeg_path)
        self.assertTrue(Path(ffmpeg_path).exists())

    def test_cue_time_to_seconds(self):
        self.assertAlmostEqual(cue_time_to_seconds("00:00:00"), 0.0)
        self.assertAlmostEqual(cue_time_to_seconds("01:00:00"), 60.0)
        self.assertAlmostEqual(cue_time_to_seconds("02:30:00"), 150.0)
        self.assertAlmostEqual(cue_time_to_seconds("00:01:75"), 2.0)
        self.assertAlmostEqual(cue_time_to_seconds("01:23:45"), 83.6, places=2)
        self.assertAlmostEqual(cue_time_to_seconds("03:15"), 195.0)
        self.assertEqual(cue_time_to_seconds(""), 0.0)
        self.assertEqual(cue_time_to_seconds(None), 0.0)


class TestExecuteImport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="malka_linux_test_"))
        self.lib_dir = self.temp_dir / "library"
        self.lib_dir.mkdir()
        self.db_path = self.temp_dir / "test.db"
        init_db(str(self.db_path))
        self.conn = get_connection(str(self.db_path))
        self.src_flac = self.temp_dir / "album.flac"
        self.src_flac.write_bytes(b"dummyflac")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _tracks(self, count=2):
        return [
            {
                "track_no": f"{i + 1:02d}",
                "title": f"Track {i + 1}",
                "artist": "Artist",
                "album_artist": "Artist",
                "album": "Album",
                "year": "2024",
                "genre": "Rock",
                "source_path": str(self.src_flac),
                "sample_rate": 96000,
                "bits_per_sample": 24,
                "index01": "00:00:00" if i == 0 else "00:01:00",
                "disc_no": "1",
                "disc_total": "1",
                "compilation": 0,
            }
            for i in range(count)
        ]

    def _album(self, mode, fmt="flac", rate=48000):
        return {
            "album": "Album",
            "album_artist": "Artist",
            "year": "2024",
            "genre": "Rock",
            "compilation": 0,
            "cover_cache_path": "",
            "remove_cover": False,
            "import_mode": mode,
            "import_format": fmt,
            "import_rate": rate,
        }

    def _analysis(self, variant=2, tracks=None):
        tracks = tracks if tracks is not None else self._tracks()
        cue = self.temp_dir / "album.cue"
        cue.write_text("dummy cue", encoding="utf-8")
        return ImportAnalysisResult(
            variant=variant,
            album="Album",
            album_artist="Artist",
            year="2024",
            genre="Rock",
            source_folder=str(self.temp_dir),
            source_flac_path=str(self.src_flac),
            cue_file_path=str(cue),
            sample_rate=96000,
            bits_per_sample=24,
            source_format="flac",
            tracks=tracks,
        )

    @patch("malka.importer.find_ffmpeg_executable", return_value=None)
    def test_conversion_without_ffmpeg_returns_clear_error(self, _mock):
        analysis = self._analysis()
        success, msg, imported = execute_import(
            analysis=analysis,
            edited_album=self._album(MODE_LOSSLESS_RESAMPLE),
            edited_tracks=analysis.tracks,
            library_path=str(self.lib_dir),
            naming_format="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertFalse(success)
        self.assertIn("FFmpeg was not found", msg)
        self.assertEqual(imported, [])

    @patch("malka.importer.find_ffmpeg_executable")
    @patch("subprocess.Popen")
    def test_image_split_without_reencode_uses_stream_copy(self, mock_popen, mock_find):
        fake_ffmpeg = self.temp_dir / "fake_ffmpeg"
        fake_ffmpeg.touch()
        mock_find.return_value = fake_ffmpeg

        captured = []

        def side_effect(cmd, **kwargs):
            captured.append(cmd)
            Path(cmd[-1]).write_bytes(b"fLaC-dummy")
            proc = MagicMock()
            proc.communicate.return_value = ("", "")
            proc.returncode = 0
            proc.poll.return_value = 0
            return proc

        mock_popen.side_effect = side_effect

        analysis = self._analysis()
        with patch("malka.importer.write_tags"):
            with patch("malka.importer.read_tags", return_value={
                "file_path": "x", "title": "x", "artist": "x", "album_artist": "x",
                "album": "x", "year": "2024", "genre": "Rock", "track_no": "01",
                "disc_no": "1", "disc_total": "1", "compilation": 0, "has_cover": 0,
                "cover_cache_path": "", "mtime": 0.0, "duration": 0.0, "bad_encoding": 0,
            }):
                success, msg, imported = execute_import(
                    analysis=analysis,
                    edited_album=self._album(MODE_COPY),
                    edited_tracks=analysis.tracks,
                    library_path=str(self.lib_dir),
                    naming_format="<track_no>. <title>",
                    db_conn=self.conn,
                )

        self.assertTrue(success, msg)
        self.assertEqual(len(captured), 2)
        self.assertIn("-c:a", captured[0])
        self.assertIn("copy", captured[0])
        self.assertTrue(captured[0][-1].endswith(".flac"))
        self.assertNotIn("-ar", captured[0])
        self.assertNotIn("-sample_fmt", captured[0])
        # Second track is sliced at 1 second.
        self.assertIn("-ss", captured[1])
        self.assertIn("1.000", captured[1])

    @patch("malka.importer.find_ffmpeg_executable")
    @patch("subprocess.Popen")
    def test_lossless_resample_command(self, mock_popen, mock_find):
        fake_ffmpeg = self.temp_dir / "fake_ffmpeg"
        fake_ffmpeg.touch()
        mock_find.return_value = fake_ffmpeg

        captured = []

        def side_effect(cmd, **kwargs):
            captured.append(cmd)
            Path(cmd[-1]).write_bytes(b"dummy")
            proc = MagicMock()
            proc.communicate.return_value = ("", "")
            proc.returncode = 0
            proc.poll.return_value = 0
            return proc

        mock_popen.side_effect = side_effect

        analysis = self._analysis()
        with patch("malka.importer.write_tags"):
            with patch("malka.importer.read_tags", return_value={
                "file_path": "x", "title": "x", "artist": "x", "album_artist": "x",
                "album": "x", "year": "2024", "genre": "Rock", "track_no": "01",
                "disc_no": "1", "disc_total": "1", "compilation": 0, "has_cover": 0,
                "cover_cache_path": "", "mtime": 0.0, "duration": 0.0, "bad_encoding": 0,
            }):
                success, msg, imported = execute_import(
                    analysis=analysis,
                    edited_album=self._album(MODE_LOSSLESS_RESAMPLE, "alac", 48000),
                    edited_tracks=analysis.tracks,
                    library_path=str(self.lib_dir),
                    naming_format="<track_no>. <title>",
                    db_conn=self.conn,
                )

        self.assertTrue(success, msg)
        cmd = captured[0]
        self.assertIn("-c:a", cmd)
        self.assertIn("alac", cmd)
        self.assertIn("-ar", cmd)
        self.assertIn("48000", cmd)
        self.assertIn("-sample_fmt", cmd)
        self.assertIn("s16p", cmd)
        self.assertTrue(cmd[-1].endswith(".m4a"))
        self.assertEqual(len(get_all_albums(self.conn)), 1)


if __name__ == "__main__":
    unittest.main()
