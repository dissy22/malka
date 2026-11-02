"""
Gapless PCM playback engine for Malka.

Qt's QMediaPlayer has no playlist/gapless API: opening the next file re-initialises
the backend and produces an audible pause.  This engine decodes the playlist with
FFmpeg into one continuous PCM stream and feeds it to QAudioSink, so track
boundaries are sample-accurate and there is no silence between consecutive tracks.
"""
import atexit
import os
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QCoreApplication, QIODevice, QMetaObject, QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_BYTES = 2
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_BYTES
# ~0.35 s of audio before the sink is allowed to start.
PREBUFFER_BYTES = int(BYTES_PER_SECOND * 0.35)
# Keep a few seconds decoded ahead; this also bridges the next FFmpeg process start.
MAX_BUFFER_BYTES = int(BYTES_PER_SECOND * 8.0)
READ_CHUNK = 65536
# Large hardware-side buffer: GUI work (grid/tiles, image decoding) must never
# be able to starve the audio thread enough to cause an audible dropout.
SINK_BUFFER_BYTES = int(BYTES_PER_SECOND * 0.5)


def _find_ffmpeg() -> Optional[str]:
    try:
        from malka.importer import find_ffmpeg_executable
        path = find_ffmpeg_executable()
        return str(path) if path else None
    except Exception:
        return None


class _PcmBuffer:
    """Thread-safe byte queue with sample offsets for track boundaries."""

    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: deque = deque()
        self._size = 0
        self.total_appended = 0
        self.boundaries: List[Dict[str, Any]] = []
        self.ended = False
        self.error = ""

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._chunks.append(data)
            self._size += len(data)
            self.total_appended += len(data)

    def read(self, maxlen: int) -> bytes:
        if maxlen <= 0:
            return b""
        with self._lock:
            if not self._chunks:
                return b""
            out = bytearray()
            while self._chunks and len(out) < maxlen:
                chunk = self._chunks[0]
                need = maxlen - len(out)
                if len(chunk) <= need:
                    out.extend(chunk)
                    self._chunks.popleft()
                    self._size -= len(chunk)
                else:
                    out.extend(chunk[:need])
                    self._chunks[0] = chunk[need:]
                    self._size -= need
                    break
            return bytes(out)

    def available(self) -> int:
        with self._lock:
            return self._size

    def add_boundary(self, track_index: int, trim_ms: int) -> None:
        with self._lock:
            self.boundaries.append({
                "offset": self.total_appended,
                "index": track_index,
                "trim_ms": int(trim_ms),
            })

    def boundary_snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.boundaries)

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._size = 0


class _PcmIODevice(QIODevice):
    def __init__(self, buffer: _PcmBuffer, parent=None):
        super().__init__(parent)
        self._buffer = buffer

    def readData(self, maxlen: int) -> bytes:
        return self._buffer.read(int(maxlen))

    def writeData(self, data) -> int:
        return 0

    def bytesAvailable(self) -> int:
        try:
            return self._buffer.available() + super().bytesAvailable()
        except Exception:
            return self._buffer.available()

    def isSequential(self) -> bool:
        return True


