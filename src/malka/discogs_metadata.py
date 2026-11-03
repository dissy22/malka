"""Discogs metadata lookup for partially filled tag fields.

This module talks only to Discogs.  It can search releases using two of the
three anchor fields (Artist / Album / Year), read master tracklists, and propose
a track title from a track number or from the file name.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from malka.discogs_config import DISCOGS_DEADLINE
from malka.discogs_client import (
    DiscogsClient,
    DiscogsError,
    _format_values,
    _is_digital,
    _is_official,
    _normalize_year,
)
from malka.discogs_models import (
    CancelCallback,
    ProgressCallback,
    SearchCancelled,
    album_search_variants,
)


@dataclass
class TrackInfo:
    position: str
    title: str
    duration: str = ""
    track_no: str = ""
    disc_no: str = ""

    @property
    def display(self) -> str:
        position = self.position or "—"
        duration = f" · {self.duration}" if self.duration else ""
        return f"{position} · {self.title}{duration}"

    @property
    def tooltip(self) -> str:
        parts = [f"Title: {self.title}"]
        if self.position:
            parts.append(f"Position: {self.position}")
        if self.duration:
            parts.append(f"Duration: {self.duration}")
        return "\n".join(parts)


@dataclass
class ReleaseCandidate:
    id: str
    entity: str
    title: str
    artist: str
    year: str
    genres: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    country: str = ""
    source_url: str = ""
    tracks: list[TrackInfo] = field(default_factory=list)
    is_digital: bool = False
    is_official: bool = True
    rating: float = 0.0
    rating_count: int = 0
    rank_score: float = 0.0
    cover_data: bytes = b""
    cover_url: str = ""
    cover_width: int = 0
    cover_height: int = 0

    @property
    def display_title(self) -> str:
        name = " — ".join(part for part in (self.artist, self.title) if part)
        if not name:
            name = self.title or self.artist or "Unknown release"
        if self.year:
            name += f" ({self.year})"
        return name

    @property
    def display_detail(self) -> str:
        parts: list[str] = []
        if self.entity == "master":
            parts.append("Master release")
        if self.formats:
            parts.append(self.formats[0])
        if self.country:
            parts.append(self.country)
        if self.tracks:
            parts.append(f"{len(self.tracks)} track{'s' if len(self.tracks) != 1 else ''}")
        if self.rating or self.rating_count:
            parts.append(f"{self.rating:.1f}/5 ({self.rating_count})")
        if not self.is_official:
            parts.append("Unofficial")
        return " · ".join(parts)

    @property
    def tooltip(self) -> str:
        lines = [self.display_title]
        if self.display_detail:
            lines.append(self.display_detail)
        if self.styles:
            lines.append(f"Styles: {', '.join(self.styles)}")
        if self.genres:
            lines.append(f"Genres: {', '.join(self.genres)}")
        if self.source_url:
            lines.append(self.source_url)
        return "\n".join(lines)

    @property
    def genre_values(self) -> list[str]:
        values: list[str] = []
        for value in list(self.styles) + list(self.genres):
            value = str(value).strip()
            if value and value not in values:
                values.append(value)
        return values


def _position_parts(position: str) -> tuple[str, str]:
    position = str(position or "").strip()
    match = re.match(r"^(\d+)\s*[-.]\s*(\d+)$", position)
    if match:
        return match.group(1), str(int(match.group(2)))
    match = re.search(r"(\d+)", position)
    if match:
        return "", str(int(match.group(1)))
    return "", ""


def _parse_tracks(detail: dict) -> list[TrackInfo]:
    tracks: list[TrackInfo] = []
    for item in detail.get("tracklist") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type_") or "track").lower()
        if kind != "track":
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        position = str(item.get("position") or "").strip()
        disc_no, track_no = _position_parts(position)
        tracks.append(
            TrackInfo(
                position=position,
                title=title,
                duration=str(item.get("duration") or "").strip(),
                track_no=track_no,
                disc_no=disc_no,
            )
        )
    return tracks


def _artists(detail: dict) -> str:
    names = [
        str(artist.get("name") or "").strip()
        for artist in (detail.get("artists") or [])
        if isinstance(artist, dict) and artist.get("name")
    ]
    return ", ".join(names)


class DiscogsMetadataClient:
    def __init__(
        self,
        token: Optional[str] = None,
        max_candidates: int = 10,
        api_base: str = "",
    ) -> None:
        if api_base:
            self.http = DiscogsClient(token=token, api_base=api_base)
        else:
            self.http = DiscogsClient(token=token)
        self.max_candidates = max(1, max_candidates)

    def find_releases(
        self,
        artist: str = "",
        album: str = "",
        year: str = "",
        progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[CancelCallback] = None,
    ) -> list[ReleaseCandidate]:
        artist = " ".join(artist.split()).strip()
        album = " ".join(album.split()).strip()
        year = _normalize_year(year)
        if not artist and not album:
            raise DiscogsError(
                "Fill at least Artist or Album — Discogs needs at least two of "
                "Artist / Album / Year for a useful lookup."
            )

        progress = progress or (lambda _message: None)
        should_cancel = should_cancel or (lambda: False)
        deadline = time.monotonic() + DISCOGS_DEADLINE

        def check_cancel() -> None:
            if should_cancel():
                raise SearchCancelled("Lookup cancelled.")
            if time.monotonic() > deadline:
                raise DiscogsError(
                    "The Discogs lookup took too long. Try again or add DISCOGS_TOKEN."
                )

        variants = album_search_variants(album) if album else [""]
        items: list[dict] = []
        seen_ids: set[str] = set()

        # Prefer the exact title with the year.  When a year is supplied we do
        # not fall back to a different year: that would produce entries such as
        # a 1992 single inside a 1991 lookup.
        for variant in variants[:2]:
            queries: list[tuple[str, str, str]] = [(artist, variant, year)]
            for query_artist, query_album, query_year in queries:
                check_cancel()
                label = query_album or query_artist or "Discogs"
                if query_year:
                    progress(f'Searching Discogs for “{label}” ({query_year})…')
                else:
                    progress(f'Searching Discogs for “{label}”…')
                found = self.http.search_database(
                    release_title=query_album,
                    artist=query_artist,
                    year=query_year,
                    per_page=100,
                )
                for item in found:
                    release_id = str(item.get("id") or "")
                    if not release_id or release_id in seen_ids:
                        continue
                    seen_ids.add(release_id)
                    items.append(item)
                if items:
                    break
            if items:
                break

        if not items:
            return []

        # Group pressings by master and keep the best member of each master.
        grouped: dict[str, dict] = {}
        for item in items:
            key = DiscogsClient._candidate_key(item)
            existing = grouped.get(key)
            if existing is None or self._item_rank(
                item, artist, album, year
            ) > self._item_rank(existing, artist, album, year):
                grouped[key] = item

        ordered = sorted(
            grouped.values(),
            key=lambda item: self._item_rank(item, artist, album, year),
            reverse=True,
        )

        candidates: list[ReleaseCandidate] = []
        for index, item in enumerate(ordered[: self.max_candidates], start=1):
            check_cancel()
            progress(f"Checking Discogs release {index}/{min(len(ordered), self.max_candidates)}…")
            candidate = self._build_candidate(item, year, album, artist)
            if candidate is None:
                continue
            if year and candidate.year:
                if _normalize_year(candidate.year) != year:
                    # The search year matched a release/pressing, but the master
                    # itself belongs to a different year.
                    continue
            candidates.append(candidate)

        if not candidates:
            return []

        # Keep every unique official master; bootlegs/live compilations are
        # used only if there is no official result at all.
        official = [candidate for candidate in candidates if candidate.is_official]
        if official:
            candidates = official

        candidates.sort(key=lambda candidate: candidate.rank_score, reverse=True)
        return candidates

    @staticmethod
    def _item_rank(item: dict, artist: str, album: str, year: str) -> float:
        values = _format_values(item)
        official = _is_official(values)
        digital = _is_digital(values)
        title = str(item.get("title") or "").lower()
        item_year = _normalize_year(str(item.get("year") or ""))
        format_text = " ".join(values).lower()
        score = 0.0
        if official:
            score += 10_000
        if digital:
            score += 1_000
        if "album" in format_text or " lp" in f" {format_text}":
            score += 4_000
        elif "single" in format_text or "promo" in format_text:
            score -= 1_000
        album_part = title.split(" - ")[-1].strip()
        if album and normalize_text(album_part) == normalize_text(album):
            score += 3_000
        elif album and album.lower() in title:
            score += 1_000
        if artist and artist.lower() in title:
            score += 1_000
        if year and item_year == year:
            score += 2_000
        return score

    def _build_candidate(
        self,
        item: dict,
        year_hint: str,
        album_hint: str = "",
        artist_hint: str = "",
    ) -> Optional[ReleaseCandidate]:
        release_id = str(item.get("id") or "")
        master_id = str(item.get("master_id") or "").strip()
        is_master = bool(master_id and master_id != "0")

        master_detail: dict = {}
        release_detail: dict = {}
        if is_master:
            master_detail = self.http.get_master(master_id)
            main_release_id = str(master_detail.get("main_release") or "").strip()
            if main_release_id:
                release_detail = self.http.get_release(main_release_id)
            if not release_detail:
                release_detail = self.http.get_release(release_id)
        else:
            release_detail = self.http.get_release(release_id)

        detail = master_detail or release_detail
        metadata = release_detail or master_detail
        if not detail:
            return None

        tracks = _parse_tracks(detail)
        if not tracks and metadata is not detail:
            tracks = _parse_tracks(metadata)

        title = str(detail.get("title") or metadata.get("title") or "").strip()
        artist = _artists(detail) or _artists(metadata)
        release_year = detail.get("year") or metadata.get("year") or item.get("year")
        year_text = str(release_year) if release_year else ""
        genres = [
            str(value).strip()
            for value in (detail.get("genres") or metadata.get("genres") or [])
            if str(value).strip()
        ]
        styles = [
            str(value).strip()
            for value in (detail.get("styles") or metadata.get("styles") or [])
            if str(value).strip()
        ]

        format_labels: list[str] = []
        for value in (metadata.get("formats") or []):
            if not isinstance(value, dict):
                continue
            name = str(value.get("name") or "").strip()
            descriptions = ", ".join(
                str(desc) for desc in (value.get("descriptions") or []) if desc
            )
            text = " / ".join(part for part in (name, descriptions) if part)
            if text and text not in format_labels:
                format_labels.append(text)
        if not format_labels:
            search_formats = [str(value) for value in (item.get("format") or []) if value]
            if search_formats:
                format_labels.append(" / ".join(search_formats))

        quality_values = _format_values(metadata) + _format_values(item) + _format_values(detail)
        is_digital = _is_digital(quality_values)
        is_official = _is_official(quality_values)

        community = (metadata.get("community") or {})
        rating_info = community.get("rating") or {}
        try:
            rating = float(rating_info.get("average") or 0.0)
        except (TypeError, ValueError):
            rating = 0.0
        try:
            rating_count = int(rating_info.get("count") or 0)
        except (TypeError, ValueError):
            rating_count = 0

        country = str(metadata.get("country") or "").strip()
        source_url = str(detail.get("uri") or "").strip()
        if not source_url:
            source_url = (
                f"https://www.discogs.com/master/{master_id}"
                if is_master
                else f"https://www.discogs.com/release/{release_id}"
            )

        year_match = bool(year_hint and _normalize_year(year_text) == year_hint)
        rank_score = 0.0
        if is_official:
            rank_score += 10_000
        if year_match:
            rank_score += 5_000
        if is_digital:
            rank_score += 1_000
        rank_score += rating * 50
        rank_score += min(rating_count, 50)

        format_text = " ".join(
            format_labels + [str(value) for value in (item.get("format") or [])]
        ).lower()
        if "album" in format_text or " lp" in f" {format_text}":
            rank_score += 4_000
        elif "single" in format_text or "promo" in format_text:
            rank_score -= 1_000
        if len(tracks) >= 4:
            rank_score += 2_000
        if len(tracks) >= 8:
            rank_score += 1_000

        album_norm = normalize_text(album_hint)
        title_norm = normalize_text(title)
        if album_norm and album_norm == title_norm:
            rank_score += 6_000
        elif album_norm and (title_norm.startswith(album_norm) or album_norm.startswith(title_norm)):
            rank_score += 2_000
        if artist_hint and artist_hint.lower() in _artists(detail).lower():
            rank_score += 500

        return ReleaseCandidate(
            id=master_id if is_master else release_id,
            entity="master" if is_master else "release",
            title=title,
            artist=artist,
            year=year_text,
            genres=genres,
            styles=styles,
            formats=format_labels,
            country=country,
            source_url=source_url,
            tracks=tracks,
            is_digital=is_digital,
            is_official=is_official,
            rating=rating,
            rating_count=rating_count,
            rank_score=rank_score,
        )


def normalize_text(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[\(\[].*?[\)\]]", " ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"\b(19|20)\d{2}\b", " ", value)
    return " ".join(value.split())


def tracks_by_number(
    candidate: ReleaseCandidate,
    track_no: str,
    disc_no: str = "",
) -> list[TrackInfo]:
    digits = "".join(ch for ch in str(track_no or "") if ch.isdigit())
    if not digits:
        return []
    wanted = int(digits)

    # Vinyl-style positions (A1, B1, C1, ...) repeat the same numeric suffix on
    # every side.  In that case the tag's track number is normally the global
    # running number, so use the tracklist order instead of matching "1" on
    # every side.
    letter_positions = any(
        re.match(r"^[A-Za-z]+\s*\d+\s*$", track.position)
        for track in candidate.tracks
    )
    if letter_positions:
        index = wanted - 1
        if 0 <= index < len(candidate.tracks):
            return [candidate.tracks[index]]
        return []

    wanted_text = str(wanted)
    disc = "".join(ch for ch in str(disc_no or "") if ch.isdigit())
    disc = str(int(disc)) if disc else ""
    matches = [
        track
        for track in candidate.tracks
        if track.track_no == wanted_text
        and (not disc or not track.disc_no or track.disc_no == disc)
    ]
    if matches:
        return matches
    index = wanted - 1
    if 0 <= index < len(candidate.tracks):
        return [candidate.tracks[index]]
    return []


def track_score(
    filename: str,
    track: TrackInfo,
    artist: str = "",
    album: str = "",
) -> float:
    file_norm = normalize_text(Path(filename).stem)
    title_norm = normalize_text(track.title)
    if not file_norm or not title_norm:
        return 0.0

    ratio = SequenceMatcher(None, file_norm, title_norm).ratio()
    title_tokens = set(title_norm.split())
    file_tokens = set(file_norm.split())
    overlap = (
        len(title_tokens & file_tokens) / len(title_tokens) if title_tokens else 0.0
    )
    substring = 1.0 if title_norm in file_norm or file_norm in title_norm else 0.0

    clean = file_norm
    for value in (artist, album):
        normalized = normalize_text(value)
        if normalized:
            clean = clean.replace(normalized, " ")
    clean = " ".join(clean.split())
    clean_ratio = SequenceMatcher(None, clean, title_norm).ratio() if clean else 0.0
    clean_tokens = set(clean.split())
    clean_overlap = (
        len(title_tokens & clean_tokens) / len(title_tokens) if title_tokens else 0.0
    )
    return max(ratio, overlap, substring, clean_ratio, clean_overlap)


def rank_tracks_by_filename(
    candidate: ReleaseCandidate,
    filename: str,
    artist: str = "",
    album: str = "",
) -> list[tuple[float, TrackInfo]]:
    ranked = [
        (track_score(filename, track, artist, album), track)
        for track in candidate.tracks
    ]
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked


def rank_tracks_by_title(
    candidate: ReleaseCandidate,
    title: str,
) -> list[tuple[float, TrackInfo]]:
    wanted = normalize_text(title)
    if not wanted:
        return []
    exact = [
        track
        for track in candidate.tracks
        if normalize_text(track.title) == wanted
    ]
    if exact:
        return [(1.0, track) for track in exact]
    # Fall back to the same fuzzy matcher used for file names.  Keep slashes
    # and dots in the title from confusing Path.stem.
    return rank_tracks_by_filename(candidate, title.replace("/", " ") + ".mp3")

