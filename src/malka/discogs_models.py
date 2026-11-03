"""Shared data models for the Discogs-only application."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

ProgressCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]


class CoverArtError(RuntimeError):
    """A user-presentable error raised during a Discogs request."""


class SearchCancelled(CoverArtError):
    """Raised internally when the user cancels a running search."""


@dataclass
class CoverImage:
    full_url: str
    thumb_url: str
    types: tuple[str, ...]
    front: bool
    entity: str
    mbid: str
    release_title: str
    release_artist: str
    release_date: str = ""
    comment: str = ""
    thumbnail: Optional[bytes] = None
    thumb_urls: tuple[str, ...] = ()
    width: int = 0
    height: int = 0
    provider: str = "Discogs"
    source_url: str = ""
    is_digital: bool = False
    is_official: bool = True
    rating: float = 0.0
    rating_count: int = 0
    rank_score: float = 0.0

    @property
    def type_label(self) -> str:
        labels = list(self.types)
        if self.front and "Front" not in labels:
            labels.insert(0, "Front")
        return ", ".join(labels) if labels else "Artwork"

    @property
    def is_front(self) -> bool:
        return self.front or "Front" in self.types

    @property
    def source_label(self) -> str:
        year = f" ({self.release_date[:4]})" if self.release_date[:4].isdigit() else ""
        return f"{self.release_title}{year}"

    @property
    def details_url(self) -> str:
        return self.source_url

    @property
    def details_label(self) -> str:
        return "Open on Discogs"

    @property
    def resolution_label(self) -> str:
        if self.width > 0 and self.height > 0:
            return f"{self.width}×{self.height}"
        return "size unknown"

    @property
    def size_kb(self) -> float:
        return len(self.thumbnail or b"") / 1024

    @property
    def size_label(self) -> str:
        if not self.thumbnail:
            return "—"
        if self.size_kb >= 100:
            return f"{self.size_kb:.0f} KB"
        return f"{self.size_kb:.1f} KB"

    @property
    def caption(self) -> str:
        return f"{self.type_label} · {self.resolution_label} · {self.size_label}"

    @property
    def tooltip(self) -> str:
        parts = [
            f"Type: {self.type_label}",
            f"Resolution: {self.resolution_label} px",
            f"File size: {self.size_label}",
            f"Release: {self.release_title}",
            f"Artist: {self.release_artist}",
        ]
        if self.release_date:
            parts.append(f"Date: {self.release_date}")
        if self.comment:
            parts.append(f"Comment: {self.comment}")
        flags = "Digital" if self.is_digital else "Physical"
        flags += " / Official" if self.is_official else " / Unofficial"
        parts.append(f"Release: {flags}")
        if self.rating or self.rating_count:
            parts.append(
                f"Discogs release rating: {self.rating:.1f}/5 "
                f"({self.rating_count} votes)"
            )
        parts.append("Source: Discogs")
        return "\n".join(parts)


@dataclass
class CoverSearchResult:
    album: str
    artist: str
    images: list[CoverImage] = field(default_factory=list)
    candidate_count: int = 0
    variants: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provider: str = "Discogs"
    year: str = ""


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _normalize_title(value: str) -> str:
    value = " ".join(value.replace("\u00a0", " ").split())
    return value.strip(" \t-–—:;")


def album_search_variants(album: str) -> list[str]:
    """Return progressively less specific variants of an album title."""
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = _normalize_title(value)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            variants.append(value)

    def strip_edition(value: str) -> str:
        return re.sub(
            r"\s*[\(\[]?(?:-|–|—|:)?\s*(?:deluxe|special|limited|expanded|"
            r"remaster(?:ed)?|anniversary|bonus|collector'?s?|complete|"
            r"definitive|single|ep)(?:\s+edition|\s+version)?[\)\]]?\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        )

    def strip_part(value: str) -> str:
        return re.sub(
            r"\s*[-–—:,]?\s*(?:part|pt\.?|volume|vol\.?|disc|cd|chapter)\s*"
            r"(?:\d+|[ivx]+|one|two|three|four)\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        )

    def strip_qualifier(value: str) -> str:
        return re.sub(
            r"\s*[\(\[](?:live|mono|stereo|single|ep|soundtrack)[^\)\]]*[\)\]]\s*$",
            "",
            value,
            flags=re.IGNORECASE,
        )

    raw = _normalize_title(album)
    current = raw
    add(current)
    for transform in (strip_edition, strip_part, strip_edition, strip_qualifier):
        current = transform(current)
        add(current)

    if " - " in raw:
        tail = raw.split(" - ", 1)[1]
        if strip_edition(tail):
            add(tail)
        for transform in (strip_edition, strip_part, strip_edition, strip_qualifier):
            tail = transform(tail)
            add(tail)

    return variants[:5]


# ---------------------------------------------------------------------------
# Image headers (no GUI dependency, safe in worker threads)
# ---------------------------------------------------------------------------


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8"):
        return 0, 0
    index = 2
    length_total = len(data)
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while index + 4 <= length_total:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xDA:
            break
        segment_length = int.from_bytes(data[index + 2 : index + 4], "big")
        if segment_length < 2:
            break
        if marker in sof_markers and index + 9 <= length_total:
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        index += 2 + segment_length
    return 0, 0


def _webp_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 30 or not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        return 0, 0
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    return 0, 0


def image_dimensions(data: bytes) -> tuple[int, int]:
    """Read image dimensions from the file header without a GUI dependency."""
    if not data or len(data) < 10:
        return 0, 0
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        if data[12:16] == b"IHDR":
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return width, height
        return 0, 0
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
        return width, height
    if data.startswith(b"BM") and len(data) >= 26:
        width = int.from_bytes(data[18:22], "little", signed=True)
        height = int.from_bytes(data[22:26], "little", signed=True)
        return abs(width), abs(height)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return _webp_dimensions(data)
    return 0, 0
