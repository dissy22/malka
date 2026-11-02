import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from malka.config import NO_DATA
from malka.db import set_track_organized, update_file_path

INVALID_WIN_CHARS = r'[<>:"/\\|?*]'


def _norm_path(path: Any) -> str:
    """Cheap absolute/normalised path key.

    Uses only string operations (no ``stat``/``realpath`` calls): on network
    shares (SMB/gvfs) every filesystem lookup costs milliseconds, and this is
    called for every track when the library is scanned or refreshed.
    """
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))
    except Exception:
        return os.path.normcase(str(path))


def _norm_roots(roots: List[str]) -> List[tuple]:
    """(normalised key, original root) pairs, longest first."""
    pairs = []
    for root in roots or []:
        key = _norm_path(root)
        if key:
            pairs.append((key, str(root)))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def sanitize_filename(name: str) -> str:
    if not name:
        return "Unknown"
    # Replace invalid chars with safe underscore
    cleaned = re.sub(INVALID_WIN_CHARS, "_", str(name))
    # Strip leading/trailing whitespaces and dots (Windows prohibited)
    cleaned = cleaned.strip(". ")
    return cleaned if cleaned else "Unknown"


def is_album_ready_to_organize(tracks: List[Dict[str, Any]]) -> Tuple[bool, str]:
    if not tracks:
        return False, "No tracks in album"

    for i, t in enumerate(tracks, start=1):
        missing = []
        track_disp = t.get("title") or f"Track #{i}"

        album_artist = t.get("album_artist", "").strip()
        if not album_artist or album_artist == NO_DATA:
            missing.append("Album Artist")

        year = t.get("year", "").strip()
        if not year or year == NO_DATA:
            missing.append("Year")

        album = t.get("album", "").strip()
        if not album or album == NO_DATA:
            missing.append("Album")

        track_no = t.get("track_no", "").strip()
        if not track_no or track_no == NO_DATA:
            missing.append("Track Number")

        title = t.get("title", "").strip()
        if not title or title == NO_DATA:
            missing.append("Title")

        if missing:
            return False, f"Track '{track_disp}' has missing required tags: {', '.join(missing)}"

    return True, "All required tags are filled"


def format_track_filename(track: Dict[str, Any], template: str) -> str:
    # Format track_no with leading zero
    raw_num = track.get("track_no", "01")
    try:
        num = int(re.match(r"^(\d+)", str(raw_num)).group(1))
        track_no_str = f"{num:02d}"
    except Exception:
        track_no_str = str(raw_num)

    disc_no_str = str(track.get("disc_no", "1")).strip() or "1"
    disc_total_str = str(track.get("disc_total", "1")).strip() or "1"
    disc_and_track = f"{disc_no_str}-{track_no_str}"

    replacements = {
        "<track_no>": track_no_str,
        "{track_no}": track_no_str,
        "<disc_no>": disc_no_str,
        "{disc_no}": disc_no_str,
        "<disc_total>": disc_total_str,
        "{disc_total}": disc_total_str,
        "<disc_and_track>": disc_and_track,
        "{disc_and_track}": disc_and_track,
        "<title>": track.get("title", "Track"),
        "{title}": track.get("title", "Track"),
        "<artist>": track.get("artist", "Artist"),
        "{artist}": track.get("artist", "Artist"),
        "<album_artist>": track.get("album_artist", "Album Artist"),
        "{album_artist}": track.get("album_artist", "Album Artist"),
        "<album>": track.get("album", "Album"),
        "{album}": track.get("album", "Album"),
        "<year>": track.get("year", "Year"),
        "{year}": track.get("year", "Year"),
    }

    result = template
    for key, val in replacements.items():
        result = result.replace(key, str(val))

    return sanitize_filename(result)


