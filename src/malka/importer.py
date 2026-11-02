"""
Album import engine for Malka.

Every import is resolved to one of four source kinds (see :mod:`malka.formats`)
and to a quality mode picked by the user:

* ``copy``              — keep the audio stream untouched (image albums are only split);
* ``lossy``             — encode to MP3 320 or AAC 224, down to the chosen ceiling;
* ``lossless_resample`` — encode to FLAC/ALAC, 16-bit, down to the chosen ceiling;
* ``hires``             — keep the original Hi-Res resolution, re-encode to FLAC/ALAC
                          (only needed for APE/WavPack images).

Nothing is ever upsampled or upscaled.
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
    get_import_tracks,
    insert_import_track,
    upsert_track,
)
from malka.formats import (
    DEFAULT_RATE,
    IMAGE_SOURCE_EXTS,
    IMPORT_SOURCE_EXTS,
    MODE_COPY,
    SOURCE_KIND_FLAC_ALAC,
    SOURCE_KIND_IMAGE_APE_WV,
    SOURCE_KIND_IMAGE_FLAC_ALAC,
    SOURCE_KIND_MP3_M4A,
    encoder_args,
    format_extension,
    format_from_extension,
    is_hires,
    is_lossless_source,
    normalize_settings,
    plan_for,
)
from malka.organizer import format_track_filename, is_track_organized, sanitize_filename
from malka.tags import (
    detect_and_fix_encoding,
    find_folder_artwork,
    get_audio_stream_info,
    read_tags,
    save_cover_cache,
    write_tags,
)

#: Files the importer accepts, by kind. APE/WavPack never enter the library.
AUDIO_EXTENSIONS = IMPORT_SOURCE_EXTS
LOSSLESS_IMAGE_EXTS = IMAGE_SOURCE_EXTS


@dataclass
class ImportAnalysisResult:
    variant: int  # 1 (lossy tracks) / 2 (image + CUE) / 3 (lossless tracks)
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
    tracks: List[Dict[str, Any]] = field(default_factory=list)
    #: One of malka.formats.SOURCE_KINDS — selects the remembered import settings.
    source_kind: str = SOURCE_KIND_MP3_M4A
    #: Quality mode: copy / lossy / lossless_resample / hires.
    mode: str = MODE_COPY
    #: Chosen codec for modes that allow a choice ("" keeps the source format).
    output_format: str = ""
    #: Resampling ceiling picked by the user (44.1 or 48 kHz).
    target_rate: int = DEFAULT_RATE
    #: True when the source is above 48 kHz and/or 16-bit.
    is_hires: bool = False
    #: True when the album is a single image + CUE and must be split.
    is_image_source: bool = False
    #: flac / alac / mp3 / m4a — the format of the source audio.
    source_format: str = ""
    #: Channel count of the source audio (only stereo is supported).
    channels: int = 2

    def __post_init__(self):
        # Keep hand-built analyses (tests, scripts) consistent with the format rules.
        if self.variant == 2:
            self.is_image_source = True
            ext = Path(self.source_flac_path or "").suffix.lower()
            if self.source_kind == SOURCE_KIND_MP3_M4A:
                self.source_kind = (
                    SOURCE_KIND_IMAGE_APE_WV if ext in (".ape", ".wv") else SOURCE_KIND_IMAGE_FLAC_ALAC
                )
            if not self.source_format:
                self.source_format = format_from_extension(ext)
        elif self.variant == 3 and self.source_kind == SOURCE_KIND_MP3_M4A:
            self.source_kind = SOURCE_KIND_FLAC_ALAC

        self.is_hires = self.is_hires or is_hires(self.sample_rate, self.bits_per_sample)
        settings = normalize_settings(
            self.source_kind,
            self.is_hires,
            {"mode": self.mode, "format": self.output_format, "rate": self.target_rate},
        )
        self.mode = settings["mode"]
        self.output_format = settings["format"]
        self.target_rate = settings["rate"]


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
    # Lossless "album images" may also be ALAC inside an .m4a container.
    lossless_files = [
        f
        for f in all_files
        if f.suffix.lower() in LOSSLESS_IMAGE_EXTS
        or (f.suffix.lower() == ".m4a" and is_lossless_source(str(f)))
    ]
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
            channels = int(stream_info.get("channels") or 2)
            if channels != 2:
                raise ValueError(
                    f"Only 2-channel (stereo) audio is supported: "
                    f"'{Path(chosen_flac_path).name}' has {channels} channels."
                )

            # CUE sheets often omit REM DATE/GENRE. Fall back to the tags of the
            # source image so the user does not have to retype them.
            source_tags = read_tags(str(chosen_flac_path))
            if cue_album.year in ("", NO_DATA) and source_tags.get("year") not in ("", NO_DATA):
                cue_album.year = source_tags["year"]
            if cue_album.genre in ("", NO_DATA) and source_tags.get("genre") not in ("", NO_DATA):
                cue_album.genre = source_tags["genre"]
            if cue_album.album in ("", NO_DATA) and source_tags.get("album") not in ("", NO_DATA):
                cue_album.album = source_tags["album"]
            if cue_album.album_artist in ("", NO_DATA) and source_tags.get("album_artist") not in ("", NO_DATA):
                cue_album.album_artist = source_tags["album_artist"]

            # If cover is not found in folder, try extracting embedded picture from source audio
            if not cover_cache:
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
            image_ext = Path(chosen_flac_path).suffix.lower()
            source_kind = (
                SOURCE_KIND_IMAGE_APE_WV
                if image_ext in (".ape", ".wv")
                else SOURCE_KIND_IMAGE_FLAC_ALAC
            )
            hires = is_hires(sample_rate, bits_per_sample)
            settings = normalize_settings(source_kind, hires, config.get_import_settings(source_kind))
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
                tracks=staged_tracks,
                source_kind=source_kind,
                mode=settings["mode"],
                output_format=settings["format"],
                target_rate=settings["rate"],
                is_hires=hires,
                source_format=format_from_extension(image_ext),
                channels=channels,
                is_image_source=True,
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
        t["channels"] = int(stream_info.get("channels") or 2)
        t["duration"] = stream_info.get("duration", 0.0)
        read_list.append(t)

    # Malka only supports stereo music.
    for t in read_list:
        if int(t.get("channels") or 2) != 2:
            raise ValueError(
                f"Only 2-channel (stereo) audio is supported: "
                f"'{Path(t['file_path']).name}' has {t['channels']} channels."
            )

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

    # Any FLAC/ALAC track makes the album "lossless": those tracks may be
    # converted, while MP3/AAC tracks in the same folder are always copied.
    has_lossless = any(is_lossless_source(t["file_path"]) for t in read_list)
    variant = 3 if has_lossless else 1
    source_kind = SOURCE_KIND_FLAC_ALAC if has_lossless else SOURCE_KIND_MP3_M4A

    # The exact source format (for display and for "keep original" imports).
    suffixes = {Path(t["file_path"]).suffix.lower() for t in read_list}
    if len(suffixes) == 1:
        only_ext = next(iter(suffixes))
        source_format = format_from_extension(only_ext)
        if only_ext == ".m4a" and has_lossless:
            source_format = "alac"
    else:
        source_format = "mixed"

    dominant_sr = read_list[0].get("sample_rate", 44100) if read_list else 44100
    dominant_bits = read_list[0].get("bits_per_sample", 16) if read_list else 16
    for t in read_list:
        if t.get("sample_rate", 44100) > dominant_sr:
            dominant_sr = t.get("sample_rate", 44100)
        if t.get("bits_per_sample", 0) > dominant_bits:
            dominant_bits = t.get("bits_per_sample", 0)

    hires = is_hires(dominant_sr, dominant_bits)
    settings = normalize_settings(source_kind, hires, config.get_import_settings(source_kind))

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
        tracks=staged_tracks,
        source_kind=source_kind,
        mode=settings["mode"],
        output_format=settings["format"],
        target_rate=settings["rate"],
        is_hires=hires,
        source_format=source_format,
        channels=2,
        is_image_source=False,
    )


def _destination_dir(lib_dir: Path, track: Dict[str, Any], is_multi_disc: bool) -> Path:
    """<Library>/<Album Artist>/<Year> - <Album>[/CD n]"""
    album_artist_folder = sanitize_filename(track.get("album_artist", "Unknown Artist"))
    year_str = sanitize_filename(track.get("year", "Unknown Year"))
    album_str = sanitize_filename(track.get("album", "Unknown Album"))
    album_folder = f"{year_str} - {album_str}"
    if is_multi_disc:
        disc_num = str(track.get("disc_no", "1")).strip() or "1"
        return lib_dir / album_artist_folder / album_folder / f"CD {disc_num}"
    return lib_dir / album_artist_folder / album_folder


def _cue_slice(track: Dict[str, Any], next_track: Optional[Dict[str, Any]], fallback_start: str) -> Tuple[float, Optional[float]]:
    """Returns (start_seconds, duration_seconds_or_None) for a CUE track."""
    start_str = track.get("index01") or fallback_start or "00:00:00"
    start = cue_time_to_seconds(start_str)
    duration: Optional[float] = None
    if next_track is not None:
        next_str = next_track.get("index00") or next_track.get("index01") or ""
        next_start = cue_time_to_seconds(next_str)
        if next_start > start:
            duration = next_start - start
    return start, duration


def _job_plan(
    analysis: ImportAnalysisResult,
    settings: Dict[str, Any],
    source_format: str,
    source_rate: int,
    source_bits: int,
) -> Dict[str, Any]:
    return plan_for(
        analysis.source_kind,
        bool(analysis.is_hires),
        settings,
        source_format or analysis.source_format or "flac",
        source_rate or analysis.sample_rate,
        source_bits or analysis.bits_per_sample,
    )


def _build_import_jobs(
    analysis: ImportAnalysisResult,
    edited_tracks: List[Dict[str, Any]],
    settings: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Resolves every edited track to a source, an optional CUE slice and a plan."""
    jobs: List[Dict[str, Any]] = []

    if analysis.variant == 2:
        cue_path = Path(analysis.cue_file_path) if analysis.cue_file_path else None
        cue_tracks = []
        if cue_path and cue_path.is_file():
            cue_album = parse_cue_file(cue_path)
            cue_tracks = cue_album.tracks if cue_album else []

        source = Path(analysis.source_flac_path) if analysis.source_flac_path else None
        if (not source or not source.exists()) and cue_path:
            for ext in (".flac", ".wv", ".ape", ".m4a"):
                matches = sorted(cue_path.parent.glob(f"*{ext}"))
                if matches:
                    source = matches[0]
                    break
        if not source or not source.exists():
            raise ValueError(
                f"Source audio file (.flac, .wv, .ape) not found for CUE: {analysis.cue_file_path}"
            )

        plan = _job_plan(
            analysis,
            settings,
            analysis.source_format or format_from_extension(source.suffix),
            analysis.sample_rate,
            analysis.bits_per_sample,
        )
        for idx, track in enumerate(edited_tracks):
            fallback = cue_tracks[idx].index01 if idx < len(cue_tracks) else ""
            start, duration = _cue_slice(
                track,
                edited_tracks[idx + 1] if idx + 1 < len(edited_tracks) else None,
                fallback,
            )
            jobs.append({
                "idx": idx,
                "track": track,
                "src": source,
                "start": start,
                "duration": duration,
                "plan": plan,
                # An image album always needs FFmpeg: either to split or to encode.
                "use_ffmpeg": True,
            })
        return jobs

    for idx, track in enumerate(edited_tracks):
        src = Path(track.get("source_path") or track.get("file_path") or "")
        source_format = format_from_extension(src.suffix)
        sample_rate = int(track.get("sample_rate") or 0)
        bits = int(track.get("bits_per_sample") or 0)
        if sample_rate <= 0 or bits <= 0:
            info = get_audio_stream_info(str(src))
            sample_rate = int(info.get("sample_rate") or 44100)
            bits = int(info.get("bits_per_sample") or 16)

        # Only lossless sources can be re-encoded; MP3/AAC are always copied.
        can_encode = is_lossless_source(str(src))
        plan = _job_plan(analysis, settings, source_format, sample_rate, bits)
        if not can_encode:
            plan = {
                "split": False,
                "copy_stream": True,
                "output_format": source_format,
                "target_rate": None,
                "reduce_bits": False,
            }
        jobs.append({
            "idx": idx,
            "track": track,
            "src": src,
            "start": 0.0,
            "duration": None,
            "plan": plan,
            "use_ffmpeg": not plan["copy_stream"],
        })
    return jobs


