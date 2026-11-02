"""Asynchronous audio-stream info lookups for the UI.

Reading a file's stream info (and its per-second bitrate profile) can touch the
network on SMB libraries, so it always happens on a worker thread and the
result is cached per file path.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

InfoDict = Dict[str, object]
Profile = Optional[List[int]]

_CACHE: Dict[str, Tuple[InfoDict, Profile]] = {}
_PENDING: Dict[str, List[Callable]] = {}


class _Hub(QObject):
    info_ready = pyqtSignal(str, object, object)


_HUB = _Hub()


def _dispatch(path: str, info: InfoDict, profile: Profile) -> None:
    for callback in _PENDING.pop(path, []):
        try:
            callback(path, info, profile)
        except Exception:
            pass


_HUB.info_ready.connect(_dispatch)


class _Worker(QRunnable):
    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        info: InfoDict = {}
        profile: Profile = None
        try:
            from malka.tags import get_audio_stream_info

            info = get_audio_stream_info(self.path)
        except Exception:
            info = {}
        try:
            from malka.bitrate import second_bitrates

            profile = second_bitrates(self.path)
        except Exception:
            profile = None
        _CACHE[self.path] = (info, profile)
        _HUB.info_ready.emit(self.path, info, profile)


def cached_audio_info(path: str) -> Optional[Tuple[InfoDict, Profile]]:
    if not path:
        return None
    return _CACHE.get(path)


def request_audio_info(path: str, callback: Callable[[str, InfoDict, Profile], None]) -> None:
    """Calls ``callback(path, info, profile)`` on the UI thread when ready."""
    if not path:
        return
    if not Path(path).exists():
        return
    cached = _CACHE.get(path)
    if cached is not None:
        callback(path, cached[0], cached[1])
        return
    _PENDING.setdefault(path, []).append(callback)
    QThreadPool.globalInstance().start(_Worker(path))
