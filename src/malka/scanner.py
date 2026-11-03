import os
from pathlib import Path
from typing import Iterable, List, Optional, Set, Union

from PyQt6.QtCore import QThread, pyqtSignal

from malka.config import NO_DATA, config
from malka.db import (
    delete_missing_tracks,
    get_cached_mtimes,
    get_connection,
    upsert_track,
)
from malka.formats import LIBRARY_EXTS
from malka.organizer import refresh_organization_flags
from malka.tags import read_tags

#: The library stores only MP3, AAC/ALAC-in-M4A and FLAC files.
SUPPORTED_EXTS = LIBRARY_EXTS


class LibraryScanner(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, current_filename
    status_text = pyqtSignal(str)
    finished_scan = pyqtSignal(int, int)  # total_scanned, deleted_count
    error = pyqtSignal(str)

    def __init__(
        self,
        library_path: Union[str, Path, Iterable[str]],
        db_path: str,
        force_rescan: bool = False,
        naming_format: Optional[str] = None,
        delete_scope: Optional[Iterable[str]] = None,
    ):
        super().__init__()
        if isinstance(library_path, (str, Path)):
            paths = [str(library_path)]
        else:
            paths = [str(p) for p in library_path if p]
        self.library_paths: List[str] = paths
        self.library_path = paths[0] if paths else ""
        self.db_path = db_path
        self.force_rescan = force_rescan
        self.delete_scope: List[str] = [str(p) for p in delete_scope] if delete_scope else list(paths)
        self.naming_format = naming_format
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        roots = [Path(p) for p in self.library_paths if p]
        valid_roots = [p for p in roots if p.exists() and p.is_dir()]
        if not valid_roots:
            if roots:
                self.error.emit(f"Specified path does not exist or is not a directory: {self.library_paths[0]}")
            else:
                self.error.emit("No music library folders configured.")
            return

        self.status_text.emit("Searching for audio files...")
        audio_files: List[str] = []
        seen: Set[str] = set()
        try:
            for root in valid_roots:
                for walk_root, _, files in os.walk(str(root)):
                    if self._is_cancelled:
                        return
                    for f in files:
                        ext = Path(f).suffix.lower()
                        if ext not in SUPPORTED_EXTS:
                            continue
                        full_path = os.path.join(walk_root, f)
                        try:
                            resolved = str(Path(full_path).resolve())
                        except Exception:
                            resolved = full_path
                        if resolved in seen:
                            continue
                        seen.add(resolved)
                        audio_files.append(full_path)
        except Exception as e:
            self.error.emit(f"Error scanning files: {e}")
            return

        total_files = len(audio_files)
        if total_files == 0:
            self.status_text.emit("No audio files found")

        conn = get_connection(self.db_path)
        try:
            cached_mtimes = {} if self.force_rescan else get_cached_mtimes(conn)
            scanned_paths: Set[str] = set()

            for i, file_path in enumerate(audio_files, start=1):
                if self._is_cancelled:
                    break

                resolved_path = str(Path(file_path).resolve())
                scanned_paths.add(resolved_path)

                self.progress.emit(i, total_files, Path(file_path).name)

                try:
                    curr_mtime = os.path.getmtime(file_path)
                except Exception:
                    curr_mtime = 0.0

                # Check if we can skip parsing
                if not self.force_rescan and resolved_path in cached_mtimes:
                    if abs(cached_mtimes[resolved_path] - curr_mtime) < 0.01:
                        continue

                # Read tags and upsert
                try:
                    track_data = read_tags(file_path)
                    upsert_track(conn, track_data)
                except Exception as e:
                    print(f"Failed to scan {file_path}: {e}")

                if i % 20 == 0:
                    conn.commit()

            conn.commit()

            # Smart compilation check only on a full scan; a partial scan must
            # not rewrite metadata belonging to other library folders.
            if len(self.delete_scope) >= len(getattr(config, "library_paths", [])):
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT album FROM tracks
                    WHERE album_artist = ? OR album_artist = artist
                    GROUP BY album
                    HAVING COUNT(DISTINCT artist) > 1 AND album != ?
                """, (NO_DATA, NO_DATA))
                for row in cursor.fetchall():
                    comp_album = row["album"]
                    cursor.execute("""
                        UPDATE tracks
                        SET album_artist = 'Various Artists', compilation = 1
                        WHERE album = ? AND (album_artist = ? OR album_artist = artist)
                    """, (comp_album, NO_DATA))
                conn.commit()

            # Never drop tracks that live under a configured library root which is
            # currently unavailable (unplugged drive, network share, ...).
            missing_roots = [p for p in roots if p not in valid_roots]
            if missing_roots:
                cursor.execute("SELECT file_path FROM tracks")
                for row in cursor.fetchall():
                    existing_path = row["file_path"]
                    for missing_root in missing_roots:
                        try:
                            Path(existing_path).resolve().relative_to(missing_root.resolve())
                            scanned_paths.add(existing_path)
                            break
                        except Exception:
                            continue

            self.status_text.emit("Synchronizing deleted files...")
            deleted_count = delete_missing_tracks(conn, scanned_paths, roots=self.delete_scope)

            # Recompute the "files need to be organized" flag for the library layout.
            template = self.naming_format or getattr(config, "track_naming_format", "<track_no>. <title>")
            try:
                # Use every configured root (not just currently mounted ones) so
                # tracks on an unplugged drive keep their "organized" state.
                flag_roots = list(dict.fromkeys(
                    list(self.library_paths) + list(getattr(config, "library_paths", []))
                ))
                refresh_organization_flags(conn, flag_roots, template)
            except Exception as exc:
                print(f"Failed to refresh organization flags: {exc}")

            self.finished_scan.emit(total_files, deleted_count)
        except Exception as e:
            self.error.emit(f"Error during scan: {e}")
        finally:
            conn.close()
