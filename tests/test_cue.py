import os
import tempfile
import unittest
from pathlib import Path

from malka.cue import parse_cue_file, parse_m3u_file


class TestCueParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="malka_cue_test_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_single_file_cue(self):
        cue_content = """
TITLE "Dark Side of the Moon"
PERFORMER "Pink Floyd"
REM DATE 1973
REM GENRE "Progressive Rock"
REM DISCNUMBER 1
REM TOTALDISCS 1
FILE "Pink Floyd - Dark Side.flac" WAVE
  TRACK 01 AUDIO
    TITLE "Speak to Me"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Breathe"
    INDEX 01 01:08:00
  TRACK 03 AUDIO
    TITLE "On the Run"
    INDEX 01 03:51:00
"""
        cue_path = self.temp_dir / "album.cue"
        with open(cue_path, "w", encoding="utf-8") as f:
            f.write(cue_content)

        album = parse_cue_file(cue_path)
        self.assertIsNotNone(album)
        self.assertEqual(album.album, "Dark Side of the Moon")
        self.assertEqual(album.album_artist, "Pink Floyd")
        self.assertEqual(album.year, "1973")
        self.assertEqual(album.genre, "Progressive Rock")
        self.assertEqual(album.disc_no, "1")
        self.assertEqual(len(album.tracks), 3)

        self.assertEqual(album.tracks[0].track_no, "01")
        self.assertEqual(album.tracks[0].title, "Speak to Me")
        self.assertEqual(album.tracks[0].artist, "Pink Floyd")
        self.assertEqual(album.tracks[0].file_name, "Pink Floyd - Dark Side.flac")
        self.assertEqual(album.tracks[0].index01, "00:00:00")

        self.assertEqual(album.tracks[1].track_no, "02")
        self.assertEqual(album.tracks[1].title, "Breathe")
        self.assertEqual(album.tracks[1].index01, "01:08:00")

    def test_parse_multi_file_cue(self):
        cue_content = """
TITLE "Inner Urge"
PERFORMER "Joe Henderson"
REM DATE "1964"
REM GENRE "Jazz"
FILE "01 - Inner Urge.flac" WAVE
  TRACK 01 AUDIO
    TITLE "Inner Urge"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Isotope"
    INDEX 00 11:57:35
FILE "02 - Isotope.flac" WAVE
    INDEX 01 00:00:00
"""
        cue_path = self.temp_dir / "multi.cue"
        with open(cue_path, "w", encoding="utf-8") as f:
            f.write(cue_content)

        album = parse_cue_file(cue_path)
        self.assertIsNotNone(album)
        self.assertEqual(len(album.tracks), 2)
        self.assertEqual(album.tracks[0].file_name, "01 - Inner Urge.flac")
        self.assertEqual(album.tracks[1].file_name, "02 - Isotope.flac")

    def test_parse_compilation_cue(self):
        cue_content = """
TITLE "Top Hits 2024"
REM DATE 2024
REM GENRE "Pop"
FILE "hits.flac" WAVE
  TRACK 01 AUDIO
    TITLE "Song One"
    PERFORMER "Artist A"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Song Two"
    PERFORMER "Artist B"
    INDEX 01 03:30:00
"""
        cue_path = self.temp_dir / "comp.cue"
        with open(cue_path, "w", encoding="utf-8") as f:
            f.write(cue_content)

        album = parse_cue_file(cue_path)
        self.assertIsNotNone(album)
        self.assertEqual(album.album_artist, "Various Artists")
        self.assertEqual(album.compilation, 1)
        self.assertEqual(album.tracks[0].artist, "Artist A")
        self.assertEqual(album.tracks[1].artist, "Artist B")

    def test_parse_m3u_playlist(self):
        m3u_content = """#EXTM3U
#EXTINF:215,Artist One - Song Alpha
01 - Song Alpha.flac
#EXTINF:180,Song Beta
02 - Song Beta.flac
03 - Song Gamma.flac
"""
        m3u_path = self.temp_dir / "playlist.m3u"
        with open(m3u_path, "w", encoding="utf-8") as f:
            f.write(m3u_content)

        entries = parse_m3u_file(m3u_path)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["artist"], "Artist One")
        self.assertEqual(entries[0]["title"], "Song Alpha")
        self.assertEqual(entries[0]["file_name"], "01 - Song Alpha.flac")
        self.assertEqual(entries[1]["title"], "Song Beta")
        self.assertEqual(entries[2]["file_name"], "03 - Song Gamma.flac")


if __name__ == "__main__":
    unittest.main()
