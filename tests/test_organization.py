import os
import subprocess
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import imageio_ffmpeg
from PyQt6.QtWidgets import QApplication

from malka.db import get_all_albums, get_connection, init_db, upsert_track
from malka.organizer import (
    apply_organization_plan,
    build_organization_plan,
    is_track_organized,
    organized_target_path,
    refresh_organization_flags,
)
from malka.scanner import LibraryScanner
from malka.tags import read_tags

app = QApplication.instance() or QApplication([])

TEMPLATE = "<track_no>. <title>"


def make_flac(path: Path, *, title="Song", artist="Artist", album="Album",
              year="2020", track="1", disc="1", disc_total="1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ac", "2",
        "-c:a", "flac",
        "-metadata", f"title={title}",
        "-metadata", f"artist={artist}",
        "-metadata", f"album_artist={artist}",
        "-metadata", f"album={album}",
        "-metadata", f"date={year}",
        "-metadata", "genre=Rock",
        "-metadata", f"track={track}",
        "-metadata", f"disc={disc}",
        "-metadata", f"disctotal={disc_total}",
        str(path),
    ]
    subprocess.run(cmd, check=True)
    return path


class TestOrganizedPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="malka_org_"))
        self.root = self.tmp / "library"
        self.root.mkdir()
        self.db = self.tmp / "db.sqlite"
        init_db(str(self.db))
        self.conn = get_connection(str(self.db))

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_canonical_path_detection(self):
        canonical = make_flac(
            self.root / "Artist" / "2020 - Album" / "01. Song.flac"
        )
        tags = read_tags(str(canonical))
        self.assertTrue(is_track_organized(tags, [str(self.root)], TEMPLATE))

        random = make_flac(self.root / "RandomFolder" / "Vse-vpered.flac")
        tags2 = read_tags(str(random))
        self.assertFalse(is_track_organized(tags2, [str(self.root)], TEMPLATE))

    def test_multi_disc_expects_cd_folder(self):
        path = make_flac(
            self.root / "Artist" / "2020 - Album" / "CD 2" / "01. Song.flac",
            disc="2", disc_total="2",
        )
        tags = read_tags(str(path))
        self.assertTrue(is_track_organized(tags, [str(self.root)], TEMPLATE))

        flat = make_flac(self.root / "Artist" / "2020 - Album" / "02. Song2.flac",
                         title="Song2", disc="2", disc_total="2")
        tags2 = read_tags(str(flat))
        self.assertFalse(is_track_organized(tags2, [str(self.root)], TEMPLATE))

    def test_disc_total_alone_means_multi_disc(self):
        path = make_flac(
            self.root / "Artist" / "2020 - Album" / "CD 1" / "01. Song.flac",
            disc="1", disc_total="4",
        )
        tags = read_tags(str(path))
        self.assertTrue(is_track_organized(tags, [str(self.root)], TEMPLATE))

        flat = make_flac(self.root / "Artist" / "2020 - Album" / "02. Song2.flac",
                         title="Song2", track="2", disc="1", disc_total="4")
        tags2 = read_tags(str(flat))
        self.assertFalse(is_track_organized(tags2, [str(self.root)], TEMPLATE))

    def test_file_outside_library_is_not_organized(self):
        outside = make_flac(self.tmp / "outside" / "01. Song.flac")
        tags = read_tags(str(outside))
        self.assertFalse(is_track_organized(tags, [str(self.root)], TEMPLATE))

    def test_build_plan_and_apply(self):
        random = make_flac(self.root / "RandomFolder" / "Vse-vpered.flac", title="Vse vpered")
        upsert_track(self.conn, read_tags(str(random)))
        self.conn.commit()

        track = dict(self.conn.execute("SELECT * FROM tracks").fetchone())
        plan = build_organization_plan(str(self.root), [track], TEMPLATE)
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0]["changed"])
        self.assertEqual(
            plan[0]["dst"],
            (self.root / "Artist" / "2020 - Album" / "01. Vse vpered.flac").resolve(),
        )

        ok, msg, updated = apply_organization_plan(plan, str(self.root), self.conn, TEMPLATE)
        self.assertTrue(ok, msg)
        self.assertFalse(random.exists())
        self.assertTrue(plan[0]["dst"].exists())
        row = self.conn.execute("SELECT * FROM tracks").fetchone()
        self.assertEqual(row["file_path"], str(plan[0]["dst"]))
        self.assertEqual(row["is_organized"], 1)
        self.assertEqual(sorted(p.name for p in (self.root / "RandomFolder").glob("*")), [])

    def test_plan_handles_name_collisions(self):
        first = make_flac(self.root / "a" / "x.flac", title="Same")
        second = make_flac(self.root / "b" / "y.flac", title="Same")
        upsert_track(self.conn, read_tags(str(first)))
        upsert_track(self.conn, read_tags(str(second)))
        self.conn.commit()
        tracks = [dict(r) for r in self.conn.execute("SELECT * FROM tracks")]
        plan = build_organization_plan(str(self.root), tracks, TEMPLATE)
        names = [p["dst"].name for p in plan]
        self.assertEqual(len(set(names)), 2)
        self.assertIn("01. Same.flac", names)
        self.assertIn("01. Same (1).flac", names)

    def test_refresh_flags_and_album_aggregate(self):
        good = make_flac(self.root / "Artist" / "2020 - Album" / "01. Song.flac")
        bad = make_flac(self.root / "loose" / "02. Song2.flac", title="Song2", track="2")
        upsert_track(self.conn, read_tags(str(good)))
        upsert_track(self.conn, read_tags(str(bad)))
        self.conn.commit()

        refresh_organization_flags(self.conn, [str(self.root)], TEMPLATE)
        rows = {Path(r["file_path"]).name: r["is_organized"] for r in self.conn.execute("SELECT * FROM tracks")}
        self.assertEqual(rows["01. Song.flac"], 1)
        self.assertEqual(rows["02. Song2.flac"], 0)

        album = get_all_albums(self.conn)[0]
        self.assertFalse(album["is_organized"])

        # Once the loose file is in place, the album counts as organized.
        self.conn.execute("DELETE FROM tracks WHERE file_path = ?", (str(bad),))
        self.conn.commit()
        bad.unlink()
        fixed = make_flac(self.root / "Artist" / "2020 - Album" / "02. Song2.flac", title="Song2", track="2")
        upsert_track(self.conn, read_tags(str(fixed)))
        refresh_organization_flags(self.conn, [str(self.root)], TEMPLATE)
        self.assertTrue(get_all_albums(self.conn)[0]["is_organized"])

    def test_refresh_uses_no_filesystem_lookups(self):
        """The startup/scan refresh must not call realpath/stat per track."""
        path = make_flac(self.root / "Artist" / "2020 - Album" / "01. Song.flac")
        upsert_track(self.conn, read_tags(str(path)))
        self.conn.commit()

        from unittest.mock import patch

        with patch("pathlib.Path.resolve", side_effect=AssertionError("filesystem lookup")):
            refresh_organization_flags(self.conn, [str(self.root)], TEMPLATE)
        row = self.conn.execute("SELECT is_organized FROM tracks").fetchone()
        self.assertEqual(row["is_organized"], 1)

    def test_scanner_sets_flags(self):
        make_flac(self.root / "Artist" / "2020 - Album" / "01. Song.flac")
        make_flac(self.root / "loose" / "x.flac", title="X", track="2")

        scanner = LibraryScanner([str(self.root)], str(self.db), force_rescan=True, naming_format=TEMPLATE)
        scanner.run()

        rows = {Path(r["file_path"]).name: r["is_organized"] for r in self.conn.execute("SELECT * FROM tracks")}
        self.assertEqual(rows["01. Song.flac"], 1)
        self.assertEqual(rows["x.flac"], 0)

    def test_organized_target_path_uses_template(self):
        track = {
            "file_path": str(self.root / "x" / "y.mp3"),
            "album_artist": "A/B",
            "album": "Al:bum",
            "year": "2020",
            "track_no": "3",
            "title": "Ti:tle",
            "disc_no": "1",
            "disc_total": "1",
        }
        expected = organized_target_path(str(self.root), track, TEMPLATE, multi_disc=False)
        self.assertEqual(expected.name, "03. Ti_tle.mp3")
        self.assertEqual(expected.parent.name, "2020 - Al_bum")
        self.assertEqual(expected.parent.parent.name, "A_B")


