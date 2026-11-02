from typing import Any, Dict

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from malka.config import NO_DATA

GENRE_ICONS = {
    "rock": "🎸",
    "hard rock": "🎸",
    "metal": "⚡",
    "heavy metal": "⚡",
    "symphonic metal": "⚡",
    "jazz": "🎷",
    "blues": "🎺",
    "electronic": "🎧",
    "techno": "🎧",
    "house": "🎧",
    "ambient": "🌌",
    "classical": "🎻",
    "folk": "🪕",
    "acoustic": "🪕",
    "hip hop": "🎙️",
    "hip-hop": "🎙️",
    "rap": "🎙️",
    "pop": "✨",
    "dance": "✨",
    "soundtrack": "🎬",
    "reggae": "🌴",
    "country": "🤠",
    "punk": "🔥",
    "indie": "☕",
}


def get_genre_icon(genre_name: str) -> str:
    if not genre_name or genre_name == NO_DATA:
        return "🎵"
    g_lower = genre_name.strip().lower()
    for key, icon in GENRE_ICONS.items():
        if key in g_lower:
            return icon
    return "🎵"


class GenreCard(QFrame):
    """
    Card representing a music genre in the library.
    Displays a frameless square banner, genre title, and album/track counts.
    Clicking the card opens all albums categorized under this genre.
    """

    genre_clicked = pyqtSignal(str)  # genre_name

    def __init__(self, genre_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.genre_data = genre_data
        self.genre_name = genre_data["genre"]
        self.album_count = genre_data.get("album_count", 0)
        self.track_count = genre_data.get("track_count", 0)

        self.setFixedSize(170, 230)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("genreCard")

        self._init_ui()
        from malka.config import config
        self.apply_theme(getattr(config, "theme", "dark"))

    def apply_theme(self, theme: str):
        self.theme = theme
        if theme == "light":
            self.setStyleSheet("""
                QFrame#genreCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#genreCard:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                    border: none;
                    border-radius: 8px;
                }
                QLabel {
                    background: transparent;
                }
            """)
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #1f2328;")
            if hasattr(self, "info_label"):
                self.info_label.setStyleSheet("color: #656d76;")
        else:
            self.setStyleSheet("""
                QFrame#genreCard {
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }
                QFrame#genreCard:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: none;
                    border-radius: 8px;
                }
                QLabel {
                    background: transparent;
                }
            """)
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #ffffff;")
            if hasattr(self, "info_label"):
                self.info_label.setStyleSheet("color: #8b949e;")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Frameless edge-to-edge square genre banner (170x170)
        self.banner_label = QLabel(self)
        self.banner_label.setFixedSize(170, 170)
        self.banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_label.setPixmap(self._create_genre_banner(self.genre_name))
        layout.addWidget(self.banner_label)

        # Genre title label
        self.title_label = QLabel()
        self.title_label.setContentsMargins(8, 0, 8, 0)
        self.title_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #ffffff;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disp_genre = self.genre_name if self.genre_name != NO_DATA else "Unspecified Genre"
        elided = self.title_label.fontMetrics().elidedText(disp_genre, Qt.TextElideMode.ElideRight, 154)
        self.title_label.setText(elided)
        self.title_label.setToolTip(disp_genre)
        layout.addWidget(self.title_label)

        # Subtitle info label (albums / tracks)
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

    def _create_genre_banner(self, genre_name: str) -> QPixmap:
        size = 170
        dpr = 2.0
        target_px = int(size * dpr)
        pix = QPixmap(target_px, target_px)
        pix.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        r = 8.0 * dpr
        path = QPainterPath()
        path.moveTo(0, target_px)
        path.lineTo(0, r)
        path.arcTo(0, 0, r * 2, r * 2, 180, -90)
        path.lineTo(target_px - r, 0)
        path.arcTo(target_px - r * 2, 0, r * 2, r * 2, 90, -90)
        path.lineTo(target_px, target_px)
        path.closeSubpath()

        # Background gradient with top-rounded corners
        grad = QLinearGradient(0, 0, 0, target_px)
        grad.setColorAt(0.0, QColor("#1c222b"))
        grad.setColorAt(1.0, QColor("#141920"))
        painter.fillPath(path, grad)

        # Centered icon
        icon_str = get_genre_icon(genre_name)
        font = QFont("Segoe UI Emoji", int(38 * dpr))
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, target_px, target_px), Qt.AlignmentFlag.AlignCenter, icon_str)
        painter.end()

        pix.setDevicePixelRatio(dpr)
        return pix

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.genre_clicked.emit(self.genre_name)
        super().mouseReleaseEvent(event)