def _ffmpeg_command(ffmpeg: Path, job: Dict[str, Any], out_file: Path) -> List[str]:
    plan = job["plan"]
    cmd = [str(ffmpeg), "-nostdin", "-y", "-loglevel", "error"]
    if job["start"] and job["start"] > 0:
        cmd += ["-ss", f"{job['start']:.3f}"]
    cmd += ["-i", str(job["src"])]
    if job["duration"]:
        cmd += ["-t", f"{job['duration']:.3f}"]
    cmd += ["-vn", "-map", "0:a:0"]
    if plan["copy_stream"]:
        cmd += ["-c:a", "copy"]
    else:
        cmd += encoder_args(plan["output_format"], plan["target_rate"], plan["reduce_bits"])
    cmd.append(str(out_file))
    return cmd


def _planned_extension(job: Dict[str, Any]) -> str:
    plan = job["plan"]
    if plan["copy_stream"]:
        return job["src"].suffix.lower()
    return format_extension(plan["output_format"])


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
    """Imports an album into the library using the chosen quality settings.

    The settings come from the import dialog (``edited_album["import_mode"]``,
    ``["import_format"]``, ``["import_rate"]``) and are clamped to the choices
    that are valid for this source. Image albums are always split per CUE track.
    """
    if not edited_tracks:
        return False, "No tracks to import.", []
    if int(getattr(analysis, "channels", 2) or 2) != 2:
        return (
            False,
            f"Only 2-channel (stereo) audio is supported; this album has "
            f"{analysis.channels} channels.",
            [],
        )

    def report_progress(curr: int, total: int, message: str, detail: str = "", pct: Optional[int] = None):
        if not progress_callback:
            return
        if pct is None:
            pct = int(min(curr / max(total, 1) * 100, 100))
        try:
            progress_callback(curr, total, message, detail, pct)
        except TypeError:
            try:
                progress_callback(curr, total, message, detail)
            except TypeError:
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

    total_tracks = len(edited_tracks)
    new_cover = edited_album.get("cover_cache_path")
    remove_cov = bool(edited_album.get("remove_cover", False))

    settings = normalize_settings(
        analysis.source_kind,
        bool(analysis.is_hires),
        {
            "mode": edited_album.get("import_mode") or analysis.mode,
            "format": edited_album.get("import_format") or analysis.output_format,
            "rate": edited_album.get("import_rate") or analysis.target_rate,
        },
    )
    analysis.mode = settings["mode"]
    analysis.output_format = settings["format"]
    analysis.target_rate = settings["rate"]

    try:
        jobs = _build_import_jobs(analysis, edited_tracks, settings)
    except ValueError as exc:
        return False, str(exc), []

    imported_paths: List[str] = []
    ffmpeg_jobs = [job for job in jobs if job["use_ffmpeg"]]
    plan0 = jobs[0]["plan"] if jobs else {}

    # ------------------ FFmpeg phase (0 - 85%) ------------------
    temp_dir: Optional[Path] = None
    if ffmpeg_jobs:
        ffmpeg_path = find_ffmpeg_executable()
        if not ffmpeg_path or not ffmpeg_path.exists():
            return (
                False,
                "FFmpeg was not found on your system. FFmpeg is required to split or convert audio "
                "(FLAC / ALAC / AAC / MP3 and APE/WavPack decoding).",
                [],
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="malka_import_"))
        for job in ffmpeg_jobs:
            job["out_file"] = temp_dir / f"{job['idx']:03d}{_planned_extension(job)}"

        action_label = "Splitting" if plan0.get("copy_stream") and plan0.get("split") else "Converting"
        report_progress(
            0,
            total_tracks,
            f"{action_label} {total_tracks} track(s)...",
            f"Processing {len(ffmpeg_jobs)} file(s) with up to {MAX_CONVERSION_WORKERS} threads...",
            0,
        )

        active_procs = set()
        procs_lock = threading.Lock()
        completed_count = [0]
        count_lock = threading.Lock()
        abort_event = threading.Event()

        def _kill_active():
            with procs_lock:
                for proc in list(active_procs):
                    try:
                        if proc.poll() is None:
                            proc.kill()
                    except Exception:
                        pass
                active_procs.clear()

        def _run_ffmpeg_job(job: Dict[str, Any]) -> Tuple[bool, str]:
            if abort_event.is_set() or (cancel_check and cancel_check()):
                return False, "Import cancelled by user."

            out_file = job["out_file"]
            cmd = _ffmpeg_command(ffmpeg_path, job, out_file)
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as exc:
                return False, f"Could not start FFmpeg: {exc}"

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
                err_line = (stderr_data or "").strip().splitlines()
                reason = err_line[-1] if err_line else "FFmpeg conversion failed"
                return False, f"FFmpeg failed on {job['src'].name}: {reason}"
            if not out_file.exists() or out_file.stat().st_size == 0:
                return False, f"FFmpeg produced no audio for {job['src'].name}"
            return True, ""

        try:
            with ThreadPoolExecutor(max_workers=MAX_CONVERSION_WORKERS) as executor:
                futures = [executor.submit(_run_ffmpeg_job, job) for job in ffmpeg_jobs]
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
                    with count_lock:
                        completed_count[0] += 1
                        done = completed_count[0]
                    pct = int((done / max(len(ffmpeg_jobs), 1)) * 85)
                    report_progress(
                        done,
                        total_tracks,
                        f"Processed {done}/{len(ffmpeg_jobs)} file(s)",
                        f"FFmpeg ({MAX_CONVERSION_WORKERS} threads)...",
                        pct,
                    )
        except Exception as exc:
            return False, f"Conversion error: {exc}", []

    # ------------------ Finalize phase: move/copy, tag, index ------------------
    try:
        for pos, job in enumerate(jobs, start=1):
            if cancel_check and cancel_check():
                return False, "Import cancelled by user.", imported_paths

            track = job["track"]
            title = track.get("title", f"Track {pos}")
            start_pct = 85 if ffmpeg_jobs else 0
            pct = int(start_pct + (pos / max(total_tracks, 1)) * (100 - start_pct))
            report_progress(
                pos,
                total_tracks,
                f"Saving track {pos}/{total_tracks}: {title}",
                "Moving to library and embedding tags...",
                pct,
            )

            dest_dir = _destination_dir(lib_dir, track, is_multi_disc)
            dest_dir.mkdir(parents=True, exist_ok=True)

            src_file: Path = job["src"]
            dest_file = dest_dir / (format_track_filename(track, naming_format) + _planned_extension(job))

            if job["use_ffmpeg"]:
                shutil.move(str(job["out_file"]), str(dest_file))
            elif src_file.resolve() != dest_file.resolve():
                shutil.copy2(src_file, dest_file)

            cover_arg = new_cover if (not remove_cov and new_cover and Path(new_cover).exists()) else None
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
            # Files are placed at their canonical path by definition; verify anyway
            # (the template or album tags may differ from the chosen layout).
            final_tags["is_organized"] = 1 if is_track_organized(
                final_tags, [str(lib_dir)], naming_format, is_multi_disc
            ) else 0
            upsert_track(db_conn, final_tags)
            imported_paths.append(str(dest_file))
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Clear staging table
    clear_import_tracks(db_conn)
    db_conn.commit()

    if ffmpeg_jobs:
        action = "converted" if not plan0.get("copy_stream") else "split"
    else:
        action = "copied unchanged"
    return True, f"Successfully imported {len(imported_paths)} tracks ({action}).", imported_paths