def cleanup_empty_dirs(start_dir: Path, stop_dir: Path) -> None:
    curr = start_dir
    try:
        stop_dir_res = stop_dir.resolve()
        while curr.resolve() != stop_dir_res and curr.resolve() != curr.parent.resolve():
            if curr.exists() and curr.is_dir():
                if not any(curr.iterdir()):
                    curr.rmdir()
                    curr = curr.parent
                else:
                    break
            else:
                curr = curr.parent
    except Exception:
        pass


def album_is_multi_disc(tracks: List[Dict[str, Any]]) -> bool:
    """True when the album needs per-disc ``CD n`` subfolders."""
    discs = {str(t.get("disc_no", "1")).strip() for t in tracks if t.get("disc_no")}
    if len(discs) > 1 or any(d not in ("1", "", NO_DATA) for d in discs):
        return True
    # disc_total > 1 is enough information even when only "CD 1" is present
    # (e.g. when importing a single disc from a multi-disc release).
    for track in tracks:
        try:
            if int(re.match(r"^(\d+)", str(track.get("disc_total", "1")).strip()).group(1)) > 1:
                return True
        except Exception:
            continue
    return False


def track_expects_disc_folder(track: Dict[str, Any]) -> bool:
    """Per-track approximation of :func:`album_is_multi_disc` (used while scanning)."""

    def _num(value: Any) -> int:
        try:
            return int(re.match(r"^(\d+)", str(value).strip()).group(1))
        except Exception:
            return 1

    return _num(track.get("disc_no", 1)) > 1 or _num(track.get("disc_total", 1)) > 1


def organized_target_path(
    library_root: str,
    track: Dict[str, Any],
    template: str,
    multi_disc: bool,
) -> Path:
    """The exact path this track must have according to the library layout."""
    lib = Path(library_root)
    safe_artist = sanitize_filename(track.get("album_artist", "Unknown Artist"))
    safe_year = sanitize_filename(track.get("year", "Unknown Year"))
    safe_album = sanitize_filename(track.get("album", "Unknown Album"))
    target_dir = lib / safe_artist / f"{safe_year} - {safe_album}"
    if multi_disc:
        disc_num = str(track.get("disc_no", "1")).strip() or "1"
        target_dir = target_dir / f"CD {disc_num}"
    ext = Path(track.get("file_path", "")).suffix.lower()
    return target_dir / f"{format_track_filename(track, template)}{ext}"


def find_containing_root(file_path: str, library_roots: List[str]) -> str:
    """Returns the configured library root that contains ``file_path`` (or "")."""
    target = _norm_path(file_path)
    if not target:
        return ""
    for key, original in _norm_roots(library_roots):
        prefix = key if key.endswith(os.sep) else key + os.sep
        if target == key or target.startswith(prefix):
            return original
    return ""


def is_track_organized(
    track: Dict[str, Any],
    library_roots: List[str],
    template: str,
    multi_disc: Optional[bool] = None,
) -> bool:
    """True when the file already sits at its canonical library path AND name."""
    file_path = str(track.get("file_path") or "")
    if not file_path:
        return False
    root = find_containing_root(file_path, library_roots)
    if not root:
        return False
    if multi_disc is None:
        multi_disc = track_expects_disc_folder(track)
    try:
        expected = organized_target_path(root, track, template, multi_disc)
        return _norm_path(file_path) == _norm_path(expected)
    except Exception:
        return False


