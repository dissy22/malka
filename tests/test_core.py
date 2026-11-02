import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from malka.config import NO_DATA
from malka.db import get_album_tracks, get_all_albums, get_connection, init_db
from malka.organizer import format_track_filename, is_album_ready_to_organize, organize_album
from malka.scanner import LibraryScanner
from malka.tags import read_tags, write_tags


def create_dummy_mp3(file_path: Path):
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    with open(file_path, "wb") as f:
        f.write(frame * 5)


def create_dummy_m4a(file_path: Path):
    def make_box(box_type, payload):
        return struct.pack(">I", len(payload) + 8) + box_type.encode("latin1") + payload

    ftyp = make_box("ftyp", b"M4A \x00\x00\x00\x00M4A mp42isom")
    mvhd_payload = (
        b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + struct.pack(">I", 1000)
        + struct.pack(">I", 5000)
        + b"\x00\x01\x00\x00"
        + b"\x01\x00"
        + b"\x00" * 10
        + b"\x00\x01\x00\x00"
        + b"\x00" * 12
        + b"\x00\x01\x00\x00"
        + b"\x00" * 12
        + b"\x40\x00\x00\x00"
        + b"\x00" * 24
        + struct.pack(">I", 2)
    )
    mvhd = make_box("mvhd", mvhd_payload)
    moov = make_box("moov", mvhd)
    mdat = make_box("mdat", b"\x00" * 200)

    with open(file_path, "wb") as f:
        f.write(ftyp + moov + mdat)


def create_dummy_image(file_path: Path, color=(255, 0, 0)):
    img = Image.new("RGB", (100, 100), color=color)
    img.save(file_path, "JPEG")


