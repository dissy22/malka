"""
Audio playback controller for Malka.

Sequential playback is handled by the gapless PCM engine (FFmpeg -> QAudioSink):
all album tracks are decoded into one continuous stream, so consecutive tracks
have no silence between them.  The controller keeps the public API and signals
used by the sidebar, album view and main window.
"""
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PyQt6.QtCore import QCoreApplication, QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtMultimedia import QAudioDevice, QMediaDevices

import malka.config as config_module
from malka.config import config
from malka.formats import PLAYABLE_EXTS
from malka.pcm_engine import PcmAudioService


def format_time_ms(ms: int) -> str:
    """Formats milliseconds into MM:SS format."""
    if ms <= 0:
        return "00:00"
    total_seconds = int(ms / 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def _norm_path(file_path: str) -> str:
    if not file_path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(str(file_path)))
    except Exception:
        return os.path.normcase(str(file_path))


def is_file_playable(file_path: str) -> Tuple[bool, str]:
    """
    Validates playback rules:
    - File exists
    - Format is one of the library formats (.mp3, .m4a[+ALAC], .flac)
    - File resides inside one of the configured library folders
    """
    if not file_path:
        return False, "No file path provided"

    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return False, f"File does not exist: {p.name}"

    ext = p.suffix.lower()
    if ext not in PLAYABLE_EXTS:
        return False, f"Unsupported format: {ext} (only {', '.join(sorted(PLAYABLE_EXTS))} can be played)"

    if getattr(config, "library_paths", []):
        try:
            if not config.is_path_in_library(file_path):
                return False, "File is outside the music library folder"
        except Exception:
            pass

    return True, ""


