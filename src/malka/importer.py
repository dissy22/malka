"""
Album import engine for Malka.
Handles Variant 1 (direct MP3/M4A/FLAC files) and Variant 2 (FLAC + CUE image conversion via QAAC).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_CONVERSION_WORKERS = max(1, min(8, os.cpu_count() or 4))

from malka.config import NO_DATA, config
from malka.cue import (
    CueAlbum,
    CueTrack,
    cue_time_to_seconds,
    get_embedded_cuesheet,
    get_embedded_flac_cuesheet,
    parse_cue_file,
    parse_m3u_file,
)
from malka.db import (
    clear_import_tracks,
    get_connection,
    get_import_tracks,
    insert_import_track,
    upsert_track,
)
from malka.organizer import format_track_filename, is_album_ready_to_organize, sanitize_filename
from malka.tags import (
    detect_and_fix_encoding,
    find_folder_artwork,
    get_audio_stream_info,
    read_tags,
    save_cover_cache,
    write_tags,
)

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".mp4", ".flac", ".wv", ".ape"}
LOSSLESS_IMAGE_EXTS = {".flac", ".wv", ".ape"}


@dataclass
class ImportAnalysisResult:
    variant: int  # 1 (direct audio files) or 2 (FLAC + CUE conversion)
    album: str
    album_artist: str
    year: str
    genre: str
    disc_no: str = "1"
    disc_total: str = "1"
    compilation: int = 0
    cover_cache_path: str = ""
    source_folder: str = ""
    source_flac_path: Optional[str] = None
    cue_file_path: Optional[str] = None
    sample_rate: int = 44100
    bits_per_sample: int = 16
    target_sample_rate: Optional[int] = None
    tracks: List[Dict[str, Any]] = field(default_factory=list)


def get_codecs_dir() -> Path:
    """Returns the path to the codecs directory within the application."""
    import sys
    exe_codecs = Path(sys.executable).parent / "codecs"
    if exe_codecs.is_dir():
        return exe_codecs
    if hasattr(sys, "_MEIPASS"):
        meipass_codecs = Path(sys._MEIPASS) / "codecs"
        if meipass_codecs.is_dir():
            return meipass_codecs
    pkg_root = Path(__file__).resolve().parents[2]
    cand = pkg_root / "codecs"
    if cand.is_dir():
        return cand
    cand = Path.cwd() / "codecs"
    if cand.is_dir():
        return cand
    return exe_codecs if getattr(sys, "frozen", False) else pkg_root / "codecs"


def find_qaac_executable() -> Optional[Path]:
    """
    Finds qaac64.exe in codecs/qaac/ (Windows only).
    Note: qaac/ in root is removed as requested; only codecs/qaac/ is supported.
    """
    import sys
    if sys.platform != "win32":
        return None

    candidates = [
        get_codecs_dir() / "qaac" / "qaac64.exe",
        Path(sys.executable).parent / "codecs" / "qaac" / "qaac64.exe",
        Path.cwd() / "codecs" / "qaac" / "qaac64.exe",
    ]
    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                return cand.resolve()
        except (OSError, PermissionError):
            continue

    return None


def find_flac_executable() -> Optional[Path]:
    """Finds flac executable in codecs/flac or on system PATH."""
    import sys
    from shutil import which
    flac_name = "flac.exe" if sys.platform == "win32" else "flac"

    candidates = [
        get_codecs_dir() / "flac" / flac_name,
        Path(sys.executable).parent / "codecs" / "flac" / flac_name,
        Path.cwd() / "codecs" / "flac" / flac_name,
    ]
    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                if sys.platform != "win32":
                    try:
                        cand.chmod(0o755)
                    except Exception:
                        pass
                return cand.resolve()
        except (OSError, PermissionError):
            continue

    found = which("flac")
    if found:
        return Path(found).resolve()
    return None


def find_ffmpeg_executable() -> Optional[Path]:
    """Finds ffmpeg in codecs/ffmpeg, imageio_ffmpeg, system PATH, active env, or standard paths."""
    import sys
    from shutil import which

    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

    # 1. Check local codecs/ffmpeg directory
    candidates = [
        get_codecs_dir() / "ffmpeg" / ffmpeg_name,
        Path(sys.executable).parent / "codecs" / "ffmpeg" / ffmpeg_name,
        Path.cwd() / "codecs" / "ffmpeg" / ffmpeg_name,
    ]
    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                if sys.platform != "win32":
                    try:
                        cand.chmod(0o755)
                    except Exception:
                        pass
                return cand.resolve()
        except (OSError, PermissionError):
            continue

    # 2. Check bundled imageio_ffmpeg (universal fallback)
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_bin and Path(ffmpeg_bin).exists():
            return Path(ffmpeg_bin).resolve()
    except Exception:
        pass

    # 3. Search system PATH
    found = which("ffmpeg")
    if found:
        return Path(found).resolve()

    # 4. Check virtualenv or active Python environment
    try:
        venv_bin = Path(sys.prefix) / "bin" / ffmpeg_name
        if venv_bin.exists() and venv_bin.is_file():
            return venv_bin.resolve()
    except (OSError, PermissionError):
        pass

    if hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix:
        try:
            base_bin = Path(sys.base_prefix) / "bin" / ffmpeg_name
            if base_bin.exists() and base_bin.is_file():
                return base_bin.resolve()
        except (OSError, PermissionError):
            pass

    # 5. Standard Linux / Unix / macOS paths
    home = Path.home()
    candidates = [
        Path("/usr/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
        Path("/snap/bin/ffmpeg"),
        Path("/var/lib/snapd/snap/bin/ffmpeg"),
        Path("/var/lib/flatpak/exports/bin/ffmpeg"),
        home / ".local" / "share" / "flatpak" / "exports" / "bin" / "ffmpeg",
        home / ".local" / "bin" / "ffmpeg",
        home / "bin" / "ffmpeg",
        Path("/home/linuxbrew/.linuxbrew/bin/ffmpeg"),
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/opt/ffmpeg/bin/ffmpeg"),
        Path("/opt/ffmpeg/ffmpeg"),
        home / ".nix-profile" / "bin" / "ffmpeg",
        Path("/nix/var/nix/profiles/default/bin/ffmpeg"),
    ]
    if sys.platform == "win32":
        candidates.extend([
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\ffmpeg\ffmpeg.exe"),
        ])

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        except (OSError, PermissionError):
            continue

    return None


def get_audio_encoder(source_ext: Optional[str] = None) -> Tuple[Optional[str], Optional[Path]]:
    """
    Determines audio encoder to use:
    - On Windows, if codecs/qaac/ contains qaac64.exe, QAAC is used.
      (FFmpeg acts as the stream decoder when needed, e.g. for .wv/.ape).
    - Otherwise, FFmpeg is used across all platforms.
    Returns (encoder_type, executable_path).
    """
    import sys
    ffmpeg = find_ffmpeg_executable()

    if sys.platform == "win32":
        qaac = find_qaac_executable()
        if qaac:
            return "qaac", qaac
        if ffmpeg:
            return "ffmpeg", ffmpeg
        return None, None
    else:
        if ffmpeg:
            return "ffmpeg", ffmpeg
        return None, None


def get_audio_encoder_label(source_ext: Optional[str] = None) -> str:
    """Returns a user-friendly label of the current encoder and settings."""
    enc_type, _ = get_audio_encoder(source_ext)
    if enc_type == "qaac":
        return "QAAC (-v 224 kbps AAC)"
    if enc_type == "ffmpeg":
        return "FFmpeg native AAC (-c:a aac -b:a 224k)"
    return "FFmpeg / QAAC (not found)"



def compute_resampling_rate(source_sample_rate: int) -> Optional[int]:
    """
    Computes QAAC output sample rate according to rules:
    - 44.1 kHz (44100) or 48 kHz (48000) -> None (keep as is)
    - Above 48 kHz (> 48000):
        If divisible by 44100 (e.g. 88200, 176400) -> 44100
        If divisible by 48000 (e.g. 96000, 192000) -> 48000
        Else -> 44100
    """
    if source_sample_rate <= 48000:
        return None
    if source_sample_rate % 44100 == 0:
        return 44100
    if source_sample_rate % 48000 == 0:
        return 48000
    return 44100


def analyze_import_folder(folder_path: str, db_conn) -> ImportAnalysisResult:
    """
    Analyzes an album directory dropped or selected for import.
    Determines Variant 1 vs Variant 2, extracts tags, and populates SQLite import_tracks.
    """
    folder = Path(folder_path).resolve()
    if not folder.is_dir():
        raise ValueError(f"Path is not a directory: {folder_path}")

    # Gather files
    all_files = [f for f in folder.rglob("*") if f.is_file()]
    audio_files = [f for f in all_files if f.suffix.lower() in AUDIO_EXTENSIONS]
    lossless_files = [f for f in all_files if f.suffix.lower() in LOSSLESS_IMAGE_EXTS]
    cue_files = [f for f in all_files if f.suffix.lower() == ".cue"]
    m3u_files = [f for f in all_files if f.suffix.lower() in (".m3u", ".m3u8")]

    # Find folder artwork if present
    artwork_path = find_folder_artwork(str(folder))
    cover_cache = ""
    if artwork_path and Path(artwork_path).exists():
        try:
            with open(artwork_path, "rb") as af:
                data = af.read()
            ext = Path(artwork_path).suffix.lstrip(".").lower()
            cover_cache = save_cover_cache(data, ext if ext in ("jpg", "png") else "jpg")
        except Exception:
            pass

    # Clear prior staging tracks
    clear_import_tracks(db_conn)

    # 1. Determine if this is Variant 2 (FLAC / WV / APE + CUE image)
    # Variant 2 criteria:
    # A single lossless file (.flac, .wv, .ape) + a CUE file (or CUE referencing a lossless file),
    # OR 1 lossless file with embedded CUE sheet.
    chosen_cue_path: Optional[Path] = None
    chosen_flac_path: Optional[Path] = None
    is_variant_2 = False

    if cue_files:
        chosen_cue_path = cue_files[0]
        parsed_cue = parse_cue_file(chosen_cue_path)
        if parsed_cue:
            ref_files = parsed_cue.referenced_files
            matched_file = None
            if ref_files:
                for rf in ref_files:
                    rf_name = Path(rf).name.lower()
                    for lf in lossless_files:
                        if lf.name.lower() == rf_name:
                            matched_file = lf
                            break
                    if matched_file:
                        break
                    rf_stem = Path(rf).stem.lower()
                    for lf in lossless_files:
                        if lf.stem.lower() == rf_stem:
                            matched_file = lf
                            break
                    if matched_file:
                        break

            if len(ref_files) <= 1 and (matched_file or lossless_files):
                is_variant_2 = True
                chosen_flac_path = matched_file or lossless_files[0]
            elif len(lossless_files) == 1 and len(audio_files) == 1:
                is_variant_2 = True
                chosen_flac_path = lossless_files[0]
            elif len(ref_files) > 1:
                all_exist = all((folder / rf).exists() or Path(rf).exists() for rf in ref_files)
                if not all_exist and len(lossless_files) == 1:
                    is_variant_2 = True
                    chosen_flac_path = lossless_files[0]
                else:
                    is_variant_2 = False
    elif len(lossless_files) == 1 and len(audio_files) == 1:
        embedded_cue = get_embedded_cuesheet(lossless_files[0])
        if embedded_cue:
            temp_cue = Path(tempfile.gettempdir()) / f"malka_embedded_{lossless_files[0].stem}.cue"
            with open(temp_cue, "w", encoding="utf-8") as f:
                f.write(embedded_cue)
            chosen_cue_path = temp_cue
            chosen_flac_path = lossless_files[0]
            is_variant_2 = True

    # ------------------ Process Variant 2 ------------------
    if is_variant_2 and chosen_cue_path and chosen_flac_path:
        cue_album = parse_cue_file(chosen_cue_path)
        if not cue_album or not cue_album.tracks:
            # Fallback to Variant 1 if cue had no tracks
            is_variant_2 = False
        else:
            stream_info = get_audio_stream_info(str(chosen_flac_path))
            sample_rate = stream_info.get("sample_rate", 44100)
            bits_per_sample = stream_info.get("bits_per_sample", 16)
            target_sr = compute_resampling_rate(sample_rate)

            # If cover is not found in folder, try extracting embedded picture from source audio
            if not cover_cache:
                source_tags = read_tags(str(chosen_flac_path))
                if source_tags.get("has_cover"):
                    cover_cache = source_tags.get("cover_cache_path", "")

            # Stage tracks into SQLite
            for t in cue_album.tracks:
                track_data = {
                    "source_path": str(chosen_flac_path),
                    "file_path": "",
                    "title": t.title,
                    "artist": t.artist,
                    "album_artist": cue_album.album_artist,
                    "album": cue_album.album,
                    "year": cue_album.year,
                    "genre": cue_album.genre,
                    "track_no": t.track_no,
                    "disc_no": t.disc_no,
                    "disc_total": t.disc_total,
                    "compilation": cue_album.compilation,
                    "has_cover": 1 if cover_cache else 0,
                    "cover_cache_path": cover_cache,
                    "source_type": "cue",
                    "cue_track_index": int(re.match(r"^(\d+)", t.track_no).group(1)) if re.match(r"^(\d+)", t.track_no) else 1,
                    "cue_file_path": str(chosen_cue_path),
                    "sample_rate": sample_rate,
                    "bits_per_sample": bits_per_sample,
                    "duration": 0.0,
                    "index01": t.index01 or "00:00:00",
                    "index00": t.index00 or "",
                    "bad_encoding": 1 if any(detect_and_fix_encoding(s_val)[0] for s_val in (t.title, t.artist, cue_album.album_artist, cue_album.album, cue_album.genre) if s_val) else 0,
                }
                insert_import_track(db_conn, track_data)

            staged_tracks = get_import_tracks(db_conn)
            return ImportAnalysisResult(
                variant=2,
                album=cue_album.album,
                album_artist=cue_album.album_artist,
                year=cue_album.year,
                genre=cue_album.genre,
                disc_no=cue_album.disc_no,
                disc_total=cue_album.disc_total,
                compilation=cue_album.compilation,
                cover_cache_path=cover_cache,
                source_folder=str(folder),
                source_flac_path=str(chosen_flac_path),
                cue_file_path=str(chosen_cue_path),
                sample_rate=sample_rate,
                bits_per_sample=bits_per_sample,
                target_sample_rate=target_sr,
                tracks=staged_tracks,
            )

    # ------------------ Process Variant 1 (Direct files) ------------------
    if not audio_files:
        raise ValueError(f"No supported audio files (.mp3, .m4a, .flac, .wv, .ape) found in {folder_path}")

    # Read tags for each file
    read_list = []
    for f in audio_files:
        t = read_tags(str(f))
        stream_info = get_audio_stream_info(str(f))
        t["sample_rate"] = stream_info.get("sample_rate", 44100)
        t["bits_per_sample"] = stream_info.get("bits_per_sample", 16)
        t["duration"] = stream_info.get("duration", 0.0)
        read_list.append(t)

    # Sort tracks by disc_no, track_no, filename
    def _sort_key(item):
        d_raw = item.get("disc_no", "1")
        tr_raw = item.get("track_no", "1")
        try:
            d = int(re.match(r"^(\d+)", str(d_raw)).group(1))
        except Exception:
            d = 1
        try:
            tr = int(re.match(r"^(\d+)", str(tr_raw)).group(1))
        except Exception:
            tr = 1
        return (d, tr, item.get("file_path", ""))

    read_list.sort(key=_sort_key)

    # Pick dominant album-level tags
    album_names = [t["album"] for t in read_list if t["album"] != NO_DATA]
    album_artists = [t["album_artist"] for t in read_list if t["album_artist"] != NO_DATA]
    years = [t["year"] for t in read_list if t["year"] != NO_DATA]
    genres = [t["genre"] for t in read_list if t["genre"] != NO_DATA]
    disc_nos = [t["disc_no"] for t in read_list if t["disc_no"] != "1"]
    disc_totals = [t["disc_total"] for t in read_list if t["disc_total"] != "1"]

    album_title = album_names[0] if album_names else folder.name
    album_art = album_artists[0] if album_artists else NO_DATA
    album_yr = years[0] if years else NO_DATA
    album_gen = genres[0] if genres else NO_DATA
    album_disc_no = disc_nos[0] if disc_nos else "1"
    album_disc_tot = disc_totals[0] if disc_totals else "1"

    # Multi-artist detection -> Various Artists compilation
    distinct_artists = {t["artist"] for t in read_list if t["artist"] != NO_DATA}
    compilation_flag = 0
    if len(distinct_artists) > 1 and (album_art == NO_DATA or album_art == "Various Artists"):
        album_art = "Various Artists"
        compilation_flag = 1
    elif any(t.get("compilation") == 1 for t in read_list):
        compilation_flag = 1

    # Check cover art across tracks if folder artwork not already found
    if not cover_cache:
        for t in read_list:
            if t.get("has_cover") and t.get("cover_cache_path"):
                cover_cache = t["cover_cache_path"]
                break

    # Stage into SQLite
    for t in read_list:
        track_cover = t.get("cover_cache_path") or cover_cache
        has_cov = 1 if track_cover else 0
        track_data = {
            "source_path": t["file_path"],
            "file_path": t["file_path"],
            "title": t["title"],
            "artist": t["artist"],
            "album_artist": album_art if album_art != NO_DATA else t["album_artist"],
            "album": album_title,
            "year": album_yr if album_yr != NO_DATA else t["year"],
            "genre": album_gen if album_gen != NO_DATA else t["genre"],
            "track_no": t["track_no"],
            "disc_no": t.get("disc_no", "1"),
            "disc_total": t.get("disc_total", "1"),
            "compilation": compilation_flag,
            "has_cover": has_cov,
            "cover_cache_path": track_cover,
            "source_type": "files",
            "cue_track_index": None,
            "cue_file_path": None,
            "sample_rate": t.get("sample_rate", 44100),
            "bits_per_sample": t.get("bits_per_sample", 16),
            "duration": t.get("duration", 0.0),
            "bad_encoding": t.get("bad_encoding", 0),
        }
        insert_import_track(db_conn, track_data)

    staged_tracks = get_import_tracks(db_conn)

    # Determine if files contain any lossless audio (.flac, .wv, .ape) -> Variant 3 (Track-by-track conversion)
    has_convertible = any(Path(t["file_path"]).suffix.lower() in LOSSLESS_IMAGE_EXTS for t in read_list)
    variant = 3 if has_convertible else 1

    dominant_sr = read_list[0].get("sample_rate", 44100) if read_list else 44100
    dominant_bits = read_list[0].get("bits_per_sample", 16) if read_list else 16
    for t in read_list:
        if t.get("sample_rate", 44100) > dominant_sr:
            dominant_sr = t.get("sample_rate", 44100)
            dominant_bits = t.get("bits_per_sample", 16)

    target_sr = compute_resampling_rate(dominant_sr) if variant == 3 else None

    return ImportAnalysisResult(
        variant=variant,
        album=album_title,
        album_artist=album_art,
        year=album_yr,
        genre=album_gen,
        disc_no=album_disc_no,
        disc_total=album_disc_tot,
        compilation=compilation_flag,
        cover_cache_path=cover_cache,
        source_folder=str(folder),
        source_flac_path=None,
        cue_file_path=None,
        sample_rate=dominant_sr,
        bits_per_sample=dominant_bits,
        target_sample_rate=target_sr,
        tracks=staged_tracks,
    )


def execute_import(
    analysis: ImportAnalysisResult,
    edited_album: Dict[str, Any],
    edited_tracks: List[Dict[str, Any]],
    library_path: str,
    naming_format: str,
    db_conn,
    progress_callback: Optional[Callable[..., None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    proc_callback: Optional[Callable[[subprocess.Popen], None]] = None,
) -> Tuple[bool, str, List[str]]:
    """
    Executes the album import:
    - Variant 1: Copies files to organized destination, writes updated tags, upserts to DB.
    - Variant 2: Runs QAAC conversion with -v 224 and resampling if > 48kHz, moves to destination, writes tags, upserts to DB.
    Provides real-time progress callbacks and supports non-blocking cancellation.
    """
    if not edited_tracks:
        return False, "No tracks to import.", []

    def report_progress(curr: int, total: int, message: str, detail: str = "", pct: Optional[int] = None):
        if not progress_callback:
            return
        if pct is None:
            pct = int(min(curr / max(total, 1) * 100, 100))
        try:
            # 5-arg signature: (curr, total, message, detail, pct)
            progress_callback(curr, total, message, detail, pct)
        except TypeError:
            try:
                # 4-arg signature: (curr, total, message, detail)
                progress_callback(curr, total, message, detail)
            except TypeError:
                # 3-arg legacy signature: (curr, total, message)
                progress_callback(curr, total, message)

    lib_dir = Path(library_path).resolve()
    lib_dir.mkdir(parents=True, exist_ok=True)

    # Determine if album spans multiple discs
    disc_numbers = set()
    for t in edited_tracks:
        d_val = str(t.get("disc_no", "1")).strip()
        match = re.match(r"^(\d+)", d_val)
        disc_numbers.add(int(match.group(1)) if match else 1)
    is_multi_disc = len(disc_numbers) > 1 or max(disc_numbers, default=1) > 1

    imported_paths: List[str] = []
    total_tracks = len(edited_tracks)

    # Shared cover path from edited_album
    new_cover = edited_album.get("cover_cache_path")
    remove_cov = bool(edited_album.get("remove_cover", False))

    # ------------------ Execute Variant 1 ------------------
    if analysis.variant == 1:
        for idx, track in enumerate(edited_tracks, start=1):
            if cancel_check and cancel_check():
                return False, "Import cancelled by user.", imported_paths

            title = track.get("title", f"Track {idx}")
            base_pct = int((idx - 1) / max(total_tracks, 1) * 100)
            report_progress(
                idx,
                total_tracks,
                f"Importing track {idx}/{total_tracks}: {title}",
                "Copying file to library...",
                base_pct,
            )

            src_file = Path(track.get("source_path", track.get("file_path", "")))
            if not src_file.exists():
                return False, f"Source file not found: {src_file}", imported_paths

            # Destination directory structure
            album_artist_folder = sanitize_filename(track.get("album_artist", "Unknown Artist"))
            year_str = sanitize_filename(track.get("year", "Unknown Year"))
            album_str = sanitize_filename(track.get("album", "Unknown Album"))
            album_folder = f"{year_str} - {album_str}"

            if is_multi_disc:
                disc_num = str(track.get("disc_no", "1")).strip() or "1"
                dest_dir = lib_dir / album_artist_folder / album_folder / f"CD {disc_num}"
            else:
                dest_dir = lib_dir / album_artist_folder / album_folder

            dest_dir.mkdir(parents=True, exist_ok=True)

            # Format track filename
            ext = src_file.suffix.lower()
            fname = format_track_filename(track, naming_format) + ext
            dest_file = dest_dir / fname

            # Copy file
            shutil.copy2(src_file, dest_file)

            # Write tags and artwork
            cover_arg = None
            if not remove_cov:
                if new_cover and Path(new_cover).exists():
                    cover_arg = new_cover

            write_tags(
                str(dest_file),
                title=track.get("title"),
                artist=track.get("artist"),
                album_artist=track.get("album_artist"),
                album=track.get("album"),
                year=track.get("year"),
                genre=track.get("genre"),
                track_no=track.get("track_no"),
                disc_no=track.get("disc_no", "1"),
                disc_total=track.get("disc_total", "1"),
                compilation=int(track.get("compilation", 0)),
                new_cover_path=cover_arg,
                remove_cover=remove_cov,
            )

            # Verify file exists on disk and read final tags
            if not dest_file.exists():
                return False, f"Destination file missing after copy: {dest_file}", imported_paths

            final_tags = read_tags(str(dest_file))
            if track.get("bad_encoding") is not None:
                final_tags["bad_encoding"] = int(track.get("bad_encoding", 0))
            upsert_track(db_conn, final_tags)
            imported_paths.append(str(dest_file))

            done_pct = int(idx / max(total_tracks, 1) * 100)
            report_progress(
                idx,
                total_tracks,
                f"Imported track {idx}/{total_tracks}: {title}",
                f"Completed ({idx}/{total_tracks})",
                done_pct,
            )

    # ------------------ Execute Variant 2 (Conversion: QAAC on Windows / FFmpeg on Linux) ------------------
    elif analysis.variant == 2:
        source_ext = Path(analysis.source_flac_path).suffix.lower() if analysis.source_flac_path else None
        enc_type, enc_path = get_audio_encoder(source_ext)
        ffmpeg_path = find_ffmpeg_executable()

        if not enc_path or not enc_path.exists():
            if sys.platform != "win32":
                return False, "FFmpeg was not found on your system. FFmpeg is required to convert audio.", []
            else:
                return False, "Neither qaac64.exe nor ffmpeg was found in codecs/ or system PATH.", []

        if enc_type == "qaac" and (not ffmpeg_path or not ffmpeg_path.exists()):
            return False, "FFmpeg was not found on your system. FFmpeg is required to decode and slice audio tracks.", []

        cue_path = Path(analysis.cue_file_path)
        if not cue_path.exists():
            return False, f"CUE file not found: {cue_path}", []

        # Temporary folder for conversion
        temp_out = Path(tempfile.mkdtemp(prefix=f"malka_{enc_type}_out_"))
        try:
            target_sr = compute_resampling_rate(analysis.sample_rate)

            cue_album = parse_cue_file(cue_path)
            cue_tracks = cue_album.tracks if cue_album else []

            source_flac = Path(analysis.source_flac_path) if analysis.source_flac_path else None
            if not source_flac or not source_flac.exists():
                cue_parent = cue_path.parent
                for t in edited_tracks:
                    fn = t.get("file_name")
                    if fn and (cue_parent / fn).exists():
                        source_flac = cue_parent / fn
                        break
                if not source_flac or not source_flac.exists():
                    for ext in (".flac", ".wv", ".ape"):
                        matches = list(cue_parent.glob(f"*{ext}"))
                        if matches:
                            source_flac = matches[0]
                            break

            if not source_flac or not source_flac.exists():
                return False, f"Source audio file (.flac, .wv, .ape) not found for CUE: {cue_path}", []

            # Build jobs for multithreaded conversion
            jobs = []
            for idx, track in enumerate(edited_tracks):
                t_num = idx + 1
                t_title = track.get("title", f"Track {t_num}")

                cue_t = cue_tracks[idx] if idx < len(cue_tracks) else None
                if not cue_t and cue_tracks:
                    t_idx = track.get("cue_track_index")
                    if t_idx is not None and 1 <= t_idx <= len(cue_tracks):
                        cue_t = cue_tracks[t_idx - 1]

                start_str = (cue_t.index01 if cue_t and cue_t.index01 else track.get("index01")) or "00:00:00"
                start_sec = cue_time_to_seconds(start_str)
                duration = None
                if idx + 1 < len(cue_tracks):
                    next_cue_t = cue_tracks[idx + 1]
                    next_start_str = next_cue_t.index00 or next_cue_t.index01
                    if next_start_str:
                        next_start = cue_time_to_seconds(next_start_str)
                        if next_start > start_sec:
                            duration = next_start - start_sec
                elif idx + 1 < len(edited_tracks):
                    next_t = edited_tracks[idx + 1]
                    next_start_str = next_t.get("index00") or next_t.get("index01")
                    if next_start_str:
                        next_start = cue_time_to_seconds(next_start_str)
                        if next_start > start_sec:
                            duration = next_start - start_sec

                out_file = temp_out / f"{t_num:02d}.m4a"
                jobs.append({
                    "idx": idx,
                    "t_num": t_num,
                    "t_title": t_title,
                    "start_sec": start_sec,
                    "duration": duration,
                    "out_file": out_file,
                    "source_file": source_flac,
                })

            report_progress(
                0,
                total_tracks,
                f"Starting {enc_type.upper()} multithreaded conversion...",
                f"Converting {total_tracks} tracks (up to {MAX_CONVERSION_WORKERS} simultaneously)...",
                0,
            )

            active_procs = set()
            procs_lock = threading.Lock()
            completed_count = [0]
            count_lock = threading.Lock()
            abort_event = threading.Event()

            def _kill_active():
                with procs_lock:
                    for p in list(active_procs):
                        try:
                            if p.poll() is None:
                                p.kill()
                        except Exception:
                            pass
                    active_procs.clear()

            def _convert_v2_track(job):
                if abort_event.is_set() or (cancel_check and cancel_check()):
                    return False, "Import cancelled by user."

                start_sec = job["start_sec"]
                duration = job["duration"]
                source_file = job["source_file"]
                out_file = job["out_file"]
                t_num = job["t_num"]
                t_title = job["t_title"]

                if enc_type == "qaac":
                    # Decode slice via FFmpeg to WAV and pipe into QAAC (-v 224 kbps)
                    ff_cmd = [
                        str(ffmpeg_path),
                        "-nostats", "-loglevel", "error",
                        "-y",
                        "-ss", f"{start_sec:.3f}",
                        "-i", str(source_file),
                    ]
                    if duration is not None:
                        ff_cmd.extend(["-t", f"{duration:.3f}"])
                    ff_cmd.extend(["-vn", "-f", "wav", "pipe:1"])

                    qaac_cmd = [
                        str(enc_path),
                        "-v", "224",
                    ]
                    if target_sr:
                        qaac_cmd.extend(["-r", str(target_sr)])
                    qaac_cmd.extend(["-o", str(out_file), "-"])

                    try:
                        ff_proc = subprocess.Popen(
                            ff_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        with procs_lock:
                            if abort_event.is_set():
                                try:
                                    ff_proc.kill()
                                except Exception:
                                    pass
                                return False, "Import cancelled by user."
                            active_procs.add(ff_proc)
                        if proc_callback:
                            proc_callback(ff_proc)

                        qaac_proc = subprocess.Popen(
                            qaac_cmd,
                            stdin=ff_proc.stdout,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        with procs_lock:
                            if abort_event.is_set():
                                try:
                                    ff_proc.kill()
                                    qaac_proc.kill()
                                except Exception:
                                    pass
                                return False, "Import cancelled by user."
                            active_procs.add(qaac_proc)
                        if proc_callback:
                            proc_callback(qaac_proc)

                        qaac_out, qaac_err = qaac_proc.communicate()
                        ff_proc.wait()
                        ff_err = ff_proc.stderr.read() if ff_proc.stderr else b""
                        try:
                            if ff_proc.stderr:
                                ff_proc.stderr.close()
                            if ff_proc.stdout:
                                ff_proc.stdout.close()
                        except Exception:
                            pass

                        with procs_lock:
                            active_procs.discard(ff_proc)
                            active_procs.discard(qaac_proc)

                        if abort_event.is_set() or (cancel_check and cancel_check()):
                            return False, "Import cancelled by user."

                        if ff_proc.returncode != 0:
                            err_line = ff_err.decode(errors="replace").strip().splitlines()[-1] if ff_err else "FFmpeg decoder failed"
                            return False, f"FFmpeg decode failed on track {t_num}: {err_line}"

                        if qaac_proc.returncode != 0:
                            err_line = qaac_err.decode(errors="replace").strip().splitlines()[-1] if qaac_err else "QAAC encoder failed"
                            return False, f"QAAC encode failed on track {t_num}: {err_line}"

                    except Exception as e:
                        return False, f"Track {t_num} conversion error: {e}"

                else:
                    # FFmpeg native encode
                    ff_cmd = [
                        str(enc_path), "-y",
                        "-ss", f"{start_sec:.3f}",
                        "-i", str(source_file),
                    ]
                    if duration is not None:
                        ff_cmd.extend(["-t", f"{duration:.3f}"])
                    ff_cmd.extend(["-vn", "-c:a", "aac", "-b:a", "224k"])
                    if target_sr:
                        ff_cmd.extend(["-ar", str(target_sr)])
                    ff_cmd.append(str(out_file))

                    try:
                        ff_proc = subprocess.Popen(
                            ff_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        with procs_lock:
                            if abort_event.is_set():
                                try:
                                    ff_proc.kill()
                                except Exception:
                                    pass
                                return False, "Import cancelled by user."
                            active_procs.add(ff_proc)
                        if proc_callback:
                            proc_callback(ff_proc)

                        _, stderr_data = ff_proc.communicate()

                        with procs_lock:
                            active_procs.discard(ff_proc)

                        if abort_event.is_set() or (cancel_check and cancel_check()):
                            return False, "Import cancelled by user."

                        if ff_proc.returncode != 0:
                            err_line = stderr_data.strip().splitlines()[-1] if stderr_data else "FFmpeg conversion failed"
                            return False, f"FFmpeg conversion failed on track {t_num}: {err_line}"

                    except Exception as e:
                        return False, f"Track {t_num} conversion error: {e}"

                with count_lock:
                    completed_count[0] += 1
                    curr_c = completed_count[0]
                pct = int((curr_c / max(total_tracks, 1)) * 85)
                report_progress(
                    curr_c,
                    total_tracks,
                    f"Converted track {curr_c}/{total_tracks}: {t_title}",
                    f"{enc_type.upper()} encoding ({MAX_CONVERSION_WORKERS} threads)...",
                    pct,
                )
                return True, ""

            with ThreadPoolExecutor(max_workers=MAX_CONVERSION_WORKERS) as executor:
                futures = [executor.submit(_convert_v2_track, job) for job in jobs]
                for future in as_completed(futures):
                    if cancel_check and cancel_check():
                        abort_event.set()
                        _kill_active()
                        return False, "Import cancelled by user.", []
                    ok, err = future.result()
                    if not ok:
                        abort_event.set()
                        _kill_active()
                        return False, err, []

            # Gather converted m4a files
            converted_files = sorted(list(temp_out.glob("*.m4a")))
            if not converted_files:
                return False, f"{enc_type.upper()} completed but no .m4a files were generated.", []

            # Step 2: Organize and write tags (85% to 100%)
            for idx, track in enumerate(edited_tracks):
                if cancel_check and cancel_check():
                    return False, "Import cancelled by user.", imported_paths

                if idx >= len(converted_files):
                    break

                t_num = idx + 1
                t_title = track.get("title", f"Track {t_num}")
                pct = int(85 + (t_num / max(total_tracks, 1)) * 15)

                report_progress(
                    t_num,
                    total_tracks,
                    f"Organizing and tagging {t_num}/{total_tracks}: {t_title}",
                    "Moving to library and embedding tags...",
                    pct,
                )

                m4a_src = converted_files[idx]

                # Destination directory
                album_artist_folder = sanitize_filename(track.get("album_artist", "Unknown Artist"))
                year_str = sanitize_filename(track.get("year", "Unknown Year"))
                album_str = sanitize_filename(track.get("album", "Unknown Album"))
                album_folder = f"{year_str} - {album_str}"

                if is_multi_disc:
                    disc_num = str(track.get("disc_no", "1")).strip() or "1"
                    dest_dir = lib_dir / album_artist_folder / album_folder / f"CD {disc_num}"
                else:
                    dest_dir = lib_dir / album_artist_folder / album_folder

                dest_dir.mkdir(parents=True, exist_ok=True)

                # Format filename with .m4a extension
                fname = format_track_filename(track, naming_format) + ".m4a"
                dest_file = dest_dir / fname

                # Move converted file to final library path
                shutil.move(str(m4a_src), str(dest_file))

                # Apply final user tags and artwork
                cover_arg = None
                if not remove_cov:
                    if new_cover and Path(new_cover).exists():
                        cover_arg = new_cover

                write_tags(
                    str(dest_file),
                    title=track.get("title"),
                    artist=track.get("artist"),
                    album_artist=track.get("album_artist"),
                    album=track.get("album"),
                    year=track.get("year"),
                    genre=track.get("genre"),
                    track_no=track.get("track_no"),
                    disc_no=track.get("disc_no", "1"),
                    disc_total=track.get("disc_total", "1"),
                    compilation=int(track.get("compilation", 0)),
                    new_cover_path=cover_arg,
                    remove_cover=remove_cov,
                )

                # Verify file exists on disk
                if not dest_file.exists():
                    return False, f"File missing after conversion and move: {dest_file}", imported_paths

                final_tags = read_tags(str(dest_file))
                if track.get("bad_encoding") is not None:
                    final_tags["bad_encoding"] = int(track.get("bad_encoding", 0))
                upsert_track(db_conn, final_tags)
                imported_paths.append(str(dest_file))

        finally:
            shutil.rmtree(temp_out, ignore_errors=True)

    # ------------------ Execute Variant 3 (Track-by-track Lossless Conversion) ------------------
    elif analysis.variant == 3:
        any_wv_ape = any(
            Path(t.get("source_path", t.get("file_path", ""))).suffix.lower() in (".wv", ".ape")
            for t in edited_tracks
        )
        source_ext = ".wv" if any_wv_ape else ".flac"
        enc_type, enc_path = get_audio_encoder(source_ext)
        ffmpeg_path = find_ffmpeg_executable()

        if not enc_path or not enc_path.exists():
            if sys.platform != "win32":
                return False, "FFmpeg was not found on your system. Please install or bundle FFmpeg to convert audio.", []
            else:
                return False, "Neither qaac64.exe nor ffmpeg was found in project or system PATH.", []

        if enc_type == "qaac" and any_wv_ape and (not ffmpeg_path or not ffmpeg_path.exists()):
            return False, "FFmpeg was not found on your system. FFmpeg is required to decode .wv/.ape audio.", []

        # Identify all tracks that need conversion (.flac, .wv, .ape)
        flac_entries = []
        for idx, track in enumerate(edited_tracks):
            src_file = Path(track.get("source_path", track.get("file_path", "")))
            if src_file.suffix.lower() in LOSSLESS_IMAGE_EXTS:
                flac_entries.append((idx, track, src_file))

        temp_out = Path(tempfile.mkdtemp(prefix=f"malka_{enc_type}_tracks_"))
        try:
            target_sr = compute_resampling_rate(analysis.sample_rate)

            report_progress(
                0,
                total_tracks,
                f"Starting {enc_type.upper()} multithreaded conversion...",
                f"Converting {len(flac_entries)} lossless tracks (up to {MAX_CONVERSION_WORKERS} simultaneously)...",
                0,
            )

            active_procs = set()
            procs_lock = threading.Lock()
            completed_count = [0]
            count_lock = threading.Lock()
            abort_event = threading.Event()

            def _kill_active_v3():
                with procs_lock:
                    for p in list(active_procs):
                        try:
                            if p.poll() is None:
                                p.kill()
                        except Exception:
                            pass
                    active_procs.clear()

            def _convert_v3_track(entry):
                if abort_event.is_set() or (cancel_check and cancel_check()):
                    return False, "Import cancelled by user."

                orig_idx, track, src_file = entry
                out_name = f"{src_file.stem}.m4a"
                out_file = temp_out / out_name
                t_num = orig_idx + 1
                t_title = track.get("title", src_file.stem)
                ext = src_file.suffix.lower()

                if enc_type == "qaac":
                    if ext in (".wv", ".ape"):
                        # Decode via FFmpeg to WAV and pipe into QAAC (-v 224 kbps)
                        ff_cmd = [
                            str(ffmpeg_path),
                            "-nostats", "-loglevel", "error",
                            "-y",
                            "-i", str(src_file),
                            "-vn", "-f", "wav", "pipe:1",
                        ]
                        qaac_cmd = [
                            str(enc_path),
                            "-v", "224",
                        ]
                        if target_sr:
                            qaac_cmd.extend(["-r", str(target_sr)])
                        qaac_cmd.extend(["-o", str(out_file), "-"])

                        try:
                            ff_proc = subprocess.Popen(
                                ff_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            )
                            with procs_lock:
                                if abort_event.is_set():
                                    try:
                                        ff_proc.kill()
                                    except Exception:
                                        pass
                                    return False, "Import cancelled by user."
                                active_procs.add(ff_proc)
                            if proc_callback:
                                proc_callback(ff_proc)

                            qaac_proc = subprocess.Popen(
                                qaac_cmd,
                                stdin=ff_proc.stdout,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            )
                            with procs_lock:
                                if abort_event.is_set():
                                    try:
                                        ff_proc.kill()
                                        qaac_proc.kill()
                                    except Exception:
                                        pass
                                    return False, "Import cancelled by user."
                                active_procs.add(qaac_proc)
                            if proc_callback:
                                proc_callback(qaac_proc)

                            qaac_out, qaac_err = qaac_proc.communicate()
                            ff_proc.wait()
                            ff_err = ff_proc.stderr.read() if ff_proc.stderr else b""
                            try:
                                if ff_proc.stderr:
                                    ff_proc.stderr.close()
                                if ff_proc.stdout:
                                    ff_proc.stdout.close()
                            except Exception:
                                pass

                            with procs_lock:
                                active_procs.discard(ff_proc)
                                active_procs.discard(qaac_proc)

                            if abort_event.is_set() or (cancel_check and cancel_check()):
                                return False, "Import cancelled by user."

                            if ff_proc.returncode != 0:
                                err_line = ff_err.decode(errors="replace").strip().splitlines()[-1] if ff_err else "FFmpeg decoder failed"
                                return False, f"FFmpeg decode failed on {src_file.name}: {err_line}"

                            if qaac_proc.returncode != 0:
                                err_line = qaac_err.decode(errors="replace").strip().splitlines()[-1] if qaac_err else "QAAC encoder failed"
                                return False, f"QAAC encode failed on {src_file.name}: {err_line}"

                        except Exception as e:
                            return False, f"Track {src_file.name} conversion error: {e}"

                    else:
                        # FLAC decoded natively by QAAC
                        qaac_cmd = [
                            str(enc_path),
                            "-v", "224",
                        ]
                        if target_sr:
                            qaac_cmd.extend(["-r", str(target_sr)])
                        qaac_cmd.extend(["-o", str(out_file), str(src_file)])

                        try:
                            proc = subprocess.Popen(
                                qaac_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            )
                            with procs_lock:
                                if abort_event.is_set():
                                    try:
                                        proc.kill()
                                    except Exception:
                                        pass
                                    return False, "Import cancelled by user."
                                active_procs.add(proc)
                            if proc_callback:
                                proc_callback(proc)

                            _, stderr_data = proc.communicate()

                            with procs_lock:
                                active_procs.discard(proc)

                            if abort_event.is_set() or (cancel_check and cancel_check()):
                                return False, "Import cancelled by user."

                            if proc.returncode != 0:
                                err_line = stderr_data.strip().splitlines()[-1] if stderr_data else "QAAC conversion failed"
                                return False, f"QAAC conversion failed on {src_file.name}: {err_line}"

                        except Exception as e:
                            return False, f"Track {src_file.name} conversion error: {e}"

                else:
                    # FFmpeg native encode
                    ff_cmd = [
                        str(enc_path), "-y",
                        "-i", str(src_file),
                        "-vn", "-c:a", "aac", "-b:a", "224k",
                    ]
                    if target_sr:
                        ff_cmd.extend(["-ar", str(target_sr)])
                    ff_cmd.append(str(out_file))

                    try:
                        ff_proc = subprocess.Popen(
                            ff_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        with procs_lock:
                            if abort_event.is_set():
                                try:
                                    ff_proc.kill()
                                except Exception:
                                    pass
                                return False, "Import cancelled by user."
                            active_procs.add(ff_proc)
                        if proc_callback:
                            proc_callback(ff_proc)

                        _, stderr_data = ff_proc.communicate()

                        with procs_lock:
                            active_procs.discard(ff_proc)

                        if abort_event.is_set() or (cancel_check and cancel_check()):
                            return False, "Import cancelled by user."

                        if ff_proc.returncode != 0:
                            err_line = stderr_data.strip().splitlines()[-1] if stderr_data else "FFmpeg conversion failed"
                            return False, f"FFmpeg conversion failed on {src_file.name}: {err_line}"

                    except Exception as e:
                        return False, f"Track {src_file.name} conversion error: {e}"

                with count_lock:
                    completed_count[0] += 1
                    curr_c = completed_count[0]
                pct = int((curr_c / max(len(flac_entries), 1)) * 85)
                report_progress(
                    curr_c,
                    total_tracks,
                    f"Converted track {curr_c}/{len(flac_entries)}: {t_title}",
                    f"{enc_type.upper()} encoding ({MAX_CONVERSION_WORKERS} threads)...",
                    pct,
                )
                return True, ""

            with ThreadPoolExecutor(max_workers=MAX_CONVERSION_WORKERS) as executor:
                futures = [executor.submit(_convert_v3_track, entry) for entry in flac_entries]
                for future in as_completed(futures):
                    if cancel_check and cancel_check():
                        abort_event.set()
                        _kill_active_v3()
                        return False, "Import cancelled by user.", []
                    ok, err = future.result()
                    if not ok:
                        abort_event.set()
                        _kill_active_v3()
                        return False, err, []

            # Step 2: Organize and write tags (85% to 100%)
            for idx, track in enumerate(edited_tracks):
                if cancel_check and cancel_check():
                    return False, "Import cancelled by user.", imported_paths

                t_num = idx + 1
                t_title = track.get("title", f"Track {t_num}")
                pct = int(85 + (t_num / max(total_tracks, 1)) * 15)

                report_progress(
                    t_num,
                    total_tracks,
                    f"Organizing and tagging {t_num}/{total_tracks}: {t_title}",
                    "Moving to library and embedding tags...",
                    pct,
                )

                src_file = Path(track.get("source_path", track.get("file_path", "")))

                # Destination directory
                album_artist_folder = sanitize_filename(track.get("album_artist", "Unknown Artist"))
                year_str = sanitize_filename(track.get("year", "Unknown Year"))
                album_str = sanitize_filename(track.get("album", "Unknown Album"))
                album_folder = f"{year_str} - {album_str}"

                if is_multi_disc:
                    disc_num = str(track.get("disc_no", "1")).strip() or "1"
                    dest_dir = lib_dir / album_artist_folder / album_folder / f"CD {disc_num}"
                else:
                    dest_dir = lib_dir / album_artist_folder / album_folder

                dest_dir.mkdir(parents=True, exist_ok=True)

                if src_file.suffix.lower() in LOSSLESS_IMAGE_EXTS:
                    # Converted file in temp_out
                    m4a_src = temp_out / (src_file.stem + ".m4a")
                    if not m4a_src.exists():
                        candidates = sorted(list(temp_out.glob("*.m4a")))
                        for cand in candidates:
                            if cand.stem.lower() == src_file.stem.lower():
                                m4a_src = cand
                                break
                        else:
                            if idx < len(candidates):
                                m4a_src = candidates[idx]

                    fname = format_track_filename(track, naming_format) + ".m4a"
                    dest_file = dest_dir / fname
                    shutil.move(str(m4a_src), str(dest_file))
                else:
                    ext = src_file.suffix.lower()
                    fname = format_track_filename(track, naming_format) + ext
                    dest_file = dest_dir / fname
                    shutil.copy2(src_file, dest_file)

                # Apply final user tags and artwork
                cover_arg = None
                if not remove_cov:
                    if new_cover and Path(new_cover).exists():
                        cover_arg = new_cover

                write_tags(
                    str(dest_file),
                    title=track.get("title"),
                    artist=track.get("artist"),
                    album_artist=track.get("album_artist"),
                    album=track.get("album"),
                    year=track.get("year"),
                    genre=track.get("genre"),
                    track_no=track.get("track_no"),
                    disc_no=track.get("disc_no", "1"),
                    disc_total=track.get("disc_total", "1"),
                    compilation=int(track.get("compilation", 0)),
                    new_cover_path=cover_arg,
                    remove_cover=remove_cov,
                )

                if not dest_file.exists():
                    return False, f"File missing after processing: {dest_file}", imported_paths

                final_tags = read_tags(str(dest_file))
                if track.get("bad_encoding") is not None:
                    final_tags["bad_encoding"] = int(track.get("bad_encoding", 0))
                upsert_track(db_conn, final_tags)
                imported_paths.append(str(dest_file))

        finally:
            shutil.rmtree(temp_out, ignore_errors=True)

    # Clear staging table
    clear_import_tracks(db_conn)
    db_conn.commit()

    return True, f"Successfully imported {len(imported_paths)} tracks into library.", imported_paths
