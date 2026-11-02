import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import imageio_ffmpeg
from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication

from malka.config import config
from malka.db import get_all_albums, get_connection, init_db, upsert_track
from malka.importer import ImportAnalysisResult, analyze_import_folder, execute_import
from malka.bitrate import bitrate_at, second_bitrates
from malka.player import PlayerController
from malka.tags import read_tags
from malka.ui.album_card import AlbumCard
from malka.ui.album_detail_view import AlbumDetailView

app = QApplication.instance() or QApplication([])


def make_flac(path: Path, *, channels: int = 2, sample_rate: int = 44100,
              bits: int = 16, title: str = "Song", track: str = "1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-ac", str(channels), "-ar", str(sample_rate), "-c:a", "flac",
        "-metadata", f"title={title}",
        "-metadata", "artist=Artist",
        "-metadata", "album_artist=Artist",
        "-metadata", "album=Album",
        "-metadata", "date=2020",
        "-metadata", "genre=Rock",
        "-metadata", f"track={track}",
    ]
    if bits > 16:
        cmd += ["-sample_fmt", "s32"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


class QualityTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="malka_quality_"))
        self.db = self.tmp / "db.sqlite"
        init_db(str(self.db))
        self.conn = get_connection(str(self.db))

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_tracks(self, **kwargs):
        paths = []
        for i in range(1, 3):
            path = make_flac(self.tmp / f"{i:02d}. track.flac", track=str(i), **kwargs)
            upsert_track(self.conn, read_tags(str(path)))
            paths.append(path)
        self.conn.commit()
        return paths


class TestStreamInfo(QualityTestBase):
    def test_read_tags_reports_stream_info(self):
        path = make_flac(self.tmp / "a.flac", sample_rate=96000, bits=24)
        tags = read_tags(str(path))
        self.assertEqual(tags["sample_rate"], 96000)
        self.assertEqual(tags["bits_per_sample"], 24)
        self.assertEqual(tags["channels"], 2)
        self.assertGreater(tags["bitrate"], 0)

    def test_lossy_codecs_have_no_bit_depth(self):
        from malka.tags import get_audio_stream_info

        aac = make_encoded(self.tmp / "aac.m4a", codec="aac")
        mp3 = make_encoded(self.tmp / "track.mp3", codec="mp3")
        flac = make_flac(self.tmp / "track.flac", bits=24)

        aac_info = get_audio_stream_info(str(aac))
        self.assertEqual(aac_info["codec"], "AAC")
        self.assertEqual(aac_info["bits_per_sample"], 0)

        mp3_info = get_audio_stream_info(str(mp3))
        self.assertEqual(mp3_info["codec"], "MP3")
        self.assertEqual(mp3_info["bits_per_sample"], 0)

        flac_info = get_audio_stream_info(str(flac))
        self.assertEqual(flac_info["codec"], "FLAC")
        self.assertEqual(flac_info["bits_per_sample"], 24)

    def test_stream_info_is_not_stored_in_the_database(self):
        path = make_flac(self.tmp / "a.flac", sample_rate=96000, bits=24)
        upsert_track(self.conn, read_tags(str(path)))
        self.conn.commit()
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(tracks)")}
        for column in ("sample_rate", "bits_per_sample", "channels", "bitrate"):
            self.assertNotIn(column, columns)

def make_encoded(path: Path, codec: str = "aac", seconds: int = 4) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-ac", "2",
    ]
    if codec == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


class TestBitrateProfile(QualityTestBase):
    def test_mp3_profile(self):
        path = make_encoded(self.tmp / "a.mp3", codec="mp3", seconds=4)
        profile = second_bitrates(str(path))
        self.assertIsNotNone(profile)
        self.assertGreaterEqual(len(profile), 3)
        self.assertTrue(all(100 <= value <= 400 for value in profile))

    def test_m4a_profile(self):
        path = make_encoded(self.tmp / "a.m4a", codec="aac", seconds=4)
        profile = second_bitrates(str(path))
        self.assertIsNotNone(profile)
        self.assertGreaterEqual(len(profile), 3)
        self.assertTrue(all(value > 0 for value in profile))

    def test_flac_has_no_profile(self):
        path = make_flac(self.tmp / "a.flac")
        self.assertIsNone(second_bitrates(str(path)))

    def test_bitrate_at_position(self):
        profile = [100, 200, 300]
        self.assertEqual(bitrate_at(profile, 0, 0), 100)
        self.assertEqual(bitrate_at(profile, 0, 1500), 200)
        self.assertEqual(bitrate_at(profile, 0, 99_999), 300)
        self.assertEqual(bitrate_at(None, 320, 1500), 320)


