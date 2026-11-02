"""Central audio-format and import-quality rules for Malka.

The library itself stores exactly four kinds of audio:

* ``.mp3``   — MPEG-1/2 Layer III
* ``.m4a``   — AAC inside an MP4 container
* ``.m4a``   — ALAC (Apple Lossless) inside an MP4 container
* ``.flac``  — FLAC

APE and WavPack are accepted *only* as single-image + CUE import sources: they
are always converted (and split) into one of the library formats on import.

Import is described by a small settings dict::

    {"mode": "lossy" | "lossless_resample" | "copy" | "hires",
     "format": "mp3" | "m4a" | "flac" | "alac",
     "rate": 44100 | 48000}

``mode`` decides what happens to the audio, ``format`` picks the target codec
where the mode allows a choice, and ``rate`` is the resampling ceiling.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

#: Everything Malka scans, indexes and plays.
LIBRARY_EXTS = {".mp3", ".m4a", ".flac"}

#: Same set, as a frozenset for membership checks in the player.
PLAYABLE_EXTS = frozenset(LIBRARY_EXTS)

#: Track-based import sources (one album = several files).
IMPORT_TRACK_EXTS = {".mp3", ".m4a", ".flac"}

#: Single-image + CUE import sources.
IMAGE_SOURCE_EXTS = {".flac", ".wv", ".ape"}

#: Every file the importer will look at.
IMPORT_SOURCE_EXTS = IMPORT_TRACK_EXTS | IMAGE_SOURCE_EXTS

# ---------------------------------------------------------------------------
# Source kinds — the key used to remember import settings in the config
# ---------------------------------------------------------------------------

SOURCE_KIND_MP3_M4A = "tracks_mp3_m4a"
SOURCE_KIND_FLAC_ALAC = "tracks_flac_alac"
SOURCE_KIND_IMAGE_FLAC_ALAC = "image_flac_alac"
SOURCE_KIND_IMAGE_APE_WV = "image_ape_wv"

SOURCE_KINDS = (
    SOURCE_KIND_MP3_M4A,
    SOURCE_KIND_FLAC_ALAC,
    SOURCE_KIND_IMAGE_FLAC_ALAC,
    SOURCE_KIND_IMAGE_APE_WV,
)

IMAGE_SOURCE_KINDS = (SOURCE_KIND_IMAGE_FLAC_ALAC, SOURCE_KIND_IMAGE_APE_WV)

SOURCE_KIND_LABELS = {
    SOURCE_KIND_MP3_M4A: "MP3 / M4A tracks",
    SOURCE_KIND_FLAC_ALAC: "FLAC / ALAC tracks",
    SOURCE_KIND_IMAGE_FLAC_ALAC: "FLAC / ALAC image + CUE",
    SOURCE_KIND_IMAGE_APE_WV: "APE / WavPack image + CUE",
}

# ---------------------------------------------------------------------------
# Quality modes
# ---------------------------------------------------------------------------

#: Re-encode to a lossy codec (MP3 320 / AAC 224).
MODE_LOSSY = "lossy"
#: Re-encode losslessly to FLAC/ALAC, 16-bit, down to the chosen ceiling rate.
MODE_LOSSLESS_RESAMPLE = "lossless_resample"
#: Keep the audio stream exactly as it is (optionally split an image into tracks).
MODE_COPY = "copy"
#: Keep the original Hi-Res resolution, but re-encode to FLAC/ALAC
#: (only needed for APE/WavPack images, which cannot live in the library).
MODE_HIRES = "hires"

MODES = (MODE_LOSSY, MODE_LOSSLESS_RESAMPLE, MODE_COPY, MODE_HIRES)

LOSSY_FORMATS = ("mp3", "m4a")
LOSSLESS_FORMATS = ("flac", "alac")
AUDIO_FORMATS = ("mp3", "m4a", "flac", "alac")

FORMAT_EXTENSIONS = {
    "mp3": ".mp3",
    "m4a": ".m4a",
    "flac": ".flac",
    "alac": ".m4a",
}

FORMAT_LABELS = {
    "mp3": "MP3 — 320 kbps",
    "m4a": "M4A (AAC) — 224 kbps",
    "flac": "FLAC — lossless",
    "alac": "ALAC — lossless (.m4a)",
}

LOSSY_BITRATES = {"mp3": "320k", "m4a": "224k"}

RATES = (44100, 48000)
DEFAULT_RATE = 48000

MAX_SAMPLE_RATE = 48000
MAX_BITS = 16


def is_hires(sample_rate: int, bits_per_sample: int) -> bool:
    """True when the source is above 48 kHz and/or above 16-bit."""
    try:
        rate = int(sample_rate or 0)
    except (TypeError, ValueError):
        rate = 0
    try:
        bits = int(bits_per_sample or 0)
    except (TypeError, ValueError):
        bits = 0
    return rate > MAX_SAMPLE_RATE or bits > MAX_BITS


def format_extension(audio_format: str) -> str:
    return FORMAT_EXTENSIONS.get(audio_format, ".m4a" if audio_format == "alac" else ".flac")


def format_label(audio_format: str) -> str:
    return FORMAT_LABELS.get(audio_format, audio_format.upper())


def format_from_extension(ext: str) -> str:
    ext = (ext or "").lower()
    if ext == ".mp3":
        return "mp3"
    if ext == ".flac":
        return "flac"
    if ext == ".m4a":
        return "m4a"
    return ext.lstrip(".")


# ---------------------------------------------------------------------------
# Which choices make sense for which source
# ---------------------------------------------------------------------------


def available_modes(source_kind: str, hires: bool) -> List[str]:
    """Ordered list of quality modes offered for this kind of import."""
    if source_kind == SOURCE_KIND_MP3_M4A:
        return [MODE_COPY]

    if source_kind in (SOURCE_KIND_FLAC_ALAC, SOURCE_KIND_IMAGE_FLAC_ALAC):
        modes = [MODE_LOSSY]
        if hires:
            modes.append(MODE_LOSSLESS_RESAMPLE)
        modes.append(MODE_COPY)
        return modes

    # APE / WavPack images cannot be stored as-is: "keep" means re-encode.
    modes = [MODE_LOSSY]
    if hires:
        modes.append(MODE_LOSSLESS_RESAMPLE)
    modes.append(MODE_HIRES)
    return modes


def mode_label(mode: str, source_kind: str, hires: bool) -> str:
    split = source_kind in IMAGE_SOURCE_KINDS

    if source_kind == SOURCE_KIND_MP3_M4A:
        return "Keep original lossy quality (no re-encoding)"

    if mode == MODE_LOSSY:
        return "Lossy quality and split into tracks" if split else "Lossy quality"

    if mode == MODE_LOSSLESS_RESAMPLE:
        return (
            "Lossless quality (resample) and split into tracks"
            if split
            else "Lossless quality (resample)"
        )

    if mode == MODE_COPY:
        if hires:
            label = "Keep original Hi-Res quality (no resample)"
        else:
            label = "Keep original lossless quality (no re-encoding)"
        return f"{label} and split into tracks" if split else label

    if mode == MODE_HIRES:
        label = "Keep original Hi-Res quality (no resample)" if hires else "Keep original lossless quality"
        if split:
            label += " and split into tracks"
        return label + " (re-encode to FLAC/ALAC)"

    return mode


def available_formats(mode: str) -> List[str]:
    """Formats the user may pick for ``mode`` — empty means "fixed by source"."""
    if mode == MODE_LOSSY:
        return list(LOSSY_FORMATS)
    if mode in (MODE_LOSSLESS_RESAMPLE, MODE_HIRES):
        return list(LOSSLESS_FORMATS)
    return []


def rate_is_used(mode: str, hires: bool) -> bool:
    """Whether the resampling-ceiling picker applies to this mode."""
    if mode == MODE_LOSSY:
        return True
    return mode == MODE_LOSSLESS_RESAMPLE and hires


def default_settings(source_kind: str, hires: bool) -> Dict[str, Any]:
    modes = available_modes(source_kind, hires)
    if MODE_COPY in modes:
        mode = MODE_COPY
    elif MODE_HIRES in modes:
        mode = MODE_HIRES
    else:
        mode = modes[0]
    return {"mode": mode, "format": "flac", "rate": DEFAULT_RATE}


def normalize_settings(source_kind: str, hires: bool, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Clamps stored settings to the choices that are valid for this import."""
    settings = default_settings(source_kind, hires)
    if not isinstance(raw, dict):
        return settings

    mode = raw.get("mode")
    if mode in available_modes(source_kind, hires):
        settings["mode"] = mode

    formats = available_formats(settings["mode"])
    if formats:
        fmt = raw.get("format")
        if fmt in formats:
            settings["format"] = fmt
        else:
            settings["format"] = "flac" if "flac" in formats else formats[0]
    else:
        settings["format"] = "flac"

    try:
        rate = int(raw.get("rate") or DEFAULT_RATE)
    except (TypeError, ValueError):
        rate = DEFAULT_RATE
    settings["rate"] = rate if rate in RATES else DEFAULT_RATE
    return settings


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


