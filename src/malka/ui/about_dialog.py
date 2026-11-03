from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from malka.config import config
from malka.ui.image_utils import emoji_icon

SUPPORT_URL = "https://boosty.to/paveldistrianov/donate"
SITE_URL = "https://dps.com.ru/malka"
EMAIL = "gml.paul93@gmail.com"
TELEGRAM = "https://t.me/paveldistrianov"


class AboutDialog(QDialog):
    """Short description, contacts, official site and license information."""

    def __init__(self, parent=None, theme: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("About Malka")
        self.setModal(True)
        self.setFixedSize(560, 380)
        self.setWindowIcon(emoji_icon("🎵"))

        if theme is not None:
            self.theme = theme
        elif hasattr(parent, "theme"):
            self.theme = parent.theme
        else:
            self.theme = getattr(config, "theme", "dark")

        self._build_ui()
        self.apply_theme(self.theme)

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(12)

        # App icon + name
        header = QHBoxLayout()
        header.setSpacing(14)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(56, 56)
        self.icon_label.setPixmap(emoji_icon("🎵").pixmap(56, 56))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.icon_label)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        self.title_label = QLabel("Malka")
        self.title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_block.addWidget(self.title_label)

        try:
            from importlib.metadata import version

            version_text = f"Version {version('malka')}"
        except Exception:
            version_text = ""
        self.subtitle_label = QLabel(
            "Personal music library organizer" + (f" · {version_text}" if version_text else "")
        )
        self.subtitle_label.setObjectName("aboutSubtitle")
        title_block.addWidget(self.subtitle_label)
        header.addLayout(title_block, 1)
        layout.addLayout(header)

        self.description_label = QLabel(
            "Malka keeps a local music library in order: it scans your folders, "
            "reads tags and artwork, plays MP3 / AAC / ALAC / FLAC through FFmpeg, "
            "and can re-organize, convert and retag albums."
        )
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

        self.contact_label = QLabel("")
        self.contact_label.setWordWrap(True)
        self.contact_label.setOpenExternalLinks(True)
        self.contact_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        layout.addWidget(self.contact_label)

        self.site_label = QLabel("")
        self.site_label.setOpenExternalLinks(True)
        self.site_label.setWordWrap(True)
        layout.addWidget(self.site_label)

        self.license_label = QLabel(
            "Malka is free software distributed under the "
            "<b>GNU General Public License v2 (GPLv2)</b>."
        )
        self.license_label.setWordWrap(True)
        self.license_label.setObjectName("aboutLicense")
        layout.addWidget(self.license_label)

        layout.addStretch(1)

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
        bg = "#ffffff" if is_light else "#0d1117"
        border = "#d0d7de" if is_light else "#30363d"

        if is_light:
            support_style = (
                "QPushButton#supportBtn { background-color: #bf3989; color: #ffffff;"
                " border: none; border-radius: 6px; padding: 8px 16px; font-weight: 600; }"
                "QPushButton#supportBtn:hover { background-color: #a12a73; }"
            )
        else:
            support_style = (
                "QPushButton#supportBtn { background-color: #db61a2; color: #0d1117;"
                " border: none; border-radius: 6px; padding: 8px 16px; font-weight: 600; }"
                "QPushButton#supportBtn:hover { background-color: #f778ba; }"
            )

        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {text_color}; font-size: 12px; }}
            QLabel#aboutSubtitle {{ color: {muted}; font-size: 12px; }}
            QLabel#aboutLicense {{ color: {muted}; font-size: 11px; }}
            QLabel a {{ color: #58a6ff; text-decoration: none; }}
            QPushButton {{
                background-color: transparent; color: {text_color};
                border: 1px solid {border}; border-radius: 6px;
                padding: 8px 18px; font-weight: 500;
            }}
            QPushButton:hover {{ background-color: rgba(127, 127, 127, 0.12); }}
            {support_style}
        """)
        self.title_label.setStyleSheet(f"color: {text_color};")

        link = "#58a6ff" if not is_light else "#0969da"
        link_style = f'style="color:{link}; text-decoration:none;"'
        self.contact_label.setText(
            "<b>Developed by Pavel Distrianov</b><br>"
            f'Email: <a href="mailto:{EMAIL}" {link_style}>{EMAIL}</a><br>'
            f'Telegram: <a href="{TELEGRAM}" {link_style}>t.me/paveldistrianov</a><br><br>'
            "Write to report a bug, suggest a feature, share your thoughts — "
            "or just say something nice."
        )
        self.site_label.setText(
            "Official site (latest version): "
            f'<a href="{SITE_URL}" {link_style}>{SITE_URL.replace("https://", "")}</a>'
        )