class TestAlbumDetailQuality(QualityTestBase):
    def _view(self):
        return AlbumDetailView(PlayerController(), self.conn)

    @staticmethod
    def _wait_for_info():
        QThreadPool.globalInstance().waitForDone(5000)
        app.processEvents()
        app.processEvents()

    def test_hires_album_shows_resolution_and_logo(self):
        self._add_tracks(sample_rate=96000, bits=24)
        album = get_all_albums(self.conn)[0]
        view = self._view()
        view.set_album(album)
        self._wait_for_info()

        self.assertIn("96 kHz", view.quality_label.text())
        self.assertIn("24-bit", view.quality_label.text())
        self.assertIn("FLAC", view.quality_label.text())
        self.assertFalse(view.hires_logo.isHidden())

    def test_aac_album_shows_no_bit_depth(self):
        path = make_encoded(self.tmp / "01. track.m4a", codec="aac")
        upsert_track(self.conn, read_tags(str(path)))
        self.conn.commit()
        album = get_all_albums(self.conn)[0]
        view = self._view()
        view.set_album(album)
        self._wait_for_info()

        text = view.quality_label.text()
        self.assertIn("44.1 kHz", text)
        self.assertIn("AAC", text)
        self.assertNotIn("-bit", text)
        self.assertTrue(view.hires_logo.isHidden())

    def test_cd_quality_album_has_no_hires_logo(self):
        self._add_tracks(sample_rate=44100, bits=16)
        album = get_all_albums(self.conn)[0]
        view = self._view()
        view.set_album(album)
        self._wait_for_info()

        self.assertIn("44.1 kHz", view.quality_label.text())
        self.assertIn("16-bit", view.quality_label.text())
        self.assertTrue(view.hires_logo.isHidden())


class TestBadgeSettings(unittest.TestCase):
    def _album(self, **extra):
        data = {
            "album": "Album", "album_artist": "Artist", "display_artist": "Artist",
            "year": "2020", "track_count": 1, "disc_count": 1,
        }
        data.update(extra)
        return data

    def test_organize_badge_can_be_hidden(self):
        with patch.object(config, "show_organize_badge", True):
            card = AlbumCard(self._album(is_organized=False), is_organize_ready=True)
            self.assertTrue(hasattr(card, "badge_organize"))
        with patch.object(config, "show_organize_badge", False):
            card = AlbumCard(self._album(is_organized=False), is_organize_ready=True)
            self.assertFalse(hasattr(card, "badge_organize"))

    def test_encoding_badge_can_be_hidden(self):
        with patch.object(config, "show_encoding_badge", True):
            card = AlbumCard(self._album(has_bad_encoding=True), is_organize_ready=True)
            self.assertTrue(hasattr(card, "badge_encoding"))
        with patch.object(config, "show_encoding_badge", False):
            card = AlbumCard(self._album(has_bad_encoding=True), is_organize_ready=True)
            self.assertFalse(hasattr(card, "badge_encoding"))


class TestChannelValidation(QualityTestBase):
    def test_mono_files_are_rejected(self):
        folder = self.tmp / "mono"
        make_flac(folder / "01. track.flac", channels=1)
        with self.assertRaisesRegex(ValueError, "2-channel"):
            analyze_import_folder(str(folder), self.conn)

    def test_multichannel_image_is_rejected(self):
        folder = self.tmp / "surround"
        folder.mkdir()
        image = make_flac(folder / "album.flac", channels=6)
        (folder / "album.cue").write_text(
            'TITLE "Album"\nPERFORMER "Artist"\n'
            f'FILE "{image.name}" WAVE\n'
            '  TRACK 01 AUDIO\n    TITLE "One"\n    INDEX 01 00:00:00\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "2-channel"):
            analyze_import_folder(str(folder), self.conn)

    def test_execute_import_guards_channels(self):
        analysis = ImportAnalysisResult(
            variant=1,
            album="Album",
            album_artist="Artist",
            year="2020",
            genre="Rock",
            channels=6,
            tracks=[{"title": "t", "file_path": str(self.tmp / "x.flac")}],
        )
        ok, msg, imported = execute_import(
            analysis=analysis,
            edited_album={},
            edited_tracks=analysis.tracks,
            library_path=str(self.tmp / "lib"),
            naming_format="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertFalse(ok)
        self.assertIn("2-channel", msg)


if __name__ == "__main__":
    unittest.main()
