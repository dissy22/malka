import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import mutagen
from mutagen.flac import FLAC, Picture as FLACPicture
from mutagen.wavpack import WavPack
from mutagen.monkeysaudio import MonkeysAudio
from mutagen.id3 import (
    ID3,
    ID3NoHeaderError,
    TIT2,
    TPE1,
    TPE2,
    TALB,
    TDRC,
    TYER,
    TCON,
    TRCK,
    TPOS,
    TCMP,
    APIC,
    PictureType,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from malka.config import CACHE_DIR, NO_DATA


def _clean_str(val: Any) -> str:
    if val is None:
        return NO_DATA
    s = str(val).strip()
    return s if s else NO_DATA


def _format_track_num(val: Any) -> str:
    if not val:
        return NO_DATA
    s = str(val).strip()
    # Handle "3/12" or "03"
    match = re.match(r"^(\d+)", s)
    if match:
        try:
            num = int(match.group(1))
            return f"{num:02d}"
        except ValueError:
            pass
    return s if s else NO_DATA


def _format_year(val: Any) -> str:
    if not val:
        return NO_DATA
    s = str(val).strip()
    match = re.search(r"\b(19\d\d|20\d\d)\b", s)
    if match:
        return match.group(1)
    return s if s else NO_DATA


def is_cyrillic_word(w: str) -> bool:
    has_cyr = bool(re.search(r"[\u0400-\u04FF]", w))
    has_lat = bool(re.search(r"[a-zA-Z]", w))
    return has_cyr and not has_lat


def detect_and_fix_encoding(text: Any) -> Tuple[bool, str]:
    """
    Detects if a string is mojibake (e.g. Russian CP1251 decoded as Latin1 / ISO-8859-1 or UTF-8 decoded as CP1251).
    Returns (is_bad, fixed_text).
    """
    if not text or not isinstance(text, str):
        return False, str(text) if text is not None else NO_DATA

    s = text.strip()
    if not s or s == NO_DATA:
        return False, s

    mojibake_chars_re = re.compile(r"[\u00C0-\u00FF]")
    if not mojibake_chars_re.search(s) and "Р" not in s and "С" not in s:
        return False, s

    candidates = []

    # 1. Latin1 / CP1252 -> CP1251 / CP866
    for enc in ("latin1", "cp1252"):
        try:
            raw = s.encode(enc)
            decoded = raw.decode("cp1251")
            candidates.append((decoded, "latin1_cp1251"))
        except Exception:
            pass
        try:
            raw = s.encode(enc)
            decoded = raw.decode("cp866")
            candidates.append((decoded, "latin1_cp866"))
        except Exception:
            pass

    # 2. CP1251 -> UTF-8
    try:
        raw = s.encode("cp1251")
        decoded = raw.decode("utf-8")
        candidates.append((decoded, "cp1251_utf8"))
    except Exception:
        pass

    # 3. CP1252 -> UTF-8
    try:
        raw = s.encode("cp1252")
        decoded = raw.decode("utf-8")
        candidates.append((decoded, "cp1252_utf8"))
    except Exception:
        pass

    cyrillic_re = re.compile(r"[\u0400-\u04FF]")
    orig_cyr = len(cyrillic_re.findall(s))

    best_candidate = None
    best_score = 0

    for cand, method in candidates:
        if cand == s:
            continue

        words = re.findall(r"\b\w+\b", cand, re.UNICODE)
        if not words:
            continue

        cyr_words = [w for w in words if is_cyrillic_word(w)]
        mixed_words = [w for w in words if re.search(r"[\u0400-\u04FF]", w) and re.search(r"[a-zA-Z]", w)]

        if mixed_words:
            continue

        total_cyr_letters = sum(len(cyrillic_re.findall(w)) for w in cyr_words)
        if total_cyr_letters >= 2 and len(cyr_words) > 0:
            score = total_cyr_letters - orig_cyr
            if score > best_score:
                best_score = score
                best_candidate = cand

    if best_candidate and best_score >= 2:
        return True, best_candidate

    return False, s


def save_cover_cache(data: bytes, ext: str = "jpg") -> str:
    if not data:
        return ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(data).hexdigest()
    cache_file = CACHE_DIR / f"{h}.{ext}"
    if not cache_file.exists():
        with open(cache_file, "wb") as f:
            f.write(data)
    return str(cache_file)


def read_tags(file_path: str) -> Dict[str, Any]:
    path = Path(file_path)
    ext = path.suffix.lower()

    result = {
        "file_path": str(path.resolve()),
        "title": NO_DATA,
        "artist": NO_DATA,
        "album_artist": NO_DATA,
        "album": NO_DATA,
        "year": NO_DATA,
        "genre": NO_DATA,
        "comment": "",
        "track_no": NO_DATA,
        "disc_no": "1",
        "disc_total": "1",
        "compilation": 0,
        "has_cover": 0,
        "cover_cache_path": "",
        "mtime": 0.0,
        "duration": 0.0,
        "bad_encoding": 0,
    }

    try:
        result["mtime"] = path.stat().st_mtime
    except Exception:
        pass

    try:
        if ext == ".mp3":
            _read_mp3_tags(file_path, result)
        elif ext in (".m4a", ".aac", ".mp4"):
            _read_mp4_tags(file_path, result)
        elif ext == ".flac":
            _read_flac_tags(file_path, result)
        elif ext == ".wv":
            _read_apev2_tags(file_path, result, is_wv=True)
        elif ext == ".ape":
            _read_apev2_tags(file_path, result, is_wv=False)
    except Exception as e:
        print(f"Error reading tags from {file_path}: {e}")

    # Detect & fix character encoding issues (mojibake)
    has_bad = False
    for k in ("title", "artist", "album_artist", "album", "genre", "comment"):
        val = result.get(k)
        if val and val != NO_DATA:
            bad, fixed = detect_and_fix_encoding(val)
            if bad:
                has_bad = True
                result[k] = fixed

    result["bad_encoding"] = 1 if has_bad else 0

    # Compilation handling
    if result["compilation"] == 1:
        if result["album_artist"] == NO_DATA or not result["album_artist"]:
            result["album_artist"] = "Various Artists"

    # Fallback: if album_artist is missing, but artist is present, or vice-versa
    if result["album_artist"] == NO_DATA and result["artist"] != NO_DATA:
        result["album_artist"] = result["artist"]

    return result


def _read_mp3_tags(file_path: str, result: Dict[str, Any]) -> None:
    try:
        audio = MP3(file_path)
    except Exception:
        return

    if hasattr(audio, "info") and hasattr(audio.info, "length"):
        result["duration"] = float(audio.info.length)

    if not audio.tags:
        return

    tags = audio.tags

    if "TIT2" in tags and tags["TIT2"].text:
        result["title"] = _clean_str(tags["TIT2"].text[0])

    if "TPE1" in tags and tags["TPE1"].text:
        result["artist"] = _clean_str(tags["TPE1"].text[0])

    if "TPE2" in tags and tags["TPE2"].text:
        result["album_artist"] = _clean_str(tags["TPE2"].text[0])

    if "TALB" in tags and tags["TALB"].text:
        result["album"] = _clean_str(tags["TALB"].text[0])

    # Year (TDRC or TYER)
    year_val = None
    if "TDRC" in tags and tags["TDRC"].text:
        year_val = tags["TDRC"].text[0]
    elif "TYER" in tags and tags["TYER"].text:
        year_val = tags["TYER"].text[0]
    result["year"] = _format_year(year_val)

    if "TCON" in tags and tags["TCON"].text:
        result["genre"] = _clean_str(tags["TCON"].text[0])

    if "TRCK" in tags and tags["TRCK"].text:
        result["track_no"] = _format_track_num(tags["TRCK"].text[0])

    # Disc number (TPOS)
    if "TPOS" in tags and tags["TPOS"].text:
        raw_disc = str(tags["TPOS"].text[0]).strip()
        match = re.match(r"^(\d+)(?:/(\d+))?", raw_disc)
        if match:
            result["disc_no"] = str(int(match.group(1)))
            if match.group(2):
                result["disc_total"] = str(int(match.group(2)))

    # Compilation flag (TCMP)
    if "TCMP" in tags and tags["TCMP"].text:
        val = str(tags["TCMP"].text[0]).strip().lower()
        if val in ("1", "true", "yes"):
            result["compilation"] = 1

    # Comment (COMM); prefer a non-empty regular comment over metadata blobs.
    try:
        comment_frames = tags.getall("COMM") if hasattr(tags, "getall") else []
        for frame in comment_frames:
            desc = str(getattr(frame, "desc", "") or "").lower()
            if any(marker in desc for marker in ("itunnorm", "itunsmpb", "itunes_cddb")):
                continue
            for text in getattr(frame, "text", []) or []:
                comment = str(text).strip()
                if comment:
                    result["comment"] = comment
                    break
            if result["comment"]:
                break
    except Exception:
        pass

    # Cover art
    for key in tags.keys():
        if key.startswith("APIC"):
            apic = tags[key]
            if apic.data:
                img_ext = "png" if "png" in (apic.mime or "").lower() else "jpg"
                cache_path = save_cover_cache(apic.data, img_ext)
                result["has_cover"] = 1
                result["cover_cache_path"] = cache_path
                break


def _read_mp4_tags(file_path: str, result: Dict[str, Any]) -> None:
    try:
        audio = MP4(file_path)
    except Exception:
        return

    if hasattr(audio, "info") and hasattr(audio.info, "length"):
        result["duration"] = float(audio.info.length)

    tags = audio.tags
    if not tags:
        return

    if "\xa9nam" in tags and tags["\xa9nam"]:
        result["title"] = _clean_str(tags["\xa9nam"][0])

    if "\xa9ART" in tags and tags["\xa9ART"]:
        result["artist"] = _clean_str(tags["\xa9ART"][0])

    if "aART" in tags and tags["aART"]:
        result["album_artist"] = _clean_str(tags["aART"][0])

    if "\xa9alb" in tags and tags["\xa9alb"]:
        result["album"] = _clean_str(tags["\xa9alb"][0])

    if "\xa9day" in tags and tags["\xa9day"]:
        result["year"] = _format_year(tags["\xa9day"][0])

    if "\xa9gen" in tags and tags["\xa9gen"]:
        result["genre"] = _clean_str(tags["\xa9gen"][0])

    if "trkn" in tags and tags["trkn"]:
        try:
            t = tags["trkn"][0]
            if isinstance(t, (tuple, list)) and len(t) > 0 and t[0]:
                result["track_no"] = f"{int(t[0]):02d}"
        except Exception:
            pass

    # Disc number ('disk')
    if "disk" in tags and tags["disk"]:
        try:
            d = tags["disk"][0]
            if isinstance(d, (tuple, list)) and len(d) > 0 and d[0]:
                result["disc_no"] = str(int(d[0]))
                if len(d) > 1 and d[1]:
                    result["disc_total"] = str(int(d[1]))
        except Exception:
            pass

    # Compilation flag ('cpil')
    if "cpil" in tags and tags["cpil"]:
        result["compilation"] = 1 if tags["cpil"] else 0

    # Comment ('©cmt')
    if "\xa9cmt" in tags and tags["\xa9cmt"]:
        result["comment"] = _clean_str(tags["\xa9cmt"][0]) if tags["\xa9cmt"][0] else ""

    # Cover art
    if "covr" in tags and tags["covr"]:
        covr_data = tags["covr"][0]
        img_ext = "png" if getattr(covr_data, "imageformat", None) == MP4Cover.FORMAT_PNG else "jpg"
        cache_path = save_cover_cache(bytes(covr_data), img_ext)
        result["has_cover"] = 1
        result["cover_cache_path"] = cache_path


def _read_flac_tags(file_path: str, result: Dict[str, Any]) -> None:
    try:
        audio = FLAC(file_path)
    except Exception:
        return

    if hasattr(audio, "info") and hasattr(audio.info, "length"):
        result["duration"] = float(audio.info.length)

    def _get(keys: list) -> Optional[str]:
        for k in keys:
            vals = audio.get(k)
            if vals:
                return vals[0]
        return None

    title = _get(["title"])
    if title:
        result["title"] = _clean_str(title)

    artist = _get(["artist"])
    if artist:
        result["artist"] = _clean_str(artist)

    album_artist = _get(["albumartist", "album artist", "ensemble"])
    if album_artist:
        result["album_artist"] = _clean_str(album_artist)

    album = _get(["album"])
    if album:
        result["album"] = _clean_str(album)

    date = _get(["date", "year"])
    if date:
        result["year"] = _format_year(date)

    genre = _get(["genre"])
    if genre:
        result["genre"] = _clean_str(genre)

    comment = _get(["comment", "description"])
    if comment:
        result["comment"] = str(comment).strip()

    # Track number & total
    track_num = _get(["tracknumber", "track"])
    if track_num:
        result["track_no"] = _format_track_num(track_num)

    # Disc number & total
    disc_num = _get(["discnumber", "disc"])
    if disc_num:
        match = re.match(r"^(\d+)(?:/(\d+))?", str(disc_num).strip())
        if match:
            result["disc_no"] = match.group(1)
            if match.group(2):
                result["disc_total"] = match.group(2)
        else:
            result["disc_no"] = str(disc_num).strip()

    disc_tot = _get(["disctotal", "totaldiscs"])
    if disc_tot:
        try:
            result["disc_total"] = str(int(str(disc_tot).strip()))
        except Exception:
            pass

    # Compilation
    comp = _get(["compilation"])
    if comp and str(comp).strip() in ("1", "true", "True", "yes"):
        result["compilation"] = 1

    # Cover art
    if audio.pictures:
        front_pics = [p for p in audio.pictures if p.type == PictureType.COVER_FRONT]
        pic = front_pics[0] if front_pics else audio.pictures[0]
        img_ext = "png" if pic.mime == "image/png" else "jpg"
        cache_path = save_cover_cache(pic.data, img_ext)
        result["has_cover"] = 1
        result["cover_cache_path"] = cache_path


def _read_apev2_tags(file_path: str, result: Dict[str, Any], is_wv: bool = False) -> None:
    try:
        if is_wv:
            audio = WavPack(file_path)
        else:
            audio = MonkeysAudio(file_path)
    except Exception:
        return

    if hasattr(audio, "info") and hasattr(audio.info, "length"):
        result["duration"] = float(audio.info.length)

    lower_map = {k.lower(): k for k in audio.keys()} if audio else {}

    def _get(keys: list) -> Optional[str]:
        for k in keys:
            vals = audio.get(k)
            if not vals and k.lower() in lower_map:
                vals = audio.get(lower_map[k.lower()])
            if vals is not None:
                if hasattr(vals, "value"):
                    v = vals.value
                    if isinstance(v, bytes):
                        try:
                            return v.decode("utf-8")
                        except Exception:
                            return v.decode("latin-1", errors="replace")
                    return str(v)
                if isinstance(vals, list) and vals:
                    return str(vals[0])
                return str(vals)
        return None

    title = _get(["title"])
    if title:
        result["title"] = _clean_str(title)

    artist = _get(["artist"])
    if artist:
        result["artist"] = _clean_str(artist)

    album_artist = _get(["albumartist", "album artist", "ensemble"])
    if album_artist:
        result["album_artist"] = _clean_str(album_artist)

    album = _get(["album"])
    if album:
        result["album"] = _clean_str(album)

    date = _get(["year", "date"])
    if date:
        result["year"] = _format_year(date)

    genre = _get(["genre"])
    if genre:
        result["genre"] = _clean_str(genre)

    comment = _get(["comment", "description"])
    if comment:
        result["comment"] = str(comment).strip()

    track_num = _get(["track", "tracknumber"])
    if track_num:
        result["track_no"] = _format_track_num(track_num)

    disc_num = _get(["disc", "discnumber"])
    if disc_num:
        match = re.match(r"^(\d+)(?:/(\d+))?", str(disc_num).strip())
        if match:
            result["disc_no"] = match.group(1)
            if match.group(2):
                result["disc_total"] = match.group(2)
        else:
            result["disc_no"] = str(disc_num).strip()

    disc_tot = _get(["disctotal", "totaldiscs"])
    if disc_tot:
        try:
            result["disc_total"] = str(int(str(disc_tot).strip()))
        except Exception:
            pass

    comp = _get(["compilation"])
    if comp and str(comp).strip() in ("1", "true", "True", "yes"):
        result["compilation"] = 1

    # Extract embedded artwork if present
    cover_keys = ["cover art (front)", "cover art (cover)", "cover art", "front cover", "cover"]
    cover_data = None
    for ck in cover_keys:
        real_key = lower_map.get(ck)
        if real_key:
            val = audio.get(real_key)
            if val:
                raw_bytes = val.value if hasattr(val, "value") else bytes(val)
                if isinstance(raw_bytes, bytes):
                    if b"\x00" in raw_bytes:
                        _, raw_bytes = raw_bytes.split(b"\x00", 1)
                    if len(raw_bytes) > 100:
                        cover_data = raw_bytes
                        break
    if cover_data:
        ext_img = "jpg"
        if cover_data.startswith(b"\x89PNG"):
            ext_img = "png"
        cache_path = save_cover_cache(cover_data, ext_img)
        if cache_path:
            result["has_cover"] = 1
            result["cover_cache_path"] = cache_path


def write_tags(
    file_path: str,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album_artist: Optional[str] = None,
    album: Optional[str] = None,
    year: Optional[str] = None,
    genre: Optional[str] = None,
    track_no: Optional[str] = None,
    disc_no: Optional[str] = None,
    disc_total: Optional[str] = None,
    compilation: Optional[int] = None,
    new_cover_path: Optional[str] = None,
    remove_cover: bool = False,
) -> Dict[str, Any]:
    """Writes updated tags to file and returns updated tag info dict."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".mp3":
        _write_mp3_tags(
            file_path, title, artist, album_artist, album, year, genre,
            track_no, disc_no, disc_total, compilation, new_cover_path, remove_cover
        )
    elif ext in (".m4a", ".aac", ".mp4"):
        _write_mp4_tags(
            file_path, title, artist, album_artist, album, year, genre,
            track_no, disc_no, disc_total, compilation, new_cover_path, remove_cover
        )
    elif ext == ".flac":
        _write_flac_tags(
            file_path, title, artist, album_artist, album, year, genre,
            track_no, disc_no, disc_total, compilation, new_cover_path, remove_cover
        )

    # Re-read to get canonical values and updated mtime
    return read_tags(file_path)


def _write_mp3_tags(
    file_path: str,
    title: Optional[str],
    artist: Optional[str],
    album_artist: Optional[str],
    album: Optional[str],
    year: Optional[str],
    genre: Optional[str],
    track_no: Optional[str],
    disc_no: Optional[str],
    disc_total: Optional[str],
    compilation: Optional[int],
    new_cover_path: Optional[str],
    remove_cover: bool,
) -> None:
    try:
        audio = MP3(file_path)
    except Exception:
        return

    if audio.tags is None:
        audio.add_tags()

    tags = audio.tags

    def _val(v: Optional[str]) -> Optional[str]:
        if v is None or v == NO_DATA:
            return None
        s = v.strip()
        return s if s else None

    if title is not None:
        v = _val(title)
        if v:
            tags["TIT2"] = TIT2(encoding=3, text=[v])
        elif "TIT2" in tags:
            del tags["TIT2"]

    if artist is not None:
        v = _val(artist)
        if v:
            tags["TPE1"] = TPE1(encoding=3, text=[v])
        elif "TPE1" in tags:
            del tags["TPE1"]

    if album_artist is not None:
        v = _val(album_artist)
        if v:
            tags["TPE2"] = TPE2(encoding=3, text=[v])
        elif "TPE2" in tags:
            del tags["TPE2"]

    if album is not None:
        v = _val(album)
        if v:
            tags["TALB"] = TALB(encoding=3, text=[v])
        elif "TALB" in tags:
            del tags["TALB"]

    if year is not None:
        v = _val(year)
        if v:
            tags["TDRC"] = TDRC(encoding=3, text=[v])
            tags["TYER"] = TYER(encoding=3, text=[v])
        else:
            if "TDRC" in tags:
                del tags["TDRC"]
            if "TYER" in tags:
                del tags["TYER"]

    if genre is not None:
        v = _val(genre)
        if v:
            tags["TCON"] = TCON(encoding=3, text=[v])
        elif "TCON" in tags:
            del tags["TCON"]

    if track_no is not None:
        v = _val(track_no)
        if v:
            tags["TRCK"] = TRCK(encoding=3, text=[_format_track_num(v)])
        elif "TRCK" in tags:
            del tags["TRCK"]

    # Disc number (TPOS)
    if disc_no is not None:
        v_d = _val(disc_no)
        v_tot = _val(disc_total)
        if v_d:
            text_val = f"{v_d}/{v_tot}" if v_tot else v_d
            tags["TPOS"] = TPOS(encoding=3, text=[text_val])
        elif "TPOS" in tags:
            del tags["TPOS"]

    # Compilation (TCMP)
    if compilation is not None:
        if compilation:
            tags["TCMP"] = TCMP(encoding=3, text=["1"])
        elif "TCMP" in tags:
            del tags["TCMP"]

    # Cover art
    if remove_cover:
        apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
        for k in apic_keys:
            del tags[k]

    if new_cover_path and Path(new_cover_path).exists():
        apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
        for k in apic_keys:
            del tags[k]

        with open(new_cover_path, "rb") as img_f:
            img_data = img_f.read()
        mime = "image/png" if new_cover_path.lower().endswith(".png") else "image/jpeg"
        tags["APIC"] = APIC(
            encoding=3,
            mime=mime,
            type=PictureType.COVER_FRONT,
            desc="Cover",
            data=img_data,
        )

    audio.save()


def _write_mp4_tags(
    file_path: str,
    title: Optional[str],
    artist: Optional[str],
    album_artist: Optional[str],
    album: Optional[str],
    year: Optional[str],
    genre: Optional[str],
    track_no: Optional[str],
    disc_no: Optional[str],
    disc_total: Optional[str],
    compilation: Optional[int],
    new_cover_path: Optional[str],
    remove_cover: bool,
) -> None:
    try:
        audio = MP4(file_path)
    except Exception:
        return

    if audio.tags is None:
        audio.add_tags()

    tags = audio.tags

    def _val(v: Optional[str]) -> Optional[str]:
        if v is None or v == NO_DATA:
            return None
        s = v.strip()
        return s if s else None

    if title is not None:
        v = _val(title)
        if v:
            tags["\xa9nam"] = [v]
        elif "\xa9nam" in tags:
            del tags["\xa9nam"]

    if artist is not None:
        v = _val(artist)
        if v:
            tags["\xa9ART"] = [v]
        elif "\xa9ART" in tags:
            del tags["\xa9ART"]

    if album_artist is not None:
        v = _val(album_artist)
        if v:
            tags["aART"] = [v]
        elif "aART" in tags:
            del tags["aART"]

    if album is not None:
        v = _val(album)
        if v:
            tags["\xa9alb"] = [v]
        elif "\xa9alb" in tags:
            del tags["\xa9alb"]

    if year is not None:
        v = _val(year)
        if v:
            tags["\xa9day"] = [v]
        elif "\xa9day" in tags:
            del tags["\xa9day"]

    if genre is not None:
        v = _val(genre)
        if v:
            tags["\xa9gen"] = [v]
        elif "\xa9gen" in tags:
            del tags["\xa9gen"]

    if track_no is not None:
        v = _val(track_no)
        if v:
            try:
                num = int(re.match(r"^(\d+)", v).group(1))
                tags["trkn"] = [(num, 0)]
            except Exception:
                pass
        elif "trkn" in tags:
            del tags["trkn"]

    # Disc number ('disk')
    if disc_no is not None:
        v_d = _val(disc_no)
        v_tot = _val(disc_total)
        if v_d:
            try:
                d_no = int(v_d)
                d_tot = int(v_tot) if v_tot else 0
                tags["disk"] = [(d_no, d_tot)]
            except Exception:
                pass
        elif "disk" in tags:
            del tags["disk"]

    # Compilation ('cpil')
    if compilation is not None:
        tags["cpil"] = bool(compilation)

    # Cover art
    if remove_cover and "covr" in tags:
        del tags["covr"]

    if new_cover_path and Path(new_cover_path).exists():
        with open(new_cover_path, "rb") as img_f:
            img_data = img_f.read()
        is_png = new_cover_path.lower().endswith(".png")
        fmt = MP4Cover.FORMAT_PNG if is_png else MP4Cover.FORMAT_JPEG
        tags["covr"] = [MP4Cover(img_data, imageformat=fmt)]

    audio.save()


def _write_flac_tags(
    file_path: str,
    title: Optional[str],
    artist: Optional[str],
    album_artist: Optional[str],
    album: Optional[str],
    year: Optional[str],
    genre: Optional[str],
    track_no: Optional[str],
    disc_no: Optional[str],
    disc_total: Optional[str],
    compilation: Optional[int],
    new_cover_path: Optional[str],
    remove_cover: bool,
) -> None:
    try:
        audio = FLAC(file_path)
    except Exception:
        return

    def _val(v: Optional[str]) -> Optional[str]:
        if v is None or v == NO_DATA:
            return None
        s = v.strip()
        return s if s else None

    if title is not None:
        v = _val(title)
        if v:
            audio["title"] = [v]
        elif "title" in audio:
            del audio["title"]

    if artist is not None:
        v = _val(artist)
        if v:
            audio["artist"] = [v]
        elif "artist" in audio:
            del audio["artist"]

    if album_artist is not None:
        v = _val(album_artist)
        if v:
            audio["albumartist"] = [v]
            if "album artist" in audio:
                del audio["album artist"]
        else:
            if "albumartist" in audio:
                del audio["albumartist"]
            if "album artist" in audio:
                del audio["album artist"]

    if album is not None:
        v = _val(album)
        if v:
            audio["album"] = [v]
        elif "album" in audio:
            del audio["album"]

    if year is not None:
        v = _val(year)
        if v:
            audio["date"] = [_format_year(v)]
        elif "date" in audio:
            del audio["date"]

    if genre is not None:
        v = _val(genre)
        if v:
            audio["genre"] = [v]
        elif "genre" in audio:
            del audio["genre"]

    if track_no is not None:
        v = _val(track_no)
        if v:
            audio["tracknumber"] = [_format_track_num(v)]
        elif "tracknumber" in audio:
            del audio["tracknumber"]

    if disc_no is not None:
        v_d = _val(disc_no)
        if v_d:
            audio["discnumber"] = [str(v_d)]
        elif "discnumber" in audio:
            del audio["discnumber"]

    if disc_total is not None:
        v_tot = _val(disc_total)
        if v_tot:
            audio["disctotal"] = [str(v_tot)]
        elif "disctotal" in audio:
            del audio["disctotal"]

    if compilation is not None:
        if compilation:
            audio["compilation"] = ["1"]
        elif "compilation" in audio:
            del audio["compilation"]

    # Cover art
    if remove_cover:
        audio.clear_pictures()

    if new_cover_path and Path(new_cover_path).exists():
        audio.clear_pictures()
        with open(new_cover_path, "rb") as img_f:
            img_data = img_f.read()
        is_png = new_cover_path.lower().endswith(".png")
        pic = FLACPicture()
        pic.type = PictureType.COVER_FRONT
        pic.mime = "image/png" if is_png else "image/jpeg"
        pic.data = img_data
        audio.add_picture(pic)

    audio.save()


def find_folder_artwork(folder_path: str) -> Optional[str]:
    """Finds image files like cover.jpg, folder.jpg, front.jpg, front.png in folder or subfolders."""
    folder = Path(folder_path)
    if not folder.is_dir():
        return None

    names = ["cover", "folder", "front", "album", "artwork", "cd"]
    exts = [".jpg", ".jpeg", ".png", ".webp"]

    # 1. Direct in folder
    for n in names:
        for ext in exts:
            p = folder / f"{n}{ext}"
            if p.is_file():
                return str(p)
            p_upper = folder / f"{n.capitalize()}{ext}"
            if p_upper.is_file():
                return str(p_upper)

    # 2. In Artwork or Scans subfolders
    for sub in ["Artwork", "artwork", "Scans", "scans", "Covers", "covers"]:
        sub_dir = folder / sub
        if sub_dir.is_dir():
            for n in names:
                for ext in exts:
                    p = sub_dir / f"{n}{ext}"
                    if p.is_file():
                        return str(p)
                    p_upper = sub_dir / f"{n.capitalize()}{ext}"
                    if p_upper.is_file():
                        return str(p_upper)
            for f in sub_dir.iterdir():
                if f.is_file() and f.suffix.lower() in exts:
                    return str(f)

    # 3. Any image in folder
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in exts:
            return str(f)

    return None


def get_audio_stream_info(file_path: str) -> Dict[str, Any]:
    """Returns sample_rate, bits_per_sample, duration, channels."""
    path = Path(file_path)
    ext = path.suffix.lower()
    info = {"sample_rate": 44100, "bits_per_sample": 16, "duration": 0.0, "channels": 2}
    try:
        if ext == ".flac":
            f = FLAC(file_path)
            info["sample_rate"] = f.info.sample_rate
            info["bits_per_sample"] = f.info.bits_per_sample
            info["duration"] = f.info.length
            info["channels"] = f.info.channels
        elif ext == ".mp3":
            f = MP3(file_path)
            info["sample_rate"] = f.info.sample_rate
            info["duration"] = f.info.length
            info["channels"] = f.info.channels
        elif ext in (".m4a", ".aac", ".mp4"):
            f = MP4(file_path)
            info["sample_rate"] = getattr(f.info, "sample_rate", 44100)
            info["bits_per_sample"] = getattr(f.info, "bits_per_sample", 16)
            info["duration"] = f.info.length
            info["channels"] = getattr(f.info, "channels", 2)
        elif ext == ".wv":
            f = WavPack(file_path)
            info["sample_rate"] = f.info.sample_rate
            info["bits_per_sample"] = getattr(f.info, "bits_per_sample", 16)
            info["duration"] = f.info.length
            info["channels"] = getattr(f.info, "channels", 2)
        elif ext == ".ape":
            f = MonkeysAudio(file_path)
            info["sample_rate"] = f.info.sample_rate
            info["bits_per_sample"] = getattr(f.info, "bits_per_sample", 16)
            info["duration"] = f.info.length
            info["channels"] = getattr(f.info, "channels", 2)
    except Exception:
        pass
    return info
