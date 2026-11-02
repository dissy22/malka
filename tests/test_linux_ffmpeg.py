import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from malka.cue import cue_time_to_seconds
from malka.db import get_album_tracks, get_all_albums, get_connection, init_db
from malka.importer import (
    ImportAnalysisResult,
    compute_resampling_rate,
    execute_import,
    find_ffmpeg_executable,
    get_audio_encoder,
)


class TestLinuxFFmpeg(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="malka_linux_test_"))
        self.lib_dir = self.temp_dir / "library"
        self.lib_dir.mkdir()
        self.db_path = self.temp_dir / "test.db"
        init_db(str(self.db_path))
        self.conn = get_connection(str(self.db_path))

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cue_time_to_seconds(self):
        self.assertAlmostEqual(cue_time_to_seconds("00:00:00"), 0.0)
        self.assertAlmostEqual(cue_time_to_seconds("01:00:00"), 60.0)
        self.assertAlmostEqual(cue_time_to_seconds("02:30:00"), 150.0)
        # 75 frames = 1 second
        self.assertAlmostEqual(cue_time_to_seconds("00:01:75"), 2.0)
        self.assertAlmostEqual(cue_time_to_seconds("01:23:45"), 83.6, places=2)
        # 2 parts MM:SS
        self.assertAlmostEqual(cue_time_to_seconds("03:15"), 195.0)
        # None or empty
        self.assertEqual(cue_time_to_seconds(""), 0.0)
        self.assertEqual(cue_time_to_seconds(None), 0.0)

    @patch("shutil.which")
    def test_encoder_selection_on_linux(self, mock_which):
        # On Linux, find_ffmpeg_executable returns ffmpeg if on PATH
        mock_which.side_effect = lambda cmd: "/usr/bin/ffmpeg" if cmd == "ffmpeg" else None

        with patch("sys.platform", "linux"):
            enc_type, enc_path = get_audio_encoder()
            self.assertEqual(enc_type, "ffmpeg")
            self.assertTrue(str(enc_path).replace("\\", "/").endswith("/ffmpeg"))

    def test_qaac_executable_never_found_on_non_windows(self):
        from malka.importer import find_qaac_executable
        with patch("sys.platform", "linux"):
            self.assertIsNone(find_qaac_executable())
        with patch("sys.platform", "darwin"):
            self.assertIsNone(find_qaac_executable())

    @patch("malka.importer.find_ffmpeg_executable", return_value=None)
    def test_encoder_selection_on_linux_when_ffmpeg_missing_never_returns_qaac(self, mock_find):
        with patch("sys.platform", "linux"):
            enc_type, enc_path = get_audio_encoder()
            self.assertIsNone(enc_type)
            self.assertIsNone(enc_path)

    @patch("malka.importer.find_ffmpeg_executable", return_value=None)
    def test_execute_import_on_linux_when_ffmpeg_missing_returns_clear_error(self, mock_find):
        analysis = ImportAnalysisResult(
            variant=2,
            album="Test Album",
            album_artist="Test Artist",
            year="2024",
            genre="Rock",
            source_folder=str(self.temp_dir),
            source_flac_path=str(self.temp_dir / "test.flac"),
            cue_file_path=str(self.temp_dir / "test.cue"),
            tracks=[{"title": "Track 1", "index01": "00:00:00"}],
        )
        with patch("sys.platform", "linux"):
            success, msg, imported = execute_import(
                analysis=analysis,
                edited_album={"album": "Test", "album_artist": "Test", "year": "2024", "genre": "Rock", "compilation": 0, "cover_cache_path": "", "remove_cover": False},
                edited_tracks=analysis.tracks,
                library_path=str(self.lib_dir),
                naming_format="<track_no>. <title>",
                db_conn=self.conn,
            )
            self.assertFalse(success)
            self.assertIn("FFmpeg was not found", msg)
            self.assertNotIn("qaac", msg.lower())

    @patch("shutil.which")
    def test_encoder_selection_on_windows_prefers_qaac(self, mock_which):
        mock_which.side_effect = lambda cmd: "C:\\qaac\\qaac64.exe" if "qaac" in cmd else "C:\\ffmpeg.exe"

        with patch("sys.platform", "win32"):
            enc_type, enc_path = get_audio_encoder()
            self.assertEqual(enc_type, "qaac")

    def test_codecs_qaac_lookup_on_windows(self):
        from malka.importer import find_qaac_executable
        with patch("sys.platform", "win32"):
            qaac_path = find_qaac_executable()
            self.assertIsNotNone(qaac_path)
            self.assertTrue(str(qaac_path).endswith("qaac64.exe"))

    @patch("malka.importer.find_qaac_executable", return_value=None)
    def test_windows_falls_back_to_ffmpeg_when_qaac_missing(self, mock_qaac):
        with patch("sys.platform", "win32"):
            enc_type, enc_path = get_audio_encoder()
            self.assertEqual(enc_type, "ffmpeg")
            self.assertIsNotNone(enc_path)

    @patch("shutil.which", return_value=None)
    def test_find_ffmpeg_finds_imageio_ffmpeg(self, mock_which):
        from malka.importer import find_ffmpeg_executable
        ffmpeg_path = find_ffmpeg_executable()
        self.assertIsNotNone(ffmpeg_path)
        self.assertTrue(Path(ffmpeg_path).exists())

    def test_find_flac_executable_structure(self):
        from malka.importer import find_flac_executable
        flac_path = find_flac_executable()
        # Should not crash, returns Path if flac installed or None
        self.assertTrue(flac_path is None or isinstance(flac_path, Path))

    @patch("malka.importer.get_audio_encoder")
    @patch("subprocess.Popen")
    def test_variant_2_ffmpeg_conversion_arguments(self, mock_popen, mock_encoder):
        fake_ffmpeg = self.temp_dir / "fake_ffmpeg"
        fake_ffmpeg.touch()
        mock_encoder.return_value = ("ffmpeg", fake_ffmpeg)

        # Create dummy source flac and cue
        src_flac = self.temp_dir / "album.flac"
        src_flac.write_bytes(b"dummyflac")
        cue_file = self.temp_dir / "album.cue"
        cue_file.write_text("dummy cue")

        # Mock Popen behavior: each ffmpeg call writes a dummy .m4a output file
        captured_cmds = []

        def side_effect(cmd, **kwargs):
            captured_cmds.append(cmd)
            # Find output file (last argument in ffmpeg call)
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"dummyaac")
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "")
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            return mock_proc

        mock_popen.side_effect = side_effect

        analysis = ImportAnalysisResult(
            variant=2,
            album="Blue Train",
            album_artist="John Coltrane",
            year="1957",
            genre="Jazz",
            source_folder=str(self.temp_dir),
            source_flac_path=str(src_flac),
            cue_file_path=str(cue_file),
            sample_rate=96000,  # Should be resampled to 48000
            bits_per_sample=24,
            tracks=[
                {
                    "track_no": "01",
                    "title": "Blue Train",
                    "artist": "John Coltrane",
                    "album_artist": "John Coltrane",
                    "album": "Blue Train",
                    "year": "1957",
                    "genre": "Jazz",
                    "index01": "00:00:00",
                },
                {
                    "track_no": "02",
                    "title": "Moment's Notice",
                    "artist": "John Coltrane",
                    "album_artist": "John Coltrane",
                    "album": "Blue Train",
                    "year": "1957",
                    "genre": "Jazz",
                    "index01": "10:41:00",
                },
            ],
        )

        with patch("malka.importer.write_tags"):
            with patch("malka.importer.read_tags") as mock_read_tags:
                mock_read_tags.side_effect = lambda p: {
                    "file_path": str(p),
                    "title": Path(p).stem,
                    "artist": "John Coltrane",
                    "album_artist": "John Coltrane",
                    "album": "Blue Train",
                    "year": "1957",
                    "genre": "Jazz",
                    "track_no": "01",
                    "disc_no": "1",
                    "disc_total": "1",
                    "compilation": 0,
                    "has_cover": 0,
                    "cover_cache_path": "",
                    "mtime": 0.0,
                }
                success, msg, imported = execute_import(
                    analysis=analysis,
                    edited_album={
                        "album": "Blue Train",
                        "album_artist": "John Coltrane",
                        "year": "1957",
                        "genre": "Jazz",
                        "compilation": 0,
                        "cover_cache_path": "",
                        "remove_cover": False,
                    },
                    edited_tracks=analysis.tracks,
                    library_path=str(self.lib_dir),
                    naming_format="<track_no>. <title>",
                    db_conn=self.conn,
                )

        self.assertTrue(success)
        self.assertEqual(len(imported), 2)
        self.assertEqual(len(captured_cmds), 2)

        # Check track 1 command: -ss 0.000, -t 641.000, -c:a aac, -b:a 224k, -ar 48000
        cmd1 = captured_cmds[0]
        self.assertIn("-ss", cmd1)
        self.assertIn("0.000", cmd1)
        self.assertIn("-t", cmd1)
        self.assertIn("-c:a", cmd1)
        self.assertIn("aac", cmd1)
        self.assertIn("-b:a", cmd1)
        self.assertIn("224k", cmd1)
        self.assertIn("-ar", cmd1)
        self.assertIn("48000", cmd1)

        # Check track 2 command: -ss 641.000 (10*60 + 41 = 641s), no -t since last track
        cmd2 = captured_cmds[1]
        self.assertIn("-ss", cmd2)
        self.assertIn("641.000", cmd2)
        self.assertNotIn("-t", cmd2)
        self.assertIn("-c:a", cmd2)
        self.assertIn("aac", cmd2)
        self.assertIn("-b:a", cmd2)
        self.assertIn("224k", cmd2)

    @patch("malka.importer.get_audio_encoder")
    @patch("subprocess.Popen")
    def test_variant_3_ffmpeg_conversion_arguments(self, mock_popen, mock_encoder):
        fake_ffmpeg = self.temp_dir / "fake_ffmpeg"
        fake_ffmpeg.touch()
        mock_encoder.return_value = ("ffmpeg", fake_ffmpeg)

        flac1 = self.temp_dir / "01. First Song.flac"
        flac1.write_bytes(b"dummy")
        flac2 = self.temp_dir / "02. Second Song.flac"
        flac2.write_bytes(b"dummy")

        captured_cmds = []

        def side_effect(cmd, **kwargs):
            captured_cmds.append(cmd)
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"dummyaac")
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = ("", "")
            mock_proc.returncode = 0
            mock_proc.wait.return_value = 0
            return mock_proc

        mock_popen.side_effect = side_effect

        analysis = ImportAnalysisResult(
            variant=3,
            album="Test FLACs",
            album_artist="Test Artist",
            year="2024",
            genre="Rock",
            sample_rate=44100,  # No resampling needed
            bits_per_sample=16,
            tracks=[
                {
                    "track_no": "01",
                    "title": "First Song",
                    "artist": "Test Artist",
                    "album_artist": "Test Artist",
                    "album": "Test FLACs",
                    "year": "2024",
                    "genre": "Rock",
                    "source_path": str(flac1),
                },
                {
                    "track_no": "02",
                    "title": "Second Song",
                    "artist": "Test Artist",
                    "album_artist": "Test Artist",
                    "album": "Test FLACs",
                    "year": "2024",
                    "genre": "Rock",
                    "source_path": str(flac2),
                },
            ],
        )

        with patch("malka.importer.write_tags"):
            with patch("malka.importer.read_tags") as mock_read_tags:
                mock_read_tags.side_effect = lambda p: {
                    "file_path": str(p),
                    "title": Path(p).stem,
                    "artist": "Test Artist",
                    "album_artist": "Test Artist",
                    "album": "Test FLACs",
                    "year": "2024",
                    "genre": "Rock",
                    "track_no": "01",
                    "disc_no": "1",
                    "disc_total": "1",
                    "compilation": 0,
                    "has_cover": 0,
                    "cover_cache_path": "",
                    "mtime": 0.0,
                }
                success, msg, imported = execute_import(
                    analysis=analysis,
                    edited_album={
                        "album": "Test FLACs",
                        "album_artist": "Test Artist",
                        "year": "2024",
                        "genre": "Rock",
                        "compilation": 0,
                        "cover_cache_path": "",
                        "remove_cover": False,
                    },
                    edited_tracks=analysis.tracks,
                    library_path=str(self.lib_dir),
                    naming_format="<track_no>. <title>",
                    db_conn=self.conn,
                )

        self.assertTrue(success)
        self.assertEqual(len(imported), 2)
        self.assertEqual(len(captured_cmds), 2)

        cmd1 = captured_cmds[0]
        self.assertIn("-c:a", cmd1)
        self.assertIn("aac", cmd1)
        self.assertIn("-b:a", cmd1)
        self.assertIn("224k", cmd1)
        # Since sample rate is 44100, no -ar needed
        self.assertNotIn("-ar", cmd1)


if __name__ == "__main__":
    unittest.main()
