import unittest

from malka.discogs_metadata import (
    ReleaseCandidate,
    TrackInfo,
    normalize_text,
    rank_tracks_by_title,
    tracks_by_number,
)
from malka.discogs_models import album_search_variants, image_dimensions


class TestDiscogsHelpers(unittest.TestCase):
    def test_album_variants_remove_edition_suffix(self):
        variants = album_search_variants("Nevermind (Deluxe Edition)")
        self.assertEqual(variants[0], "Nevermind (Deluxe Edition)")
        self.assertIn("Nevermind", variants)

    def test_track_number_and_title_matching(self):
        candidate = ReleaseCandidate(
            id="1",
            entity="master",
            title="Album",
            artist="Artist",
            year="2000",
            tracks=[
                TrackInfo("1", "First Song", "3:00", "1", "1"),
                TrackInfo("2", "Second Song", "4:00", "2", "1"),
            ],
        )
        self.assertEqual(tracks_by_number(candidate, "2")[0].title, "Second Song")
        self.assertEqual(rank_tracks_by_title(candidate, "Second Song")[0][1].title, "Second Song")
        self.assertIn("second", normalize_text("Second (Song)"))

    def test_image_dimensions_for_png(self):
        png = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x02\x58\x00\x00\x02\x58\x08\x06\x00\x00\x00"
        )
        self.assertEqual(image_dimensions(png), (600, 600))


if __name__ == "__main__":
    unittest.main()
