from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from malka.config import config
from malka.ui.image_utils import app_icon, get_resource_path

APP_VERSION = "1.0"
SUPPORT_URL = "https://boosty.to/paveldistrianov/donate"
SITE_URL = "https://dps.com.ru/malka"
EMAIL = "gml.paul93@gmail.com"
TELEGRAM = "https://t.me/paveldistrianov"


class AboutDialog(QDialog):
    """About window with product, author and project sections."""

    def __init__(self, parent=None, theme: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle(f"About Malka {APP_VERSION}")
        self.setModal(True)
        self.setFixedSize(760, 620)
        self.setWindowIcon(app_icon())

        if theme is not None:
            self.theme = theme
        elif hasattr(parent, "theme"):
            self.theme = parent.theme
        else:
            self.theme = getattr(config, "theme", "dark")

        self._build_ui()
        self.apply_theme(self.theme)

    # ------------------------------------------------------------------
    @staticmethod
    def _rounded_photo(size: int = 120, radius: int = 12) -> QPixmap:
        path = get_resource_path("about_photo.png")
        if not path or not Path(path).exists():
            return QPixmap()
        source = QPixmap(path)
        if source.isNull():
            return QPixmap()
        scaled = source.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cropped = scaled.copy(
            (scaled.width() - size) // 2,
            (scaled.height() - size) // 2,
            size,
            size,
        )
        result = QPixmap(size, size)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, size, size, radius, radius)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        return result

    def _section(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("aboutSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 13, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("aboutSectionTitle")
        layout.addWidget(heading)
        return frame, layout

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(14)

        # Header ---------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(16)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("aboutAppIcon")
        self.icon_label.setFixedSize(84, 84)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand = app_icon().pixmap(72, 72)
        if not brand.isNull():
            self.icon_label.setPixmap(brand)
        header.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)

        title_block = QVBoxLayout()
        title_block.setSpacing(3)
        self.title_label = QLabel("Malka")
        self.title_label.setObjectName("aboutTitle")
        self.title_label.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
        title_block.addWidget(self.title_label)

        subtitle_row = QHBoxLayout()
        subtitle_row.setSpacing(9)
        self.subtitle_label = QLabel("Personal music library organizer")
        self.subtitle_label.setObjectName("aboutSubtitle")
        subtitle_row.addWidget(self.subtitle_label)
        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setObjectName("aboutVersion")
        subtitle_row.addWidget(self.version_label)
        subtitle_row.addStretch(1)
        title_block.addLayout(subtitle_row)
        header.addLayout(title_block, 1)
        layout.addLayout(header)

        # About ----------------------------------------------------------
        about_frame, about_layout = self._section("ABOUT")
        self.description_label = QLabel(
            "Malka keeps a local music library in order: it scans your folders, "
            "reads tags and artwork, plays MP3 / AAC / ALAC / FLAC through FFmpeg, "
            "and can re-organize, convert and retag albums."
        )
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("aboutBody")
        about_layout.addWidget(self.description_label)
        layout.addWidget(about_frame)

        # Author ---------------------------------------------------------
        author_frame, author_layout = self._section("AUTHOR")
        author_row = QHBoxLayout()
        author_row.setSpacing(16)

        photo = self._rounded_photo(120, 14)
        self.photo_label = QLabel()
        self.photo_label.setObjectName("aboutPhoto")
        self.photo_label.setFixedSize(120, 120)
        self.photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if photo.isNull():
            self.photo_label.hide()
        else:
            self.photo_label.setPixmap(photo)
        author_row.addWidget(self.photo_label, 0, Qt.AlignmentFlag.AlignTop)

        author_text = QVBoxLayout()
        author_text.setSpacing(4)
        author_name = QLabel("Pavel Distrianov")
        author_name.setObjectName("aboutAuthorName")
        author_text.addWidget(author_name)
        author_role = QLabel("Developer & maintainer")
        author_role.setObjectName("aboutAuthorRole")
        author_text.addWidget(author_role)
        self.contact_label = QLabel("")
        self.contact_label.setWordWrap(True)
        self.contact_label.setOpenExternalLinks(True)
        self.contact_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.contact_label.setObjectName("aboutLinks")
        author_text.addWidget(self.contact_label)
        author_note = QLabel(
            "Bug reports, feature ideas and kind words are always welcome."
        )
        author_note.setWordWrap(True)
        author_note.setObjectName("aboutMuted")
        author_text.addWidget(author_note)
        author_text.addStretch(1)
        author_row.addLayout(author_text, 1)
        author_layout.addLayout(author_row)
        layout.addWidget(author_frame)

        # Project --------------------------------------------------------
        project_frame, project_layout = self._section("PROJECT")
        self.site_label = QLabel("")
        self.site_label.setOpenExternalLinks(True)
        self.site_label.setWordWrap(True)
        self.site_label.setObjectName("aboutLinks")
        project_layout.addWidget(self.site_label)
        self.license_label = QLabel(
            "Malka is free software distributed under the "
            "<b>GNU General Public License v2 (GPLv2)</b>."
        )
        self.license_label.setWordWrap(True)
        self.license_label.setObjectName("aboutMuted")
        project_layout.addWidget(self.license_label)
        layout.addWidget(project_frame)

        layout.addStretch(1)

        # Footer ---------------------------------------------------------
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_support = QPushButton("Support the project")
        self.btn_support.setObjectName("supportBtn")
        self.btn_support.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_support.setToolTip(SUPPORT_URL)
        self.btn_support.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL))
        )
        buttons.addWidget(self.btn_support)
        buttons.addStretch(1)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = theme == "light"
        text_color = "#1f2328" if is_light else "#e6edf3"
        muted = "#57606a" if is_light else "#8b949e"
        bg = "#f6f8fa" if is_light else "#0d1117"
        section_bg = "#ffffff" if is_light else "#161b22"
        border = "#d0d7de" if is_light else "#30363d"
        link = "#0969da" if is_light else "#58a6ff"
        version_bg = "#eaeef2" if is_light else "#21262d"
        version_fg = "#57606a" if is_light else "#c9d1d9"

        support_bg = "#1f883d" if is_light else "#238636"
        support_hover = "#1a7f37" if is_light else "#2ea043"
        support_border = "#1a7f37" if is_light else "#2ea043"

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text_color}; font-size: 12px; }}
            QLabel#aboutAppIcon {{
                background: transparent;
            }}
            QLabel#aboutTitle {{
                color: {text_color};
                font-size: 30px;
                font-weight: 700;
            }}
            QLabel#aboutSubtitle {{ color: {muted}; font-size: 12px; }}
            QLabel#aboutVersion {{
                color: {version_fg};
                background: {version_bg};
                border-radius: 8px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 600;
            }}
            QFrame#aboutSection {{
                background: {section_bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QLabel#aboutSectionTitle {{
                color: {muted};
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#aboutBody {{ color: {text_color}; font-size: 12px; }}
            QLabel#aboutAuthorName {{
                color: {text_color};
                font-size: 17px;
                font-weight: 700;
            }}
            QLabel#aboutAuthorRole {{ color: {muted}; font-size: 11px; }}
            QLabel#aboutMuted {{ color: {muted}; font-size: 11px; }}
            QLabel#aboutLinks {{ color: {text_color}; font-size: 12px; }}
            QLabel a {{ color: {link}; text-decoration: none; }}
            QPushButton {{
                background-color: transparent;
                color: {text_color};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: 500;
            }}
            QPushButton:hover {{ background-color: rgba(127, 127, 127, 0.12); }}
            QPushButton#supportBtn {{
                background-color: {support_bg};
                color: #ffffff;
                border: 1px solid {support_border};
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: 600;
            }}
            QPushButton#supportBtn:hover {{ background-color: {support_hover}; }}
        """)
        self.title_label.setStyleSheet(f"color: {text_color};")

        link_style = f'style="color:{link}; text-decoration:none;"'
        self.contact_label.setText(
            f'Email: <a href="mailto:{EMAIL}" {link_style}>{EMAIL}</a><br>'
            f'Telegram: <a href="{TELEGRAM}" {link_style}>t.me/paveldistrianov</a>'
        )
        self.site_label.setText(
            "Official site (latest version): "
            f'<a href="{SITE_URL}" {link_style}>{SITE_URL.replace("https://", "")}</a>'
        )
