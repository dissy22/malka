import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from malka.formats import SOURCE_KINDS

DEFAULT_NAMING_FORMAT = "<track_no>. <title>"


def get_app_dir() -> Path:
    """
    Returns the portable application data directory:
    Always located in the application folder: <app_folder>/.malka
    """
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        # Development mode: project root directory (parent of src)
        base_dir = Path(__file__).resolve().parent.parent.parent

    app_dir = base_dir / ".malka"

    # One-time migration: if local .malka doesn't exist yet, but old Path.home() / .malka exists,
    # copy the config and library database so the user's data isn't lost on update.
    old_home_dir = Path.home() / ".malka"
    if not app_dir.exists() and old_home_dir.exists() and old_home_dir.is_dir():
        try:
            shutil.copytree(old_home_dir, app_dir, dirs_exist_ok=True)
        except Exception:
            pass

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


APP_DIR = get_app_dir()
CONFIG_FILE = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "covers"
ARTISTS_CACHE_DIR = APP_DIR / "artists"
THUMBNAILS_CACHE_DIR = APP_DIR / "thumbnails"
DEFAULT_DB_PATH = APP_DIR / "library.db"

NO_DATA = "No data provided"


class Config:
    def __init__(self):
        self.library_paths: List[str] = []
        self.track_naming_format: str = DEFAULT_NAMING_FORMAT
        self.db_path: str = str(DEFAULT_DB_PATH)
        self.audio_device_id: str = ""
        self.theme: str = "dark"
        self.show_scrollbars: bool = True
        self.show_organize_badge: bool = True
        self.show_encoding_badge: bool = True
        self.album_sort_mode: str = "artist_year"
        self.artist_sort_mode: str = "name_asc"
        self.genre_sort_mode: str = "name_asc"
        self.view_mode: str = "tiles"
        self.volume: int = 100
        self.playback_state: Optional[Dict[str, Any]] = None
        # Remembered import quality settings per source kind (see malka.formats).
        self.import_settings: Dict[str, Dict[str, Any]] = {}
        self.load()

    # ------------------------------------------------------------------
    # Library folder helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_folder(folder: Any) -> str:
        if not folder:
            return ""
        try:
            return str(Path(str(folder)).expanduser().resolve())
        except Exception:
            return str(folder)

    @staticmethod
    def _path_key(folder: Any) -> str:
        try:
            return os.path.normcase(str(Path(str(folder)).expanduser().resolve()))
        except Exception:
            return os.path.normcase(str(folder))

    def set_library_paths(self, paths: Iterable[str]) -> None:
        """Replaces the configured library roots, preserving order and de-duplicating."""
        unique: List[str] = []
        seen = set()
        for p in paths or []:
            normalized = self._normalize_folder(p)
            if not normalized:
                continue
            key = self._path_key(normalized)
            if key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        self.library_paths = unique

    def add_library_path(self, folder: str) -> bool:
        """Adds a folder to the library roots. Returns False if it was already present."""
        normalized = self._normalize_folder(folder)
        if not normalized:
            return False
        key = self._path_key(normalized)
        if any(self._path_key(p) == key for p in self.library_paths):
            return False
        self.library_paths.append(normalized)
        return True

    def remove_library_path(self, folder: str) -> None:
        key = self._path_key(folder)
        self.library_paths = [p for p in self.library_paths if self._path_key(p) != key]

    @property
    def library_path(self) -> str:
        """Legacy single-folder accessor: the first configured library root."""
        return self.library_paths[0] if self.library_paths else ""

    @library_path.setter
    def library_path(self, value: str) -> None:
        self.set_library_paths([value] if value else [])

    def is_path_in_library(self, file_path: str) -> bool:
        if not self.library_paths:
            return True
        try:
            target = Path(file_path).expanduser().resolve()
        except Exception:
            return False
        for root in self.library_paths:
            try:
                target.relative_to(Path(root).expanduser().resolve())
                return True
            except Exception:
                continue
        return False

    def library_root_for_path(self, file_path: str) -> Optional[str]:
        """Returns the most specific configured library root containing file_path."""
        if not self.library_paths:
            return None
        try:
            target = Path(file_path).expanduser().resolve()
        except Exception:
            return None
        best: Optional[str] = None
        best_len = -1
        for root in self.library_paths:
            try:
                resolved = Path(root).expanduser().resolve()
                target.relative_to(resolved)
            except Exception:
                continue
            if len(str(resolved)) > best_len:
                best = root
                best_len = len(str(resolved))
        return best

    # ------------------------------------------------------------------
    # Import settings
    # ------------------------------------------------------------------
    def get_import_settings(self, source_kind: str) -> Dict[str, Any]:
        """Returns the remembered quality settings for a kind of import."""
        stored = self.import_settings.get(source_kind)
        return dict(stored) if isinstance(stored, dict) else {}

    def set_import_settings(self, source_kind: str, settings: Dict[str, Any]) -> None:
        """Remembers mode/format/rate for a kind of import."""
        if source_kind not in SOURCE_KINDS or not isinstance(settings, dict):
            return
        self.import_settings[source_kind] = {
            "mode": str(settings.get("mode") or ""),
            "format": str(settings.get("format") or "flac"),
            "rate": int(settings.get("rate") or 48000),
        }

    def load(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ARTISTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        THUMBNAILS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_paths = data.get("library_paths")
                    if isinstance(raw_paths, list) and raw_paths:
                        self.set_library_paths([str(p) for p in raw_paths if p])
                    else:
                        legacy = data.get("library_path", "")
                        self.set_library_paths([legacy] if legacy else [])
                    self.track_naming_format = data.get("track_naming_format", DEFAULT_NAMING_FORMAT)
                    saved_db = data.get("db_path", "")
                    if not saved_db or str(Path.home() / ".malka") in saved_db:
                        self.db_path = str(DEFAULT_DB_PATH)
                    else:
                        self.db_path = saved_db
                    self.audio_device_id = data.get("audio_device_id", "")
                    self.theme = data.get("theme", "dark")
                    self.show_scrollbars = data.get("show_scrollbars", True)
                    self.show_organize_badge = bool(data.get("show_organize_badge", True))
                    self.show_encoding_badge = bool(data.get("show_encoding_badge", True))
                    self.album_sort_mode = data.get("album_sort_mode", "artist_year")
                    self.artist_sort_mode = data.get("artist_sort_mode", "name_asc")
                    self.genre_sort_mode = data.get("genre_sort_mode", "name_asc")
                    self.view_mode = data.get("view_mode", "tiles") if data.get("view_mode") in ("tiles", "table") else "tiles"
                    try:
                        self.volume = max(0, min(100, int(data.get("volume", 100))))
                    except Exception:
                        self.volume = 100
                    saved_state = data.get("playback_state")
                    self.playback_state = saved_state if isinstance(saved_state, dict) else None
                    saved_imports = data.get("import_settings")
                    if isinstance(saved_imports, dict):
                        for kind in SOURCE_KINDS:
                            value = saved_imports.get(kind)
                            if isinstance(value, dict):
                                self.import_settings[kind] = {
                                    "mode": str(value.get("mode") or ""),
                                    "format": str(value.get("format") or "flac"),
                                    "rate": int(value.get("rate") or 48000),
                                }
            except Exception:
                pass

    def save_volume(self) -> None:
        """Persists only the playback volume, leaving all other config values intact."""
        APP_DIR.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {}
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
        data["volume"] = max(0, min(100, int(self.volume)))
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_runtime_state(self) -> None:
        """Persists volume and the resumable playback session without touching settings."""
        APP_DIR.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {}
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
        data["volume"] = max(0, min(100, int(self.volume)))
        if self.playback_state:
            data["playback_state"] = self.playback_state
        else:
            data.pop("playback_state", None)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "library_paths": self.library_paths,
            # Keep writing the legacy key so older builds can still open the config.
            "library_path": self.library_path,
            "track_naming_format": self.track_naming_format,
            "db_path": self.db_path,
            "audio_device_id": self.audio_device_id,
            "theme": self.theme,
            "show_scrollbars": self.show_scrollbars,
            "show_organize_badge": self.show_organize_badge,
            "show_encoding_badge": self.show_encoding_badge,
            "album_sort_mode": self.album_sort_mode,
            "artist_sort_mode": self.artist_sort_mode,
            "genre_sort_mode": self.genre_sort_mode,
            "view_mode": self.view_mode,
            "volume": self.volume,
            "playback_state": self.playback_state,
            "import_settings": {k: dict(v) for k, v in self.import_settings.items()},
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


config = Config()