class _DecodeWorker(threading.Thread):
    """Decodes consecutive tracks into one uninterrupted PCM byte stream."""

    def __init__(self, tracks: List[str], start_index: int, start_offset_ms: int, buffer: _PcmBuffer):
        super().__init__(daemon=True)
        self.tracks = tracks
        self.start_index = max(0, int(start_index))
        self.start_offset_ms = max(0, int(start_offset_ms))
        self.buffer = buffer
        self._stop_event = threading.Event()
        self._proc: Optional[subprocess.Popen] = None

    def stop(self):
        self._stop_event.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass

    def _cmd(self, path: str, trim_ms: int) -> List[str]:
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("FFmpeg executable was not found")
        cmd = [ffmpeg, "-nostdin", "-loglevel", "error"]
        if trim_ms > 0:
            cmd += ["-ss", f"{trim_ms / 1000.0:.3f}"]
        cmd += [
            "-i", path,
            "-vn",
            "-ac", str(CHANNELS),
            "-ar", str(SAMPLE_RATE),
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-",
        ]
        return cmd

    def run(self):
        try:
            first = True
            for index in range(self.start_index, len(self.tracks)):
                if self._stop_event.is_set():
                    return
                path = self.tracks[index]
                trim_ms = self.start_offset_ms if first else 0
                first = False
                self.buffer.add_boundary(index, trim_ms)
                cmd = self._cmd(path, trim_ms)

                creationflags = 0
                if sys.platform == "win32":
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        bufsize=0,
                        creationflags=creationflags,
                    )
                except Exception as e:
                    self.buffer.error = f"Could not start FFmpeg: {e}"
                    self.buffer.ended = True
                    return
                self._proc = proc
                got_audio = False
                try:
                    while not self._stop_event.is_set():
                        chunk = proc.stdout.read(READ_CHUNK) if proc.stdout else b""
                        if not chunk:
                            break
                        got_audio = True
                        self.buffer.append(chunk)
                        while self.buffer.available() > MAX_BUFFER_BYTES and not self._stop_event.is_set():
                            time.sleep(0.01)
                finally:
                    try:
                        if proc.poll() is None:
                            proc.kill()
                        if proc.stdout:
                            proc.stdout.close()
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                    self._proc = None

                if self._stop_event.is_set():
                    return
                if not got_audio:
                    self.buffer.error = f"Could not decode audio: {os.path.basename(path)}"
                    self.buffer.ended = True
                    return
            self.buffer.ended = True
        except Exception as e:
            self.buffer.error = str(e)
            self.buffer.ended = True


