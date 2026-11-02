"""
Player Sidebar widget for Malka.
Provides persistent playback controls on the right side of the window:
- Album artwork
- Track title, artist, album, and year
- Interactive seek bar with position / duration timestamps
- Play/Pause, Previous, Next, Stop buttons
- Volume slider
Closes when the Stop button is clicked.
"""
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from malka.config import NO_DATA, config
from malka.player import PlayerController, format_time_ms
from malka.ui.image_utils import (
    create_square_placeholder,
    get_cached_square_pixmap,
    get_resource_icon,
    request_async_square_pixmap,
)


class ClickableSlider(QSlider):
    """QSlider that jumps directly to the clicked position and emits seek events."""

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,
                opt,
                QStyle.SubControl.SC_SliderGroove,
                self,
            )
            handle = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,
                opt,
                QStyle.SubControl.SC_SliderHandle,
                self,
            )

            if self.orientation() == Qt.Orientation.Horizontal:
                slider_len = groove.width() - handle.width()
                slider_min = groove.x() + handle.width() // 2
                pos = event.pos().x() - slider_min
            else:
                slider_len = groove.height() - handle.height()
                slider_min = groove.y() + handle.height() // 2
                pos = groove.height() - (event.pos().y() - slider_min)

            if slider_len > 0:
                fraction = max(0.0, min(1.0, pos / slider_len))
                val = int(self.minimum() + fraction * (self.maximum() - self.minimum()))
                self.setValue(val)
                self.sliderMoved.emit(val)
        super().mousePressEvent(event)