def refresh_organization_flags(
    db_conn,
    library_roots: List[str],
    template: str,
) -> int:
    """Recomputes ``tracks.is_organized`` for every track. Returns the count of organized tracks."""
    rows = db_conn.execute(
        """
        SELECT id, file_path, title, artist, album_artist, album, year,
               track_no, disc_no, disc_total, is_organized
        FROM tracks
        """
    ).fetchall()
    if not rows:
        return 0

    tracks = [dict(r) for r in rows]
    multi_by_album: Dict[Tuple[str, str], bool] = {}
    for t in tracks:
        key = (str(t.get("album") or ""), str(t.get("album_artist") or ""))
        multi_by_album.setdefault(key, False)
        if track_expects_disc_folder(t):
            multi_by_album[key] = True

    organized = 0
    updates = []
    for t in tracks:
        multi = multi_by_album.get((str(t.get("album") or ""), str(t.get("album_artist") or "")), False)
        value = 1 if is_track_organized(t, library_roots, template, multi) else 0
        organized += value
        if value != int(t.get("is_organized") or 0):
            updates.append((value, int(t["id"])))
    if updates:
        try:
            db_conn.executemany("UPDATE tracks SET is_organized = ? WHERE id = ?", updates)
        except Exception:
            for value, track_id in updates:
                set_track_organized(db_conn, track_id, value)
        db_conn.commit()
    return organized


def build_organization_plan(
    library_path: str,
    tracks: List[Dict[str, Any]],
    template: str,
) -> List[Dict[str, Any]]:
    """Builds the from -> to rename/move list without touching the disk."""
    lib = Path(library_path)
    multi = album_is_multi_disc(tracks)
    claimed: set = set()
    plan: List[Dict[str, Any]] = []

    for track in tracks:
        src = Path(track.get("file_path", ""))
        dst = organized_target_path(str(lib), track, template, multi)
        src_key = _norm_path(src)

        if dst.exists() and _norm_path(dst) != src_key:
            base = dst.stem
            ext = dst.suffix
            counter = 1
            while dst.exists() or _norm_path(dst) in claimed:
                dst = dst.parent / f"{base} ({counter}){ext}"
                counter += 1
        else:
            base = dst.stem
            ext = dst.suffix
            counter = 1
            while _norm_path(dst) in claimed:
                dst = dst.parent / f"{base} ({counter}){ext}"
                counter += 1

        dst_key = _norm_path(dst)
        claimed.add(dst_key)
        plan.append({
            "track": track,
            "track_id": track.get("id"),
            "src": src,
            "dst": dst,
            "changed": src_key != dst_key,
        })
    return plan


def apply_organization_plan(
    plan: List[Dict[str, Any]],
    library_path: str,
    db_conn,
    template: str = "",
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """Executes a plan built by :func:`build_organization_plan`."""
    lib_path = Path(library_path).resolve()
    updated_tracks: List[Dict[str, Any]] = []
    moved = 0

    for item in plan:
        track = item["track"]
        src_path = Path(item["src"])
        target_file = Path(item["dst"])

        if item["changed"]:
            if not src_path.exists():
                return False, f"File not found on disk: {src_path}", updated_tracks
            try:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_path), str(target_file))
            except Exception as e:
                return False, f"Error moving file {src_path.name}: {e}", updated_tracks
            cleanup_empty_dirs(src_path.parent, lib_path)
            moved += 1

        new_path_str = str(target_file.resolve())
        track_id = item.get("track_id") or track.get("id")
        try:
            if track_id is not None:
                update_file_path(db_conn, int(track_id), new_path_str)
                set_track_organized(db_conn, int(track_id), 1)
        except Exception:
            pass

        t_copy = dict(track)
        t_copy["file_path"] = new_path_str
        t_copy["is_organized"] = 1
        updated_tracks.append(t_copy)

    db_conn.commit()
    if moved:
        return True, f"Successfully organized {moved} file(s)", updated_tracks
    return True, "Album is already organized", updated_tracks


def organize_album(
    library_path: str,
    tracks: List[Dict[str, Any]],
    template: str,
    db_conn,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    ready, reason = is_album_ready_to_organize(tracks)
    if not ready:
        return False, reason, tracks

    lib_path = Path(library_path).resolve()
    if not lib_path.exists():
        return False, f"Library directory not found: {library_path}", tracks

    plan = build_organization_plan(str(lib_path), tracks, template)
    return apply_organization_plan(plan, str(lib_path), db_conn, template)