class PcmAudioEngine(QObject):
    """Owns a QAudioSink and a continuous FFmpeg decoding pipeline."""

    track_index_changed = pyqtSignal(int)
    position_changed = pyqtSignal(int)  # position inside the current track, ms
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device: QAudioDevice = QMediaDevices.defaultAudioOutput()
        self._volume = 1.0
        self._tracks: List[str] = []
        self._start_index = 0
        self._seek_ms = 0
        self._buffer: Optional[_PcmBuffer] = None
        self._worker: Optional[_DecodeWorker] = None
        self._sink: Optional[QAudioSink] = None
        self._io: Optional[_PcmIODevice] = None
        self._session = 0
        self._started = False
        self._want_play = False
        self._paused = False
        self._finished = False
        self._current_index = -1
        self._current_boundary = None
        self._error_sent = False
        self._pause_position = 0
        self._restart_after_pause = False
        # Updated by the audio thread; read lock-free by the GUI thread.
        self.published_position = 0

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_audio_device(self, device: QAudioDevice):
        if device and not device.isNull():
            self._device = device
            self._destroy_sink()

    def current_audio_device(self) -> QAudioDevice:
        return self._device

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, float(volume)))
        try:
            # Do not unmute a paused/reset sink: hardware may still drain its
            # last period, and that must stay silent.
            if self._sink is not None and self._started and not self._paused:
                self._sink.setVolume(self._volume)
        except Exception:
            pass

    def volume(self) -> float:
        return self._volume

    def set_tracks(self, tracks: List[str], start_index: int = 0, offset_ms: int = 0, play: bool = True):
        self._stop_session()
        if not tracks:
            return
        self._tracks = list(tracks)
        self._start_index = max(0, min(start_index, len(self._tracks) - 1))
        self._seek_ms = max(0, int(offset_ms))
        self._current_index = self._start_index
        self._current_boundary = None
        self._buffer = _PcmBuffer()
        self._finished = False
        self._error_sent = False
        self._want_play = bool(play)
        self._paused = not play
        self._started = False
        self._pause_position = self._seek_ms
        self._restart_after_pause = False
        self.published_position = self._seek_ms
        self._session += 1
        self._worker = _DecodeWorker(self._tracks, self._start_index, self._seek_ms, self._buffer)
        self._worker.start()

    def play(self):
        if not self._tracks or self._finished:
            return
        if self._restart_after_pause and self._buffer is not None:
            # Pause flushed the hardware buffer, so resume by restarting the
            # decoder at the exact paused position instead of playing stale PCM.
            self._restart_after_pause = False
            self.set_tracks(self._tracks, self._current_index, self._pause_position, play=True)
            return
        if not self._buffer:
            return
        self._want_play = True
        self._paused = False
        if self._started and self._sink is not None:
            try:
                self._sink.resume()
            except Exception:
                pass
        else:
            self._poll()

    def pause(self):
        if self._started and self._sink is not None:
            # Capture the audible position first; then drop the hardware buffer
            # so the sound stops immediately rather than draining for seconds.
            self._pause_position = self.position_ms()
            self.published_position = self._pause_position
            self._restart_after_pause = True
            self._destroy_sink()
            self._started = False
            self.position_changed.emit(self._pause_position)
        self._paused = True
        self._want_play = False

    @pyqtSlot()
    def stop(self):
        self._stop_session()

    def seek(self, offset_ms: int):
        """Restarts the stream at a position inside the current track."""
        if not self._tracks or self._current_index < 0:
            return
        was_play = self.is_playing() or self._started and not self._paused
        self.set_tracks(self._tracks, self._current_index, offset_ms, play=was_play)

    def is_playing(self) -> bool:
        return bool(self._want_play and not self._paused and not self._finished)

    def is_started(self) -> bool:
        return self._started

    def position_ms(self) -> int:
        if self._restart_after_pause:
            return int(self._pause_position)
        if not self._started or self._sink is None or self._buffer is None:
            return self._seek_ms
        try:
            played_bytes = self._sink.processedUSecs() * BYTES_PER_SECOND / 1_000_000.0
        except Exception:
            return self._seek_ms
        boundary = self._current_boundary
        if boundary is not None:
            return int(boundary["trim_ms"] + max(0.0, played_bytes - boundary["offset"]) / BYTES_PER_SECOND * 1000.0)
        return self._seek_ms

    def buffered_ms(self) -> int:
        if not self._buffer:
            return 0
        return int(self._buffer.available() / BYTES_PER_SECOND * 1000)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _stop_session(self):
        self._session += 1
        self._want_play = False
        self._paused = False
        self._started = False
        self._finished = False
        self._current_boundary = None
        self._restart_after_pause = False
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                pass
            self._worker = None
        # Tear the old sink down completely. It is muted before deletion, so any
        # last hardware period drains silently; the next session gets a new sink.
        self._destroy_sink()
        if self._buffer is not None:
            self._buffer.clear()
            self._buffer = None

    def _destroy_sink(self):
        sink = self._sink
        if sink is not None:
            try:
                sink.setVolume(0.0)
            except Exception:
                pass
            try:
                sink.stop()
            except Exception:
                pass
            try:
                sink.reset()
            except Exception:
                pass
            try:
                sink.deleteLater()
            except Exception:
                pass
            self._sink = None
        if self._io is not None:
            try:
                self._io.close()
            except Exception:
                pass
            self._io = None

    def _format(self) -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return fmt

    def _start_sink(self) -> bool:
        if self._buffer is None:
            return False
        try:
            device = self._device
            if device is None or device.isNull():
                device = QMediaDevices.defaultAudioOutput()
            if device.isNull():
                self._send_error("No audio output device is available")
                return False
            fmt = self._format()
            if not device.isFormatSupported(fmt):
                self._send_error("Audio device does not support 48 kHz stereo PCM")
                return False
            sink = self._sink
            if sink is None:
                sink = QAudioSink(device, fmt, self)
                try:
                    sink.setBufferSize(SINK_BUFFER_BYTES)
                except Exception:
                    pass
                self._sink = sink
            sink.setVolume(self._volume)
            io = _PcmIODevice(self._buffer, self)
            io.open(QIODevice.OpenModeFlag.ReadOnly)
            self._io = io
            sink.start(io)
            self._started = True
            if self._paused:
                sink.suspend()
            return True
        except Exception as e:
            self._send_error(f"Could not start audio output: {e}")
            return False

    def _send_error(self, message: str):
        if not self._error_sent:
            self._error_sent = True
            self.error.emit(message)

    def _poll(self):
        buffer = self._buffer
        if buffer is None:
            return
        if buffer.error:
            self._send_error(buffer.error)
            self._stop_session()
            return

        if not self._started:
            if self._want_play and (buffer.available() >= PREBUFFER_BYTES or buffer.ended):
                if not self._start_sink():
                    return
            else:
                return

        if self._sink is None:
            return

        try:
            played_bytes = self._sink.processedUSecs() * BYTES_PER_SECOND / 1_000_000.0
        except Exception:
            return

        boundaries = buffer.boundary_snapshot()
        current = self._current_boundary
        for boundary in boundaries:
            if boundary["offset"] <= played_bytes + 1024:
                current = boundary
            else:
                break
        if current is not None and current is not self._current_boundary:
            if current["index"] != self._current_index:
                self._current_index = current["index"]
                self.published_position = 0
                self.track_index_changed.emit(self._current_index)
            self._current_boundary = current

        current_position = self.position_ms()
        self.published_position = current_position
        self.position_changed.emit(current_position)

        if buffer.ended and played_bytes >= buffer.total_appended - BYTES_PER_SECOND * 0.05:
            self._finished = True
            self._want_play = False
            try:
                self._sink.stop()
            except Exception:
                pass
            self._started = False
            self.finished.emit()
            self._stop_session()


