import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from malka.config import NO_DATA
from malka.db import update_file_path

INVALID_WIN_CHARS = r'[<>:"/\\|?*]'


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

    # Determine if album has multiple discs
    discs = {str(t.get("disc_no", "1")).strip() for t in tracks if t.get("disc_no")}
    has_multiple_discs = len(discs) > 1 or any(d not in ("1", "", NO_DATA) for d in discs)

    updated_tracks = []

    for t in tracks:
        src_path = Path(t["file_path"]).resolve()
        if not src_path.exists():
            return False, f"File not found on disk: {src_path}", tracks

        safe_artist = sanitize_filename(t["album_artist"])
        safe_year = sanitize_filename(t["year"])
        safe_album = sanitize_filename(t["album"])

        album_dir = lib_path / safe_artist / f"{safe_year} - {safe_album}"
        if has_multiple_discs:
            disc_num = str(t.get("disc_no", "1")).strip() or "1"
            target_dir = album_dir / f"CD {disc_num}"
        else:
            target_dir = album_dir

        target_dir.mkdir(parents=True, exist_ok=True)

        base_name = format_track_filename(t, template)
        ext = src_path.suffix.lower()
        target_file = target_dir / f"{base_name}{ext}"

        # If source and destination are already identical, skip move
        if src_path.resolve() == target_file.resolve():
            updated_tracks.append(t)
            continue

        # Handle file name collisions if a different file already has this name
        if target_file.exists() and target_file.resolve() != src_path.resolve():
            counter = 1
            while target_file.exists() and target_file.resolve() != src_path.resolve():
                target_file = target_dir / f"{base_name} ({counter}){ext}"
                counter += 1

        old_parent = src_path.parent

        try:
            shutil.move(str(src_path), str(target_file))
        except Exception as e:
            return False, f"Error moving file {src_path.name}: {e}", tracks

        # Clean empty old directories up to library_path
        cleanup_empty_dirs(old_parent, lib_path)

        new_path_str = str(target_file.resolve())
        update_file_path(db_conn, t["id"], new_path_str)

        t_copy = dict(t)
        t_copy["file_path"] = new_path_str
        updated_tracks.append(t_copy)

    db_conn.commit()
    return True, f"Successfully organized {len(tracks)} tracks", updated_tracks
