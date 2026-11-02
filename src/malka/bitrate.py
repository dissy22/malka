"""Per-second average bitrate profile of a compressed audio file.

The status bar shows the average bitrate of the second currently being played.
For MP4 (AAC/ALAC) and MP3 this is computed exactly from the container/sample
data; for formats we cannot cheaply index (FLAC) ``None`` is returned and the
caller falls back to the file's overall average bitrate.
"""

import struct
from pathlib import Path
from typing import List, Optional

_CACHE = {}


def _cache_key(path: Path):
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except Exception:
        return (str(path), 0, 0)


def second_bitrates(file_path: str) -> Optional[List[int]]:
    """Returns kbps per whole second of audio, or ``None`` if unsupported."""
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext not in (".m4a", ".mp3"):
        return None
    key = _cache_key(path)
    if key in _CACHE:
        return _CACHE[key]
    try:
        if ext == ".m4a":
            profile = _mp4_profile(path)
        else:
            profile = _mp3_profile(path)
    except Exception:
        profile = None
    _CACHE[key] = profile
    return profile


def bitrate_at(profile: Optional[List[int]], fallback_kbps: int, position_ms: int) -> int:
    """Bitrate (kbps) of the second containing ``position_ms``."""
    if profile:
        index = max(0, int(position_ms)) // 1000
        index = min(index, len(profile) - 1)
        return int(profile[index])
    return int(fallback_kbps or 0)


# ---------------------------------------------------------------------------
# MP4 / M4A (AAC, ALAC)
# ---------------------------------------------------------------------------

_CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}


def _read_box_header(f) -> Optional[tuple]:
    start = f.tell()
    header = f.read(8)
    if len(header) < 8:
        return None
    size, box_type = struct.unpack(">I4s", header)
    header_size = 8
    if size == 1:
        large = f.read(8)
        if len(large) < 8:
            return None
        size = struct.unpack(">Q", large)[0]
        header_size = 16
    elif size == 0:
        f.seek(0, 2)
        size = f.tell() - start
    return box_type, start, header_size, size


def _iter_boxes(data: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        box_type = data[pos + 4:pos + 8]
        header_size = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header_size = 16
        elif size == 0:
            size = end - pos
        if size < header_size or pos + size > end:
            return
        yield box_type, pos + header_size, pos + size
        pos += size


def _find_box(data: bytes, start: int, end: int, target: bytes):
    for box_type, payload_start, payload_end in _iter_boxes(data, start, end):
        if box_type == target:
            return payload_start, payload_end
    return None


def _mp4_profile(path: Path) -> Optional[List[int]]:
    with open(path, "rb") as f:
        moov = None
        while True:
            header = _read_box_header(f)
            if header is None:
                break
            box_type, start, header_size, size = header
            if box_type == b"moov":
                f.seek(start + header_size)
                moov = f.read(size - header_size)
                break
            f.seek(start + size)
        if not moov:
            return None

    boxes = _iter_boxes(moov, 0, len(moov))
    traks = [(s, e) for t, s, e in boxes if t == b"trak"]
    for trak_start, trak_end in traks:
        mdia = _find_box(moov, trak_start, trak_end, b"mdia")
        if not mdia:
            continue
        mdhd = _find_box(moov, mdia[0], mdia[1], b"mdhd")
        minf = _find_box(moov, mdia[0], mdia[1], b"minf")
        if not mdhd or not minf:
            continue
        stbl = _find_box(moov, minf[0], minf[1], b"stbl")
        if not stbl:
            continue
        stsz = _find_box(moov, stbl[0], stbl[1], b"stsz")
        stts = _find_box(moov, stbl[0], stbl[1], b"stts")
        if not stsz or not stts:
            continue

        version = moov[mdhd[0]]
        if version == 1:
            timescale = struct.unpack(">I", moov[mdhd[0] + 20:mdhd[0] + 24])[0]
        else:
            timescale = struct.unpack(">I", moov[mdhd[0] + 12:mdhd[0] + 16])[0]
        if not timescale:
            continue

        pos = stsz[0] + 4
        sample_size = struct.unpack(">I", moov[pos:pos + 4])[0]
        sample_count = struct.unpack(">I", moov[pos + 4:pos + 8])[0]
        pos += 8
        if sample_size:
            sizes = [sample_size] * sample_count
        else:
            sizes = list(struct.unpack(f">{sample_count}I", moov[pos:pos + sample_count * 4]))

        pos = stts[0] + 4
        entry_count = struct.unpack(">I", moov[pos:pos + 4])[0]
        pos += 4
        durations = []
        for _ in range(entry_count):
            count, delta = struct.unpack(">II", moov[pos:pos + 8])
            pos += 8
            durations.extend([delta] * count)

        profile: List[int] = []
        seconds_bytes = 0
        elapsed_units = 0
        second_index = 0
        for i, size in enumerate(sizes):
            seconds_bytes += size
            elapsed_units += durations[i] if i < len(durations) else 0
            while elapsed_units >= timescale:
                elapsed_units -= timescale
                profile.append(int(round(seconds_bytes * 8 / 1000)))
                seconds_bytes = 0
        return profile or None
    return None


# ---------------------------------------------------------------------------
# MP3
# ---------------------------------------------------------------------------

_BITRATES_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
_BITRATES_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
_SAMPLE_RATES = {
    3: [44100, 48000, 32000],   # MPEG 1
    2: [22050, 24000, 16000],   # MPEG 2
    0: [11025, 12000, 8000],    # MPEG 2.5
}


def _mp3_profile(path: Path) -> Optional[List[int]]:
    with open(path, "rb") as f:
        data = f.read()
    offset = 0
    if data[:3] == b"ID3" and len(data) > 10:
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        offset = 10 + size

    profile: List[int] = []
    seconds_bytes = 0
    elapsed = 0.0
    while offset + 4 <= len(data):
        if data[offset:offset + 3] == b"TAG":
            break
        header = struct.unpack(">I", data[offset:offset + 4])[0]
        if (header & 0xFFE00000) != 0xFFE00000:
            offset += 1
            continue
        version_bits = (header >> 19) & 0x3
        layer_bits = (header >> 17) & 0x3
        bitrate_index = (header >> 12) & 0xF
        rate_index = (header >> 10) & 0x3
        padding = (header >> 9) & 0x1
        if layer_bits != 1 or bitrate_index in (0, 15) or rate_index == 3:
            offset += 1
            continue
        sample_rate = _SAMPLE_RATES.get(version_bits, [44100])[rate_index]
        table = _BITRATES_V1L3 if version_bits == 3 else _BITRATES_V2L3
        bitrate = table[bitrate_index]
        samples = 1152 if version_bits == 3 else 576
        frame_len = int((144 if version_bits == 3 else 72) * bitrate * 1000 / sample_rate) + padding
        if frame_len <= 4:
            offset += 1
            continue

        seconds_bytes += frame_len
        elapsed += samples / sample_rate
        while elapsed >= 1.0:
            elapsed -= 1.0
            profile.append(int(round(seconds_bytes * 8 / 1000)))
            seconds_bytes = 0
        offset += frame_len

    return profile or None