class _AudioEngineThread(QThread):
    """Dedicated Qt event loop for QAudioSink, independent of the GUI thread."""

    def __init__(self):
        super().__init__()
        self.engine: Optional[PcmAudioEngine] = None
        self.ready = threading.Event()
        self.failure = ""

    def run(self):
        try:
            self.engine = PcmAudioEngine()
        except Exception as e:
            self.failure = str(e)
        self.ready.set()
        self.exec()


class PcmAudioService(QObject):
    """
    GUI-thread facade for the audio engine.

    The real QAudioSink/QTimer live in a dedicated QThread with its own event
    loop.  GUI rendering, album-grid construction and thumbnail decoding can no
    longer stop the audio output just by keeping the main event loop busy.
    """

    track_index_changed = pyqtSignal(int)
    position_changed = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    _cmd_set_tracks = pyqtSignal(list, int, int, bool)
    _cmd_play = pyqtSignal()
    _cmd_pause = pyqtSignal()
    _cmd_seek = pyqtSignal(int)
    _cmd_volume = pyqtSignal(float)
    _cmd_device = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[_AudioEngineThread] = None
        self._engine: Optional[PcmAudioEngine] = None
        self._volume = 1.0
        self._device = QMediaDevices.defaultAudioOutput()
        self._last_position = 0
        self._current_index = -1
        self._want_play = False
        self._paused = True
        self._position_pending = False
        _SERVICE_INSTANCES.append(self)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    # ------------------------------------------------------------------
    # Thread lifecycle / commands
    # ------------------------------------------------------------------
    def _ensure_thread(self) -> bool:
        if self._thread is not None and self._thread.isRunning() and self._engine is not None:
            return True
        thread = _AudioEngineThread()
        thread.start()
        if not thread.ready.wait(5.0):
            self.error.emit("Audio engine thread did not start")
            thread.quit()
            return False
        if thread.engine is None:
            self.error.emit(thread.failure or "Could not create audio engine")
            thread.quit()
            return False

        self._thread = thread
        self._engine = thread.engine
        engine = self._engine

        engine.track_index_changed.connect(self._on_track_index_changed)
        engine.position_changed.connect(self._on_position_changed)
        engine.finished.connect(self._on_finished)
        engine.error.connect(self._on_error)

        self._cmd_set_tracks.connect(engine.set_tracks, Qt.ConnectionType.QueuedConnection)
        self._cmd_play.connect(engine.play, Qt.ConnectionType.QueuedConnection)
        self._cmd_pause.connect(engine.pause, Qt.ConnectionType.QueuedConnection)
        self._cmd_seek.connect(engine.seek, Qt.ConnectionType.QueuedConnection)
        self._cmd_volume.connect(engine.set_volume, Qt.ConnectionType.QueuedConnection)
        self._cmd_device.connect(engine.set_audio_device, Qt.ConnectionType.QueuedConnection)

        self._cmd_volume.emit(self._volume)
        if self._device is not None and not self._device.isNull():
            self._cmd_device.emit(self._device)
        return True

    def shutdown(self):
        engine = self._engine
        thread = self._thread
        self._want_play = False
        self._paused = True
        if engine is not None:
            try:
                QMetaObject.invokeMethod(engine, "stop", Qt.ConnectionType.BlockingQueuedConnection)
            except Exception:
                pass
        self._engine = None
        if thread is not None:
            try:
                thread.quit()
                thread.wait(3000)
            except Exception:
                pass
        self._thread = None

    def stop(self):
        self.shutdown()

    # ------------------------------------------------------------------
    # Public API used by PlayerController
    # ------------------------------------------------------------------
    def set_tracks(self, tracks: List[str], start_index: int = 0, offset_ms: int = 0, play: bool = True):
        if not self._ensure_thread():
            return
        self._last_position = int(offset_ms)
        self._position_pending = True
        self._current_index = int(start_index)
        self._want_play = bool(play)
        self._paused = not play
        self._cmd_set_tracks.emit(list(tracks), int(start_index), int(offset_ms), bool(play))

    def play(self):
        if self._engine is None:
            return
        self._want_play = True
        self._paused = False
        self._cmd_play.emit()

    def pause(self):
        if self._engine is None:
            return
        self._want_play = False
        self._paused = True
        self._cmd_pause.emit()

    def seek(self, offset_ms: int):
        if self._engine is None:
            return
        self._last_position = int(offset_ms)
        self._cmd_seek.emit(int(offset_ms))

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, float(volume)))
        if self._engine is not None:
            self._cmd_volume.emit(self._volume)

    def volume(self) -> float:
        return self._volume

    def set_audio_device(self, device: QAudioDevice):
        if device and not device.isNull():
            self._device = device
            if self._engine is not None:
                self._cmd_device.emit(device)

    def current_audio_device(self) -> QAudioDevice:
        return self._device

    def is_playing(self) -> bool:
        return bool(self._want_play and not self._paused)

    def is_started(self) -> bool:
        return bool(self._engine is not None and self._want_play)

    def position_ms(self) -> int:
        if self._position_pending:
            return int(self._last_position)
        engine = self._engine
        if engine is not None:
            try:
                return int(getattr(engine, "published_position", self._last_position))
            except Exception:
                pass
        return int(self._last_position)

    def buffered_ms(self) -> int:
        return 1 if self._engine is not None else 0

    # ------------------------------------------------------------------
    # Engine -> GUI signal forwarding
    # ------------------------------------------------------------------
    def _on_track_index_changed(self, index: int):
        self._current_index = index
        self._last_position = 0
        self._position_pending = False
        self.track_index_changed.emit(index)

    def _on_position_changed(self, position_ms: int):
        self._last_position = int(position_ms)
        self._position_pending = False
        self.position_changed.emit(int(position_ms))

    def _on_finished(self):
        self._want_play = False
        self._paused = False
        self.finished.emit()

    def _on_error(self, message: str):
        self._want_play = False
        self.error.emit(message)


# Services are kept alive until application shutdown; their worker threads must
# not be destroyed while still running.
_SERVICE_INSTANCES: List[PcmAudioService] = []


def _shutdown_all_services():
    for service in list(_SERVICE_INSTANCES):
        try:
            service.shutdown()
        except Exception:
            pass


atexit.register(_shutdown_all_services)
