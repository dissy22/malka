from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from malka.config import DEFAULT_NAMING_FORMAT, config
from malka.organizer import format_track_filename


class SettingsDialog(QDialog):
    settings_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Library Settings")
        self.resize(600, 480)

        self.init_ui()
        self.apply_theme(getattr(config, "theme", "dark"))

    def apply_theme(self, theme: str):
        if theme == "light":
            self.setStyleSheet("""
                QDialog {
                    background-color: #ffffff;
                    color: #1f2328;
                }
                QLineEdit, QComboBox {
                    background-color: #f6f8fa;
                    border: 1px solid #d0d7de;
                    border-radius: 6px;
                    padding: 6px 10px;
                    color: #1f2328;
                }
                QLineEdit:focus, QComboBox:focus {
                    border: 1px solid #0969da;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    color: #1f2328;
                    border: 1px solid #d0d7de;
                    selection-background-color: #f6f8fa;
                    selection-color: #0969da;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::item {
                    color: #1f2328;
                    background-color: #ffffff;
                    min-height: 24px;
                }
                QComboBox::item:selected {
                    background-color: #f6f8fa;
                    color: #0969da;
                }
                QListWidget {
                    background-color: #ffffff;
                    border: 1px solid #d0d7de;
                    border-radius: 6px;
                    color: #1f2328;
                    padding: 4px;
                }
                QListWidget::item {
                    padding: 4px 6px;
                    border-radius: 4px;
                }
                QListWidget::item:selected {
                    background-color: #eaeef2;
                    color: #0969da;
                }
                QPushButton {
                    background-color: #f6f8fa;
                    border: 1px solid #d0d7de;
                    border-radius: 6px;
                    color: #24292f;
                    padding: 6px 14px;
                }
                QPushButton:hover {
                    background-color: #eaeef2;
                    border-color: #b0b8c1;
                }
                QPushButton#saveBtn {
                    background-color: #0969da;
                    border: 1px solid #0969da;
                    color: #ffffff;
                    font-weight: bold;
                }
                QPushButton#saveBtn:hover {
                    background-color: #0860ca;
                }
                QLabel {
                    color: #57606a;
                }
                QCheckBox {
                    color: #1f2328;
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 1px solid #d0d7de;
                    border-radius: 4px;
                    background-color: #ffffff;
                }
                QCheckBox::indicator:checked {
                    background-color: #0969da;
                    border-color: #0969da;
                }
            """)
        else:
            self.setStyleSheet("""
                QDialog {
                    background-color: #202020;
                    color: #c9d1d9;
                }
                QLineEdit, QComboBox {
                    background-color: #1e1e1e;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                    padding: 6px 10px;
                    color: #c9d1d9;
                }
                QLineEdit:focus, QComboBox:focus {
                    border: 1px solid #007acc;
                }
                QComboBox QAbstractItemView {
                    background-color: #1e1e1e;
                    color: #c9d1d9;
                    selection-background-color: #30363d;
                    selection-color: #ffffff;
                    border: 1px solid #3c3c3c;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::item {
                    color: #c9d1d9;
                    background-color: #1e1e1e;
                    min-height: 24px;
                }
                QComboBox::item:selected {
                    background-color: #30363d;
                    color: #ffffff;
                }
                QListWidget {
                    background-color: #15191f;
                    border: 1px solid #30363d;
                    border-radius: 6px;
                    color: #c9d1d9;
                    padding: 4px;
                }
                QListWidget::item {
                    padding: 4px 6px;
                    border-radius: 4px;
                }
                QListWidget::item:selected {
                    background-color: #30363d;
                    color: #ffffff;
                }
                QPushButton {
                    background-color: #333333;
                    border: 1px solid #444444;
                    border-radius: 4px;
                    color: #c9d1d9;
                    padding: 6px 14px;
                }
                QPushButton:hover {
                    background-color: #404040;
                    border-color: #666666;
                    color: #ffffff;
                }
                QPushButton#saveBtn {
                    background-color: #007acc;
                    border: 1px solid #0098ff;
                    color: #ffffff;
                    font-weight: bold;
                }
                QLabel {
                    color: #c9d1d9;
                }
                QCheckBox {
                    color: #c9d1d9;
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                    background-color: #1e1e1e;
                }
                QCheckBox::indicator:checked {
                    background-color: #007acc;
                    border-color: #007acc;
                }
            """)

        if hasattr(self, "theme_combo"):
            color_hex = "#1f2328" if theme == "light" else "#c9d1d9"
            pal = self.theme_combo.palette()
            text_color = QColor(color_hex)
            pal.setColor(QPalette.ColorRole.Text, text_color)
            pal.setColor(QPalette.ColorRole.WindowText, text_color)
            pal.setColor(QPalette.ColorRole.ButtonText, text_color)
            self.theme_combo.setPalette(pal)
            if self.theme_combo.view():
                view_pal = self.theme_combo.view().palette()
                view_pal.setColor(QPalette.ColorRole.Text, text_color)
                view_pal.setColor(QPalette.ColorRole.WindowText, text_color)
                view_pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff" if theme == "light" else "#1e1e1e"))
                self.theme_combo.view().setPalette(view_pal)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(18, 18, 18, 18)

        form = QFormLayout()
        form.setSpacing(12)

        # Library folders (multiple roots are supported)
        folders_widget = QWidget()
        folders_layout = QVBoxLayout(folders_widget)
        folders_layout.setContentsMargins(0, 0, 0, 0)
        folders_layout.setSpacing(6)

        self.paths_list = QListWidget()
        self.paths_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.paths_list.setMinimumHeight(96)
        for path in getattr(config, "library_paths", []):
            self.paths_list.addItem(path)
        folders_layout.addWidget(self.paths_list)

        folders_buttons = QHBoxLayout()
        folders_buttons.setContentsMargins(0, 0, 0, 0)
        folders_buttons.setSpacing(8)
        self.btn_browse = QPushButton("Add Folder...")
        self.btn_browse.clicked.connect(self._on_browse)
        folders_buttons.addWidget(self.btn_browse)

        self.btn_remove_folder = QPushButton("Remove")
        self.btn_remove_folder.clicked.connect(self._on_remove_folder)
        folders_buttons.addWidget(self.btn_remove_folder)
        folders_buttons.addStretch()
        folders_layout.addLayout(folders_buttons)

        form.addRow("Library Folders:", folders_widget)
        self.library_paths_hint = QLabel("All listed folders are scanned and searched as one library.")
        self.library_paths_hint.setStyleSheet("color: #888888; font-size: 8pt;")
        form.addRow("", self.library_paths_hint)

        # Naming template
        self.template_edit = QLineEdit(config.track_naming_format)
        self.template_edit.textChanged.connect(self._update_preview)
        form.addRow("Track Filename Template:", self.template_edit)

        # Theme selection
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        curr_theme = getattr(config, "theme", "dark")
        self.theme_combo.setCurrentText("Light" if curr_theme == "light" else "Dark")
        self.theme_combo.currentTextChanged.connect(lambda t: self.apply_theme(t.lower()))
        form.addRow("Interface Theme:", self.theme_combo)

        # Scrollbars setting
        self.scrollbars_checkbox = QCheckBox("Show scrollbars in windows (slim & stylish)")
        self.scrollbars_checkbox.setChecked(getattr(config, "show_scrollbars", True))
        form.addRow("Scrollbars:", self.scrollbars_checkbox)

        # Preview label
        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        form.addRow("Filename Example:", self.preview_label)

        layout.addLayout(form)

        # Help info
        help_label = QLabel(
            "Available template tokens:\n"
            "  <track_no> — track number with leading zero (e.g. 01, 02)\n"
            "  <title> — track title\n"
            "  <artist> — artist\n"
            "  <album_artist> — album artist\n"
            "  <album> — album title\n"
            "  <year> — release year"
        )
        help_label.setStyleSheet("color: #888888; font-size: 8pt; line-height: 1.4;")
        layout.addWidget(help_label)

        layout.addStretch()

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("saveBtn")
        self.btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        self._update_preview()

    def _on_browse(self):
        start_dir = str(Path.home())
        current = self.paths_list.currentItem()
        if current and current.text():
            start_dir = current.text()
        elif self.paths_list.count() > 0:
            start_dir = self.paths_list.item(0).text()
        directory = QFileDialog.getExistingDirectory(
            self,
            "Add Music Library Folder",
            start_dir,
        )
        if directory:
            existing = {self.paths_list.item(i).text() for i in range(self.paths_list.count())}
            if directory not in existing:
                self.paths_list.addItem(directory)

    def _on_remove_folder(self):
        row = self.paths_list.currentRow()
        if row >= 0:
            self.paths_list.takeItem(row)

    def _update_preview(self):
        tmpl = self.template_edit.text().strip() or DEFAULT_NAMING_FORMAT
        sample_track = {
            "track_no": "1",
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
            "album_artist": "Queen",
            "album": "A Night at the Opera",
            "year": "1975",
        }
        name = format_track_filename(sample_track, tmpl)
        self.preview_label.setText(f"{name}.mp3")

    def _on_save(self):
        paths = [self.paths_list.item(i).text().strip() for i in range(self.paths_list.count())]
        paths = [p for p in paths if p]
        new_tmpl = self.template_edit.text().strip() or DEFAULT_NAMING_FORMAT

        config.set_library_paths(paths)
        config.track_naming_format = new_tmpl
        config.theme = self.theme_combo.currentText().lower()
        config.show_scrollbars = self.scrollbars_checkbox.isChecked()
        config.save()

        self.settings_saved.emit()
        self.accept()
