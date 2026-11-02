import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from malka.config import NO_DATA, config
from malka.db import (
    get_album_decade_statistics,
    get_album_statistics,
    get_artist_image,
    get_artist_statistics,
    get_genre_statistics,
)
from malka.ui.image_utils import get_cached_square_pixmap, request_async_square_pixmap

# Palette for pie chart decades and bar charts
DECADE_COLORS = {
    "1900s": "#5c7cfa",
    "1910s": "#339af0",
    "1920s": "#22b8cf",
    "1930s": "#20c997",
    "1940s": "#51cf66",
    "1950s": "#94d82d",
    "1960s": "#fcc419",
    "1970s": "#ff922b",
    "1980s": "#ff6b6b",
    "1990s": "#f06595",
    "2000s": "#cc5de8",
    "2010s": "#845ef7",
    "2020s": "#4dabf7",
    "Pre-1900": "#a9e34b",
    "Unknown": "#868e96",
}

FALLBACK_PALETTE = [
    "#388bfd", "#3fb950", "#f0883e", "#bc8cff",
    "#f778ba", "#56d364", "#e3b341", "#79c0ff",
    "#ff7b72", "#2ea043", "#a371f7", "#d29922",
]


class StatBarRow(QFrame):
    """
    A single clickable row in the statistics linear bar chart.
    Displays rank, thumbnail/avatar, title, subtitle, horizontal filled bar, count badge, and percentage.
    """
    clicked = pyqtSignal(dict)

    def __init__(
        self,
        item_data: Dict[str, Any],
        rank: int,
        val: int,
        max_val: int,
        total_val: int,
        val_unit: str = "tracks",
        item_type: str = "artist",  # "artist", "album", "genre"
        is_pinned: bool = False,
        theme: str = "dark",
        parent=None,
    ):
        super().__init__(parent)
        self.item_data = item_data
        self.rank = rank
        self.val = val
        self.max_val = max(max_val, 1)
        self.total_val = max(total_val, 1)
        self.val_unit = val_unit
        self.item_type = item_type
        self.is_pinned = is_pinned
        self.theme = theme

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(54)
        self._init_ui()
        self.apply_theme(theme)

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)

        # Rank badge
        self.rank_lbl = QLabel(f"#{self.rank}")
        self.rank_lbl.setFixedWidth(38)
        self.rank_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rank_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        layout.addWidget(self.rank_lbl)

        # Thumbnail / Avatar
        self.thumb_lbl = QLabel()
        self.thumb_lbl.setFixedSize(40, 40)
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_thumbnail()
        layout.addWidget(self.thumb_lbl)

        # Title & Subtitle block — fixed width so the bars line up on every row.
        text_widget = QWidget()
        text_widget.setFixedWidth(330)
        text_block = QVBoxLayout(text_widget)
        text_block.setContentsMargins(0, 0, 0, 0)
        text_block.setSpacing(2)

        self.title_lbl = QLabel()
        self.title_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.title_lbl.setFixedWidth(330)
        self.title_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        text_block.addWidget(self.title_lbl)

        self.sub_lbl = QLabel()
        self.sub_lbl.setFont(QFont("Segoe UI", 8))
        self.sub_lbl.setFixedWidth(330)
        text_block.addWidget(self.sub_lbl)

        self._set_elided_texts()
        layout.addWidget(text_widget, 0)

        # Horizontal Bar container
        self.bar_widget = HorizontalBarWidget(
            value=self.val,
            max_value=self.max_val,
            color=self._get_bar_color(),
            theme=self.theme,
        )
        self.bar_widget.setFixedHeight(12)
        layout.addWidget(self.bar_widget, 3)

        # Metric value badge
        self.badge_lbl = QLabel(f"{self.val} {self.val_unit}")
        self.badge_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.badge_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.badge_lbl.setFixedWidth(90)
        layout.addWidget(self.badge_lbl)

        # Percentage
        pct = (self.val / self.total_val) * 100.0 if self.total_val > 0 else 0.0
        self.pct_lbl = QLabel(f"{pct:.1f}%")
        self.pct_lbl.setFont(QFont("Segoe UI", 8))
        self.pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.pct_lbl.setFixedWidth(50)
        layout.addWidget(self.pct_lbl)

        if self.is_pinned:
            self.pin_badge = QLabel("📍 Pinned")
            self.pin_badge.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            self.pin_badge.setStyleSheet("""
                background-color: rgba(227, 98, 9, 0.9);
                color: #ffffff;
                border-radius: 4px;
                padding: 2px 6px;
            """)
            layout.addWidget(self.pin_badge)

    def _set_elided_texts(self):
        title = self._get_title()
        subtitle = self._get_subtitle()
        metrics_title = self.title_lbl.fontMetrics()
        metrics_sub = self.sub_lbl.fontMetrics()
        self.title_lbl.setText(metrics_title.elidedText(title, Qt.TextElideMode.ElideRight, 320))
        self.title_lbl.setToolTip(title)
        self.sub_lbl.setText(metrics_sub.elidedText(subtitle, Qt.TextElideMode.ElideRight, 320))
        self.sub_lbl.setToolTip(subtitle)

    @staticmethod
    def _initials(name: str) -> str:
        words = [w for w in str(name or "").split() if w]
        if not words:
            return "🎤"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[-1][0]).upper()

    def _get_title(self) -> str:
        if self.item_type == "artist":
            return self.item_data.get("artist_name", "Unknown Artist")
        elif self.item_type == "album":
            return self.item_data.get("album", "Untitled Album")
        else:
            return self.item_data.get("genre", "Unknown Genre")

    def _get_subtitle(self) -> str:
        if self.item_type == "artist":
            alb_cnt = self.item_data.get("album_count", 0)
            return f"{alb_cnt} album{'s' if alb_cnt != 1 else ''}"
        elif self.item_type == "album":
            artist = self.item_data.get("album_artist", "Unknown Artist")
            year = self.item_data.get("year", "")
            yr_str = f" • {year}" if year and year != NO_DATA else ""
            return f"{artist}{yr_str}"
        else:
            alb_cnt = self.item_data.get("album_count", 0)
            return f"{alb_cnt} album{'s' if alb_cnt != 1 else ''}"

    def _get_bar_color(self) -> str:
        if self.item_type == "artist":
            return "#1f6feb" if self.val_unit == "tracks" else "#238636"
        elif self.item_type == "album":
            return "#388bfd"
        else:
            return "#bc8cff" if self.val_unit == "tracks" else "#f0883e"

    def _load_thumbnail(self):
        if self.item_type == "artist":
            # Artists must never borrow an album cover: use their own image or
            # the initials placeholder.
            img_p = self.item_data.get("image_path") or None
        else:
            img_p = (
                self.item_data.get("image_path")
                or self.item_data.get("cover_path")
                or self.item_data.get("sample_cover")
            )
        self._thumb_source = img_p
        pix = get_cached_square_pixmap(img_p, size=40, radius_top=6) if img_p else None

        if pix and not pix.isNull():
            is_circle = (self.item_type == "artist")
            self.thumb_lbl.setPixmap(self._round_pixmap(pix, 40, is_circle=is_circle))
            return

        # Never decode full-size artwork synchronously in a statistics list;
        # use RAM/disk thumbnails and generate missing ones in the background.
        self.thumb_lbl.setPixmap(self._create_placeholder(40))
        if img_p:
            request_async_square_pixmap(
                img_p,
                size=40,
                radius_top=6,
                callback=self._on_thumbnail_loaded,
            )

    def _on_thumbnail_loaded(self, path: str, pixmap: QPixmap):
        if self._thumb_source and Path(self._thumb_source).resolve() == Path(path).resolve():
            if not pixmap.isNull():
                is_circle = (self.item_type == "artist")
                self.thumb_lbl.setPixmap(self._round_pixmap(pixmap, 40, is_circle=is_circle))

    def _round_pixmap(self, src: QPixmap, size: int, is_circle: bool = False) -> QPixmap:
        # Cached thumbnails already carry a devicePixelRatio (usually 2.0).
        # Scale in physical pixels with Lanczos, otherwise a 40 px avatar is
        # drawn at 20 px (a quarter of its allocated QLabel area).
        from malka.ui.image_utils import resize_pixmap_lanczos

        dpr = src.devicePixelRatio() or 1.0
        target_px = max(1, int(round(size * dpr)))
        scaled = resize_pixmap_lanczos(src, target_px, target_px) if (
            src.width() != target_px or src.height() != target_px
        ) else src
        cropped = scaled

        dest = QPixmap(target_px, target_px)
        dest.setDevicePixelRatio(dpr)
        dest.fill(Qt.GlobalColor.transparent)
        painter = QPainter(dest)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Logical coordinates: the canvas is target_px physical, size logical.
        path = QPainterPath()
        if is_circle:
            path.addEllipse(0, 0, size, size)
        else:
            path.addRoundedRect(0, 0, size, size, 6, 6)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        return dest

    def _create_placeholder(self, size: int) -> QPixmap:
        # Draw at the physical resolution of the screen, otherwise the avatar is
        # upscaled by Qt and looks blurry on HiDPI displays.
        app = QApplication.instance()
        dpr = app.primaryScreen().devicePixelRatio() if (app and app.primaryScreen()) else 1.0
        target = max(1, int(round(size * dpr)))
        dest = QPixmap(target, target)
        dest.setDevicePixelRatio(dpr)
        dest.fill(Qt.GlobalColor.transparent)
        painter = QPainter(dest)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        is_light = (self.theme == "light")
        bg_col = QColor("#eaeef2" if is_light else "#21262d")
        text_col = QColor("#57606a" if is_light else "#8b949e")

        # Painting happens in logical coordinates; the pixmap itself carries
        # the device pixel ratio, so the 40 px avatar is rendered at 80 px.
        path = QPainterPath()
        if self.item_type == "artist":
            path.addEllipse(0, 0, size, size)
        else:
            path.addRoundedRect(0, 0, size, size, 6, 6)
        painter.fillPath(path, bg_col)

        # Draw icon, initials (artists) or the first letter.
        title = self._get_title()
        symbol = title[0].upper() if title else "?"
        if self.item_type == "genre":
            symbol = "🎸"
        elif self.item_type == "album":
            symbol = "💿"
        elif self.item_type == "artist":
            symbol = self._initials(title)

        painter.setPen(text_col)
        painter.setFont(QFont("Segoe UI", 10 if self.item_type == "artist" else 12, QFont.Weight.Bold))
        painter.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, symbol)
        painter.end()
        return dest

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")

        if self.is_pinned:
            bg_col = "rgba(227, 98, 9, 0.10)" if is_light else "rgba(227, 98, 9, 0.12)"
        else:
            bg_col = "transparent"

        hover_bg = "rgba(0, 0, 0, 0.035)" if is_light else "rgba(255, 255, 255, 0.045)"

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_col};
                border: none;
                border-radius: 8px;
            }}
            QFrame:hover {{
                background-color: {hover_bg};
            }}
        """)

        text_col = "#1f2328" if is_light else "#e6edf3"
        sub_col = "#656d76" if is_light else "#8b949e"
        badge_bg = "#eaeef2" if is_light else "#21262d"

        self.rank_lbl.setStyleSheet(f"color: {sub_col}; background: {badge_bg}; border-radius: 4px; padding: 2px;")
        self.title_lbl.setStyleSheet(f"color: {text_col}; background: transparent; border: none;")
        self.sub_lbl.setStyleSheet(f"color: {sub_col}; background: transparent; border: none;")
        self.badge_lbl.setStyleSheet(f"color: {text_col}; background: transparent; border: none;")
        self.pct_lbl.setStyleSheet(f"color: {sub_col}; background: transparent; border: none;")

        if hasattr(self, "bar_widget"):
            self.bar_widget.apply_theme(theme)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_data)
        super().mousePressEvent(event)


class HorizontalBarWidget(QWidget):
    """Horizontal bar indicating proportion relative to max value."""
    def __init__(self, value: int, max_value: int, color: str = "#1f6feb", theme: str = "dark", parent=None):
        super().__init__(parent)
        self.value = value
        self.max_value = max(max_value, 1)
        self.color = color
        self.theme = theme

    def apply_theme(self, theme: str):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        is_light = (self.theme == "light")
        bg_col = QColor("#d0d7de" if is_light else "#30363d")
        fill_col = QColor(self.color)

        w = self.width()
        h = self.height()
        radius = h / 2.0

        # Background track
        bg_path = QPainterPath()
        bg_path.addRoundedRect(0, 0, w, h, radius, radius)
        painter.fillPath(bg_path, bg_col)

        # Filled portion
        fill_w = max(4.0, (self.value / self.max_value) * w)
        fill_path = QPainterPath()
        fill_path.addRoundedRect(0, 0, fill_w, h, radius, radius)
        painter.fillPath(fill_path, fill_col)
        painter.end()


class DecadePieChart(QWidget):
    """
    Antialiased circular donut / pie chart displaying albums grouped by 10-year intervals starting from 1900.
    Supports hover highlighting, tooltips, slice clicking, and interactive legend.
    """
    decade_clicked = pyqtSignal(str)  # emitted when a decade slice or legend item is clicked

    def __init__(self, decades_data: List[Dict[str, Any]], total_albums: int, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.decades = decades_data
        self.total_albums = total_albums
        self.theme = theme
        self.hovered_idx = -1
        self.selected_decade: Optional[str] = None

        self.setMouseTracking(True)
        self.setMinimumSize(320, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)

    def set_data(self, decades_data: List[Dict[str, Any]], total_albums: int):
        self.decades = decades_data
        self.total_albums = total_albums
        self.hovered_idx = -1
        self.update()

    def apply_theme(self, theme: str):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        is_light = (self.theme == "light")
        text_col = QColor("#1f2328" if is_light else "#e6edf3")
        sub_col = QColor("#656d76" if is_light else "#8b949e")
        hole_col = QColor("#ffffff" if is_light else "#0d1117")

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        outer_radius = min(w, h) * 0.40
        inner_radius = outer_radius * 0.55

        if self.total_albums == 0 or not self.decades:
            painter.setPen(sub_col)
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No albums with year data found.")
            painter.end()
            return

        start_angle = 90.0  # start at top (12 o'clock)
        for i, d in enumerate(self.decades):
            cnt = d["album_count"]
            span_angle = (cnt / self.total_albums) * 360.0
            col_str = DECADE_COLORS.get(d["decade"], FALLBACK_PALETTE[i % len(FALLBACK_PALETTE)])
            base_col = QColor(col_str)

            is_hover = (i == self.hovered_idx)
            is_sel = (d["decade"] == self.selected_decade)

            r_outer = outer_radius + (6 if (is_hover or is_sel) else 0)
            rect_outer = QRectF(cx - r_outer, cy - r_outer, r_outer * 2, r_outer * 2)

            # Draw slice
            painter.setPen(QPen(hole_col, 2))
            painter.setBrush(QBrush(base_col))
            painter.drawPie(rect_outer, int(start_angle * 16), int(-span_angle * 16))

            start_angle -= span_angle

        # Donut hole
        hole_rect = QRectF(cx - inner_radius, cy - inner_radius, inner_radius * 2, inner_radius * 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(hole_col))
        painter.drawEllipse(hole_rect)

        # Center Text (Total Albums or Hovered Decade)
        if 0 <= self.hovered_idx < len(self.decades):
            hd = self.decades[self.hovered_idx]
            main_text = hd["decade"]
            sub_text = f"{hd['album_count']} albums ({hd['percentage']:.1f}%)"
        elif self.selected_decade:
            match = next((d for d in self.decades if d["decade"] == self.selected_decade), None)
            main_text = self.selected_decade
            sub_text = f"{match['album_count']} albums" if match else ""
        else:
            main_text = f"{self.total_albums}"
            sub_text = "Albums"

        painter.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        painter.setPen(text_col)
        fm = painter.fontMetrics()
        h_main = fm.height()
        painter.drawText(QRectF(cx - inner_radius, cy - inner_radius + (inner_radius * 0.3), inner_radius * 2, h_main),
                         Qt.AlignmentFlag.AlignCenter, main_text)

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(sub_col)
        painter.drawText(QRectF(cx - inner_radius, cy - inner_radius + (inner_radius * 0.3) + h_main + 2, inner_radius * 2, 20),
                         Qt.AlignmentFlag.AlignCenter, sub_text)

        painter.end()

    def mouseMoveEvent(self, event):
        pos = event.position()
        idx = self._get_slice_at_pos(pos)
        if idx != self.hovered_idx:
            self.hovered_idx = idx
            self.update()
            if 0 <= idx < len(self.decades):
                d = self.decades[idx]
                QToolTip.showText(event.globalPosition().toPoint(), f"Decade: {d['decade']}\n{d['album_count']} albums ({d['percentage']:.1f}%)", self)
            else:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hovered_idx = -1
        self.update()
        QToolTip.hideText()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._get_slice_at_pos(event.position())
            if 0 <= idx < len(self.decades):
                dec = self.decades[idx]["decade"]
                if self.selected_decade == dec:
                    self.selected_decade = None  # toggle deselect
                else:
                    self.selected_decade = dec
                self.decade_clicked.emit(self.selected_decade or "")
                self.update()
        super().mousePressEvent(event)

    def _get_slice_at_pos(self, pos: QPointF) -> int:
        if self.total_albums == 0 or not self.decades:
            return -1

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        dx = pos.x() - cx
        dy = pos.y() - cy
        dist = math.hypot(dx, dy)

        outer_radius = min(w, h) * 0.40 + 8
        inner_radius = outer_radius * 0.50
        if dist < inner_radius or dist > outer_radius:
            return -1

        # Angle in degrees clockwise from 12 o'clock
        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad) + 90.0
        if angle_deg < 0:
            angle_deg += 360.0

        cum_angle = 0.0
        for i, d in enumerate(self.decades):
            span = (d["album_count"] / self.total_albums) * 360.0
            if cum_angle <= angle_deg < cum_angle + span:
                return i
            cum_angle += span

        return -1


class StatRankView(QWidget):
    """
    Standard ranked list view implementing:
    - Search field with auto-complete dropdown and pinning.
    - Top 10 items.
    - 'Load more (from top)' button.
    - Pinned item (if between top and bottom).
    - 'Load more (from bottom)' button.
    - Bottom 10 items.
    """
    item_clicked = pyqtSignal(dict)

    def __init__(self, item_type: str = "artist", val_unit: str = "tracks", theme: str = "dark", parent=None):
        super().__init__(parent)
        self.setObjectName("statRankView")
        self.item_type = item_type
        self.val_unit = val_unit
        self.theme = theme

        self.all_items: List[Dict[str, Any]] = []
        self.pinned_key: Optional[str] = None
        self.top_count = 10
        self.bottom_count = 10

        self._build_ui()
        self.apply_theme(theme)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Search Bar with autocomplete
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 4)
        search_row.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(f"🔍 Search {self.item_type} to pinpoint position...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        search_row.addWidget(self.search_edit, 1)

        self.btn_clear_pin = QPushButton("Clear Pin")
        self.btn_clear_pin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_pin.clicked.connect(self._clear_pin)
        self.btn_clear_pin.hide()
        search_row.addWidget(self.btn_clear_pin)

        layout.addLayout(search_row)

        # Scroll Area for the rows
        self.scroll = QScrollArea()
        self.scroll.setObjectName("statScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea#statScroll { background: transparent; border: none; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self.update_scrollbars()

        self.rows_container = QWidget()
        self.rows_container.setObjectName("statRowsContainer")
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(6)

        # Sections inside rows layout
        self.top_container = QVBoxLayout()
        self.top_container.setSpacing(6)
        self.rows_layout.addLayout(self.top_container)

        # Load more from top button
        self.btn_load_top = QPushButton("⬇ Load more (from top)")
        self.btn_load_top.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load_top.clicked.connect(self._on_load_more_top)
        self.rows_layout.addWidget(self.btn_load_top)

        # Pinned item section (shown between top and bottom when item is not in either slice)
        self.pinned_container = QFrame()
        self.pinned_container.setObjectName("pinnedContainer")
        self.pinned_layout = QVBoxLayout(self.pinned_container)
        self.pinned_layout.setContentsMargins(4, 4, 4, 4)
        self.pinned_layout.setSpacing(4)
        self.pinned_container.hide()
        self.rows_layout.addWidget(self.pinned_container)

        # Load more from bottom button
        self.btn_load_bottom = QPushButton("⬆ Load more (from bottom)")
        self.btn_load_bottom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load_bottom.clicked.connect(self._on_load_more_bottom)
        self.rows_layout.addWidget(self.btn_load_bottom)

        # Bottom container
        self.bottom_container = QVBoxLayout()
        self.bottom_container.setSpacing(6)
        self.rows_layout.addLayout(self.bottom_container)

        self.rows_layout.addStretch()
        self.scroll.setWidget(self.rows_container)
        layout.addWidget(self.scroll, 1)

    def set_items(self, items: List[Dict[str, Any]], val_unit: str = "tracks"):
        self.all_items = items
        self.val_unit = val_unit
        self.top_count = 10
        self.bottom_count = 10
        self._setup_completer()
        self._refresh_rows()

    def _setup_completer(self):
        names = []
        for it in self.all_items:
            key = self._get_item_key(it)
            if key:
                names.append(key)
        completer = QCompleter(names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._on_completer_activated)
        self.search_edit.setCompleter(completer)

    def _get_item_key(self, item: Dict[str, Any]) -> str:
        if self.item_type == "artist":
            return item.get("artist_name", "")
        elif self.item_type == "album":
            return item.get("album", "")
        else:
            return item.get("genre", "")

    def _on_completer_activated(self, text: str):
        self.pinned_key = text.strip()
        self.btn_clear_pin.show()
        self._refresh_rows()

    def _on_search_text_changed(self, text: str):
        t = text.strip()
        if not t:
            self._clear_pin()
        else:
            # Check for exact match
            match = next((self._get_item_key(it) for it in self.all_items if self._get_item_key(it).lower() == t.lower()), None)
            if match:
                self.pinned_key = match
                self.btn_clear_pin.show()
                self._refresh_rows()

    def _clear_pin(self):
        self.pinned_key = None
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.btn_clear_pin.hide()
        self._refresh_rows()

    def _on_load_more_top(self):
        total = len(self.all_items)
        self.top_count = min(self.top_count + 10, total)
        self._refresh_rows()

    def _on_load_more_bottom(self):
        total = len(self.all_items)
        self.bottom_count = min(self.bottom_count + 10, total)
        self._refresh_rows()

    def _clear_layout(self, l: QVBoxLayout):
        while l.count():
            item = l.takeAt(0)
            w = item.widget()
            if w:
                # Hide immediately: deleteLater() is only processed when control
                # returns to the event loop, and a stale widget would otherwise
                # keep painting on top of the freshly created rows.
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _refresh_rows(self):
        self._clear_layout(self.top_container)
        self._clear_layout(self.bottom_container)
        self._clear_layout(self.pinned_layout)
        self.pinned_container.hide()

        total = len(self.all_items)
        if total == 0:
            self.btn_load_top.hide()
            self.btn_load_bottom.hide()
            empty_lbl = QLabel(f"No {self.item_type}s found in library.")
            empty_lbl.setStyleSheet("color: #8b949e; padding: 20px;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.top_container.addWidget(empty_lbl)
            return

        max_val = max((self._get_item_val(it) for it in self.all_items), default=1)
        total_val = sum((self._get_item_val(it) for it in self.all_items))

        # Check pinned item index
        pinned_idx = -1
        if self.pinned_key:
            target = self.pinned_key.strip().lower()
            for idx, it in enumerate(self.all_items):
                if self._get_item_key(it).strip().lower() == target:
                    pinned_idx = idx
                    break

        all_merged = (self.top_count + self.bottom_count >= total)

        if all_merged:
            # Show all items continuously in top container
            self.btn_load_top.hide()
            self.btn_load_bottom.hide()
            for rank, it in enumerate(self.all_items, start=1):
                is_pin = (rank - 1 == pinned_idx)
                row = StatBarRow(
                    item_data=it,
                    rank=rank,
                    val=self._get_item_val(it),
                    max_val=max_val,
                    total_val=total_val,
                    val_unit=self.val_unit,
                    item_type=self.item_type,
                    is_pinned=is_pin,
                    theme=self.theme,
                )
                row.clicked.connect(self.item_clicked.emit)
                self.top_container.addWidget(row)
        else:
            # Top slice: 0 to top_count
            top_slice = self.all_items[:self.top_count]
            for rank, it in enumerate(top_slice, start=1):
                is_pin = (rank - 1 == pinned_idx)
                row = StatBarRow(
                    item_data=it,
                    rank=rank,
                    val=self._get_item_val(it),
                    max_val=max_val,
                    total_val=total_val,
                    val_unit=self.val_unit,
                    item_type=self.item_type,
                    is_pinned=is_pin,
                    theme=self.theme,
                )
                row.clicked.connect(self.item_clicked.emit)
                self.top_container.addWidget(row)

            # Top button label
            top_rem = max(0, total - self.bottom_count - self.top_count)
            self.btn_load_top.setText(f"⬇ Load more (from top) — +10 (remaining: {top_rem})")
            self.btn_load_top.show()

            # Pinned item between top and bottom?
            if pinned_idx >= self.top_count and pinned_idx < (total - self.bottom_count):
                it = self.all_items[pinned_idx]
                pin_row = StatBarRow(
                    item_data=it,
                    rank=pinned_idx + 1,
                    val=self._get_item_val(it),
                    max_val=max_val,
                    total_val=total_val,
                    val_unit=self.val_unit,
                    item_type=self.item_type,
                    is_pinned=True,
                    theme=self.theme,
                )
                pin_row.clicked.connect(self.item_clicked.emit)
                self.pinned_layout.addWidget(pin_row)
                self.pinned_container.show()
            else:
                self.pinned_container.hide()

            # Bottom button label
            self.btn_load_bottom.setText(f"⬆ Load more (from bottom) — +10 (remaining: {top_rem})")
            self.btn_load_bottom.show()

            # Bottom slice: total - bottom_count to total
            bottom_start = total - self.bottom_count
            bottom_slice = self.all_items[bottom_start:]
            for i, it in enumerate(bottom_slice):
                rank = bottom_start + i + 1
                is_pin = (rank - 1 == pinned_idx)
                row = StatBarRow(
                    item_data=it,
                    rank=rank,
                    val=self._get_item_val(it),
                    max_val=max_val,
                    total_val=total_val,
                    val_unit=self.val_unit,
                    item_type=self.item_type,
                    is_pinned=is_pin,
                    theme=self.theme,
                )
                row.clicked.connect(self.item_clicked.emit)
                self.bottom_container.addWidget(row)

    def _get_item_val(self, item: Dict[str, Any]) -> int:
        if self.val_unit == "albums":
            return int(item.get("album_count", 0))
        return int(item.get("track_count", 0))

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")

        btn_bg = "rgba(0, 0, 0, 0.04)" if is_light else "rgba(255, 255, 255, 0.05)"
        btn_text = "#1f2328" if is_light else "#c9d1d9"
        hover_bg = "rgba(0, 0, 0, 0.07)" if is_light else "rgba(255, 255, 255, 0.09)"
        input_bg = "rgba(0, 0, 0, 0.035)" if is_light else "rgba(255, 255, 255, 0.05)"

        self.setStyleSheet(f"""
            QWidget#statRankView, QWidget#statRowsContainer {{
                background: transparent;
            }}
            QScrollArea#statScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#statScroll > QWidget > QWidget {{
                background: transparent;
            }}
        """)

        btn_style = f"""
            QPushButton {{
                background-color: {btn_bg};
                border: none;
                border-radius: 8px;
                color: {btn_text};
                padding: 6px 14px;
                font-weight: 500;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: #58a6ff;
            }}
        """
        self.btn_load_top.setStyleSheet(btn_style)
        self.btn_load_bottom.setStyleSheet(btn_style)

        self.btn_clear_pin.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn_bg};
                border: none;
                border-radius: 8px;
                color: #cf222e;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)

        self.search_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {input_bg};
                border: none;
                border-radius: 12px;
                padding: 6px 12px;
                color: {btn_text};
                font-size: 12px;
            }}
            QLineEdit:focus {{
                background-color: {hover_bg};
            }}
        """)

        # Recursively apply theme to rows
        for i in range(self.top_container.count()):
            w = self.top_container.itemAt(i).widget()
            if isinstance(w, StatBarRow):
                w.apply_theme(theme)
        for i in range(self.bottom_container.count()):
            w = self.bottom_container.itemAt(i).widget()
            if isinstance(w, StatBarRow):
                w.apply_theme(theme)
        for i in range(self.pinned_layout.count()):
            w = self.pinned_layout.itemAt(i).widget()
            if isinstance(w, StatBarRow):
                w.apply_theme(theme)
        self.update_scrollbars()

    def update_scrollbars(self):
        policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if getattr(config, "show_scrollbars", True) else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        if hasattr(self, "scroll"):
            self.scroll.setVerticalScrollBarPolicy(policy)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


