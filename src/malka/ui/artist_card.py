import hashlib
import shutil
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QFileDialog, QFrame, QLabel, QMenu, QVBoxLayout

from malka.config import ARTISTS_CACHE_DIR, NO_DATA
from malka.db import set_artist_image
from malka.ui.image_utils import (
    ARTIST_IMAGE_SIZE,
    create_square_placeholder,
    get_cached_square_pixmap,
    invalidate_image_cache,
    request_async_square_pixmap,
    save_square_artist_image,
)


class ArtistCard(QFrame):
    """
    Artist tile with a frameless square photo and a right-click context menu
    for adding and removing custom artist images.
    """

    artist_clicked = pyqtSignal(str)  # artist_name
    image_updated = pyqtSignal(str, str)  # artist_name, new_image_path (or "")

    def __init__(self, artist_data: Dict[str, Any], db_conn, parent=None):
        super().__init__(parent)
        self.artist_data = artist_data
        self.artist_name = artist_data["name"]
        self.album_count = artist_data.get("album_count", 0)
        self.track_count = artist_data.get("track_count", 0)
        self.image_path = artist_data.get("image_path", "")
        self.sample_cover = artist_data.get("sample_cover", "")
        self.db_conn = db_conn

        self.setFixedSize(170, 230)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("artistCard")

        self._init_ui()
        from malka.config import config
        self.apply_theme(getattr(config, "theme", "dark"))

    def apply_theme(self, theme: str):
        self.theme = theme
        if theme == "light":
            self.setStyleSheet("""
                QFrame#artistCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#artistCard:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                    border: none;
                    border-radius: 8px;
                }
                QLabel {
                    background: transparent;
                }
            """)
            if hasattr(self, "name_label"):
                self.name_label.setStyleSheet("color: #1f2328;")
            if hasattr(self, "sub_label"):
                self.sub_label.setStyleSheet("color: #656d76;")
        else:
            self.setStyleSheet("""
                QFrame#artistCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#artistCard:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: none;
                    border-radius: 8px;
                }
                QLabel {
                    background: transparent;
                }
            """)
            if hasattr(self, "name_label"):
                self.name_label.setStyleSheet("color: #ffffff;")
            if hasattr(self, "sub_label"):
                self.sub_label.setStyleSheet("color: #8b949e;")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Frameless edge-to-edge square photo (170x170)
        self.avatar_label = QLabel(self)
        self.avatar_label.setFixedSize(170, 170)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_avatar_pixmap()
        layout.addWidget(self.avatar_label)

        # Artist name label
        self.name_label = QLabel()
        self.name_label.setContentsMargins(8, 0, 8, 0)
        self.name_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.name_label.setStyleSheet("color: #ffffff;")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disp_name = self.artist_name if self.artist_name != NO_DATA else "Unknown Artist"
        elided = self.name_label.fontMetrics().elidedText(disp_name, Qt.TextElideMode.ElideRight, 154)
        self.name_label.setText(elided)
        self.name_label.setToolTip(disp_name)
        layout.addWidget(self.name_label)

        # Info label (albums and tracks count)
        self.info_label = QLabel()
        self.info_label.setContentsMargins(8, 0, 8, 0)
        self.info_label.setFont(QFont("Segoe UI", 8))
        self.info_label.setStyleSheet("color: #8b949e;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        alb_text = f"{self.album_count} {'album' if self.album_count == 1 else 'albums'}"
        tr_text = f"{self.track_count} {'track' if self.track_count == 1 else 'tracks'}"
        self.info_label.setText(f"{alb_text} • {tr_text}")
        layout.addWidget(self.info_label)

        layout.addStretch()

    def _update_avatar_pixmap(self):
        size = 170
        has_image = bool(self.image_path and Path(self.image_path).exists())
        if has_image:
            cached_pix = get_cached_square_pixmap(self.image_path, size=size, radius_top=8)
            if cached_pix:
                self.avatar_label.setPixmap(cached_pix)
                return

            initials = self._get_initials(self.artist_name)
            placeholder = create_square_placeholder(
                size=size,
                text_or_icon=initials,
                radius_top=8,
                bg_color="#1f242c",
                fg_color="#8b949e",
                is_initials=True,
            )
            self.avatar_label.setPixmap(placeholder)

            request_async_square_pixmap(
                self.image_path,
                size=size,
                radius_top=8,
                callback=self._on_avatar_loaded,
            )
            return

        # Placeholder with initials and top-rounded corners
        initials = self._get_initials(self.artist_name)
        placeholder = create_square_placeholder(
            size=size,
            text_or_icon=initials,
            radius_top=8,
            bg_color="#1f242c",
            fg_color="#8b949e",
            is_initials=True,
        )
        self.avatar_label.setPixmap(placeholder)

    def _on_avatar_loaded(self, path: str, pixmap: QPixmap):
        if self.image_path and Path(self.image_path).resolve() == Path(path).resolve():
            if not pixmap.isNull():
                self.avatar_label.setPixmap(pixmap)

    def _get_initials(self, name: str) -> str:
        if not name or name == NO_DATA:
            return "🎤"
        words = [w for w in name.strip().split() if w]
        if not words:
            return "🎤"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[-1][0]).upper()

    def _has_image(self) -> bool:
        return bool(self.image_path and Path(self.image_path).exists())

    def _add_artist_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select Image for {self.artist_name}",
            "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)",
        )
        if not file_path:
            return

        dest = self._cache_artist_image(self.artist_name, file_path)
        set_artist_image(self.db_conn, self.artist_name, dest)
        self.image_path = dest
        self._update_avatar_pixmap()
        self.image_updated.emit(self.artist_name, dest)

    def _remove_artist_image(self):
        set_artist_image(self.db_conn, self.artist_name, None)
        self.image_path = ""
        self._update_avatar_pixmap()
        self.image_updated.emit(self.artist_name, "")

    def _cache_artist_image(self, artist_name: str, src_path: str) -> str:
        ARTISTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(artist_name.strip().lower().encode("utf-8")).hexdigest()[:16]
        ext = Path(src_path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        dest = ARTISTS_CACHE_DIR / f"{h}{ext}"

        # Artist photos are displayed at <=340 px. Shrinking them once on import
        # keeps disk cache small and makes later loads/decodes dramatically faster.
        if not save_square_artist_image(src_path, dest, ARTIST_IMAGE_SIZE):
            shutil.copy2(src_path, dest)
        invalidate_image_cache(dest)
        return str(dest)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #21262d;
                color: #ffffff;
                border: 1px solid #444c56;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #30363d;
            }
        """)

        image_action = QAction(
            "Change artist image" if self._has_image() else "Add artist image",
            self,
        )
        image_action.triggered.connect(self._add_artist_image)
        menu.addAction(image_action)

        if self._has_image():
            remove_action = QAction("Remove artist image", self)
            remove_action.triggered.connect(self._remove_artist_image)
            menu.addAction(remove_action)

        menu.exec(event.globalPos())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.artist_clicked.emit(self.artist_name)
        super().mouseReleaseEvent(event)