class PlayerController(QObject):
    """Playlist/queue control on top of the gapless PcmAudioEngine."""

    track_started = pyqtSignal(dict, dict)  # (track_dict, album_dict)
    state_changed = pyqtSignal(bool)  # True = playing, False = paused/stopped
    position_changed = pyqtSignal(int, int)  # (position_ms, duration_ms)
    playback_stopped = pyqtSignal()
    audio_device_changed = pyqtSignal(object)  # QAudioDevice
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.playlist: List[Dict[str, Any]] = []
        self.current_album: Dict[str, Any] = {}
        self.current_index: int = -1
        self.current_track: Optional[Dict[str, Any]] = None
        self._operation_suspended = False

        self.engine = PcmAudioService()
        self.engine.track_index_changed.connect(self._on_engine_track_changed)
        self.engine.position_changed.connect(self._on_engine_position)
        self.engine.finished.connect(self._on_engine_finished)
        self.engine.error.connect(self._on_engine_error)

        # Persist volume lazily while the slider is being dragged.
        self._volume_save_timer = QTimer(self)
        self._volume_save_timer.setSingleShot(True)
        self._volume_save_timer.setInterval(400)
        self._volume_save_timer.timeout.connect(self._save_volume)
        self._volume_save_target: Optional[object] = None

        self._init_audio_device()

        try:
            saved_volume = int(getattr(config, "volume", 100))
        except Exception:
            saved_volume = 100
        self.set_volume(saved_volume, persist=False)

        # Publish the restored position immediately after a restore/seek.
        self.position_changed.emit(0, 0)

    # ------------------------------------------------------------------
    # Output device / volume
    # ------------------------------------------------------------------
    def _init_audio_device(self):
        devices = QMediaDevices.audioOutputs()
        target_dev = None
        if config.audio_device_id:
            for d in devices:
                dev_id = bytes(d.id()).decode("latin1", errors="replace")
                if dev_id == config.audio_device_id:
                    target_dev = d
                    break
        if not target_dev:
            target_dev = QMediaDevices.defaultAudioOutput()
        if target_dev and not target_dev.isNull():
            self.engine.set_audio_device(target_dev)

    def get_audio_devices(self) -> List[QAudioDevice]:
        return QMediaDevices.audioOutputs()

    def get_current_audio_device(self) -> QAudioDevice:
        return self.engine.current_audio_device()

    def set_audio_device(self, device: QAudioDevice):
        if device and not device.isNull():
            was_playing = self.is_playing()
            position = self.engine.position_ms()
            self.engine.set_audio_device(device)
            config.audio_device_id = bytes(device.id()).decode("latin1", errors="replace")
            config.save()
            if self.current_track is not None:
                self._begin_session(self.current_index, position, play=was_playing)
            self.audio_device_changed.emit(device)

    def _save_volume(self):
        try:
            current_target = getattr(config_module, "CONFIG_FILE", None)
            if self._volume_save_target is not None and current_target != self._volume_save_target:
                return
            config.volume = self.get_volume()
            if hasattr(config, "save_volume"):
                config.save_volume()
            else:
                config.save()
        except Exception:
            pass

    def set_volume(self, volume_percent: int, persist: bool = True):
        """volume_percent between 0 and 100."""
        try:
            clamped = max(0, min(100, int(volume_percent)))
        except Exception:
            clamped = 0
        self.engine.set_volume(clamped / 100.0)
        try:
            config.volume = clamped
        except Exception:
            pass
        if persist:
            self._volume_save_target = getattr(config_module, "CONFIG_FILE", None)
            self._volume_save_timer.start()

    def get_volume(self) -> int:
        try:
            return int(round(self.engine.volume() * 100))
        except Exception:
            return int(getattr(config, "volume", 100))

    def is_playing(self) -> bool:
        return self.engine.is_playing()

    def is_active(self) -> bool:
        return self.current_track is not None

    # ------------------------------------------------------------------
    # Playlist control
    # ------------------------------------------------------------------
    def play_album(self, album_data: Dict[str, Any], tracks: List[Dict[str, Any]], start_index: int = 0) -> bool:
        playable_tracks = []
        for t in tracks:
            ok, _ = is_file_playable(t.get("file_path", ""))
            if ok:
                playable_tracks.append(t)

        if not playable_tracks:
            self.error_occurred.emit("No playable .mp3, .m4a or .flac tracks found in this album.")
            return False

        self.playlist = playable_tracks
        self.current_album = album_data
        target_idx = max(0, min(start_index, len(self.playlist) - 1))
        return self.play_index(target_idx)

    def play_track(self, track: Dict[str, Any], album_data: Dict[str, Any], tracks: Optional[List[Dict[str, Any]]] = None) -> bool:
        fp = track.get("file_path", "")
        ok, msg = is_file_playable(fp)
        if not ok:
            self.error_occurred.emit(msg)
            return False

        if tracks:
            playable_tracks = [t for t in tracks if is_file_playable(t.get("file_path", ""))[0]]
            self.playlist = playable_tracks if playable_tracks else [track]
            self.current_album = album_data
            try:
                target_idx = next(
                    i for i, t in enumerate(self.playlist)
                    if _norm_path(t.get("file_path", "")) == _norm_path(fp)
                )
            except StopIteration:
                target_idx = 0
            return self.play_index(target_idx)
        self.playlist = [track]
        self.current_album = album_data
        return self.play_index(0)

    def play_index(self, index: int) -> bool:
        if index < 0 or index >= len(self.playlist):
            self.stop()
            return False

        self.current_index = index
        self.current_track = self.playlist[index]
        file_path = self.current_track.get("file_path", "")
        ok, msg = is_file_playable(file_path)
        if not ok:
            self.error_occurred.emit(msg)
            if self.current_index + 1 < len(self.playlist):
                return self.play_index(self.current_index + 1)
            self.stop()
            return False

        self._operation_suspended = False
        self._begin_session(index, 0, play=True)
        self.track_started.emit(self.current_track, self.current_album)
        self.state_changed.emit(True)
        self.position_changed.emit(0, self._duration_ms())
        return True

    def toggle_play_pause(self):
        if self.is_playing():
            self.pause()
        elif self.current_track:
            self.play()
        elif self.playlist:
            self.play_index(0)

    def play(self):
        if not self.current_track:
            return
        if self.engine.is_started() or self.engine.buffered_ms() > 0:
            self.engine.play()
        else:
            self._begin_session(self.current_index, self.engine.position_ms(), play=True)
        self.state_changed.emit(True)

    def pause(self):
        self.engine.pause()
        self.state_changed.emit(False)

    def stop(self):
        self.engine.stop()
        self._operation_suspended = False
        self.current_track = None
        self.playlist = []
        self.current_index = -1
        self.current_album = {}
        self.playback_stopped.emit()
        self.state_changed.emit(False)

    def next_track(self) -> bool:
        if not self.playlist or self.current_index < 0:
            return False
        next_index = self.current_index + 1
        if next_index < len(self.playlist):
            return self.play_index(next_index)
        self.stop()
        return False

    def prev_track(self) -> bool:
        if not self.playlist:
            return False
        if self.engine.position_ms() > 3000:
            self.seek(0)
            return True
        if self.current_index > 0:
            return self.play_index(self.current_index - 1)
        self.seek(0)
        return True

    def seek(self, position_ms: int):
        if not self.current_track:
            return
        position_ms = max(0, int(position_ms))
        self._begin_session(self.current_index, position_ms, play=self.is_playing())
        self.position_changed.emit(position_ms, self._duration_ms())

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------
    def _duration_ms(self) -> int:
        if not self.current_track:
            return 0
        try:
            return max(0, int(float(self.current_track.get("duration", 0.0)) * 1000))
        except Exception:
            return 0

    def _begin_session(self, index: int, offset_ms: int, play: bool):
        if index < 0 or index >= len(self.playlist):
            return
        paths = [t.get("file_path", "") for t in self.playlist]
        self.engine.set_tracks(paths, index, offset_ms, play=play)
        if not play:
            self.state_changed.emit(False)

    def _on_engine_track_changed(self, index: int):
        if index < 0 or index >= len(self.playlist):
            return
        self.current_index = index
        self.current_track = self.playlist[index]
        self.track_started.emit(self.current_track, self.current_album)
        self.position_changed.emit(0, self._duration_ms())

    def _on_engine_position(self, position_ms: int):
        if self._operation_suspended:
            return
        self.position_changed.emit(int(position_ms), self._duration_ms())

    def _on_engine_finished(self):
        self.stop()

    def _on_engine_error(self, message: str):
        self.error_occurred.emit(message)
        self.state_changed.emit(False)

    def position_ms(self) -> int:
        return self.engine.position_ms()

    # ------------------------------------------------------------------
    # Playback state persistence
    # ------------------------------------------------------------------
    def get_playback_state(self) -> Optional[Dict[str, Any]]:
        if not self.current_track or not self.playlist:
            return None
        return {
            "file_path": self.current_track.get("file_path", ""),
            "position_ms": int(self.engine.position_ms()),
            "index": int(self.current_index),
            "album": dict(self.current_album or {}),
            "tracks": [dict(t) for t in self.playlist],
            "volume": self.get_volume(),
        }

    def restore_playback_state(self, state: Dict[str, Any]) -> bool:
        if not isinstance(state, dict):
            return False
        raw_tracks = state.get("tracks") or []
        if not isinstance(raw_tracks, list) or not raw_tracks:
            return False
        tracks = [dict(t) for t in raw_tracks if isinstance(t, dict)]
        file_path = str(state.get("file_path", ""))
        index = int(state.get("index", -1) or -1)
        if index < 0 or index >= len(tracks):
            index = next(
                (i for i, t in enumerate(tracks) if _norm_path(t.get("file_path", "")) == _norm_path(file_path)),
                0,
            )
        if not tracks:
            return False
        track = tracks[index]
        ok, _ = is_file_playable(track.get("file_path", ""))
        if not ok:
            return False

        self.playlist = tracks
        self.current_index = index
        self.current_track = track
        self.current_album = dict(state.get("album") or {})
        if not self.current_album:
            self.current_album = {
                "album": track.get("album", ""),
                "album_artist": track.get("album_artist", ""),
                "display_artist": track.get("artist", ""),
                "year": track.get("year", ""),
                "cover_path": track.get("cover_cache_path", ""),
            }
        position = max(0, int(state.get("position_ms", 0) or 0))
        self._begin_session(index, position, play=False)
        self.track_started.emit(self.current_track, self.current_album)
        self.state_changed.emit(False)
        self.position_changed.emit(position, self._duration_ms())
        return True

    # ------------------------------------------------------------------
    # Cooperative file operations
    # ------------------------------------------------------------------
    def suspend_for_file_operation(self, file_paths: Iterable[str]) -> Optional[Dict[str, Any]]:
        keys = {_norm_path(p) for p in file_paths if p}
        if not keys:
            return None
        current_path = self.current_track.get("file_path", "") if self.current_track else ""
        if not current_path or _norm_path(current_path) not in keys:
            return None

        state = {
            "suspended": True,
            "file_path": current_path,
            "position": int(self.engine.position_ms()),
            "was_playing": self.is_playing(),
            "index": self.current_index,
        }
        self._operation_suspended = True
        self.engine.stop()
        try:
            QCoreApplication.processEvents()
            QThread.msleep(25)
        except Exception:
            pass
        return state

    def resume_after_file_operation(self, state: Optional[Dict[str, Any]], path_map: Optional[Dict[str, str]] = None):
        if not state:
            return
        mapping = {_norm_path(k): v for k, v in (path_map or {}).items()}
        old_path = state.get("file_path", "")
        new_path = mapping.get(_norm_path(old_path), old_path)
        self._operation_suspended = False
        if not new_path or not Path(new_path).exists():
            self.stop()
            return

        index = int(state.get("index", self.current_index))
        if 0 <= index < len(self.playlist):
            self.playlist[index]["file_path"] = new_path
        if self.current_track and _norm_path(self.current_track.get("file_path", "")) == _norm_path(old_path):
            self.current_track["file_path"] = new_path
        else:
            self.current_index = index if 0 <= index < len(self.playlist) else self.current_index
            self.current_track = self.playlist[self.current_index] if self.current_index >= 0 else self.current_track

        self._begin_session(self.current_index, int(state.get("position", 0)), play=bool(state.get("was_playing")))
        self.track_started.emit(self.current_track, self.current_album)
        self.state_changed.emit(bool(state.get("was_playing")))
        self.position_changed.emit(int(state.get("position", 0)), self._duration_ms())
