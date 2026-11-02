import os
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from malka.config import NO_DATA
from malka.db import get_all_albums, get_album_tracks, get_connection, get_import_tracks, init_db
from malka.importer import (
    analyze_import_folder,
    compute_resampling_rate,
    execute_import,
    find_qaac_executable,
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

    def test_resampling_rules(self):
        # 44.1 kHz and 48 kHz: no resampling
        self.assertIsNone(compute_resampling_rate(44100))
        self.assertIsNone(compute_resampling_rate(48000))
        self.assertIsNone(compute_resampling_rate(22050))
        self.assertIsNone(compute_resampling_rate(32000))

        # > 48 kHz divisible by 44100 -> 44100
        self.assertEqual(compute_resampling_rate(88200), 44100)
        self.assertEqual(compute_resampling_rate(176400), 44100)

        # > 48 kHz divisible by 48000 -> 48000
        self.assertEqual(compute_resampling_rate(96000), 48000)
        self.assertEqual(compute_resampling_rate(192000), 48000)

        # Other rates above 48 kHz
        self.assertEqual(compute_resampling_rate(88240), 44100)

    def test_qaac_executable_found(self):
        qaac = find_qaac_executable()
        self.assertIsNotNone(qaac)
        self.assertTrue(qaac.exists())

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

    def test_variant_2_single_flac_cue_conversion(self):
        # Create a single FLAC + CUE image folder
        album_src = self.temp_dir / "Source_Cue_Album"
        album_src.mkdir()

        # Generate a small 3-second stereo WAV
        wav_path = album_src / "temp.wav"
        with wave.open(str(wav_path), "w") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(44100)
            for i in range(44100 * 3):
                w.writeframes(struct.pack("<hh", 1000, 1000))

        # Convert WAV to FLAC using refalac / flac or write minimal FLAC
        flac_path = album_src / "album.flac"

        # Use foobar flac.exe or qaac decode/convert
        flac_tool = Path(r"C:\Program Files\foobar2000\encoders\flac.exe")
        if flac_tool.exists():
            import subprocess
            subprocess.run([str(flac_tool), "-s", str(wav_path), "-o", str(flac_path)], check=True)
            wav_path.unlink()
        else:
            self.skipTest("flac.exe encoder not found for Variant 2 synthetic test")

        # Create CUE sheet defining 2 tracks
        cue_path = album_src / "album.cue"
        cue_text = f"""
TITLE "Ambient Journey"
PERFORMER "Sound Explorer"
REM DATE 2023
REM GENRE "Ambient"
FILE "{flac_path.name}" WAVE
  TRACK 01 AUDIO
    TITLE "First Dawn"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second Light"
    INDEX 01 00:01:50
"""
        with open(cue_path, "w", encoding="utf-8") as f:
            f.write(cue_text)

        # Analyze folder
        analysis = analyze_import_folder(str(album_src), self.conn)
        self.assertEqual(analysis.variant, 2)
        self.assertEqual(analysis.album, "Ambient Journey")
        self.assertEqual(analysis.album_artist, "Sound Explorer")
        self.assertEqual(len(analysis.tracks), 2)

        # Execute Import (QAAC conversion to M4A)
        edited_album = {
            "album": "Ambient Journey",
            "album_artist": "Sound Explorer",
            "year": "2023",
            "genre": "Ambient",
            "compilation": 0,
            "cover_cache_path": "",
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
        self.assertEqual(len(imported), 2)

        # Check that converted tracks exist with .m4a extension
        dest_folder = self.lib_dir / "Sound Explorer" / "2023 - Ambient Journey"
        self.assertTrue(dest_folder.exists())
        self.assertTrue((dest_folder / "01. First Dawn.m4a").exists())
        self.assertTrue((dest_folder / "02. Second Light.m4a").exists())

        # Check DB reflects the new album and tracks
        alb_tracks = get_album_tracks(self.conn, "Ambient Journey", "Sound Explorer")
        self.assertEqual(len(alb_tracks), 2)
        self.assertEqual(alb_tracks[0]["title"], "First Dawn")
        self.assertEqual(alb_tracks[1]["title"], "Second Light")

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

        # Check encoder selection uses QAAC on Windows with FFmpeg decoder available
        from malka.importer import get_audio_encoder, find_ffmpeg_executable
        enc_type, enc_path = get_audio_encoder(".ape")
        self.assertEqual(enc_type, "qaac")
        self.assertIsNotNone(enc_path)
        self.assertTrue(enc_path.exists())
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

        # Check encoder selection uses QAAC on Windows with FFmpeg decoder available
        from malka.importer import get_audio_encoder, find_ffmpeg_executable
        enc_type, enc_path = get_audio_encoder(".wv")
        self.assertEqual(enc_type, "qaac")
        self.assertIsNotNone(enc_path)
        self.assertTrue(enc_path.exists())
        ffmpeg_path = find_ffmpeg_executable()
        self.assertIsNotNone(ffmpeg_path)
        self.assertTrue(ffmpeg_path.exists())


if __name__ == "__main__":
    unittest.main()