def _effective_rate(source_rate: int, ceiling: int) -> Optional[int]:
    """Rate to force, or ``None`` when the source is already at/below the ceiling."""
    try:
        source = int(source_rate or 0)
    except (TypeError, ValueError):
        source = 0
    if source <= 0:
        return ceiling
    return ceiling if source > ceiling else None


def plan_for(
    source_kind: str,
    hires: bool,
    settings: Dict[str, Any],
    source_format: str,
    source_rate: int,
    source_bits: int,
) -> Dict[str, Any]:
    """Resolves the concrete operation for a given source.

    Returns a dict with:

    * ``split`` — split an image album into one file per CUE track;
    * ``copy_stream`` — keep the audio stream untouched (no re-encode);
    * ``output_format`` — mp3 / m4a / flac / alac;
    * ``target_rate`` — forced sample rate, or ``None`` to keep the source's;
    * ``reduce_bits`` — reduce to 16-bit (lossless resample only).
    """
    settings = normalize_settings(source_kind, hires, settings)
    mode = settings["mode"]
    split = source_kind in IMAGE_SOURCE_KINDS

    if mode == MODE_COPY:
        return {
            "split": split,
            "copy_stream": True,
            "output_format": source_format,
            "target_rate": None,
            "reduce_bits": False,
        }

    if mode == MODE_LOSSY:
        fmt = settings["format"] if settings["format"] in LOSSY_FORMATS else "m4a"
        return {
            "split": split,
            "copy_stream": False,
            "output_format": fmt,
            "target_rate": _effective_rate(source_rate, settings["rate"]),
            "reduce_bits": False,
        }

    if mode == MODE_LOSSLESS_RESAMPLE:
        fmt = settings["format"] if settings["format"] in LOSSLESS_FORMATS else "flac"
        target = settings["rate"] if hires else None
        return {
            "split": split,
            "copy_stream": False,
            "output_format": fmt,
            "target_rate": _effective_rate(source_rate, target) if target else None,
            "reduce_bits": True,
        }

    # MODE_HIRES: keep resolution, but the format has to be a library one.
    fmt = settings["format"] if settings["format"] in LOSSLESS_FORMATS else "flac"
    return {
        "split": split,
        "copy_stream": False,
        "output_format": fmt,
        "target_rate": None,
        "reduce_bits": False,
    }


