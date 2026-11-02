from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
)

from malka.config import NO_DATA, config
from malka.importer import (
    ImportAnalysisResult,
    find_ffmpeg_executable,
    get_audio_encoder,
    get_audio_encoder_label,
)
from malka.ui.edit_dialog import BaseAlbumEditDialog, CoverPreviewWidget


class ImportDialog(BaseAlbumEditDialog):
    """
    Import dialog allowing album-level and single-track metadata editing prior to import.
    Displays source info banner (direct audio file copy vs QAAC conversion and resampling).
    Shares the exact layout, controls, and dark styling with EditAlbumDialog.
    """

    def __init__(self, analysis: ImportAnalysisResult, parent=None, theme: Optional[str] = None):
        self.analysis = analysis
        super().__init__(tracks=analysis.tracks, parent=parent, theme=theme)

        self.setWindowTitle("Import Album to Library")

        # Top banner with source and format details
        self._setup_banner()

        # Destination folder selector (only when several library roots are configured)
        self._setup_destination()

        # Populate album values directly from analysis if provided
        self._apply_analysis_metadata()

        # Configure action button for import
        self.btn_action.setText("Import to Library")
        self.btn_action.setObjectName("importBtn")
        self.btn_import = self.btn_action  # alias for tests and callers
        self.btn_action.clicked.connect(self._on_import_clicked)

        # Backward compatibility aliases
        self.cover_widget = self.album_cover_widget
        self.cb_compilation = self.compilation_checkbox
        self.cb_apply_artist_all = self.artist_same_checkbox

        # Apply theme to banner
        self.apply_theme(self.theme)

        # Validate readiness
        self._validate_readiness()

    def _setup_banner(self):
        self.banner = QFrame()
        self.banner.setObjectName("importBannerFrame")
        banner_layout = QVBoxLayout(self.banner)
        banner_layout.setContentsMargins(12, 10, 12, 10)
        banner_layout.setSpacing(4)

        folder_name = Path(self.analysis.source_folder).name if self.analysis.source_folder else "Selected Folder"
        self.banner_title_lbl = QLabel(f"<b>Import Source:</b> {folder_name}")
        banner_layout.addWidget(self.banner_title_lbl)

        source_ext = Path(self.analysis.source_flac_path).suffix.lower() if self.analysis.source_flac_path else None
        encoder_label = get_audio_encoder_label(source_ext)
        enc_type, enc_path = get_audio_encoder(source_ext)
        ffmpeg_path = find_ffmpeg_executable()
        warn_msg = ""
        if self.analysis.variant in (2, 3):
            if not enc_path or not enc_path.exists():
                import sys
                if sys.platform != "win32":
                    warn_msg = f"<br><span style='color: #cf222e; font-weight: bold;'>⚠ FFmpeg is required to convert {source_ext or 'lossless'} audio, but was not found!</span>"
                else:
                    warn_msg = "<br><span style='color: #cf222e; font-weight: bold;'>⚠ Neither QAAC nor FFmpeg is available! Please install FFmpeg or QAAC.</span>"
            elif enc_type == "qaac" and (not ffmpeg_path or not ffmpeg_path.exists()):
                warn_msg = "<br><span style='color: #cf222e; font-weight: bold;'>⚠ FFmpeg is required to decode audio tracks for QAAC, but was not found in codecs/ffmpeg/!</span>"

        if self.analysis.variant == 2:
            ext_label = source_ext.lstrip(".").upper() if source_ext else "FLAC"
            sr_info = f"{self.analysis.sample_rate} Hz, {self.analysis.bits_per_sample}-bit"
            if self.analysis.target_sample_rate:
                resample_info = f"Resampling to <b>{self.analysis.target_sample_rate} Hz 16-bit</b>"
            else:
                resample_info = f"Keeping original <b>{self.analysis.sample_rate} Hz 16-bit</b>"
            detail_text = (
                f"🔀 <b>Variant 2 ({ext_label} + CUE):</b> Splitting & converting via {encoder_label}. "
                f"Source: {sr_info} → {resample_info}.{warn_msg}"
            )
        elif self.analysis.variant == 3:
            sr_info = f"{self.analysis.sample_rate} Hz, {self.analysis.bits_per_sample}-bit"
            if self.analysis.target_sample_rate:
                resample_info = f"Resampling to <b>{self.analysis.target_sample_rate} Hz 16-bit</b>"
            else:
                resample_info = f"Keeping original <b>{self.analysis.sample_rate} Hz 16-bit</b>"
            detail_text = (
                f"🔀 <b>Variant 3 (Track-by-track Lossless):</b> Converting {len(self.tracks)} tracks via {encoder_label}. "
                f"Source: {sr_info} → {resample_info}.{warn_msg}"
            )
        else:
            detail_text = (
                f"📁 <b>Variant 1 (Audio Files):</b> Direct import of {len(self.tracks)} tracks into library. "
                f"Original audio stream preserved."
            )

        self.banner_detail_lbl = QLabel(detail_text)
        self.banner_detail_lbl.setWordWrap(True)
        banner_layout.addWidget(self.banner_detail_lbl)

        self.top_banner_container.addWidget(self.banner)

    def _setup_destination(self):
        self.destination_combo = None
        paths = list(getattr(config, "library_paths", []))
        if len(paths) <= 1:
            return

        frame = QFrame()
        frame.setObjectName("importDestinationFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        label = QLabel("Import into library folder:")
        layout.addWidget(label)

        self.destination_combo = QComboBox()
        for path in paths:
            self.destination_combo.addItem(path, path)
        self.destination_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self.destination_combo, 1)
        self.top_banner_container.addWidget(frame)

    def get_destination_library(self) -> Optional[str]:
        if self.destination_combo is not None and self.destination_combo.count() > 0:
            return self.destination_combo.currentData() or self.destination_combo.currentText()
        paths = list(getattr(config, "library_paths", []))
        return paths[0] if paths else None

    def apply_theme(self, theme: str):
        super().apply_theme(theme)
        is_light = (theme == "light")
        if hasattr(self, "banner"):
            if is_light:
                self.banner.setStyleSheet("""
                    QFrame#importBannerFrame {
                        background-color: #ffffff;
                        border: 1px solid #d0d7de;
                        border-radius: 6px;
                    }
                """)
                if hasattr(self, "banner_title_lbl"):
                    self.banner_title_lbl.setStyleSheet("color: #0969da; font-size: 13px; font-weight: bold;")
                if hasattr(self, "banner_detail_lbl"):
                    self.banner_detail_lbl.setStyleSheet("color: #57606a; font-size: 12px;")
            else:
                self.banner.setStyleSheet("""
                    QFrame#importBannerFrame {
                        background-color: #161b22;
                        border: 1px solid #30363d;
                        border-radius: 6px;
                    }
                """)
                if hasattr(self, "banner_title_lbl"):
                    self.banner_title_lbl.setStyleSheet("color: #58a6ff; font-size: 13px; font-weight: bold;")
                if hasattr(self, "banner_detail_lbl"):
                    self.banner_detail_lbl.setStyleSheet("color: #c9d1d9; font-size: 12px;")

    def _apply_analysis_metadata(self):
        if self.analysis.album and self.analysis.album != NO_DATA:
            self.album_edit.setText(self.analysis.album)
        if self.analysis.album_artist and self.analysis.album_artist != NO_DATA:
            self.album_artist_edit.setText(self.analysis.album_artist)

        first_art = self.analysis.album_artist
        if (not first_art or first_art == NO_DATA) and self.tracks:
            first_art = self.tracks[0].get("artist", "")
        if first_art and first_art != NO_DATA:
            self.artist_edit.setText(first_art)

        if self.analysis.year and self.analysis.year != NO_DATA:
            self.year_edit.setText(self.analysis.year)
        if self.analysis.genre and self.analysis.genre != NO_DATA:
            self.genre_edit.setText(self.analysis.genre)
        if self.analysis.disc_total and str(self.analysis.disc_total) not in ("", NO_DATA):
            self.disc_total_edit.setText(str(self.analysis.disc_total))
        if self.analysis.compilation:
            self.compilation_checkbox.setChecked(True)
        if self.analysis.cover_cache_path and Path(self.analysis.cover_cache_path).exists():
            self.album_cover_widget.set_original_cover(self.analysis.cover_cache_path)

        # Check if bad encoding was flagged in analysis or any track
        if getattr(self.analysis, "bad_encoding", 0) == 1 or any(t.get("bad_encoding") == 1 for t in self.tracks):
            self.has_bad_encoding = True
            self.encoding_warning_frame.setVisible(True)
            self.fix_encoding_checkbox.setChecked(True)

        # Trigger sync to tracks
        self._on_album_fields_changed()

    def _on_import_clicked(self):
        self._save_current_single_track_form()
        self._on_album_fields_changed()

        if not self._validate_readiness():
            QMessageBox.warning(self, "Incomplete Tags", "Please fill all required tags before importing.")
            return

        if self.analysis.variant in (2, 3):
            source_ext = Path(self.analysis.source_flac_path).suffix.lower() if self.analysis.source_flac_path else None
            enc_type, enc_path = get_audio_encoder(source_ext)
            ffmpeg_path = find_ffmpeg_executable()
            if not enc_path or not enc_path.exists():
                import sys
                if sys.platform != "win32":
                    QMessageBox.critical(
                        self,
                        "FFmpeg Required",
                        f"FFmpeg is required to convert {source_ext or 'audio'} audio, but it was not found.\n\n"
                        "Please ensure ffmpeg is available in codecs/ffmpeg/ or installed on your system."
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "Audio Encoder Required",
                        "Neither QAAC nor FFmpeg was found. Please ensure qaac64.exe is in codecs/qaac/ or ffmpeg in codecs/ffmpeg/."
                    )
                return
            if enc_type == "qaac" and (not ffmpeg_path or not ffmpeg_path.exists()):
                QMessageBox.critical(
                    self,
                    "FFmpeg Decoder Required",
                    "FFmpeg is required to decode audio tracks for QAAC, but was not found.\n\n"
                    "Please ensure ffmpeg is available in codecs/ffmpeg/ or installed on your system."
                )
                return

        self.accept()

    def get_result_data(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Returns (edited_album_dict, edited_tracks_list)."""
        self._save_current_single_track_form()
        self._on_album_fields_changed()

        fix_enc = self.fix_encoding_checkbox.isChecked()
        for t in self.tracks:
            if fix_enc:
                t["bad_encoding"] = 0
                from malka.tags import detect_and_fix_encoding
                for k in ("title", "artist", "album_artist", "album", "genre"):
                    val = t.get(k)
                    if val and val != NO_DATA:
                        _, fixed_val = detect_and_fix_encoding(str(val))
                        t[k] = fixed_val
            else:
                t["bad_encoding"] = 1 if self.has_bad_encoding else int(t.get("bad_encoding", 0))

        cover_path = None
        remove_cover = False
        if self.album_cover_widget.action == "new":
            cover_path = self.album_cover_widget.new_image_path
        elif self.album_cover_widget.action == "delete":
            remove_cover = True
        elif self.album_cover_widget.original_image_path:
            cover_path = self.album_cover_widget.original_image_path

        edited_album = {
            "album": self.album_edit.text().strip(),
            "album_artist": self.album_artist_edit.text().strip(),
            "year": self.year_edit.text().strip(),
            "genre": self.genre_edit.text().strip(),
            "compilation": 1 if self.compilation_checkbox.isChecked() else 0,
            "disc_total": self.disc_total_edit.text().strip() or "1",
            "cover_cache_path": cover_path,
            "remove_cover": remove_cover,
        }
        return edited_album, self.tracks