class AlbumDecadeView(QWidget):
    """
    Sub-view displaying:
    - Interactive circular donut / pie chart of albums by decade (1900s ... 2020s).
    - Legend with color swatches, decade labels, album counts, and percentages.
    - Album list filtered by selected decade (or all albums), where each album is clickable.
    """
    album_clicked = pyqtSignal(dict)

    def __init__(self, db_conn, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.setObjectName("albumDecadeView")
        self.db_conn = db_conn
        self.theme = theme
        self.decades_data: List[Dict[str, Any]] = []
        self.total_albums = 0
        self.selected_decade: Optional[str] = None
        self._data_cache: Optional[Dict[str, Any]] = None

        self._build_ui()
        self.apply_theme(theme)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Upper row: Pie Chart (Left) + Legend (Right)
        top_frame = QFrame()
        top_frame.setObjectName("pieTopFrame")
        top_layout = QHBoxLayout(top_frame)
        top_layout.setContentsMargins(12, 10, 12, 10)
        top_layout.setSpacing(16)

        self.pie_chart = DecadePieChart([], 0, theme=self.theme)
        self.pie_chart.decade_clicked.connect(self._on_decade_selected)
        top_layout.addWidget(self.pie_chart, 1)

        # Legend container with scroll
        self.legend_scroll = QScrollArea()
        self.legend_scroll.setObjectName("statScroll")
        self.legend_scroll.setWidgetResizable(True)
        self.legend_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.legend_scroll.setFixedWidth(280)
        self.legend_scroll.setStyleSheet("QScrollArea#statScroll { background: transparent; border: none; }")
        self.legend_scroll.viewport().setAutoFillBackground(False)

        self.legend_container = QWidget()
        self.legend_container.setObjectName("statLegendContainer")
        self.legend_layout = QVBoxLayout(self.legend_container)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(4)
        self.legend_scroll.setWidget(self.legend_container)
        top_layout.addWidget(self.legend_scroll)

        layout.addWidget(top_frame, 0)

        # Bottom section: Filtered albums header & list
        header_row = QHBoxLayout()
        self.filter_lbl = QLabel("Albums in Library (All Decades):")
        self.filter_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header_row.addWidget(self.filter_lbl)

        self.btn_reset_filter = QPushButton("Show All")
        self.btn_reset_filter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_filter.clicked.connect(self._reset_filter)
        self.btn_reset_filter.hide()
        header_row.addWidget(self.btn_reset_filter)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Albums list scroll
        self.albums_scroll = QScrollArea()
        self.albums_scroll.setObjectName("statScroll")
        self.albums_scroll.setWidgetResizable(True)
        self.albums_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.albums_scroll.setStyleSheet("QScrollArea#statScroll { background: transparent; border: none; }")
        self.albums_scroll.viewport().setAutoFillBackground(False)
        self.update_scrollbars()

        self.albums_container = QWidget()
        self.albums_container.setObjectName("statAlbumsContainer")
        self.albums_layout = QVBoxLayout(self.albums_container)
        self.albums_layout.setContentsMargins(0, 0, 4, 0)
        self.albums_layout.setSpacing(6)
        self.albums_scroll.setWidget(self.albums_container)
        layout.addWidget(self.albums_scroll, 1)

    def reload_data(self, force: bool = False):
        if not force and self._data_cache is not None:
            res = self._data_cache
        else:
            res = get_album_decade_statistics(self.db_conn)
            self._data_cache = res
        self.total_albums = res.get("total_albums", 0)
        self.decades_data = res.get("decades", [])
        self.pie_chart.set_data(self.decades_data, self.total_albums)
        self._populate_legend()
        self._populate_albums()

    def invalidate_cache(self):
        self._data_cache = None

    def _on_decade_selected(self, decade: str):
        self.selected_decade = decade if decade else None
        if self.selected_decade:
            self.filter_lbl.setText(f"Albums from {self.selected_decade}:")
            self.btn_reset_filter.show()
        else:
            self.filter_lbl.setText("Albums in Library (All Decades):")
            self.btn_reset_filter.hide()
        self._populate_albums()

    def _reset_filter(self):
        self.selected_decade = None
        self.pie_chart.selected_decade = None
        self.filter_lbl.setText("Albums in Library (All Decades):")
        self.btn_reset_filter.hide()
        self.pie_chart.update()
        self._populate_albums()

    def _populate_legend(self):
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        is_light = (self.theme == "light")
        text_col = "#1f2328" if is_light else "#e6edf3"
        sub_col = "#656d76" if is_light else "#8b949e"

        title = QLabel("<b>Decades Breakdown</b>")
        title.setStyleSheet(f"color: {text_col}; font-size: 11px;")
        self.legend_layout.addWidget(title)

        for i, d in enumerate(self.decades_data):
            col_str = DECADE_COLORS.get(d["decade"], FALLBACK_PALETTE[i % len(FALLBACK_PALETTE)])
            row_frame = QFrame()
            row_frame.setCursor(Qt.CursorShape.PointingHandCursor)
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(4, 3, 4, 3)
            row_layout.setSpacing(8)

            # Swatch
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(f"background-color: {col_str}; border-radius: 3px;")
            row_layout.addWidget(swatch)

            # Name
            lbl_name = QLabel(d["decade"])
            lbl_name.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl_name.setStyleSheet(f"color: {text_col};")
            row_layout.addWidget(lbl_name)

            row_layout.addStretch()

            # Count & %
            lbl_info = QLabel(f"{d['album_count']} ({d['percentage']:.1f}%)")
            lbl_info.setFont(QFont("Segoe UI", 8))
            lbl_info.setStyleSheet(f"color: {sub_col};")
            row_layout.addWidget(lbl_info)

            # Connect click on row
            dec_val = d["decade"]
            row_frame.mousePressEvent = lambda e, dv=dec_val: self._on_legend_clicked(dv)
            self.legend_layout.addWidget(row_frame)

        self.legend_layout.addStretch()

    def _on_legend_clicked(self, decade: str):
        if self.selected_decade == decade:
            self._reset_filter()
        else:
            self.pie_chart.selected_decade = decade
            self.pie_chart.update()
            self._on_decade_selected(decade)

    def _populate_albums(self):
        while self.albums_layout.count():
            item = self.albums_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # Collect target albums
        if self.selected_decade:
            match = next((d for d in self.decades_data if d["decade"] == self.selected_decade), None)
            albums = match["albums"] if match else []
        else:
            albums = []
            for d in self.decades_data:
                albums.extend(d["albums"])

        if not albums:
            empty = QLabel("No albums found for this decade.")
            empty.setStyleSheet("color: #8b949e; padding: 12px;")
            self.albums_layout.addWidget(empty)
            return

        max_tr = max((a["track_count"] for a in albums), default=1)
        tot_tr = sum((a["track_count"] for a in albums))

        for rank, a in enumerate(albums, start=1):
            row = StatBarRow(
                item_data=a,
                rank=rank,
                val=a["track_count"],
                max_val=max_tr,
                total_val=tot_tr,
                val_unit="tracks",
                item_type="album",
                theme=self.theme,
            )
            row.clicked.connect(self.album_clicked.emit)
            self.albums_layout.addWidget(row)

        self.albums_layout.addStretch()

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")
        bg_col = "rgba(0, 0, 0, 0.018)" if is_light else "rgba(255, 255, 255, 0.025)"
        text_col = "#1f2328" if is_light else "#e6edf3"

        self.setStyleSheet(f"""
            QWidget#albumDecadeView, QWidget#statLegendContainer, QWidget#statAlbumsContainer {{
                background: transparent;
            }}
            QScrollArea#statScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#statScroll > QWidget > QWidget {{
                background: transparent;
            }}
        """)

        top_f = self.findChild(QFrame, "pieTopFrame")
        if top_f:
            top_f.setStyleSheet(f"""
                QFrame#pieTopFrame {{
                    background-color: {bg_col};
                    border: none;
                    border-radius: 12px;
                }}
            """)

        self.filter_lbl.setStyleSheet(f"color: {text_col}; font-size: 13px; font-weight: bold;")
        self.btn_reset_filter.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #58a6ff;
                font-weight: bold;
                border: none;
                padding: 2px 8px;
            }
            QPushButton:hover {
                text-decoration: underline;
            }
        """)

        self.pie_chart.apply_theme(theme)
        self._populate_legend()
        for i in range(self.albums_layout.count()):
            w = self.albums_layout.itemAt(i).widget()
            if isinstance(w, StatBarRow):
                w.apply_theme(theme)
        self.update_scrollbars()

    def update_scrollbars(self):
        policy = Qt.ScrollBarPolicy.ScrollBarAsNeeded if getattr(config, "show_scrollbars", True) else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        if hasattr(self, "legend_scroll"):
            self.legend_scroll.setVerticalScrollBarPolicy(policy)
            self.legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if hasattr(self, "albums_scroll"):
            self.albums_scroll.setVerticalScrollBarPolicy(policy)
            self.albums_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


class StatisticsView(QWidget):
    """
    Main Statistics container embedded into MainWindow stacked widget.
    Synchronizes with view switcher:
    - Artists: Ranked list (Most tracks / Most albums) with artist image.
    - Albums: Ranked list (Most tracks) OR Circular pie chart by decade.
    - Genres: Ranked list (Most tracks / Most albums).
    """
    artist_selected = pyqtSignal(str)
    album_selected = pyqtSignal(str, str)  # album_name, album_artist
    genre_selected = pyqtSignal(str)

    def __init__(self, db_conn, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.setObjectName("statisticsView")
        self.db_conn = db_conn
        self.theme = theme
        self.current_category = "artists"  # "artists", "albums", "genres"
        self.artist_mode = "tracks"        # "tracks", "albums"
        self.album_mode = "tracks"         # "tracks", "decades"
        self.genre_mode = "tracks"         # "tracks", "albums"
        self._items_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        self._build_ui()
        self.apply_theme(theme)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 6, 12, 10)
        main_layout.setSpacing(10)

        # Header controls row: Title & Sub-category switchers
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        self.title_lbl = QLabel("📊 Statistics")
        self.title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        header_row.addWidget(self.title_lbl)

        header_row.addStretch()

        # Sub-switcher container
        self.sub_switcher_frame = QFrame()
        self.sub_switcher_frame.setObjectName("subSwitcherFrame")
        self.sub_switcher_frame.setFixedHeight(30)
        sub_layout = QHBoxLayout(self.sub_switcher_frame)
        sub_layout.setContentsMargins(2, 2, 2, 2)
        sub_layout.setSpacing(0)

        self.btn_sub_1 = QPushButton("Most tracks")
        self.btn_sub_2 = QPushButton("Most albums")
        for b in (self.btn_sub_1, self.btn_sub_2):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            sub_layout.addWidget(b)

        self.btn_sub_1.clicked.connect(self._on_sub_1_clicked)
        self.btn_sub_2.clicked.connect(self._on_sub_2_clicked)
        header_row.addWidget(self.sub_switcher_frame)

        main_layout.addLayout(header_row)

        # Category Stack:
        # Index 0: Artists Rank View
        # Index 1: Albums Stack (Index 0 = Albums Rank View, Index 1 = Album Decade View)
        # Index 2: Genres Rank View
        self.cat_stack = QStackedWidget()

        # 0. Artists view
        self.artists_view = StatRankView(item_type="artist", val_unit="tracks", theme=self.theme)
        self.artists_view.item_clicked.connect(self._on_artist_clicked)
        self.cat_stack.addWidget(self.artists_view)

        # 1. Albums views
        self.albums_stack = QStackedWidget()
        self.albums_rank_view = StatRankView(item_type="album", val_unit="tracks", theme=self.theme)
        self.albums_rank_view.item_clicked.connect(self._on_album_clicked)
        self.albums_stack.addWidget(self.albums_rank_view)

        self.albums_decade_view = AlbumDecadeView(self.db_conn, theme=self.theme)
        self.albums_decade_view.album_clicked.connect(self._on_album_clicked)
        self.albums_stack.addWidget(self.albums_decade_view)

        self.cat_stack.addWidget(self.albums_stack)

        # 2. Genres view
        self.genres_view = StatRankView(item_type="genre", val_unit="tracks", theme=self.theme)
        self.genres_view.item_clicked.connect(self._on_genre_clicked)
        self.cat_stack.addWidget(self.genres_view)

        main_layout.addWidget(self.cat_stack, 1)

    def set_category(self, category: str):
        """Sets category to 'artists', 'albums', or 'genres'."""
        self.current_category = category
        if category == "artists":
            self.cat_stack.setCurrentIndex(0)
            self.title_lbl.setText("📊 Artists Statistics")
            self.btn_sub_1.setText("Most tracks")
            self.btn_sub_2.setText("Most albums")
            self.btn_sub_1.setVisible(True)
            self.btn_sub_2.setVisible(True)
            self._update_sub_buttons_style(self.artist_mode == "tracks")
            self._load_artists()
        elif category == "albums":
            self.cat_stack.setCurrentIndex(1)
            self.title_lbl.setText("📊 Albums Statistics")
            self.btn_sub_1.setText("Most tracks")
            self.btn_sub_2.setText("Albums by decade")
            self.btn_sub_1.setVisible(True)
            self.btn_sub_2.setVisible(True)
            self._update_sub_buttons_style(self.album_mode == "tracks")
            if self.album_mode == "tracks":
                self.albums_stack.setCurrentIndex(0)
                self._load_albums()
            else:
                self.albums_stack.setCurrentIndex(1)
                self.albums_decade_view.reload_data()
        elif category == "genres":
            self.cat_stack.setCurrentIndex(2)
            self.title_lbl.setText("📊 Genres Statistics")
            self.btn_sub_1.setText("Most tracks")
            self.btn_sub_2.setText("Most albums")
            self.btn_sub_1.setVisible(True)
            self.btn_sub_2.setVisible(True)
            self._update_sub_buttons_style(self.genre_mode == "tracks")
            self._load_genres()

    def refresh_current(self):
        self.invalidate_cache()
        self.set_category(self.current_category)

    def invalidate_cache(self):
        self._items_cache.clear()
        if hasattr(self, "albums_decade_view"):
            self.albums_decade_view.invalidate_cache()

    def _on_sub_1_clicked(self):
        if self.current_category == "artists":
            self.artist_mode = "tracks"
            self._update_sub_buttons_style(True)
            self._load_artists()
        elif self.current_category == "albums":
            self.album_mode = "tracks"
            self.albums_stack.setCurrentIndex(0)
            self._update_sub_buttons_style(True)
            self._load_albums()
        elif self.current_category == "genres":
            self.genre_mode = "tracks"
            self._update_sub_buttons_style(True)
            self._load_genres()

    def _on_sub_2_clicked(self):
        if self.current_category == "artists":
            self.artist_mode = "albums"
            self._update_sub_buttons_style(False)
            self._load_artists()
        elif self.current_category == "albums":
            self.album_mode = "decades"
            self.albums_stack.setCurrentIndex(1)
            self._update_sub_buttons_style(False)
            self.albums_decade_view.reload_data()
        elif self.current_category == "genres":
            self.genre_mode = "albums"
            self._update_sub_buttons_style(False)
            self._load_genres()

    def _load_artists(self):
        cache_key = ("artists", self.artist_mode)
        items = self._items_cache.get(cache_key)
        if items is None:
            items = get_artist_statistics(self.db_conn, sort_by=self.artist_mode)
            self._items_cache[cache_key] = items
        self.artists_view.set_items(items, val_unit=self.artist_mode)

    def _load_albums(self):
        cache_key = ("albums", "tracks")
        items = self._items_cache.get(cache_key)
        if items is None:
            items = get_album_statistics(self.db_conn, sort_by="tracks")
            self._items_cache[cache_key] = items
        self.albums_rank_view.set_items(items, val_unit="tracks")

    def _load_genres(self):
        cache_key = ("genres", self.genre_mode)
        items = self._items_cache.get(cache_key)
        if items is None:
            items = get_genre_statistics(self.db_conn, sort_by=self.genre_mode)
            self._items_cache[cache_key] = items
        self.genres_view.set_items(items, val_unit=self.genre_mode)

    def _on_artist_clicked(self, item_data: dict):
        name = item_data.get("artist_name") or item_data.get("raw_artist_name", "")
        if name:
            self.artist_selected.emit(name)

    def _on_album_clicked(self, item_data: dict):
        alb = item_data.get("album") or item_data.get("raw_album", "")
        art = item_data.get("album_artist") or item_data.get("raw_album_artist", "")
        if alb:
            self.album_selected.emit(alb, art)

    def _on_genre_clicked(self, item_data: dict):
        gen = item_data.get("genre") or item_data.get("raw_genre", "")
        if gen:
            self.genre_selected.emit(gen)

    def _update_sub_buttons_style(self, first_active: bool):
        is_light = (self.theme == "light")
        active_bg = "#ffffff" if is_light else "#21262d"
        active_text = "#1f2328" if is_light else "#ffffff"
        inactive_text = "#656d76" if is_light else "#8b949e"

        btn1_bg = active_bg if first_active else "transparent"
        btn1_text = active_text if first_active else inactive_text
        btn1_weight = "bold" if first_active else "normal"

        btn2_bg = active_bg if not first_active else "transparent"
        btn2_text = active_text if not first_active else inactive_text
        btn2_weight = "bold" if not first_active else "normal"

        self.btn_sub_1.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn1_bg};
                color: {btn1_text};
                border: none;
                border-radius: 5px;
                padding: 4px 12px;
                font-weight: {btn1_weight};
                font-size: 11px;
            }}
        """)
        self.btn_sub_2.setStyleSheet(f"""
            QPushButton {{
                background-color: {btn2_bg};
                color: {btn2_text};
                border: none;
                border-radius: 5px;
                padding: 4px 12px;
                font-weight: {btn2_weight};
                font-size: 11px;
            }}
        """)

    def apply_theme(self, theme: str):
        self.theme = theme
        is_light = (theme == "light")

        text_col = "#1f2328" if is_light else "#e6edf3"
        switcher_bg = "rgba(0, 0, 0, 0.05)" if is_light else "rgba(255, 255, 255, 0.05)"

        self.setStyleSheet(f"""
            QWidget#statisticsView {{
                background: transparent;
            }}
        """)
        self.title_lbl.setStyleSheet(f"color: {text_col};")
        self.sub_switcher_frame.setStyleSheet(f"""
            QFrame#subSwitcherFrame {{
                background-color: {switcher_bg};
                border: none;
                border-radius: 8px;
            }}
        """)

        active_sub1 = (
            (self.current_category == "artists" and self.artist_mode == "tracks") or
            (self.current_category == "albums" and self.album_mode == "tracks") or
            (self.current_category == "genres" and self.genre_mode == "tracks")
        )
        self._update_sub_buttons_style(active_sub1)

        self.artists_view.apply_theme(theme)
        self.albums_rank_view.apply_theme(theme)
        self.albums_decade_view.apply_theme(theme)
        self.genres_view.apply_theme(theme)
        self.update_scrollbars()

    def update_scrollbars(self):
        for view in (self.artists_view, self.albums_rank_view, self.albums_decade_view, self.genres_view):
            if hasattr(view, "update_scrollbars"):
                view.update_scrollbars()