# ---------------------------------------------------------------------------
# FFmpeg argument building
# ---------------------------------------------------------------------------


def encoder_args(output_format: str, target_rate: Optional[int], reduce_bits: bool) -> List[str]:
    """FFmpeg output arguments for a resolved plan."""
    args: List[str] = []

    if output_format == "flac":
        args += ["-c:a", "flac"]
    elif output_format == "alac":
        args += ["-c:a", "alac"]
    elif output_format == "m4a":
        args += ["-c:a", "aac", "-b:a", LOSSY_BITRATES["m4a"]]
    elif output_format == "mp3":
        args += ["-c:a", "libmp3lame", "-b:a", LOSSY_BITRATES["mp3"]]
    else:
        raise ValueError(f"Unsupported output format: {output_format}")

    if target_rate:
        args += ["-ar", str(target_rate)]

    if reduce_bits:
        if output_format == "alac":
            args += ["-sample_fmt", "s16p"]
        elif output_format == "flac":
            args += ["-sample_fmt", "s16"]

    return args


# ---------------------------------------------------------------------------
# Lossless detection
# ---------------------------------------------------------------------------


def is_lossless_source(file_path: str) -> bool:
    """True for FLAC / ALAC (and APE/WavPack images)."""
    ext = Path(file_path).suffix.lower()
    if ext == ".flac":
        return True
    if ext in (".ape", ".wv"):
        return True
    if ext == ".m4a":
        try:
            from mutagen.mp4 import MP4

            codec = str(getattr(MP4(file_path).info, "codec", "")).lower()
            return codec.startswith("alac")
        except Exception:
            return False
    return False


def is_alac_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() == ".m4a" and is_lossless_source(file_path)
