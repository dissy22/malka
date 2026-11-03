"""Discogs metadata and artwork picker for the tag editor.

The dialog is intentionally self-contained: it runs the network lookup in a
QThread, shows the matching masters/releases with their primary artwork, and
returns a plain dictionary of tag values plus a local cover file path.
"""

from __future__ import annotations

import html
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from malka.config import CACHE_DIR
from malka.discogs_client import DiscogsClient, DiscogsError
from malka.discogs_imaging import detect_extension, prepare_artwork
from malka.discogs_metadata import (
    DiscogsMetadataClient,
    ReleaseCandidate,
    TrackInfo,
    rank_tracks_by_filename,
    rank_tracks_by_title,
    tracks_by_number,
)
from malka.ui.image_utils import checkbox_checkmark_qss


STYLE_DARK = """
    QDialog { background:#0d1117; color:#e6edf3; }
    QWidget { color:#e6edf3; }
    QLabel { color:#e6edf3; }
    QLabel#discogsSubtitle { color:#8b949e; font-size:11px; }
    QLabel#discogsTitle { font-size:17px; font-weight:700; color:#ffffff; }
    QLabel#discogsPreview {
        background:#0d1117; border:1px solid #30363d; border-radius:6px;
    }
    QLineEdit, QComboBox {
        background:#0d1117; border:1px solid #30363d; border-radius:5px;
        padding:6px 9px; color:#ffffff;
    }
    QLineEdit:focus, QComboBox:focus { border-color:#58a6ff; }
    QComboBox QAbstractItemView {
        background:#161b22; color:#e6edf3; border:1px solid #30363d;
        selection-background-color:#1f6feb; selection-color:#ffffff;
    }
    QListWidget {
        background:#0d1117; border:1px solid #30363d; border-radius:6px;
        color:#e6edf3; padding:4px;
    }
    QListWidget::item { padding:6px; border-bottom:1px solid #21262d; }
    QListWidget::item:selected { background:#1f6feb; color:#ffffff; }
    QPushButton {
        background:#21262d; border:1px solid #30363d; border-radius:5px;
        color:#e6edf3; padding:7px 14px; min-width:82px;
    }
    QPushButton:hover { background:#30363d; border-color:#8b949e; }
    QPushButton#discogsApply {
        background:#238636; border-color:#2ea043; color:#ffffff; font-weight:600;
    }
    QPushButton#discogsApply:hover { background:#2ea043; }
    QPushButton:disabled { background:#161b22; color:#6e7681; border-color:#30363d; }
    QSplitter::handle { background:#30363d; width:1px; }
"""

STYLE_LIGHT = """
    QDialog { background:#f6f8fa; color:#1f2328; }
    QWidget { color:#1f2328; }
    QLabel { color:#1f2328; }
    QLabel#discogsSubtitle { color:#656d76; font-size:11px; }
    QLabel#discogsTitle { font-size:17px; font-weight:700; color:#1f2328; }
    QLabel#discogsPreview {
        background:#ffffff; border:1px solid #d0d7de; border-radius:6px;
    }
    QLineEdit, QComboBox {
        background:#ffffff; border:1px solid #d0d7de; border-radius:5px;
        padding:6px 9px; color:#1f2328;
    }
    QLineEdit:focus, QComboBox:focus { border-color:#0969da; }
    QComboBox QAbstractItemView {
        background:#ffffff; color:#1f2328; border:1px solid #d0d7de;
        selection-background-color:#eaeef2; selection-color:#0969da;
    }
    QListWidget {
        background:#ffffff; border:1px solid #d0d7de; border-radius:6px;
        color:#1f2328; padding:4px;
    }
    QListWidget::item { padding:6px; border-bottom:1px solid #eaeef2; }
    QListWidget::item:selected { background:#eaeef2; color:#0969da; }
    QPushButton {
        background:#f6f8fa; border:1px solid #d0d7de; border-radius:5px;
        color:#1f2328; padding:7px 14px; min-width:82px;
    }
    QPushButton:hover { background:#eaeef2; border-color:#b0b8c1; }
    QPushButton#discogsApply {
        background:#1f883d; border-color:#1a7f37; color:#ffffff; font-weight:600;
    }
    QPushButton#discogsApply:hover { background:#1a7f37; }
    QPushButton:disabled { background:#f6f8fa; color:#8c959f; border-color:#d0d7de; }
    QSplitter::handle { background:#d0d7de; width:1px; }
"""


