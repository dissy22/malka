from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from malka.formats import (
    DEFAULT_RATE,
    format_extension,
    MODE_COPY,
    MODE_HIRES,
    MODE_LOSSLESS_RESAMPLE,
    MODE_LOSSY,
    RATES,
    SOURCE_KIND_MP3_M4A,
    available_formats,
    available_modes,
    format_label,
    is_hires,
    mode_label,
    normalize_settings,
    plan_for,
    rate_is_used,
)
from malka.importer import ImportAnalysisResult, find_ffmpeg_executable
from malka.organizer import format_track_filename, sanitize_filename
from malka.ui.edit_dialog import BaseAlbumEditDialog


class ImportDialog(BaseAlbumEditDialog):
    """
    Import dialog: album/track metadata plus the quality settings that decide
    what happens to the audio (keep / lossy / lossless resample / hi-res).

    The summary block at the top always describes the effective operation and
    the exact destination folder for the current selections.
    """

    def __init__(self, analysis: ImportAnalysisResult, parent=None, theme: Optional[str] = None):
        self.analysis = analysis
        self.hires = bool(analysis.is_hires) or is_hires(analysis.sample_rate, analysis.bits_per_sample)
        stored = config.get_import_settings(analysis.source_kind)
        self._settings = normalize_settings(
            analysis.source_kind,
            self.hires,
            stored or {
                "mode": analysis.mode,
                "format": analysis.output_format,
                "rate": analysis.target_rate,
            },
        )

        super().__init__(tracks=analysis.tracks, parent=parent, theme=theme)

        self.setWindowTitle("Import Album to Library")

        self._setup_summary()
        self._setup_quality_options()
        self._setup_destination()

        self._apply_analysis_metadata()

        self.btn_action.setText("Import to Library")
        self.btn_action.setObjectName("importBtn")
        self.btn_import = self.btn_action
        self.btn_action.clicked.connect(self._on_import_clicked)

        # Backward-compatibility aliases
        self.cover_widget = self.album_cover_widget
        self.cb_compilation = self.compilation_checkbox
        self.cb_apply_artist_all = self.artist_same_checkbox

        self._connect_summary_signals()
        self._sync_quality_widgets()
        self._apply_fixed_size()

        self.apply_theme(self.theme)
        self._refresh_summary()
        self._validate_readiness()

    # ------------------------------------------------------------------
    # Layout: summary, quality settings, destination
    # ------------------------------------------------------------------
    def _setup_summary(self):
        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("importSummaryFrame")
        layout = QVBoxLayout(self.summary_frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self.summary_title_lbl = QLabel("")
        self.summary_title_lbl.setObjectName("importSummaryTitle")
        self.summary_title_lbl.setWordWrap(True)
        layout.addWidget(self.summary_title_lbl)

        self.summary_body_lbl = QLabel("")
        self.summary_body_lbl.setObjectName("importSummaryBody")
        self.summary_body_lbl.setWordWrap(True)
        layout.addWidget(self.summary_body_lbl)

        # Backwards-compatible aliases (older callers/tests look for "banner").
        self.banner = self.summary_frame
        self.banner_title_lbl = self.summary_title_lbl
        self.banner_detail_lbl = self.summary_body_lbl

        self.top_banner_container.addWidget(self.summary_frame)

    def _setup_quality_options(self):
        frame = QFrame()
        frame.setObjectName("importOptionsFrame")
        self.options_frame = frame
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        # 1. Quality mode
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(10)
        mode_label_widget = QLabel("Quality:")
        mode_label_widget.setMinimumWidth(80)
        mode_row.addWidget(mode_label_widget)

        self.mode_combo = QComboBox()
        for mode in available_modes(self.analysis.source_kind, self.hires):
            self.mode_combo.addItem(mode_label(mode, self.analysis.source_kind, self.hires), mode)
        index = self.mode_combo.findData(self._settings["mode"])
        self.mode_combo.setCurrentIndex(max(0, index))
        self.mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        # 2. Format
        format_row = QHBoxLayout()
        format_row.setContentsMargins(0, 0, 0, 0)
        format_row.setSpacing(10)
        self.format_label_widget = QLabel("Format:")
        self.format_label_widget.setMinimumWidth(80)
        format_row.addWidget(self.format_label_widget)

        self.format_combo = QComboBox()
        self.format_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        format_row.addWidget(self.format_combo, 1)
        layout.addLayout(format_row)

        # 3. Resampling ceiling
        rate_row = QHBoxLayout()
        rate_row.setContentsMargins(0, 0, 0, 0)
        rate_row.setSpacing(10)
        self.rate_label_widget = QLabel("Resample to:")
        self.rate_label_widget.setMinimumWidth(80)
        rate_row.addWidget(self.rate_label_widget)

        self.rate_combo = QComboBox()
        for rate in RATES:
            self.rate_combo.addItem(f"{rate / 1000:g} kHz", rate)
        rate_index = self.rate_combo.findData(self._settings["rate"])
        self.rate_combo.setCurrentIndex(max(0, rate_index))
        self.rate_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        rate_row.addWidget(self.rate_combo, 1)
        layout.addLayout(rate_row)

        self.top_banner_container.addWidget(frame)

        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.format_combo.currentIndexChanged.connect(self._refresh_summary)
        self.rate_combo.currentIndexChanged.connect(self._refresh_summary)

    def _setup_destination(self):
        frame = QFrame()
        frame.setObjectName("importDestinationFrame")
        self.destination_frame = frame
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        label = QLabel("Library:")
        label.setMinimumWidth(80)
        layout.addWidget(label)

        self.destination_combo = QComboBox()
        paths = list(getattr(config, "library_paths", []))
        for path in paths:
            self.destination_combo.addItem(path, path)
        if not paths:
            self.destination_combo.addItem("No library folder configured", "")
        self.destination_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.destination_combo.currentIndexChanged.connect(self._refresh_summary)
        layout.addWidget(self.destination_combo, 1)

        self.top_banner_container.addWidget(frame)

    def _apply_fixed_size(self):
        """Fixed size: 25% taller than the base editor plus the settings rows."""
        base_height = 600
        height = int(base_height * 1.25) + 140  # summary + quality rows + spacing
        self.setFixedSize(920, max(height, 890))

    def _connect_summary_signals(self):
        for widget in (self.album_edit, self.album_artist_edit, self.year_edit):
            widget.textChanged.connect(self._refresh_summary)

    # ------------------------------------------------------------------
    # Settings <-> widgets
    # ------------------------------------------------------------------
    def get_destination_library(self) -> Optional[str]:
        if self.destination_combo is not None and self.destination_combo.count() > 0:
            return self.destination_combo.currentData() or self.destination_combo.currentText()
        paths = list(getattr(config, "library_paths", []))
        return paths[0] if paths else None

    @staticmethod
    def _format_display(fmt: str) -> str:
        return {"mp3": "MP3", "m4a": "M4A", "flac": "FLAC", "alac": "ALAC"}.get(fmt, "MP3 / M4A")

    def _source_format(self) -> str:
        if self.analysis.source_format:
            return self.analysis.source_format
        ext = Path(self.analysis.source_flac_path or "").suffix.lower()
        if ext == ".flac":
            return "flac"
        if ext == ".m4a":
            return "alac"
        return "flac" if self.analysis.variant in (2, 3) else "m4a"

    def _on_mode_changed(self):
        self._sync_quality_widgets()
        self._refresh_summary()

    def _sync_quality_widgets(self):
        mode = self.mode_combo.currentData()
        formats = available_formats(mode)

        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        if formats:
            for fmt in formats:
                self.format_combo.addItem(format_label(fmt), fmt)
            wanted = self._settings.get("format")
            idx = self.format_combo.findData(wanted) if wanted in formats else -1
            self.format_combo.setCurrentIndex(0 if idx < 0 else idx)
            self.format_combo.setEnabled(len(formats) > 1)
        else:
            original = self._source_format()
            self.format_combo.addItem(
                f"Original — {self._format_display(original)} (no re-encoding)", original
            )
            self.format_combo.setCurrentIndex(0)
            self.format_combo.setEnabled(False)
        self.format_combo.blockSignals(False)

        self._settings["mode"] = mode
        self._settings["format"] = self.format_combo.currentData() or self._source_format()

        show_rate = rate_is_used(mode, self.hires)
        self.rate_label_widget.setVisible(show_rate)
        self.rate_combo.setVisible(show_rate)

    def _current_settings(self) -> Dict[str, Any]:
        return {
            "mode": self.mode_combo.currentData() or MODE_COPY,
            "format": self.format_combo.currentData() or self._source_format(),
            "rate": int(self.rate_combo.currentData() or DEFAULT_RATE),
        }

    def get_target_settings(self) -> Dict[str, Any]:
        return dict(self._current_settings())

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def _effective_plan(self) -> Dict[str, Any]:
        return plan_for(
            self.analysis.source_kind,
            self.hires,
            self._current_settings(),
            self._source_format(),
            self.analysis.sample_rate,
            self.analysis.bits_per_sample,
        )

    def _source_line(self) -> str:
        count = len(self.tracks)
        rate = int(self.analysis.sample_rate or 0)
        bits = int(self.analysis.bits_per_sample or 0)
        fmt = self._format_display(self._source_format())
        resolution = f"{rate / 1000:g} kHz / {bits}-bit"
        if self.analysis.is_image_source:
            return f"Source: album image + CUE · {count} tracks · {fmt} · {resolution}"
        return f"Source: {count} tracks · {fmt} · {resolution}"

    def _action_line(self, plan: Dict[str, Any]) -> str:
        count = len(self.tracks)
        split = plan["split"]
        tracks_word = "track" if count == 1 else "tracks"
        prefix = f"Split into {count} {tracks_word} · " if split else ""

        if plan["copy_stream"]:
            if split:
                return prefix + f"keep the original audio stream (no re-encoding) → {plan['output_format'].upper()}"
            return "keep the original file (no re-encoding, no resampling)"

        if self.analysis.source_kind == SOURCE_KIND_MP3_M4A:
            return "keep the original lossy file (no re-encoding)"

        fmt = plan["output_format"].upper()
        rate = plan["target_rate"]
        bits = int(self.analysis.bits_per_sample or 0)
        mode = self._current_settings()["mode"]

        if mode == MODE_LOSSY:
            detail = f"encode to {fmt} · {rate / 1000:g} kHz" if rate else f"encode to {fmt}"
            return prefix + detail
        if mode == MODE_LOSSLESS_RESAMPLE:
            detail = (
                f"encode to {fmt} · {rate / 1000:g} kHz · 16-bit"
                if rate
                else f"encode to {fmt} · 16-bit"
            )
            return prefix + detail
        # MODE_HIRES — keep the resolution, re-encode into a library format
        if fmt == "FLAC":
            bits = min(bits or 24, 24)  # FLAC supports up to 24-bit
        detail = f"re-encode to {fmt} · keep {self.analysis.sample_rate / 1000:g} kHz / {bits}-bit"
        return prefix + detail

    def _example_filename(self, plan: Dict[str, Any]) -> str:
        if not self.tracks:
            return ""
        track = self.tracks[0]
        if plan["copy_stream"]:
            ext = Path(
                track.get("source_path") or track.get("file_path") or self.analysis.source_flac_path or ""
            ).suffix.lower() or ".flac"
        else:
            ext = format_extension(plan["output_format"])
        pattern = getattr(config, "track_naming_format", "<track_no>. <title>")
        return format_track_filename(track, pattern) + ext

    def _destination_path(self) -> Optional[Path]:
        root = self.get_destination_library()
        if not root:
            return None
        album = self.album_edit.text().strip()
        artist = self.album_artist_edit.text().strip() or self.artist_edit.text().strip()
        year = self.year_edit.text().strip()

        album_dir = sanitize_filename(album) if album and album != NO_DATA else "Unknown Album"
        artist_dir = sanitize_filename(artist) if artist and artist != NO_DATA else "Unknown Artist"
        year_dir = sanitize_filename(year) if year and year != NO_DATA else "Unknown Year"

        path = Path(root) / artist_dir / f"{year_dir} - {album_dir}"
        if self.is_multi_disc:
            path = path / "CD <n>"
        return path

    def _refresh_summary(self):
        if not hasattr(self, "summary_body_lbl"):
            return
        album = self.album_edit.text().strip() or "No album"
        artist = self.album_artist_edit.text().strip() or "No artist"
        year = self.year_edit.text().strip() or "No year"

        self.summary_title_lbl.setText(
            f"<b>{escape(album)}</b> &nbsp;·&nbsp; {escape(artist)} &nbsp;·&nbsp; {escape(year)}"
        )

        plan = self._effective_plan()
        lines = [self._source_line(), f"Action: {self._action_line(plan)}"]

        dest = self._destination_path()
        if dest is not None:
            example = self._example_filename(plan)
            suffix = f" &nbsp;·&nbsp; e.g. <code>{escape(example)}</code>" if example else ""
            lines.append(f"Destination: <code>{escape(str(dest))}</code>{suffix}")
        else:
            lines.append("Destination: <span style='color:#cf222e'>no library folder configured</span>")

        needs_ffmpeg = plan["split"] or not plan["copy_stream"]
        if needs_ffmpeg and not self._ffmpeg_available():
            lines.append(
                "<span style='color:#cf222e;font-weight:bold'>"
                "⚠ FFmpeg was not found — this import cannot run.</span>"
            )

        self.summary_body_lbl.setText("<br>".join(lines))

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def apply_theme(self, theme: str):
        super().apply_theme(theme)
        is_light = theme == "light"

        border = "1px solid #d0d7de" if is_light else "1px solid #30363d"
        bg = "#ffffff" if is_light else "#161b22"
        title_col = "#0969da" if is_light else "#58a6ff"
        body_col = "#57606a" if is_light else "#c9d1d9"

        for frame, name in (
            (getattr(self, "summary_frame", None), "importSummaryFrame"),
            (getattr(self, "options_frame", None), "importOptionsFrame"),
            (getattr(self, "destination_frame", None), "importDestinationFrame"),
        ):
            if frame is not None:
                frame.setStyleSheet(
                    f"QFrame#{name} {{ background-color: {bg}; border: {border}; border-radius: 6px; }}"
                )
        if hasattr(self, "summary_title_lbl"):
            self.summary_title_lbl.setStyleSheet(
                f"color: {title_col}; font-size: 13px; font-weight: bold;"
            )
            self.summary_body_lbl.setStyleSheet(f"color: {body_col}; font-size: 12px;")

        combo_style = (
            """
            QComboBox {
                background-color: %(combo_bg)s;
                color: %(fg)s;
                border: %(border)s;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QComboBox:disabled { color: %(muted)s; background-color: %(combo_disabled)s; }
            QComboBox::drop-down { border: none; width: 22px; }
            QComboBox QAbstractItemView {
                background-color: %(combo_bg)s;
                color: %(fg)s;
                border: %(border)s;
                selection-background-color: %(sel)s;
                selection-color: #ffffff;
            }
        """
            % {
                "combo_bg": "#ffffff" if is_light else "#0d1117",
                "combo_disabled": "#f6f8fa" if is_light else "#161b22",
                "fg": "#1f2328" if is_light else "#c9d1d9",
                "muted": "#57606a" if is_light else "#8b949e",
                "border": border,
                "sel": "#0969da" if is_light else "#1f6feb",
            }
        )
        for name in ("mode_combo", "format_combo", "rate_combo", "destination_combo"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setStyleSheet(combo_style)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
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

        if getattr(self.analysis, "bad_encoding", 0) == 1 or any(
            t.get("bad_encoding") == 1 for t in self.tracks
        ):
            self.has_bad_encoding = True
            self.encoding_warning_frame.setVisible(True)
            self.fix_encoding_checkbox.setChecked(True)

        self._on_album_fields_changed()

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------
    def _ffmpeg_available(self) -> bool:
        path = find_ffmpeg_executable()
        return bool(path) and Path(path).exists()

    def _on_import_clicked(self):
        # Album fields are already synced live; flush only the single-track form
        # so per-track edits are not overwritten by the album values.
        self._save_current_single_track_form()

        if not self._validate_readiness():
            QMessageBox.warning(self, "Incomplete Tags", "Please fill all required tags before importing.")
            return

        plan = self._effective_plan()
        if (plan["split"] or not plan["copy_stream"]) and not self._ffmpeg_available():
            QMessageBox.critical(
                self,
                "FFmpeg Required",
                "FFmpeg is required to split or convert this album, but it was not found.\n\n"
                "Please ensure ffmpeg is available in codecs/ffmpeg/ or installed on your system.",
            )
            return

        self.accept()

    def get_result_data(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Returns (edited_album_dict, edited_tracks_list)."""
        self._save_current_single_track_form()

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

        settings = self._current_settings()
        self.analysis.mode = settings["mode"]
        self.analysis.output_format = settings["format"]
        self.analysis.target_rate = settings["rate"]

        edited_album = {
            "album": self.album_edit.text().strip(),
            "album_artist": self.album_artist_edit.text().strip(),
            "year": self.year_edit.text().strip(),
            "genre": self.genre_edit.text().strip(),
            "compilation": 1 if self.compilation_checkbox.isChecked() else 0,
            "disc_total": self.disc_total_edit.text().strip() or "1",
            "cover_cache_path": cover_path,
            "remove_cover": remove_cover,
            "import_mode": settings["mode"],
            "import_format": settings["format"],
            "import_rate": settings["rate"],
        }
        return edited_album, self.tracks