class TestMalkaCore(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="malka_test_"))
        self.db_path = self.test_dir / "test_library.db"
        init_db(str(self.db_path))
        self.conn = get_connection(str(self.db_path))

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mp3_read_and_write_tags(self):
        mp3_file = self.test_dir / "test.mp3"
        create_dummy_mp3(mp3_file)

        # 1. Read untagged MP3
        tags = read_tags(str(mp3_file))
        self.assertEqual(tags["title"], NO_DATA)
        self.assertEqual(tags["artist"], NO_DATA)
        self.assertEqual(tags["album"], NO_DATA)
        self.assertEqual(tags["track_no"], NO_DATA)
        self.assertEqual(tags["has_cover"], 0)

        # 2. Write tags to MP3
        cover_img = self.test_dir / "cover.jpg"
        create_dummy_image(cover_img, color=(0, 128, 255))

        write_tags(
            str(mp3_file),
            title="Song 1",
            artist="Artist One",
            album_artist="Band A",
            album="First Record",
            year="2021",
            genre="Rock",
            track_no="1",
            new_cover_path=str(cover_img),
        )

        # 3. Read back and verify
        tags2 = read_tags(str(mp3_file))
        self.assertEqual(tags2["title"], "Song 1")
        self.assertEqual(tags2["artist"], "Artist One")
        self.assertEqual(tags2["album_artist"], "Band A")
        self.assertEqual(tags2["album"], "First Record")
        self.assertEqual(tags2["year"], "2021")
        self.assertEqual(tags2["genre"], "Rock")
        self.assertEqual(tags2["track_no"], "01")  # leading zero
        self.assertEqual(tags2["has_cover"], 1)
        self.assertTrue(Path(tags2["cover_cache_path"]).exists())

        # 4. Remove cover
        write_tags(str(mp3_file), remove_cover=True)
        tags3 = read_tags(str(mp3_file))
        self.assertEqual(tags3["has_cover"], 0)

    def test_m4a_read_and_write_tags(self):
        m4a_file = self.test_dir / "test.m4a"
        create_dummy_m4a(m4a_file)

        # 1. Read untagged M4A
        tags = read_tags(str(m4a_file))
        self.assertEqual(tags["title"], NO_DATA)
        self.assertEqual(tags["track_no"], NO_DATA)

        # 2. Write tags
        cover_img = self.test_dir / "cover2.jpg"
        create_dummy_image(cover_img, color=(255, 128, 0))

        write_tags(
            str(m4a_file),
            title="M4A Track",
            artist="M4A Artist",
            album_artist="M4A Band",
            album="M4A Album",
            year="2022",
            genre="Electronic",
            track_no="2",
            new_cover_path=str(cover_img),
        )

        # 3. Read back
        tags2 = read_tags(str(m4a_file))
        self.assertEqual(tags2["title"], "M4A Track")
        self.assertEqual(tags2["artist"], "M4A Artist")
        self.assertEqual(tags2["album_artist"], "M4A Band")
        self.assertEqual(tags2["album"], "M4A Album")
        self.assertEqual(tags2["year"], "2022")
        self.assertEqual(tags2["genre"], "Electronic")
        self.assertEqual(tags2["track_no"], "02")
        self.assertEqual(tags2["has_cover"], 1)

    def test_organize_readiness_validation(self):
        # Incomplete track
        incomplete_track = {
            "title": "Song",
            "artist": "Artist",
            "album_artist": NO_DATA,
            "album": "Album",
            "year": "2020",
            "track_no": "01",
        }
        ready, reason = is_album_ready_to_organize([incomplete_track])
        self.assertFalse(ready)
        self.assertIn("Album Artist", reason)

        # Complete track
        complete_track = {
            "title": "Song",
            "artist": "Artist",
            "album_artist": "Artist",
            "album": "Album",
            "year": "2020",
            "track_no": "01",
        }
        ready2, _ = is_album_ready_to_organize([complete_track])
        self.assertTrue(ready2)

    def test_organize_album_flow(self):
        # Create unorganized folder structure
        raw_folder = self.test_dir / "Downloads" / "Unsorted"
        raw_folder.mkdir(parents=True)
        raw_file = raw_folder / "random_file_name.mp3"
        create_dummy_mp3(raw_file)

        # Tag the file
        write_tags(
            str(raw_file),
            title="Yesterday",
            artist="The Beatles",
            album_artist="The Beatles",
            album="Help!",
            year="1965",
            genre="Rock",
            track_no="13",
        )

        # Scan and insert into DB
        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        albums = get_all_albums(self.conn)
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["album"], "Help!")

        tracks = get_album_tracks(self.conn, "Help!", "The Beatles")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["track_no"], "13")

        # Organize
        ready, _ = is_album_ready_to_organize(tracks)
        self.assertTrue(ready)

        success, msg, updated = organize_album(
            library_path=str(self.test_dir),
            tracks=tracks,
            template="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertTrue(success)

        # Check destination file
        expected_dest = self.test_dir / "The Beatles" / "1965 - Help!" / "13. Yesterday.mp3"
        self.assertTrue(expected_dest.exists())

        # Check that old folder was cleaned up
        self.assertFalse(raw_file.exists())
        self.assertFalse(raw_folder.exists())

        # Check DB was updated with new path
        updated_tracks = get_album_tracks(self.conn, "Help!", "The Beatles")
        self.assertEqual(updated_tracks[0]["file_path"], str(expected_dest.resolve()))


    def test_sanitize_characters(self):
        from malka.organizer import sanitize_filename
        self.assertEqual(sanitize_filename('AC/DC'), 'AC_DC')
        self.assertEqual(sanitize_filename('What?'), 'What_')
        self.assertEqual(sanitize_filename('Star*Wars'), 'Star_Wars')
        self.assertEqual(sanitize_filename('Track: Name'), 'Track_ Name')
        self.assertEqual(sanitize_filename('  Spaces  ... '), 'Spaces')

    def test_multi_track_album_organization(self):
        # Create a folder with 2 tracks
        album_dir = self.test_dir / "Unsorted_Album"
        album_dir.mkdir(parents=True)
        t1 = album_dir / "track_a.mp3"
        t2 = album_dir / "track_b.mp3"
        create_dummy_mp3(t1)
        create_dummy_mp3(t2)

        write_tags(
            str(t1),
            title="Come Together",
            artist="The Beatles",
            album_artist="The Beatles",
            album="Abbey Road",
            year="1969",
            track_no="1",
        )
        write_tags(
            str(t2),
            title="Something",
            artist="The Beatles",
            album_artist="The Beatles",
            album="Abbey Road",
            year="1969",
            track_no="2",
        )

        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        tracks = get_album_tracks(self.conn, "Abbey Road", "The Beatles")
        self.assertEqual(len(tracks), 2)
        ready, _ = is_album_ready_to_organize(tracks)
        self.assertTrue(ready)

        success, msg, updated = organize_album(
            library_path=str(self.test_dir),
            tracks=tracks,
            template="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertTrue(success)

        dest_t1 = self.test_dir / "The Beatles" / "1969 - Abbey Road" / "01. Come Together.mp3"
        dest_t2 = self.test_dir / "The Beatles" / "1969 - Abbey Road" / "02. Something.mp3"
        self.assertTrue(dest_t1.exists())
        self.assertTrue(dest_t2.exists())
        self.assertFalse(album_dir.exists())

        # Check DB updated
        tracks_after = get_album_tracks(self.conn, "Abbey Road", "The Beatles")
        self.assertEqual(len(tracks_after), 2)
        paths = [t["file_path"] for t in tracks_after]
        self.assertIn(str(dest_t1.resolve()), paths)
        self.assertIn(str(dest_t2.resolve()), paths)

    def test_multi_disc_sorting_and_organization(self):
        album_dir = self.test_dir / "White_Album_Raw"
        album_dir.mkdir(parents=True)
        d1_t1 = album_dir / "d1_t1.mp3"
        d2_t1 = album_dir / "d2_t1.mp3"
        create_dummy_mp3(d1_t1)
        create_dummy_mp3(d2_t1)

        write_tags(
            str(d1_t1),
            title="Back in the U.S.S.R.",
            artist="The Beatles",
            album_artist="The Beatles",
            album="The Beatles",
            year="1968",
            track_no="1",
            disc_no="1",
            disc_total="2",
        )
        write_tags(
            str(d2_t1),
            title="Birthday",
            artist="The Beatles",
            album_artist="The Beatles",
            album="The Beatles",
            year="1968",
            track_no="1",
            disc_no="2",
            disc_total="2",
        )

        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        # Check sorting: Disc 1 must come before Disc 2
        tracks = get_album_tracks(self.conn, "The Beatles", "The Beatles")
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]["title"], "Back in the U.S.S.R.")
        self.assertEqual(tracks[0]["disc_no"], "1")
        self.assertEqual(tracks[1]["title"], "Birthday")
        self.assertEqual(tracks[1]["disc_no"], "2")

        # Organize: multi-disc must create CD 1 and CD 2 folders
        success, msg, _ = organize_album(
            library_path=str(self.test_dir),
            tracks=tracks,
            template="<track_no>. <title>",
            db_conn=self.conn,
        )
        self.assertTrue(success)

        cd1_file = self.test_dir / "The Beatles" / "1968 - The Beatles" / "CD 1" / "01. Back in the U.S.S.R.mp3"
        cd2_file = self.test_dir / "The Beatles" / "1968 - The Beatles" / "CD 2" / "01. Birthday.mp3"
        self.assertTrue(cd1_file.exists())
        self.assertTrue(cd2_file.exists())

    def test_compilation_detection(self):
        comp_dir = self.test_dir / "Soundtrack"
        comp_dir.mkdir(parents=True)
        t1 = comp_dir / "song1.mp3"
        t2 = comp_dir / "song2.mp3"
        create_dummy_mp3(t1)
        create_dummy_mp3(t2)

        write_tags(
            str(t1),
            title="Track by Artist A",
            artist="Artist A",
            album="Pulp Fiction",
            year="1994",
            track_no="1",
        )
        write_tags(
            str(t2),
            title="Track by Artist B",
            artist="Artist B",
            album="Pulp Fiction",
            year="1994",
            track_no="2",
        )

        scanner = LibraryScanner(str(self.test_dir), str(self.db_path))
        scanner.run()

        albums = get_all_albums(self.conn)
        # Should be detected as a single compilation album under "Various Artists"
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]["album_artist"], "Various Artists")
        self.assertEqual(albums[0]["track_count"], 2)


if __name__ == "__main__":
    unittest.main()