def _pixmap(data: bytes, size: int) -> QPixmap:
    pix = QPixmap()
    if not data or not pix.loadFromData(data):
        return QPixmap()
    return pix.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class DiscogsSearchWorker(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(list, str)
    failed = pyqtSignal(str)

    def __init__(self, artist: str, album: str, year: str, with_covers: bool, parent=None):
        super().__init__(parent)
        self.artist = artist
        self.album = album
        self.year = year
        self.with_covers = with_covers
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            meta = DiscogsMetadataClient(max_candidates=6)
            candidates = meta.find_releases(
                artist=self.artist,
                album=self.album,
                year=self.year,
                progress=self.progress.emit,
                should_cancel=lambda: self._cancelled,
            )
            warning = ""
            if self.with_covers and candidates:
                client = DiscogsClient()
                for index, candidate in enumerate(candidates, start=1):
                    if self._cancelled:
                        return
                    self.progress.emit(f"Downloading artwork {index}/{len(candidates)}…")
                    try:
                        cover = client.cover_for(
                            candidate.entity,
                            candidate.id,
                            candidate.title,
                            candidate.artist,
                            candidate.year,
                            candidate.source_url,
                        )
                    except Exception:
                        cover = None
                    if cover and cover.thumbnail:
                        candidate.cover_data = cover.thumbnail
                        candidate.cover_url = cover.full_url
                        candidate.cover_width = cover.width
                        candidate.cover_height = cover.height
                    elif not warning:
                        warning = "Some Discogs releases have no available artwork."
            if not self._cancelled:
                self.succeeded.emit(candidates, warning)
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


class DiscogsDialog(QDialog):
    """Search Discogs and apply release metadata and/or cover artwork."""

    def __init__(
        self,
        *,
        album: str = "",
        artist: str = "",
        year: str = "",
        theme: str = "dark",
        parent=None,
        mode: str = "all",
        field: str = "",
        track_title: str = "",
        track_no: str = "",
        disc_no: str = "",
        file_path: str = "",
    ):
        super().__init__(parent)
        self.theme = theme
        self.mode = mode
        self.field = field
        self.track_title = track_title
        self.track_no = track_no
        self.disc_no = disc_no
        self.file_path = file_path
        self.candidates: List[ReleaseCandidate] = []
        self.worker: Optional[DiscogsSearchWorker] = None
        self.metadata: Dict[str, str] = {}
        self.cover_path = ""

        self.setWindowTitle("Search Discogs")
        self.resize(940, 620)
        self.setMinimumSize(820, 540)
        self._build_ui()
        self.apply_theme(theme)
        self.album_edit.setText(album)
        self.artist_edit.setText(artist)
        self.year_edit.setText(year)
        if album or artist:
            self.search()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel("Search Discogs")
        title.setObjectName("discogsTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Find release metadata, track positions and artwork. "
            "Results can fill the whole album or the selected track."
        )
        subtitle.setObjectName("discogsSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.album_edit = QLineEdit()
        self.album_edit.setPlaceholderText("Album")
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("Artist")
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Year")
        self.year_edit.setFixedWidth(70)
        search_row.addWidget(self.album_edit, 3)
        search_row.addWidget(self.artist_edit, 2)
        search_row.addWidget(self.year_edit, 0)
        self.btn_search = QPushButton("Search")
        self.btn_search.clicked.connect(self.search)
        search_row.addWidget(self.btn_search)
        root.addLayout(search_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("discogsSubtitle")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.results_list = QListWidget()
        self.results_list.setIconSize(QSize(56, 56))
        self.results_list.setWordWrap(True)
        self.results_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_list.currentRowChanged.connect(self._on_candidate_selected)
        splitter.addWidget(self.results_list)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(8)

        self.preview = QLabel("No artwork loaded")
        self.preview.setObjectName("discogsPreview")
        self.preview.setFixedSize(250, 250)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)

        self.detail_label = QLabel("Select a release to see its metadata.")
        self.detail_label.setObjectName("discogsSubtitle")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.TextFormat.RichText)
        detail_layout.addWidget(self.detail_label)

        self.track_combo = QComboBox()
        self.track_combo.setVisible(mode_is_track(self.mode))
        self.track_label = QLabel("Track:")
        self.track_label.setVisible(mode_is_track(self.mode))
        track_row = QHBoxLayout()
        track_row.addWidget(self.track_label)
        track_row.addWidget(self.track_combo, 1)
        detail_layout.addLayout(track_row)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Artwork size:"))
        self.size_combo = QComboBox()
        self.size_combo.addItem("Original", 0)
        for size in (500, 600, 800, 1000, 1200):
            self.size_combo.addItem(f"{size} × {size}", size)
        size_row.addWidget(self.size_combo)
        size_row.addStretch(1)
        detail_layout.addLayout(size_row)
        detail_layout.addStretch(1)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.result_count = QLabel("")
        self.result_count.setObjectName("discogsSubtitle")
        footer.addWidget(self.result_count)
        footer.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        self.btn_apply = QPushButton("Apply to tags")
        self.btn_apply.setObjectName("discogsApply")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self._apply_selected)
        footer.addWidget(self.btn_apply)
        root.addLayout(footer)

    def apply_theme(self, theme: str):
        self.theme = theme
        self.setStyleSheet(
            (STYLE_LIGHT if theme == "light" else STYLE_DARK) + checkbox_checkmark_qss()
        )
        color = "#0969da" if theme == "light" else "#58a6ff"
        self.detail_label.setStyleSheet(f"color:{color};")
        self.preview.setStyleSheet(
            "background:#ffffff;border:1px solid #d0d7de;border-radius:6px;"
            if theme == "light"
            else "background:#0d1117;border:1px solid #30363d;border-radius:6px;"
        )

    # ------------------------------------------------------------------
    def search(self):
        if self.worker and self.worker.isRunning():
            return
        album = self.album_edit.text().strip()
        artist = self.artist_edit.text().strip()
        year = self.year_edit.text().strip()
        if not album and not artist:
            QMessageBox.information(
                self, "Search Discogs", "Enter at least an artist or an album title."
            )
            return
        self.btn_search.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.results_list.clear()
        self.candidates = []
        self.status_label.setText("Searching Discogs…")
        self.worker = DiscogsSearchWorker(
            artist, album, year, with_covers=self.mode != "field", parent=self
        )
        self.worker.progress.connect(self.status_label.setText)
        self.worker.succeeded.connect(self._on_results)
        self.worker.failed.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self):
        self.btn_search.setEnabled(True)
        self.worker = None

    def _on_error(self, message: str):
        self.status_label.setText(f"Discogs: {message}")
        self.btn_search.setEnabled(True)

    def _on_results(self, candidates: List[ReleaseCandidate], warning: str):
        self.candidates = list(candidates or [])
        self.results_list.clear()
        for candidate in self.candidates:
            text = candidate.display_title
            detail = candidate.display_detail
            if detail:
                text += f"\n{detail}"
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, 62))
            item.setToolTip(candidate.tooltip)
            if candidate.cover_data:
                pix = _pixmap(candidate.cover_data, 56)
                if not pix.isNull():
                    item.setIcon(QIcon(pix))
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            self.results_list.addItem(item)
        count = len(self.candidates)
        self.result_count.setText(
            f"{count} release{'s' if count != 1 else ''} found"
        )
        if warning:
            self.status_label.setText(warning)
        elif count:
            self.status_label.setText("Select a release and apply it to the tags.")
        else:
            self.status_label.setText(
                "No matching releases found. Try a shorter album title or remove the year."
            )
        if self.candidates:
            self.results_list.setCurrentRow(0)

    # ------------------------------------------------------------------
    def _on_candidate_selected(self, row: int):
        if row < 0 or row >= len(self.candidates):
            self.btn_apply.setEnabled(False)
            return
        candidate = self.candidates[row]
        pix = _pixmap(candidate.cover_data, 250)
        if pix.isNull():
            self.preview.setText("No artwork available")
        else:
            self.preview.setPixmap(pix)
        parts = [
            f"<b>{html.escape(candidate.artist or 'Unknown artist')}</b>",
            f"{html.escape(candidate.title)}" + (f" ({html.escape(candidate.year)})" if candidate.year else ""),
        ]
        if candidate.formats:
            parts.append(html.escape(candidate.formats[0]))
        if candidate.country:
            parts.append(html.escape(candidate.country))
        if candidate.genre_values:
            parts.append("Genre: " + html.escape(", ".join(candidate.genre_values[:4])))
        if candidate.tracks:
            parts.append(f"{len(candidate.tracks)} tracks")
        self.detail_label.setText("<br>".join(parts))

        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for track in candidate.tracks:
            self.track_combo.addItem(track.display, track)
        self.track_combo.blockSignals(False)
        if (
            mode_is_track(self.mode)
            or self.mode == "all"
            or self.field in ("title", "track_no", "disc_no")
        ):
            self._select_matching_track(candidate)
        self.btn_apply.setEnabled(True)

    def _select_matching_track(self, candidate: ReleaseCandidate):
        choice: Optional[TrackInfo] = None
        if self.mode == "track":
            if self.track_no:
                matches = tracks_by_number(candidate, self.track_no, self.disc_no)
                if matches:
                    choice = matches[0]
            if choice is None and self.track_title:
                ranked = rank_tracks_by_title(candidate, self.track_title)
                if ranked and ranked[0][0] >= 0.6:
                    choice = ranked[0][1]
            if choice is None and self.file_path:
                ranked = rank_tracks_by_filename(
                    candidate,
                    Path(self.file_path).stem,
                    candidate.artist,
                    candidate.title,
                )
                if ranked and ranked[0][0] >= 0.55:
                    choice = ranked[0][1]
        if choice is not None:
            for index in range(self.track_combo.count()):
                track = self.track_combo.itemData(index)
                if track is choice or (
                    track.position == choice.position and track.title == choice.title
                ):
                    self.track_combo.setCurrentIndex(index)
                    break

    def _selected_track(self) -> Optional[TrackInfo]:
        if self.track_combo.count() == 0:
            return None
        data = self.track_combo.currentData()
        return data if isinstance(data, TrackInfo) else None

    def _apply_selected(self):
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self.candidates):
            return
        candidate = self.candidates[row]
        track = self._selected_track()
        if mode_is_track(self.mode) and track is None and self.track_combo.count():
            return
        genre = ", ".join(candidate.genre_values[:3])
        discs = [
            int(track.disc_no)
            for track in candidate.tracks
            if str(track.disc_no).isdigit()
        ]
        disc_total = str(max(discs)) if discs else "1"
        values = {
            "album": candidate.title,
            "album_artist": candidate.artist,
            "artist": candidate.artist,
            "year": candidate.year,
            "genre": genre,
            "disc_total": disc_total,
        }
        if mode_is_track(self.mode):
            if track is not None:
                values["title"] = track.title
                values["track_no"] = track.track_no
                values["disc_no"] = track.disc_no
        if self.mode == "field" and self.field:
            key = self.field
            if key == "album_artist":
                values = {"album_artist": candidate.artist}
            elif key == "genre":
                values = {"genre": genre}
            elif key == "title":
                values = {"title": track.title if track else ""}
            elif key == "track_no":
                values = {"track_no": track.track_no if track else ""}
            elif key == "disc_no":
                values = {"disc_no": track.disc_no if track else ""}
            else:
                values = {key: values.get(key, "")}
        self.metadata = {k: v for k, v in values.items() if v}
        self.cover_path = self._save_cover(candidate)
        self.accept()

    def _save_cover(self, candidate: ReleaseCandidate) -> str:
        if not candidate.cover_data:
            return ""
        try:
            target = self.size_combo.currentData() or 0
            prepared = prepare_artwork(candidate.cover_data, target or None)
            ext = prepared.extension
            path = CACHE_DIR / f"discogs_{uuid.uuid4().hex}.{ext}"
            path.write_bytes(prepared.data)
            return str(path)
        except Exception:
            return ""

    def _stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1500)

    def reject(self):
        self._stop_worker()
        super().reject()

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)


def mode_is_track(mode: str) -> bool:
    return mode == "track"