class TestOrganizeDialog(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="malka_orgdlg_"))
        self.root1 = self.tmp / "lib1"
        self.root2 = self.tmp / "lib2"
        self.root1.mkdir()
        self.root2.mkdir()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dialog_lists_every_rename_and_switches_root(self):
        from malka.ui.organize_dialog import OrganizeDialog

        track = {
            "id": 1,
            "file_path": str(make_flac(self.root1 / "Random" / "x.flac")),
            "album_artist": "Artist",
            "album": "Album",
            "year": "2020",
            "track_no": "1",
            "title": "Song",
            "disc_no": "1",
            "disc_total": "1",
        }
        dlg = OrganizeDialog([track], [str(self.root1), str(self.root2)], str(self.root1), TEMPLATE)
        dlg.show()

        self.assertEqual(dlg.left_table.rowCount(), 1)
        self.assertEqual(dlg.right_table.rowCount(), 1)
        # Only the part after the shared prefix is shown...
        self.assertEqual(dlg.left_table.item(0, 0).text(), os.path.join("Random", "x.flac"))
        self.assertEqual(
            dlg.right_table.item(0, 0).text(),
            os.path.join("Artist", "2020 - Album", "01. Song.flac"),
        )
        # ...while tooltips keep the absolute paths.
        self.assertEqual(dlg.left_table.item(0, 0).toolTip(), str(self.root1 / "Random" / "x.flac"))
        self.assertIn(str(self.root1), dlg.right_table.item(0, 0).toolTip())
        self.assertIn("Common prefix hidden", dlg.prefix_lbl.text())
        self.assertEqual(dlg.chosen_library(), str(self.root1))

        # Each pane has its own horizontal scrollbar and keeps file names readable.
        for pane in (dlg.left_table, dlg.right_table):
            self.assertEqual(pane.horizontalScrollBarPolicy().name, "ScrollBarAsNeeded")
            self.assertEqual(pane.horizontalScrollMode().name, "ScrollPerPixel")
            self.assertEqual(pane.textElideMode().name, "ElideLeft")
        self.assertIsNot(dlg.left_table.horizontalScrollBar(), dlg.right_table.horizontalScrollBar())

        # Switching the target library re-targets every row.
        dlg.root_combo.setCurrentIndex(1)
        self.assertEqual(dlg.chosen_library(), str(self.root2))
        self.assertIn(str(self.root2), dlg.right_table.item(0, 0).toolTip())
        self.assertTrue(dlg.plan()[0]["changed"])
        dlg.reject()

    def test_difference_toggle_shows_full_paths(self):
        from malka.ui.organize_dialog import OrganizeDialog

        good = make_flac(self.root1 / "Artist" / "2020 - Album" / "01. Song.flac")
        loose = make_flac(self.root1 / "Random" / "x.flac", title="Other", track="2")
        base = {
            "album_artist": "Artist", "album": "Album", "year": "2020",
            "disc_no": "1", "disc_total": "1",
        }
        tracks = [
            dict(base, id=1, file_path=str(good), track_no="1", title="Song"),
            dict(base, id=2, file_path=str(loose), track_no="2", title="Other"),
        ]
        dlg = OrganizeDialog(tracks, [str(self.root1)], str(self.root1), TEMPLATE)
        dlg.show()

        # Checked (default): only the differing part of changed rows.
        self.assertTrue(dlg.show_diff_cb.isChecked())
        self.assertEqual(dlg.left_table.rowCount(), 1)
        self.assertEqual(dlg.left_table.item(0, 0).text(), os.path.join("Random", "x.flac"))

        # Unchecked: full paths for every track, including unchanged ones.
        dlg.show_diff_cb.setChecked(False)
        self.assertEqual(dlg.left_table.rowCount(), 2)
        self.assertEqual(dlg.left_table.item(0, 0).text(), str(good))
        self.assertEqual(dlg.left_table.item(1, 0).text(), str(loose))
        self.assertEqual(dlg.prefix_lbl.text(), "")
        self.assertEqual(dlg.right_table.item(0, 0).text(), "already in place")
        self.assertIn("Other", dlg.right_table.item(1, 0).text())
        dlg.reject()

    def test_dialog_marks_already_organized_files(self):
        from malka.ui.organize_dialog import OrganizeDialog

        path = make_flac(self.root1 / "Artist" / "2020 - Album" / "01. Song.flac")
        track = {
            "id": 1,
            "file_path": str(path),
            "album_artist": "Artist",
            "album": "Album",
            "year": "2020",
            "track_no": "1",
            "title": "Song",
            "disc_no": "1",
            "disc_total": "1",
        }
        dlg = OrganizeDialog([track], [str(self.root1)], str(self.root1), TEMPLATE)
        dlg.show()
        self.assertFalse(dlg.plan()[0]["changed"])
        self.assertFalse(dlg.btn_apply.isEnabled())
        # Nothing to change => the compact view is empty...
        self.assertEqual(dlg.left_table.rowCount(), 0)
        # ...but the full view shows the row as already in place.
        dlg.show_diff_cb.setChecked(False)
        self.assertEqual(dlg.left_table.rowCount(), 1)
        self.assertEqual(dlg.left_table.item(0, 0).text(), str(path))
        self.assertEqual(dlg.right_table.item(0, 0).text(), "already in place")
        dlg.reject()


class TestAlbumCardOrganizeState(unittest.TestCase):
    def _album(self, is_organized: bool):
        return {
            "album": "Album",
            "album_artist": "Artist",
            "display_artist": "Artist",
            "year": "2020",
            "track_count": 1,
            "disc_count": 1,
            "is_organized": is_organized,
        }

    def test_badge_and_menu_when_not_organized(self):
        from malka.ui.album_card import AlbumCard

        card = AlbumCard(self._album(False), is_organize_ready=True)
        self.assertTrue(hasattr(card, "badge_organize"))
        menu = card.build_context_menu()
        action = next(a for a in menu.actions() if a.text() == "Organize album files")
        self.assertTrue(action.isEnabled())

    def test_menu_disabled_when_organized(self):
        from malka.ui.album_card import AlbumCard

        card = AlbumCard(self._album(True), is_organize_ready=True)
        self.assertFalse(hasattr(card, "badge_organize"))
        menu = card.build_context_menu()
        action = next(a for a in menu.actions() if a.text() == "Organize album files")
        self.assertFalse(action.isEnabled())


if __name__ == "__main__":
    unittest.main()
