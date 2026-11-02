"""Small desktop-integration helpers used by the UI."""
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _spawn(args) -> bool:
    try:
        subprocess.Popen(args)
        return True
    except Exception:
        return False


def open_folder(folder_path: str) -> bool:
    """Opens a folder in the system file manager."""
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return False
    if sys.platform == "win32":
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
            return True
        except Exception:
            return _spawn(["explorer", str(folder)])
    if sys.platform == "darwin":
        return _spawn(["open", str(folder)])
    return _spawn(["xdg-open", str(folder)])


def reveal_file(file_path: str) -> bool:
    """Opens the file manager at the given file, selecting it when supported."""
    path = Path(file_path)
    if path.exists() and path.is_dir():
        return open_folder(str(path))
    folder = path.parent
    if not folder.exists():
        return False

    if sys.platform == "win32":
        # explorer returns a non-zero exit code even on success, so just spawn it.
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
            return True
        except Exception:
            return open_folder(str(folder))
    if sys.platform == "darwin":
        return _spawn(["open", "-R", str(path)])
    return _spawn(["xdg-open", str(folder)])


def find_folder_for_path(file_path: str) -> Optional[str]:
    path = Path(file_path)
    return str(path.parent) if path.exists() else None
