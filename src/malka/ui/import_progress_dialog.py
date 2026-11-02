import subprocess
import threading
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from malka.config import config
from malka.db import get_connection
from malka.importer import ImportAnalysisResult, execute_import


class ImportWorker(QThread):
    """
    Background worker thread for executing album import without freezing the UI.
    Handles Variant 1 (file copy + tagging) and Variant 2 (QAAC FLAC+CUE conversion).
    """

    progress_update = pyqtSignal(int, int, str, str, int)  # curr, total, msg, detail, pct
    finished_import = pyqtSignal(bool, str, list)  # success, message, imported_paths

    def __init__(
        self,
        analysis: ImportAnalysisResult,
        edited_album: Dict[str, Any],
        edited_tracks: List[Dict[str, Any]],
        library_path: str,
        naming_format: str,
        db_path: str,
    ):
        super().__init__()
        self.analysis = analysis
        self.edited_album = edited_album
        self.edited_tracks = edited_tracks
        self.library_path = library_path
        self.naming_format = naming_format
        self.db_path = db_path
        self._is_cancelled = False
        self._active_procs = set()
        self._procs_lock = threading.Lock()

    def cancel(self):
        self._is_cancelled = True
        with self._procs_lock:
            for p in list(self._active_procs):
                try:
                    if p.poll() is None:
                        p.kill()
                except Exception:
                    pass
            self._active_procs.clear()

    def run(self):
        # Dedicated thread-local SQLite connection
        db_conn = get_connection(self.db_path)
        try:
            def on_progress(curr: int, total: int, msg: str, detail: str = "", pct: int = 0):
                if self._is_cancelled:
                    return
                self.progress_update.emit(curr, total, msg, detail, pct)

            def check_cancelled() -> bool:
                return self._is_cancelled

            def set_proc(p: subprocess.Popen):
                with self._procs_lock:
                    self._active_procs.add(p)

            success, msg, imported = execute_import(
                analysis=self.analysis,
                edited_album=self.edited_album,
                edited_tracks=self.edited_tracks,
                library_path=self.library_path,
                naming_format=self.naming_format,
                db_conn=db_conn,
                progress_callback=on_progress,
                cancel_check=check_cancelled,
                proc_callback=set_proc,
            )
            self.finished_import.emit(success, msg, imported)
        except Exception as e:
            self.finished_import.emit(False, str(e), [])
        finally:
            try:
                db_conn.close()
            except Exception:
                pass


