"""Background workers for the Discogs lookups."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from malka.discogs_client import DiscogsClient
from malka.discogs_metadata import DiscogsMetadataClient
from malka.discogs_models import CoverArtError, SearchCancelled


class DiscogsCoverWorker(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, album: str, artist: str, year: str = "", parent=None):
        super().__init__(parent)
        self.album = album
        self.artist = artist
        self.year = year

    def run(self):
        try:
            result = DiscogsClient().search(
                self.album,
                self.artist,
                year=self.year,
                progress=self.progress.emit,
                should_cancel=self.isInterruptionRequested,
            )
        except SearchCancelled:
            return
        except CoverArtError as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(f"Unexpected error: {exc}")
        else:
            if not self.isInterruptionRequested():
                self.succeeded.emit(result)


class DiscogsMetadataWorker(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, artist: str, album: str, year: str, parent=None):
        super().__init__(parent)
        self.artist = artist
        self.album = album
        self.year = year

    def run(self):
        try:
            candidates = DiscogsMetadataClient().find_releases(
                self.artist,
                self.album,
                self.year,
                progress=self.progress.emit,
                should_cancel=self.isInterruptionRequested,
            )
        except SearchCancelled:
            return
        except CoverArtError as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(f"Unexpected error: {exc}")
        else:
            if not self.isInterruptionRequested():
                self.succeeded.emit(candidates)
