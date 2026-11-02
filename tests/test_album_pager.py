import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QPushButton, QWidget

from malka.ui.main_window import MainWindow, album_page_marker, format_page_label

app = QApplication.instance() or QApplication([])


def album(album_name="Album", artist="Artist", year="2000"):
    return {
        "album": album_name,
        "album_artist": artist,
        "display_artist": artist,
        "year": year,
        "track_count": 1,
        "disc_count": 1,
    }


class TestPageMarkers(unittest.TestCase):
    def test_title_sort_uses_album_letters(self):
        item = album("Kindred", "Burial", "2012")
        self.assertEqual(album_page_marker(item, "title_asc"), "K")
        self.assertEqual(album_page_marker(item, "title_desc"), "K")
        self.assertEqual(album_page_marker(album("!!!", "X"), "title_asc"), "#")

    def test_artist_sort_uses_three_artist_letters(self):
        item = album("Kindred", "Burial", "2012")
        self.assertEqual(album_page_marker(item, "artist_year"), "BUR")
        self.assertEqual(album_page_marker(album("A", "Bo"), "artist_year"), "BO")
        self.assertEqual(album_page_marker(album("A", ""), "artist_year"), "#")

    def test_year_sort_uses_years(self):
        self.assertEqual(album_page_marker(album(year="2012"), "year_asc"), "2012")
        self.assertEqual(album_page_marker(album(year="1997-05-21"), "year_desc"), "1997")
        self.assertEqual(album_page_marker(album(year="No data provided"), "year_asc"), "#")

    def test_label_format(self):
        self.assertEqual(format_page_label("BUR", "BUR"), "BUR")
        self.assertEqual(format_page_label("BUR", "COC"), "BUR-COC")
        self.assertEqual(format_page_label("1970", "1975"), "1970-1975")


class _PagerHarness(MainWindow):
    """Cheap stand-in: only the fields used by _update_album_pager."""

    def __init__(self, sort_mode: str, page_size: int = 2):
        self.album_sort_mode = sort_mode
        self.album_page = 0
        self.album_page_size = page_size
        self.theme = "dark"
        self._albums_pager_layout = QHBoxLayout()
        self._albums_pager_header = QFrame()


class TestPagerLabels(unittest.TestCase):
    def _labels(self, sort_mode, albums):
        harness = _PagerHarness(sort_mode, page_size=2)
        items = [("album", item) for item in albums]
        harness._update_album_pager(
            (len(albums) + 1) // 2,
            items,
        )
        buttons = [
            harness._albums_pager_layout.itemAt(i).widget()
            for i in range(harness._albums_pager_layout.count())
            if isinstance(harness._albums_pager_layout.itemAt(i).widget(), QPushButton)
        ]
        return [button.text() for button in buttons]

    def test_artist_year_labels(self):
        albums = [
            album("A", "Burial"),
            album("B", "Cocorosie"),
            album("C", "Daft Punk"),
            album("D", "Zola Jesus"),
        ]
        self.assertEqual(self._labels("artist_year", albums), ["BUR-COC", "DAF-ZOL"])

    def test_year_labels(self):
        albums = [
            album(year="1970"),
            album(year="1975"),
            album(year="1980"),
            album(year="1981"),
        ]
        self.assertEqual(self._labels("year_asc", albums), ["1970-1975", "1980-1981"])

    def test_title_labels(self):
        albums = [
            album("Apple"),
            album("Banana"),
            album("Cherry"),
            album("Date"),
        ]
        self.assertEqual(self._labels("title_asc", albums), ["A-B", "C-D"])

    def test_duplicate_labels_get_page_numbers(self):
        albums = [
            album("A", "Burial"),
            album("B", "Burial"),
            album("C", "Burial"),
            album("D", "Burial"),
        ]
        labels = self._labels("artist_year", albums)
        self.assertEqual(labels, ["BUR · 1", "BUR · 2"])


if __name__ == "__main__":
    unittest.main()