class ImportProgressDialog(QDialog):
    """
    Modal progress dialog with real-time encoding and import status updates.
    Ensures 100% responsiveness and zero UI freezing during heavy QAAC conversions.
    """

    def __init__(
        self,
        analysis: ImportAnalysisResult,
        edited_album: Dict[str, Any],
        edited_tracks: List[Dict[str, Any]],
        library_path: str,
        naming_format: str,
        db_path: str,
        parent=None,
        auto_start: bool = True,
        theme: Optional[str] = None,
    ):
        super().__init__(parent)
        self.analysis = analysis
        self.edited_album = edited_album
        self.edited_tracks = edited_tracks

        if theme is not None:
            self.theme = theme
        elif hasattr(parent, "theme"):
            self.theme = parent.theme
        else:
            self.theme = getattr(config, "theme", "dark")

        self.result_success = False
        self.result_msg = ""
        self.result_imported: List[str] = []
        self._is_closing = False

        self.setWindowTitle("Importing Album")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedSize(540, 250)

        self._init_ui()
        self.apply_theme(self.theme)

        # Initialize and start background worker
        self.worker = ImportWorker(
            analysis=analysis,
            edited_album=edited_album,
            edited_tracks=edited_tracks,
            library_path=library_path,
            naming_format=naming_format,
            db_path=db_path,
        )
        self.worker.progress_update.connect(self._on_progress_update)
        self.worker.finished_import.connect(self._on_finished_import)
        if auto_start:
            self.worker.start()

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")
        if is_light:
            self.setStyleSheet("""
                QDialog {
                    background-color: #f6f8fa;
                    color: #1f2328;
                }
                QLabel {
                    color: #1f2328;
                }
                QProgressBar {
                    background-color: #eaeef2;
                    border: 1px solid #d0d7de;
                    border-radius: 6px;
                    text-align: center;
                    color: #1f2328;
                    font-weight: bold;
                    font-size: 11px;
                    height: 22px;
                }
                QProgressBar::chunk {
                    background-color: #0969da;
                    border-radius: 5px;
                }
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d0d7de;
                    border-radius: 5px;
                    color: #1f2328;
                    padding: 6px 16px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #eaeef2;
                    border-color: #b0b8c1;
                    color: #1f2328;
                }
                QPushButton:pressed {
                    background-color: #dbe0e6;
                }
            """)
            if hasattr(self, "header_lbl"):
                self.header_lbl.setStyleSheet("font-size: 14px; color: #0969da; font-weight: bold;")
            if hasattr(self, "phase_lbl"):
                self.phase_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #1f2328;")
            if hasattr(self, "detail_lbl"):
                self.detail_lbl.setStyleSheet("font-size: 11px; color: #656d76;")
            if hasattr(self, "counter_lbl"):
                self.counter_lbl.setStyleSheet("font-size: 12px; color: #656d76;")
        else:
            self.setStyleSheet("""
                QDialog {
                    background-color: #0d1117;
                    color: #e6edf3;
                }
                QLabel {
                    color: #e6edf3;
                }
                QProgressBar {
                    background-color: #161b22;
                    border: 1px solid #30363d;
                    border-radius: 6px;
                    text-align: center;
                    color: #ffffff;
                    font-weight: bold;
                    font-size: 11px;
                    height: 22px;
                }
                QProgressBar::chunk {
                    background-color: #238636;
                    border-radius: 5px;
                }
                QPushButton {
                    background-color: #21262d;
                    border: 1px solid #30363d;
                    border-radius: 5px;
                    color: #c9d1d9;
                    padding: 6px 16px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #30363d;
                    color: #ffffff;
                }
                QPushButton:pressed {
                    background-color: #161b22;
                }
            """)
            if hasattr(self, "header_lbl"):
                self.header_lbl.setStyleSheet("font-size: 14px; color: #58a6ff; font-weight: bold;")
            if hasattr(self, "phase_lbl"):
                self.phase_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff;")
            if hasattr(self, "detail_lbl"):
                self.detail_lbl.setStyleSheet("font-size: 11px; color: #8b949e;")
            if hasattr(self, "counter_lbl"):
                self.counter_lbl.setStyleSheet("font-size: 12px; color: #8b949e;")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        # Header: Album title & artist
        alb_name = self.edited_album.get("album", "Unknown Album")
        art_name = self.edited_album.get("album_artist", "Unknown Artist")
        self.header_lbl = QLabel(f"<b>Importing:</b> {alb_name} — <i>{art_name}</i>")
        layout.addWidget(self.header_lbl)

        # Phase / message label
        self.phase_lbl = QLabel("Starting import process...")
        layout.addWidget(self.phase_lbl)

        # Detail label (speed, percentage, ETA)
        self.detail_lbl = QLabel("Preparing files and encoder...")
        layout.addWidget(self.detail_lbl)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Footer with counter and Cancel button
        footer_layout = QHBoxLayout()
        self.counter_lbl = QLabel(f"Track 0 of {len(self.edited_tracks)}")
        footer_layout.addWidget(self.counter_lbl)

        footer_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        footer_layout.addWidget(self.btn_cancel)

        layout.addLayout(footer_layout)

    def _on_progress_update(self, curr: int, total: int, msg: str, detail: str, pct: int):
        self.phase_lbl.setText(msg)
        self.detail_lbl.setText(detail)
        self.counter_lbl.setText(f"Track {curr} of {total}")
        self.progress_bar.setValue(pct)

    def accept(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.wait(3000)
        super().accept()

    def reject(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().reject()

    def _on_finished_import(self, success: bool, msg: str, imported_files: list):
        self.result_success = success
        self.result_msg = msg
        self.result_imported = imported_files
        self._is_closing = True
        if success:
            self.accept()
        else:
            self.reject()

    def _on_cancel_clicked(self):
        reply = QMessageBox.question(
            self,
            "Cancel Import",
            "Are you sure you want to cancel the album import?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.phase_lbl.setText("Cancelling import...")
            self.detail_lbl.setText("Terminating processes and cleaning temporary files...")
            self.btn_cancel.setEnabled(False)
            self.worker.cancel()

    def closeEvent(self, event):
        if self._is_closing:
            event.accept()
            return

        if self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Import",
                "Import is in progress. Do you want to cancel it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.worker.wait(3000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