class ClickableLabel(QLabel):
    """Clickable QLabel with pointing hand cursor and click signal."""
    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PlayerSidebar(QFrame):
    """
    Persistent right sidebar showing current playback details and controls.
    """

    artist_clicked = pyqtSignal(str)
    album_clicked = pyqtSignal(dict, str, str)

    def __init__(self, controller: PlayerController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setFixedWidth(290)
        self.setObjectName("playerSidebar")
        self.theme = getattr(config, "theme", "dark")

        self._user_dragging = False
        self._current_duration_ms = 0
        self._current_cover_path = ""
        self._current_track: Dict[str, Any] = {}
        self._current_album_data: Dict[str, Any] = {}
        self._current_artist_name: str = ""
        self._current_album_name: str = ""
        self._current_album_artist: str = ""

        self._init_ui()
        self.apply_theme(self.theme)

        # Connect controller signals
        self.controller.track_started.connect(self._on_track_started)
        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.position_changed.connect(self._on_position_changed)
        self.controller.playback_stopped.connect(self._on_playback_stopped)
        self.controller.audio_device_changed.connect(self._on_audio_device_changed)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 20)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header Title
        header_layout = QHBoxLayout()
        self.header_lbl = QLabel("NOW PLAYING")
        self.header_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.header_lbl.setStyleSheet("color: #8b949e; letter-spacing: 1px;")
        header_layout.addWidget(self.header_lbl)
        header_layout.addStretch()

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("sidebarCloseBtn")
        self.btn_close.setToolTip("Stop & Close Player")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self._on_stop_clicked)
        header_layout.addWidget(self.btn_close)
        layout.addLayout(header_layout)

        # Large Album Artwork
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(254, 254)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_placeholder_cover()
        layout.addWidget(self.cover_label, 0, Qt.AlignmentFlag.AlignCenter)

        # Track Information Section
        info_container = QVBoxLayout()
        info_container.setSpacing(3)
        info_container.setContentsMargins(0, 4, 0, 0)

        # Title (prominent & bold)
        self.title_label = QLabel("No track playing")
        self.title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #ffffff;")
        self.title_label.setWordWrap(True)
        info_container.addWidget(self.title_label)

        # Artist (clickable link to artist)
        self.artist_label = ClickableLabel("—")
        self.artist_label.setObjectName("sidebarArtist")
        self.artist_label.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.artist_label.setStyleSheet("""
            QLabel#sidebarArtist {
                color: #58a6ff;
            }
            QLabel#sidebarArtist:hover {
                color: #79c0ff;
                text-decoration: underline;
            }
        """)
        self.artist_label.setWordWrap(True)
        self.artist_label.setToolTip("Go to artist")
        self.artist_label.clicked.connect(self._on_artist_label_clicked)
        info_container.addWidget(self.artist_label)

        # Album & Year (clickable link to album)
        self.album_label = ClickableLabel("—")
        self.album_label.setObjectName("sidebarAlbum")
        self.album_label.setFont(QFont("Segoe UI", 8))
        self.album_label.setStyleSheet("""
            QLabel#sidebarAlbum {
                color: #8b949e;
            }
            QLabel#sidebarAlbum:hover {
                color: #c9d1d9;
                text-decoration: underline;
            }
        """)
        self.album_label.setWordWrap(True)
        self.album_label.setToolTip("Go to album")
        self.album_label.clicked.connect(self._on_album_label_clicked)
        info_container.addWidget(self.album_label)

        layout.addLayout(info_container)

        # Seek Bar & Timestamps
        seek_container = QVBoxLayout()
        seek_container.setSpacing(4)
        seek_container.setContentsMargins(0, 6, 0, 0)

        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderReleased.connect(self._on_slider_released)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
        seek_container.addWidget(self.seek_slider)

        time_layout = QHBoxLayout()
        self.time_current_label = QLabel("00:00")
        self.time_current_label.setFont(QFont("Segoe UI", 8))
        self.time_current_label.setStyleSheet("color: #8b949e;")
        time_layout.addWidget(self.time_current_label)

        time_layout.addStretch()

        self.time_total_label = QLabel("00:00")
        self.time_total_label.setFont(QFont("Segoe UI", 8))
        self.time_total_label.setStyleSheet("color: #8b949e;")
        time_layout.addWidget(self.time_total_label)
        seek_container.addLayout(time_layout)

        layout.addLayout(seek_container)

        # Playback Controls (Prev, Play/Pause, Next, Stop)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_prev = QPushButton()
        self.btn_prev.setProperty("class", "controlBtn")
        self.btn_prev.setIcon(get_resource_icon("prev.png"))
        self.btn_prev.setIconSize(QSize(20, 20))
        self.btn_prev.setToolTip("Previous track")
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.clicked.connect(self.controller.prev_track)
        controls_layout.addWidget(self.btn_prev)

        self.btn_play_pause = QPushButton()
        self.btn_play_pause.setProperty("class", "controlBtn")
        self.btn_play_pause.setIcon(get_resource_icon("play.png"))
        self.btn_play_pause.setIconSize(QSize(20, 20))
        self.btn_play_pause.setToolTip("Play / Pause")
        self.btn_play_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_pause.clicked.connect(self.controller.toggle_play_pause)
        controls_layout.addWidget(self.btn_play_pause)

        self.btn_next = QPushButton()
        self.btn_next.setProperty("class", "controlBtn")
        self.btn_next.setIcon(get_resource_icon("next.png"))
        self.btn_next.setIconSize(QSize(20, 20))
        self.btn_next.setToolTip("Next track")
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.clicked.connect(self.controller.next_track)
        controls_layout.addWidget(self.btn_next)

        self.btn_stop = QPushButton()
        self.btn_stop.setProperty("class", "controlBtn")
        self.btn_stop.setIcon(get_resource_icon("stop.png"))
        self.btn_stop.setIconSize(QSize(18, 18))
        self.btn_stop.setToolTip("Stop & Close")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        controls_layout.addWidget(self.btn_stop)

        layout.addLayout(controls_layout)

        # Volume Bar
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(8)
        volume_layout.setContentsMargins(6, 6, 6, 0)

        self.vol_icon = QLabel("🔊")
        self.vol_icon.setStyleSheet("color: #8b949e; font-size: 13px;")
        volume_layout.addWidget(self.vol_icon)

        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.controller.get_volume())
        self.volume_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volume_slider.valueChanged.connect(self.controller.set_volume)
        volume_layout.addWidget(self.volume_slider)

        layout.addLayout(volume_layout)

        # Audio Output Device Selector
        device_layout = QHBoxLayout()
        device_layout.setSpacing(8)
        device_layout.setContentsMargins(6, 4, 6, 0)

        self.dev_icon = QLabel("🎧")
        self.dev_icon.setStyleSheet("color: #8b949e; font-size: 13px;")
        device_layout.addWidget(self.dev_icon)

        self.device_combo = QComboBox()
        self.device_combo.setToolTip("Select Audio Output Device")
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._populate_audio_devices()
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        device_layout.addWidget(self.device_combo)

        layout.addLayout(device_layout)
        layout.addStretch()

    def _set_placeholder_cover(self):
        pix = create_square_placeholder(size=254, text_or_icon="🎵", radius_top=8, bg_color="#21262d", fg_color="#6e7681")
        self.cover_label.setPixmap(pix)

    def _on_track_started(self, track: Dict[str, Any], album_data: Dict[str, Any]):
        title = track.get("title", "Unknown Track")
        artist = track.get("artist") or album_data.get("display_artist") or album_data.get("album_artist", "Unknown Artist")
        album = album_data.get("album", track.get("album", "Unknown Album"))
        year = album_data.get("year") or track.get("year", "")
        year_str = f" ({year})" if year and year != NO_DATA else ""

        self._current_track = track
        self._current_album_data = album_data
        self._current_artist_name = artist
        self._current_album_name = album
        self._current_album_artist = album_data.get("album_artist") or track.get("album_artist", "")

        self.title_label.setText(title)
        self.title_label.setToolTip(title)

        self.artist_label.setText(artist)
        self.artist_label.setToolTip(f"View artist: {artist}")

        self.album_label.setText(f"{album}{year_str}")
        self.album_label.setToolTip(f"View album: {album}")

        self.btn_play_pause.setIcon(get_resource_icon("pause.png"))

        # Cover image (non-blocking)
        cover_path = album_data.get("cover_path") or track.get("cover_cache_path", "")
        self._current_cover_path = cover_path
        if cover_path:
            cached = get_cached_square_pixmap(cover_path, size=254, radius_top=8)
            if cached:
                self.cover_label.setPixmap(cached)
            else:
                self._set_placeholder_cover()
                request_async_square_pixmap(cover_path, size=254, radius_top=8, callback=self._on_cover_loaded)
        else:
            self._set_placeholder_cover()

    def _on_artist_label_clicked(self):
        if self._current_artist_name and self._current_artist_name not in ("—", NO_DATA, "Unknown Artist"):
            self.artist_clicked.emit(self._current_artist_name)

    def _on_album_label_clicked(self):
        if self._current_album_name and self._current_album_name not in ("—", NO_DATA, "Unknown Album"):
            self.album_clicked.emit(self._current_album_data, self._current_album_name, self._current_album_artist)

    def _on_cover_loaded(self, path: str, pixmap: QPixmap):
        if self._current_cover_path and Path(self._current_cover_path).resolve() == Path(path).resolve():
            if not pixmap.isNull():
                self.cover_label.setPixmap(pixmap)

    def apply_theme(self, theme: str):
        self.theme = theme
        if theme == "light":
            self.setStyleSheet("""
                QFrame#playerSidebar {
                    background-color: #ffffff;
                    border: 1px solid #d0d7de;
                    border-radius: 14px;
                }
                QLabel {
                    background: transparent;
                }
                QSlider::groove:horizontal {
                    height: 4px;
                    background: #d0d7de;
                    border-radius: 2px;
                }
                QSlider::sub-page:horizontal {
                    background: #0969da;
                    border-radius: 2px;
                }
                QSlider::handle:horizontal {
                    background: #1f2328;
                    width: 12px;
                    height: 12px;
                    margin: -4px 0;
                    border-radius: 6px;
                }
                QSlider::handle:horizontal:hover {
                    background: #0969da;
                }
                QPushButton.controlBtn {
                    background-color: transparent;
                    border: none;
                    color: #24292f;
                    border-radius: 19px;
                    min-width: 38px;
                    max-width: 38px;
                    min-height: 38px;
                    max-height: 38px;
                }
                QPushButton.controlBtn:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                    border: none;
                    color: #0969da;
                }
                QPushButton.controlBtn:pressed {
                    background-color: rgba(0, 0, 0, 0.12);
                    border: none;
                }
                QPushButton#sidebarCloseBtn {
                    background-color: transparent;
                    border: none;
                    color: #656d76;
                    border-radius: 14px;
                    min-width: 28px;
                    max-width: 28px;
                    min-height: 28px;
                    max-height: 28px;
                    font-size: 11px;
                }
                QPushButton#sidebarCloseBtn:hover {
                    background-color: rgba(0, 0, 0, 0.06);
                    border: none;
                    color: #24292f;
                }
                QPushButton#sidebarCloseBtn:pressed {
                    background-color: rgba(0, 0, 0, 0.12);
                    border: none;
                }
                QComboBox {
                    background-color: #f6f8fa;
                    border: 1px solid #d0d7de;
                    border-radius: 6px;
                    color: #1f2328;
                    padding: 4px 8px;
                    font-size: 8pt;
                }
                QComboBox:hover {
                    background-color: #eaeef2;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 16px;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    border: 1px solid #d0d7de;
                    color: #1f2328;
                    selection-background-color: #f6f8fa;
                    selection-color: #0969da;
                }
            """)
            if hasattr(self, "header_lbl"):
                self.header_lbl.setStyleSheet("color: #656d76; letter-spacing: 1px;")
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #1f2328;")
            if hasattr(self, "artist_label"):
                self.artist_label.setStyleSheet("""
                    QLabel#sidebarArtist { color: #0969da; }
                    QLabel#sidebarArtist:hover { color: #0550ae; text-decoration: underline; }
                """)
            if hasattr(self, "album_label"):
                self.album_label.setStyleSheet("""
                    QLabel#sidebarAlbum { color: #656d76; }
                    QLabel#sidebarAlbum:hover { color: #1f2328; text-decoration: underline; }
                """)
            if hasattr(self, "time_current_label"):
                self.time_current_label.setStyleSheet("color: #656d76;")
            if hasattr(self, "time_total_label"):
                self.time_total_label.setStyleSheet("color: #656d76;")
            if hasattr(self, "vol_icon"):
                self.vol_icon.setStyleSheet("color: #656d76; font-size: 13px;")
            if hasattr(self, "dev_icon"):
                self.dev_icon.setStyleSheet("color: #656d76; font-size: 13px;")
        else:
            self.setStyleSheet("""
                QFrame#playerSidebar {
                    background-color: #161b22;
                    border: none;
                    border-radius: 14px;
                }
                QLabel {
                    background: transparent;
                }
                QSlider::groove:horizontal {
                    height: 4px;
                    background: #30363d;
                    border-radius: 2px;
                }
                QSlider::sub-page:horizontal {
                    background: #58a6ff;
                    border-radius: 2px;
                }
                QSlider::handle:horizontal {
                    background: #ffffff;
                    width: 12px;
                    height: 12px;
                    margin: -4px 0;
                    border-radius: 6px;
                }
                QSlider::handle:horizontal:hover {
                    background: #79c0ff;
                }
                QPushButton.controlBtn {
                    background-color: transparent;
                    border: none;
                    color: #c9d1d9;
                    border-radius: 19px;
                    min-width: 38px;
                    max-width: 38px;
                    min-height: 38px;
                    max-height: 38px;
                }
                QPushButton.controlBtn:hover {
                    background-color: rgba(255, 255, 255, 0.12);
                    border: none;
                    color: #ffffff;
                }
                QPushButton.controlBtn:pressed {
                    background-color: rgba(255, 255, 255, 0.22);
                    border: none;
                }
                QPushButton#sidebarCloseBtn {
                    background-color: transparent;
                    border: none;
                    color: #8b949e;
                    border-radius: 14px;
                    min-width: 28px;
                    max-width: 28px;
                    min-height: 28px;
                    max-height: 28px;
                    font-size: 11px;
                }
                QPushButton#sidebarCloseBtn:hover {
                    background-color: rgba(255, 255, 255, 0.12);
                    border: none;
                    color: #ffffff;
                }
                QPushButton#sidebarCloseBtn:pressed {
                    background-color: rgba(255, 255, 255, 0.22);
                    border: none;
                }
                QComboBox {
                    background-color: rgba(255, 255, 255, 0.04);
                    border: none;
                    border-radius: 6px;
                    color: #c9d1d9;
                    padding: 4px 8px;
                    font-size: 8pt;
                }
                QComboBox:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: none;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 16px;
                }
                QComboBox QAbstractItemView {
                    background-color: #161b22;
                    border: none;
                    color: #c9d1d9;
                    selection-background-color: #30363d;
                    selection-color: #ffffff;
                }
            """)
            if hasattr(self, "header_lbl"):
                self.header_lbl.setStyleSheet("color: #8b949e; letter-spacing: 1px;")
            if hasattr(self, "title_label"):
                self.title_label.setStyleSheet("color: #ffffff;")
            if hasattr(self, "artist_label"):
                self.artist_label.setStyleSheet("""
                    QLabel#sidebarArtist { color: #58a6ff; }
                    QLabel#sidebarArtist:hover { color: #79c0ff; text-decoration: underline; }
                """)
            if hasattr(self, "album_label"):
                self.album_label.setStyleSheet("""
                    QLabel#sidebarAlbum { color: #8b949e; }
                    QLabel#sidebarAlbum:hover { color: #c9d1d9; text-decoration: underline; }
                """)
            if hasattr(self, "time_current_label"):
                self.time_current_label.setStyleSheet("color: #8b949e;")
            if hasattr(self, "time_total_label"):
                self.time_total_label.setStyleSheet("color: #8b949e;")
            if hasattr(self, "vol_icon"):
                self.vol_icon.setStyleSheet("color: #8b949e; font-size: 13px;")
            if hasattr(self, "dev_icon"):
                self.dev_icon.setStyleSheet("color: #8b949e; font-size: 13px;")

        # Update icons
        if hasattr(self, "btn_prev"):
            self.btn_prev.setIcon(get_resource_icon("prev.png", theme=theme))
            is_playing = self.controller.is_playing()
            self.btn_play_pause.setIcon(get_resource_icon("pause.png" if is_playing else "play.png", theme=theme))
            self.btn_next.setIcon(get_resource_icon("next.png", theme=theme))
            self.btn_stop.setIcon(get_resource_icon("stop.png", theme=theme))

    def _on_state_changed(self, is_playing: bool):
        self.btn_play_pause.setIcon(get_resource_icon("pause.png" if is_playing else "play.png", theme=self.theme))

    def _on_position_changed(self, pos_ms: int, dur_ms: int):
        self._current_duration_ms = dur_ms
        self.time_current_label.setText(format_time_ms(pos_ms))
        self.time_total_label.setText(format_time_ms(dur_ms))

        if not self._user_dragging and dur_ms > 0:
            fraction = pos_ms / dur_ms
            slider_val = int(fraction * 1000)
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(slider_val)
            self.seek_slider.blockSignals(False)

    def _on_slider_pressed(self):
        self._user_dragging = True

    def _on_slider_released(self):
        self._user_dragging = False
        if self._current_duration_ms > 0:
            target_ms = int((self.seek_slider.value() / 1000.0) * self._current_duration_ms)
            self.controller.seek(target_ms)

    def _on_slider_moved(self, value: int):
        if self._current_duration_ms > 0:
            target_ms = int((value / 1000.0) * self._current_duration_ms)
            self.time_current_label.setText(format_time_ms(target_ms))

    def _on_stop_clicked(self):
        self.controller.stop()
        self.hide()

    def _on_playback_stopped(self):
        self.btn_play_pause.setIcon(get_resource_icon("play.png", theme=self.theme))
        self.seek_slider.setValue(0)
        self.time_current_label.setText("00:00")
        self.time_total_label.setText("00:00")

    def _populate_audio_devices(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        devices = self.controller.get_audio_devices()
        current_dev = self.controller.get_current_audio_device()
        curr_id = bytes(current_dev.id()).decode("latin1", errors="replace") if (current_dev and not current_dev.isNull()) else ""

        selected_idx = 0
        for i, d in enumerate(devices):
            d_id = bytes(d.id()).decode("latin1", errors="replace")
            name = d.description()
            if d.isDefault():
                name += " (Default)"
            self.device_combo.addItem(name, d)
            if curr_id and d_id == curr_id:
                selected_idx = i

        if self.device_combo.count() > 0:
            self.device_combo.setCurrentIndex(selected_idx)
        self.device_combo.blockSignals(False)

    def _on_device_selected(self, index: int):
        if index >= 0:
            dev = self.device_combo.itemData(index)
            if dev:
                self.controller.set_audio_device(dev)

    def _on_audio_device_changed(self, device):
        self._populate_audio_devices()
