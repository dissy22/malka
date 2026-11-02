import os
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from malka.config import NO_DATA
from malka.db import get_all_albums, get_album_tracks, get_connection, get_import_tracks, init_db
from malka.formats import MODE_COPY, MODE_LOSSLESS_RESAMPLE, MODE_LOSSY
from malka.importer import (
    analyze_import_folder,
    execute_import,
    find_ffmpeg_executable,
)
from malka.tags import read_tags, write_tags


class TestImportFlow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="malka_import_test_"))
        self.lib_dir = self.temp_dir / "library"
        self.lib_dir.mkdir()
        self.db_path = self.temp_dir / "test.db"
        init_db(str(self.db_path))
        self.conn = get_connection(str(self.db_path))

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ffmpeg_encoder_found(self):
        ffmpeg_path = find_ffmpeg_executable()
        self.assertIsNotNone(ffmpeg_path)
        self.assertTrue(Path(ffmpeg_path).exists())

    def test_variant_1_analysis_and_import(self):
        # Test Variant 1 with Wishmaster if present
        candidates = [
            Path("C:/Programming/Malka/files_to_import/2000 - Wishmaster"),
            Path(__file__).resolve().parent.parent / "files_to_import/2000 - Wishmaster",
            Path("files_to_import/2000 - Wishmaster"),
        ]
        wishmaster_dir = next((p for p in candidates if p.exists()), None)
        if not wishmaster_dir:
            self.skipTest("files_to_import/2000 - Wishmaster folder not found")

        analysis = analyze_import_folder(str(wishmaster_dir), self.conn)
        self.assertEqual(analysis.variant, 1)
        self.assertEqual(analysis.album, "Wishmaster")
        self.assertEqual(analysis.album_artist, "Nightwish")
        self.assertEqual(len(analysis.tracks), 14)

        # Check that tracks were staged into SQLite import_tracks table
        staged = get_import_tracks(self.conn)
        self.assertEqual(len(staged), 14)
        self.assertEqual(staged[0]["title"], "She Is My Sin")
        self.assertEqual(staged[0]["track_no"], "01")

        # Execute Import
        edited_album = {
            "album": "Wishmaster (Remastered)",
            "album_artist": "Nightwish",
            "year": "2000",
            "genre": "Symphonic Metal",
            "compilation": 0,
            "cover_cache_path": analysis.cover_cache_path,
            "remove_cover": False,
        }
        edited_tracks = [dict(t) for t in staged]
        for t in edited_tracks:
            t["album"] = "Wishmaster (Remastered)"
            t["genre"] = "Symphonic Metal"

        success, msg, imported = execute_import(
            analysis=analysis,
            edited_album=edited_album,
            edited_tracks=edited_tracks,
            library_path=str(self.lib_dir),
            naming_format="<track_no>. <title>",
            db_conn=self.conn,
        )

        self.assertTrue(success)
        self.assertEqual(len(imported), 14)

        # Check library folder structure: <lib>/Nightwish/2000 - Wishmaster (Remastered)/
        dest_folder = self.lib_dir / "Nightwish" / "2000 - Wishmaster (Remastered)"
        self.assertTrue(dest_folder.exists())
        self.assertTrue((dest_folder / "01. She Is My Sin.m4a").exists())

        # Check SQLite tracks table has been updated
        albums = get_all_albums(self.conn)
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["album"], "Wishmaster (Remastered)")
        self.assertEqual(albums[0]["track_count"], 14)

        # Check import_tracks table is cleared after completion
        self.assertEqual(len(get_import_tracks(self.conn)), 0)

    def test_variant_3_flac_tracks_conversion_and_artwork(self):
        # Test Variant 3 with Joe Henderson (track-by-track FLAC + folder.jpg)
        candidates = [
            Path("C:/Programming/Malka/files_to_import/Joe Henderson - Inner Urge (1964, 2024, Blue Note-Japan)"),
            Path(__file__).resolve().parent.parent / "files_to_import/Joe Henderson - Inner Urge (1964, 2024, Blue Note-Japan)",
            Path("files_to_import/Joe Henderson - Inner Urge (1964, 2024, Blue Note-Japan)"),
        ]
        joe_dir = next((p for p in candidates if p.exists()), None)
        if not joe_dir:
            self.skipTest("Joe Henderson folder not found")

        analysis = analyze_import_folder(str(joe_dir), self.conn)
        self.assertEqual(analysis.variant, 3)
        self.assertEqual(analysis.album, "Inner Urge")
        self.assertEqual(analysis.album_artist, "Joe Henderson")
        self.assertEqual(len(analysis.tracks), 5)
        self.assertTrue(bool(analysis.cover_cache_path))

        # Staged tracks
        staged = get_import_tracks(self.conn)
        self.assertEqual(len(staged), 5)
        self.assertEqual(staged[0]["track_no"], "01")
        self.assertEqual(staged[0]["title"], "Inner Urge")

        # Import Joe Henderson
        edited_album = {
            "album": "Inner Urge",
            "album_artist": "Joe Henderson",
            "year": "1964",
            "genre": "Jazz",
            "compilation": 0,
            "cover_cache_path": analysis.cover_cache_path,
            "remove_cover": False,
        }
        success, msg, imported = execute_import(
            analysis=analysis,
            edited_album=edited_album,
            edited_tracks=staged,
            library_path=str(self.lib_dir),
            naming_format="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertTrue(success)
        self.assertEqual(len(imported), 5)

        dest_folder = self.lib_dir / "Joe Henderson" / "1964 - Inner Urge"
        self.assertTrue((dest_folder / "01. Inner Urge.m4a").exists())
        self.assertTrue((dest_folder / "05. Night and Day.m4a").exists())

    def _make_flac_image_album(self) -> Path:
        """Builds a small real FLAC image + CUE album using the bundled FFmpeg."""
        import imageio_ffmpeg
        import subprocess

        album_src = self.temp_dir / "Source_Cue_Album"
        album_src.mkdir()
        flac_path = album_src / "album.flac"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
                "-ac", "2", "-ar", "96000", "-sample_fmt", "s32", "-c:a", "flac",
                str(flac_path),
            ],
            check=True,
        )
        cue_path = album_src / "album.cue"
        cue_path.write_text(
            'TITLE "Ambient Journey"\n'
            'PERFORMER "Sound Explorer"\n'
            "REM DATE 2023\n"
            'REM GENRE "Ambient"\n'
            f'FILE "{flac_path.name}" WAVE\n'
            '  TRACK 01 AUDIO\n    TITLE "First Dawn"\n    INDEX 01 00:00:00\n'
            '  TRACK 02 AUDIO\n    TITLE "Second Light"\n    INDEX 01 00:01:50\n',
            encoding="utf-8",
        )
        return album_src

    def _import_cue_album(self, mode=MODE_COPY, fmt="flac", rate=48000):
        album_src = self._make_flac_image_album()
        analysis = analyze_import_folder(str(album_src), self.conn)
        self.assertEqual(analysis.variant, 2)
        self.assertEqual(analysis.album, "Ambient Journey")
        self.assertEqual(analysis.album_artist, "Sound Explorer")
        self.assertEqual(len(analysis.tracks), 2)
        self.assertEqual(analysis.sample_rate, 96000)

        edited_album = {
            "album": "Ambient Journey",
            "album_artist": "Sound Explorer",
            "year": "2023",
            "genre": "Ambient",
            "compilation": 0,
            "cover_cache_path": "",
            "remove_cover": False,
        }
        edited_album["import_mode"] = mode
        edited_album["import_format"] = fmt
        edited_album["import_rate"] = rate

        success, msg, imported = execute_import(
            analysis=analysis,
            edited_album=edited_album,
            edited_tracks=analysis.tracks,
            library_path=str(self.lib_dir),
            naming_format="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertTrue(success, msg)
        self.assertEqual(len(imported), 2)
        return analysis, imported

    def test_variant_2_image_split_to_m4a(self):
        self._import_cue_album(MODE_LOSSY, fmt="m4a", rate=48000)
        dest_folder = self.lib_dir / "Sound Explorer" / "2023 - Ambient Journey"
        self.assertTrue((dest_folder / "01. First Dawn.m4a").exists())
        self.assertTrue((dest_folder / "02. Second Light.m4a").exists())

        alb_tracks = get_album_tracks(self.conn, "Ambient Journey", "Sound Explorer")
        self.assertEqual(len(alb_tracks), 2)
        self.assertEqual(alb_tracks[0]["title"], "First Dawn")
        self.assertEqual(alb_tracks[1]["title"], "Second Light")

    def test_variant_2_image_split_to_flac_with_resampling(self):
        self._import_cue_album(MODE_LOSSLESS_RESAMPLE, fmt="flac", rate=48000)
        dest_folder = self.lib_dir / "Sound Explorer" / "2023 - Ambient Journey"
        first = dest_folder / "01. First Dawn.flac"
        second = dest_folder / "02. Second Light.flac"
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

        # 96 kHz source must be reduced to 48 kHz / 16-bit.
        from malka.tags import get_audio_stream_info
        info = get_audio_stream_info(str(first))
        self.assertEqual(info["sample_rate"], 48000)
        self.assertEqual(info["bits_per_sample"], 16)
        self.assertGreaterEqual(first.stat().st_size, 1000)

    def test_variant_2_real_louis_armstrong_import(self):
        candidates = [
            Path("C:/Programming/Malka/files_to_import/Louis Armstrong - Classic Louis Armstrong (1999)"),
            Path(__file__).resolve().parent.parent / "files_to_import/Louis Armstrong - Classic Louis Armstrong (1999)",
            Path("files_to_import/Louis Armstrong - Classic Louis Armstrong (1999)"),
        ]
        armstrong_dir = next((p for p in candidates if p.exists()), None)
        if not armstrong_dir:
            self.skipTest("Louis Armstrong folder not found in files_to_import")

        # 1. Analyze
        analysis = analyze_import_folder(str(armstrong_dir), self.conn)
        self.assertEqual(analysis.variant, 2)
        self.assertEqual(analysis.album, "Classic Louis Armstrong")
        self.assertEqual(analysis.album_artist, "Louis Armstrong")
        self.assertEqual(analysis.year, "1999")
        self.assertEqual(analysis.genre, "Jazz")
        self.assertEqual(analysis.sample_rate, 44100)
        self.assertEqual(len(analysis.tracks), 17)
        self.assertTrue(bool(analysis.cover_cache_path))

        # Check track 1 and last track
        self.assertEqual(analysis.tracks[0]["track_no"], "01")
        self.assertEqual(analysis.tracks[0]["title"], "What a wonderful world")
        self.assertEqual(analysis.tracks[16]["track_no"], "17")
        self.assertEqual(analysis.tracks[16]["title"], "La Cucaracha")

        # 2. Execute import
        edited_album = {
            "album": analysis.album,
            "album_artist": analysis.album_artist,
            "year": analysis.year,
            "genre": analysis.genre,
            "compilation": analysis.compilation,
            "cover_cache_path": analysis.cover_cache_path,
            "remove_cover": False,
        }
        success, msg, imported = execute_import(
            analysis=analysis,
            edited_album=edited_album,
            edited_tracks=analysis.tracks,
            library_path=str(self.lib_dir),
            naming_format="<track_no>. <title>",
            db_conn=self.conn,
        )

        self.assertTrue(success)
        self.assertEqual(len(imported), 17)

        # 3. Check files on disk
        dest_dir = self.lib_dir / "Louis Armstrong" / "1999 - Classic Louis Armstrong"
        self.assertTrue(dest_dir.exists())
        self.assertTrue((dest_dir / "01. What a wonderful world.m4a").exists())
        self.assertTrue((dest_dir / "17. La Cucaracha.m4a").exists())

        # 4. Check DB records
        albums = get_all_albums(self.conn)
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["album"], "Classic Louis Armstrong")
        self.assertEqual(albums[0]["track_count"], 17)

        # Verify tags from actual disk file
        track1_tags = read_tags(str(dest_dir / "01. What a wonderful world.m4a"))
        self.assertEqual(track1_tags["title"], "What a wonderful world")
        self.assertEqual(track1_tags["artist"], "Louis Armstrong")
        self.assertEqual(track1_tags["album"], "Classic Louis Armstrong")
        self.assertEqual(track1_tags["year"], "1999")
        self.assertEqual(track1_tags["track_no"], "01")
        self.assertEqual(track1_tags["has_cover"], 1)

    def test_variant_2_ape_analysis_and_encoder(self):
        candidates = [
            Path("C:/Programming/Malka/files_to_import/1989 - Gula Gula"),
            Path(__file__).resolve().parent.parent / "files_to_import/1989 - Gula Gula",
            Path("files_to_import/1989 - Gula Gula"),
        ]
        gula_dir = next((p for p in candidates if p.exists()), None)
        if not gula_dir:
            self.skipTest("1989 - Gula Gula folder not found in files_to_import")

        analysis = analyze_import_folder(str(gula_dir), self.conn)
        self.assertEqual(analysis.variant, 2)
        self.assertTrue(analysis.source_flac_path.endswith(".ape"))
        self.assertEqual(analysis.album_artist, "Mari Boine")
        self.assertEqual(analysis.year, "2003")
        self.assertEqual(len(analysis.tracks), 11)
        self.assertTrue(bool(analysis.cover_cache_path))

        # FFmpeg is the only encoder backend.
        ffmpeg_path = find_ffmpeg_executable()
        self.assertIsNotNone(ffmpeg_path)
        self.assertTrue(ffmpeg_path.exists())

    def test_variant_2_wv_analysis_and_encoder(self):
        candidates = [
            Path("C:/Programming/Malka/files_to_import/Robert Wyatt - Old Rottenhat (1986)(1998)(Hannibal Records HNCD 1434)"),
            Path(__file__).resolve().parent.parent / "files_to_import/Robert Wyatt - Old Rottenhat (1986)(1998)(Hannibal Records HNCD 1434)",
            Path("files_to_import/Robert Wyatt - Old Rottenhat (1986)(1998)(Hannibal Records HNCD 1434)"),
        ]
        wyatt_dir = next((p for p in candidates if p.exists()), None)
        if not wyatt_dir:
            self.skipTest("Robert Wyatt folder not found in files_to_import")

        analysis = analyze_import_folder(str(wyatt_dir), self.conn)
        self.assertEqual(analysis.variant, 2)
        self.assertTrue(analysis.source_flac_path.endswith(".wv"))
        self.assertEqual(analysis.album_artist, "Robert Wyatt")
        self.assertEqual(analysis.year, "1998")
        self.assertEqual(len(analysis.tracks), 10)
        self.assertTrue(bool(analysis.cover_cache_path))

        # FFmpeg is the only encoder backend.
        ffmpeg_path = find_ffmpeg_executable()
        self.assertIsNotNone(ffmpeg_path)
        self.assertTrue(ffmpeg_path.exists())


if __name__ == "__main__":
    unittest.main()
