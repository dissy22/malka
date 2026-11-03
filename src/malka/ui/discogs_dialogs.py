"""Small Discogs dialogs: progress, single-choice and the artwork gallery."""

from __future__ import annotations

import html
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from malka.discogs_models import CoverImage, image_dimensions
from malka.ui.image_utils import checkbox_checkmark_qss


def _rounded_pixmap(pixmap: QPixmap, radius: int = 8) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    rounded = QPixmap(pixmap.size())
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return rounded


def _pixmap_from_bytes(
    data: Optional[bytes],
    size: int,
    background: str = "#0d1117",
) -> QPixmap:
    if data:
        source = QPixmap()
        if source.loadFromData(data) and not source.isNull():
            scaled = source.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            canvas = QPixmap(size, size)
            canvas.fill(QColor(background))
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(
                (size - scaled.width()) // 2,
                (size - scaled.height()) // 2,
                scaled,
            )
            painter.end()
            return _rounded_pixmap(canvas)
    canvas = QPixmap(size, size)
    canvas.fill(QColor(background))
    return canvas


def dialog_qss(theme: str) -> str:
    light = theme == "light"
    background = "#ffffff" if light else "#0d1117"
    panel = "#f6f8fa" if light else "#161b22"
    text = "#1f2328" if light else "#e6edf3"
    muted = "#656d76" if light else "#8b949e"
    border = "#d0d7de" if light else "#30363d"
    hover = "#eaeef2" if light else "#21262d"
    accent = "#0969da" if light else "#58a6ff"
    return f"""
        QDialog {{ background:{background}; color:{text}; }}
        QWidget {{ color:{text}; }}
        QLabel {{ color:{text}; }}
        QLabel#dialogTitle {{ font-size:17px; font-weight:700; color:{text}; }}
        QLabel#dialogSubtitle {{ color:{muted}; font-size:11px; }}
        QLabel#galleryPreview {{
            background:{panel}; border:1px solid {border}; border-radius:8px;
        }}
        QLineEdit, QComboBox {{
            background:{background}; border:1px solid {border}; border-radius:5px;
            padding:6px 9px; color:{text};
        }}
        QListWidget {{
            background:{background}; border:1px solid {border}; border-radius:6px;
            color:{text}; padding:4px;
        }}
        QListWidget::item {{ padding:7px; border-bottom:1px solid {panel}; }}
        QListWidget::item:selected {{ background:{hover}; color:{accent}; }}
        QPushButton {{
            background:{panel}; border:1px solid {border}; border-radius:5px;
            color:{text}; padding:7px 14px; min-width:82px;
        }}
        QPushButton:hover {{ background:{hover}; border-color:{accent}; }}
        QPushButton#dialogUse {{
            background:#238636; border-color:#2ea043; color:#ffffff;
            font-weight:600;
        }}
        QPushButton#dialogUse:hover {{ background:#2ea043; }}
        QPushButton:disabled {{ color:{muted}; border-color:{border}; background:{background}; }}
        QProgressBar {{
            border:1px solid {border}; border-radius:4px; background:{background};
            max-height:8px;
        }}
        QProgressBar::chunk {{ background:{accent}; border-radius:3px; }}
    """


