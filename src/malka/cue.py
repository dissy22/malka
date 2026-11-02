"""
CUE sheet and M3U playlist parser for Malka.
Supports various encodings (UTF-8, CP1251, CP1252, Latin-1).
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from mutagen.flac import FLAC
from malka.config import NO_DATA


@dataclass
class CueTrack:
    track_no: str
    title: str
    artist: str
    file_name: Optional[str] = None
    index01: Optional[str] = None
    index00: Optional[str] = None
    disc_no: str = "1"
    disc_total: str = "1"


@dataclass
class CueAlbum:
    album: str
    album_artist: str
    year: str
    genre: str
    disc_no: str = "1"
    disc_total: str = "1"
    compilation: int = 0
    cue_path: Optional[str] = None
    referenced_files: List[str] = field(default_factory=list)
    tracks: List[CueTrack] = field(default_factory=list)


def _read_file_text(path: Path) -> Optional[str]:
    encodings = ["utf-8-sig", "utf-8", "cp1251", "windows-1251", "cp1252", "latin-1"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    # Fallback with replacement
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def parse_cue_file(cue_path: Path) -> Optional[CueAlbum]:
    """Parses a .cue file and returns a CueAlbum structure."""
    text = _read_file_text(cue_path)
    if not text:
        return None

    album = NO_DATA
    album_artist = NO_DATA
    year = NO_DATA
    genre = NO_DATA
    disc_no = "1"
    disc_total = "1"
    compilation = 0

    referenced_files: List[str] = []
    tracks: List[CueTrack] = []
    current_file: Optional[str] = None
    current_track: Optional[CueTrack] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # REM lines (comments / metadata)
        rem_match = re.match(r"^REM\s+(\w+)\s+(.*)$", line, re.IGNORECASE)
        if rem_match:
            k = rem_match.group(1).upper()
            v = rem_match.group(2).strip('"\'; ')
            if k in ("DATE", "YEAR"):
                year_m = re.search(r"\b(19\d\d|20\d\d)\b", v)
                year = year_m.group(1) if year_m else v
            elif k == "GENRE":
                genre = v if v else NO_DATA
            elif k in ("DISCNUMBER", "DISC"):
                disc_no = v if v else "1"
            elif k in ("TOTALDISCS", "DISCTOTAL"):
                disc_total = v if v else "1"
            elif k in ("COMPILATION", "TCMP") and v.lower() in ("1", "true", "yes"):
                compilation = 1
            continue

        # FILE command
        file_match = re.match(r'^FILE\s+"([^"]+)"\s+(.*)$', line, re.IGNORECASE)
        if not file_match:
            file_match = re.match(r"^FILE\s+(\S+)\s+(.*)$", line, re.IGNORECASE)
        if file_match:
            current_file = file_match.group(1)
            if current_file not in referenced_files:
                referenced_files.append(current_file)
            if current_track and not current_track.index01:
                # In EAC cuesheets, FILE for track N can appear after TRACK N AUDIO (pregap was in previous file)
                current_track.file_name = current_file
            continue

        # TRACK command
        track_match = re.match(r"^TRACK\s+(\d+)\s+AUDIO", line, re.IGNORECASE)
        if track_match:
            if current_track:
                tracks.append(current_track)
            num = int(track_match.group(1))
            current_track = CueTrack(
                track_no=f"{num:02d}",
                title=NO_DATA,
                artist=NO_DATA,
                file_name=current_file,
                disc_no=disc_no,
                disc_total=disc_total,
            )
            continue

        # TITLE command
        title_match = re.match(r'^TITLE\s+"([^"]+)"', line, re.IGNORECASE)
        if not title_match:
            title_match = re.match(r"^TITLE\s+(.*)$", line, re.IGNORECASE)
        if title_match:
            val = title_match.group(1).strip('"\'; ')
            if current_track:
                current_track.title = val if val else NO_DATA
            else:
                album = val if val else NO_DATA
            continue

        # PERFORMER command
        perf_match = re.match(r'^PERFORMER\s+"([^"]+)"', line, re.IGNORECASE)
        if not perf_match:
            perf_match = re.match(r"^PERFORMER\s+(.*)$", line, re.IGNORECASE)
        if perf_match:
            val = perf_match.group(1).strip('"\'; ')
            if current_track:
                current_track.artist = val if val else NO_DATA
            else:
                album_artist = val if val else NO_DATA
            continue

        # INDEX 01
        index01_m = re.match(r"^INDEX\s+01\s+(\d{2}:\d{2}:\d{2})", line, re.IGNORECASE)
        if index01_m and current_track:
            current_track.index01 = index01_m.group(1)
            continue

        # INDEX 00
        index00_m = re.match(r"^INDEX\s+00\s+(\d{2}:\d{2}:\d{2})", line, re.IGNORECASE)
        if index00_m and current_track:
            current_track.index00 = index00_m.group(1)
            continue

    if current_track:
        tracks.append(current_track)

    # Check compilation if multiple distinct track artists exist
    distinct_artists = {t.artist for t in tracks if t.artist != NO_DATA}
    if len(distinct_artists) > 1 and album_artist == NO_DATA:
        album_artist = "Various Artists"
        compilation = 1

    # Fill default track artist from album artist if missing
    for t in tracks:
        if t.artist == NO_DATA and album_artist != NO_DATA:
            t.artist = album_artist
        t.disc_no = disc_no
        t.disc_total = disc_total

    return CueAlbum(
        album=album,
        album_artist=album_artist,
        year=year,
        genre=genre,
        disc_no=disc_no,
        disc_total=disc_total,
        compilation=compilation,
        cue_path=str(cue_path.resolve()),
        referenced_files=referenced_files,
        tracks=tracks,
    )


def parse_m3u_file(m3u_path: Path) -> List[Dict[str, Any]]:
    """Parses an .m3u / .m3u8 playlist file."""
    text = _read_file_text(m3u_path)
    if not text:
        return []

    entries: List[Dict[str, Any]] = []
    current_artist = None
    current_title = None
    current_duration = 0.0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTINF:"):
            # Format: #EXTINF:123,Artist - Title  or  #EXTINF:123,Title
            match = re.match(r"^#EXTINF:(-?\d+(?:\.\d+)?)\s*,\s*(.*)$", line)
            if match:
                try:
                    current_duration = float(match.group(1))
                except Exception:
                    current_duration = 0.0
                info = match.group(2).strip()
                if " - " in info:
                    parts = info.split(" - ", 1)
                    current_artist = parts[0].strip()
                    current_title = parts[1].strip()
                else:
                    current_title = info
            continue

        if line.startswith("#"):
            continue

        # Audio file reference
        entries.append({
            "file_name": line,
            "artist": current_artist,
            "title": current_title,
            "duration": current_duration,
        })
        current_artist = None
        current_title = None
        current_duration = 0.0

    return entries


def get_embedded_flac_cuesheet(flac_path: Path) -> Optional[str]:
    """Extracts embedded cuesheet text from a FLAC file if present."""
    try:
        audio = FLAC(str(flac_path))
        if hasattr(audio, "cuesheet") and audio.cuesheet:
            return str(audio.cuesheet)
        for key in audio.keys():
            if key.lower() == "cuesheet":
                vals = audio.get(key)
                if vals:
                    return vals[0]
    except Exception:
        pass
    return None


def get_embedded_wv_cuesheet(wv_path: Path) -> Optional[str]:
    """Extracts embedded cuesheet text from a WavPack file if present."""
    try:
        from mutagen.wavpack import WavPack
        audio = WavPack(str(wv_path))
        for key in audio.keys():
            if key.lower() == "cuesheet":
                val = audio[key]
                if hasattr(val, "value"):
                    v = val.value
                    if isinstance(v, bytes):
                        return v.decode("utf-8", errors="replace")
                    return str(v)
                if isinstance(val, list) and val:
                    return str(val[0])
                return str(val)
    except Exception:
        pass
    return None


def get_embedded_ape_cuesheet(ape_path: Path) -> Optional[str]:
    """Extracts embedded cuesheet text from a Monkey's Audio file if present."""
    try:
        from mutagen.monkeysaudio import MonkeysAudio
        audio = MonkeysAudio(str(ape_path))
        for key in audio.keys():
            if key.lower() == "cuesheet":
                val = audio[key]
                if hasattr(val, "value"):
                    v = val.value
                    if isinstance(v, bytes):
                        return v.decode("utf-8", errors="replace")
                    return str(v)
                if isinstance(val, list) and val:
                    return str(val[0])
                return str(val)
    except Exception:
        pass
    return None


def get_embedded_cuesheet(audio_path: Path) -> Optional[str]:
    """Extracts embedded cuesheet from .flac, .wv, or .ape file if present."""
    ext = audio_path.suffix.lower()
    if ext == ".flac":
        return get_embedded_flac_cuesheet(audio_path)
    elif ext == ".wv":
        return get_embedded_wv_cuesheet(audio_path)
    elif ext == ".ape":
        return get_embedded_ape_cuesheet(audio_path)
    return None


def cue_time_to_seconds(ts: Optional[str]) -> float:
    """
    Converts a CUE sheet timestamp string (MM:SS:FF) into seconds.
    FF represents CD frames (75 frames per second).
    """
    if not ts:
        return 0.0
    parts = str(ts).strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60.0 + int(parts[1]) + int(parts[2]) / 75.0
        elif len(parts) == 2:
            return int(parts[0]) * 60.0 + float(parts[1])
        return float(ts)
    except (ValueError, TypeError):
        return 0.0