class DiscogsBusyDialog(QDialog):
    """Small modal progress dialog used while a request is running."""

    canceled = pyqtSignal()

    def __init__(self, title: str, message: str, parent=None, theme: str = "dark"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(440)
        self.setModal(True)
        self.setStyleSheet(dialog_qss(theme) + checkbox_checkmark_qss())
        self._cancel_emitted = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        layout.addWidget(title_label)
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setObjectName("dialogSubtitle")
        layout.addWidget(self.message_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        buttons.addWidget(self.btn_cancel)
        layout.addLayout(buttons)

    def set_message(self, message: str):
        self.message_label.setText(message)

    def _on_cancel(self):
        if not self._cancel_emitted:
            self._cancel_emitted = True
            self.canceled.emit()
        self.reject()

    def closeEvent(self, event):
        if not self._cancel_emitted:
            self._cancel_emitted = True
            self.canceled.emit()
        super().closeEvent(event)


class DiscogsChoiceDialog(QDialog):
    def __init__(
        self,
        title: str,
        subtitle: str,
        entries: List[Tuple[str, str, Any]],
        parent=None,
        theme: str = "dark",
        select_label: str = "Use selected",
    ):
        super().__init__(parent)
        self._entries = entries
        self._theme = theme
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(760, 480)
        self.setMinimumSize(620, 380)
        self.setStyleSheet(dialog_qss(theme) + checkbox_checkmark_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        root.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setWordWrap(True)
        root.addWidget(subtitle_label)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._update_button)
        self.list.itemDoubleClicked.connect(lambda _item: self._accept_selected())
        root.addWidget(self.list, 1)

        for display, tooltip, value in entries:
            item = QListWidgetItem(display)
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setSizeHint(QSize(0, 48))
            self.list.addItem(item)

        footer = QHBoxLayout()
        hint = QLabel("Select one item, then confirm.")
        hint.setObjectName("dialogSubtitle")
        footer.addWidget(hint)
        footer.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        self.btn_use = QPushButton(select_label)
        self.btn_use.setObjectName("dialogUse")
        self.btn_use.setDefault(True)
        self.btn_use.clicked.connect(self._accept_selected)
        footer.addWidget(self.btn_use)
        root.addLayout(footer)
        if entries:
            self.list.setCurrentRow(0)
        self._update_button()

    def selected_value(self) -> Optional[Any]:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_button(self, *_args):
        self.btn_use.setEnabled(self.list.currentItem() is not None)

    def _accept_selected(self):
        if self.list.currentItem() is not None:
            self.accept()


class DiscogsGalleryDialog(QDialog):
    """Choose one downloaded Discogs artwork, optionally square-resized."""

    def __init__(
        self,
        images: List[CoverImage],
        album: str,
        artist: str = "",
        theme: str = "dark",
        parent=None,
    ):
        super().__init__(parent)
        self._images: List[CoverImage] = []
        for image in images:
            if image.thumbnail and (image.width <= 0 or image.height <= 0):
                image.width, image.height = image_dimensions(image.thumbnail)
            if image.thumbnail:
                self._images.append(image)
        self._selected: Optional[CoverImage] = None
        self._theme = theme
        self.setWindowTitle("Select cover art")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(1040, 700)
        self.setMinimumSize(860, 560)
        self.setStyleSheet(dialog_qss(theme) + checkbox_checkmark_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        title = QLabel("Choose cover art")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        subtitle = QLabel(
            f"{len(self._images)} image{'s' if len(self._images) != 1 else ''} found "
            f"for “{album}”" + (f" by {artist}." if artist else ".")
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        content = QHBoxLayout()
        content.setSpacing(16)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setSpacing(4)
        self.grid.setIconSize(QSize(180, 180))
        self.grid.setGridSize(QSize(222, 252))
        self.grid.setWordWrap(True)
        self.grid.setUniformItemSizes(True)
        self.grid.currentItemChanged.connect(self._on_current_item_changed)
        self.grid.itemDoubleClicked.connect(self._on_item_double_clicked)
        content.addWidget(self.grid, 1)

        preview_panel = QFrame()
        preview_panel.setFixedWidth(330)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(10)
        preview_title = QLabel("Selected artwork")
        preview_title.setObjectName("dialogTitle")
        preview_layout.addWidget(preview_title)
        self.preview = QLabel()
        self.preview.setObjectName("galleryPreview")
        self.preview.setFixedSize(290, 290)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview)
        self.detail_label = QLabel("Select an image to see its details.")
        self.detail_label.setObjectName("dialogSubtitle")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.TextFormat.RichText)
        preview_layout.addWidget(self.detail_label)
        preview_layout.addStretch(1)
        content.addWidget(preview_panel)
        root.addLayout(content, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setObjectName("dialogSubtitle")
        footer.addWidget(self.count_label)
        self.resize_checkbox = QCheckBox("Resize to:")
        footer.addWidget(self.resize_checkbox)
        self.resize_combo = QComboBox()
        for size in (500, 600, 800, 1000, 1200):
            self.resize_combo.addItem(f"{size} × {size}", size)
        self.resize_combo.setCurrentIndex(3)
        self.resize_combo.setFixedWidth(130)
        self.resize_combo.setEnabled(False)
        self.resize_checkbox.toggled.connect(self.resize_combo.setEnabled)
        footer.addWidget(self.resize_combo)
        footer.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        self.btn_use = QPushButton("Use this artwork")
        self.btn_use.setObjectName("dialogUse")
        self.btn_use.setEnabled(False)
        self.btn_use.setDefault(True)
        self.btn_use.clicked.connect(self._use_selected)
        footer.addWidget(self.btn_use)
        root.addLayout(footer)

        for image in self._images:
            self._add_image(image)
        if self.grid.count():
            self.grid.setCurrentRow(0)
        self.count_label.setText(
            f"{len(self._images)} image{'s' if len(self._images) != 1 else ''} available"
        )

    def _add_image(self, image: CoverImage):
        item = QListWidgetItem()
        item.setIcon(QIcon(_pixmap_from_bytes(image.thumbnail, 180)))
        item.setText(image.caption)
        item.setToolTip(image.tooltip)
        item.setData(Qt.ItemDataRole.UserRole, image)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        item.setSizeHint(QSize(214, 244))
        self.grid.addItem(item)

    def _on_current_item_changed(self, current, _previous):
        if current is None:
            self._selected = None
            self.btn_use.setEnabled(False)
            return
        image = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(image, CoverImage):
            return
        self._selected = image
        self.btn_use.setEnabled(bool(image.thumbnail))
        self.preview.setPixmap(_pixmap_from_bytes(image.thumbnail, 290))
        parts = [
            f"<b>Type:</b> {html.escape(image.type_label)}",
            f"<b>Resolution:</b> {image.resolution_label}",
            f"<b>File size:</b> {image.size_label}",
            f"<b>Release:</b> {html.escape(image.release_title)}",
        ]
        if image.release_artist:
            parts.append(f"<b>Artist:</b> {html.escape(image.release_artist)}")
        if image.release_date:
            parts.append(f"<b>Date:</b> {html.escape(image.release_date)}")
        release_type = "Digital" if image.is_digital else "Physical"
        release_type += " / Official" if image.is_official else " / Unofficial"
        parts.append(f"<b>Release type:</b> {html.escape(release_type)}")
        if image.rating or image.rating_count:
            parts.append(
                f"<b>Discogs release rating:</b> {image.rating:.1f}/5 "
                f"({image.rating_count} votes)"
            )
        self.detail_label.setText("<br>".join(parts))

    def _on_item_double_clicked(self, item):
        self.grid.setCurrentItem(item)
        self._use_selected()

    def _use_selected(self):
        if self._selected is not None and self._selected.thumbnail:
            self.accept()

    def selected_image(self) -> Optional[CoverImage]:
        return self._selected

    def selected_resize_size(self) -> Optional[int]:
        if not self.resize_checkbox.isChecked():
            return None
        value = self.resize_combo.currentData()
        return int(value) if value else None
