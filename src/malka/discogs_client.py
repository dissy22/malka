"""Discogs cover search and metadata helpers.

The client searches Discogs releases, groups pressings by master release, and
uses the master's canonical primary image.  The image bytes are downloaded during
the search and later embedded without a second network request.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from malka.discogs_config import (
    DISCOGS_API_BASE,
    DISCOGS_API_INTERVAL,
    DISCOGS_DEADLINE,
    DISCOGS_MAX_RELEASES_PER_QUERY,
    DISCOGS_USER_AGENT,
    HTTP_TIMEOUT,
    MAX_IMAGES,
    discogs_token,
)
from malka.discogs_models import (
    CoverArtError,
    CoverImage,
    CoverSearchResult,
    SearchCancelled,
    album_search_variants,
    image_dimensions,
)

ProgressCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]


class DiscogsError(CoverArtError):
    """A user-presentable error from the Discogs API."""


DIGITAL_FORMATS = {
    "file",
    "mp3",
    "flac",
    "aac",
    "wav",
    "aiff",
    "alac",
    "m4a",
    "ogg",
    "opus",
    "wma",
    "digital",
}


def _normalize_year(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:4] if len(digits) >= 4 else ""


def _format_values(item: dict) -> list[str]:
    values: list[str] = []
    for value in item.get("format") or []:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    for fmt in item.get("formats") or []:
        if not isinstance(fmt, dict):
            continue
        name = str(fmt.get("name") or "").strip()
        if name:
            values.append(name)
        for desc in fmt.get("descriptions") or []:
            if desc:
                values.append(str(desc).strip())
    return values


def _is_digital(values: list[str]) -> bool:
    return any(value.lower() in DIGITAL_FORMATS for value in values)


def _is_official(values: list[str]) -> bool:
    text = " ".join(values).lower()
    return "unofficial" not in text and "bootleg" not in text


def _secure_discogs_url(url: str) -> str:
    if url.startswith("http://i.discogs.com/") or url.startswith("http://img.discogs.com/"):
        return "https://" + url[len("http://") :]
    return url


class DiscogsClient:
    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = HTTP_TIMEOUT,
        max_releases: int = DISCOGS_MAX_RELEASES_PER_QUERY,
        api_base: str = DISCOGS_API_BASE,
    ) -> None:
        self.token = (token if token is not None else discogs_token()).strip()
        self.timeout = timeout
        self.max_releases = max(1, max_releases)
        self.api_base = api_base.rstrip("/")
        self._lock = threading.Lock()
        self._last_api_request = 0.0

    # -- public API ---------------------------------------------------------

    def search(
        self,
        album: str,
        artist: str = "",
        year: str = "",
        progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[CancelCallback] = None,
    ) -> CoverSearchResult:
        album = " ".join(album.split()).strip()
        artist = " ".join(artist.split()).strip()
        year = _normalize_year(year)
        if not album:
            raise DiscogsError("The Album field is empty. Enter an album title first.")

        variants = album_search_variants(album)
        result = CoverSearchResult(
            album=album,
            artist=artist,
            variants=variants,
            provider="Discogs",
            year=year,
        )
        progress = progress or (lambda _message: None)
        should_cancel = should_cancel or (lambda: False)
        deadline = time.monotonic() + DISCOGS_DEADLINE

        def check_cancel() -> None:
            if should_cancel():
                raise SearchCancelled("Search cancelled.")
            if time.monotonic() > deadline:
                raise DiscogsError(
                    "The Discogs search took too long. Please try again or add "
                    "DISCOGS_TOKEN for a higher rate limit."
                )

        def collect_queries(variant: str) -> list[dict]:
            """Search with and without the optional year/artist hints."""
            queries: list[tuple[str, str]] = []
            if artist:
                if year:
                    queries.append((artist, year))
                queries.append((artist, ""))
            else:
                if year:
                    queries.append(("", year))
                queries.append(("", ""))

            found: list[dict] = []
            seen: set[str] = set()
            for query_artist, query_year in queries:
                check_cancel()
                for item in self._search_releases(variant, query_artist, query_year):
                    release_id = str(item.get("id") or "")
                    if not release_id or release_id in seen:
                        continue
                    seen.add(release_id)
                    found.append(item)

            # If the artist hint made everything empty, retry without it.
            if not found and artist:
                fallback_queries = ([year] if year else []) + [""]
                for query_year in fallback_queries:
                    check_cancel()
                    for item in self._search_releases(variant, "", query_year):
                        release_id = str(item.get("id") or "")
                        if not release_id or release_id in seen:
                            continue
                        seen.add(release_id)
                        found.append(item)
            return found

        seen_candidate_keys: set[str] = set()

        # The exact title and the base title (after removing "Part 2", editions,
        # etc.).  Avoid making an unbounded number of API requests.
        for variant in variants[:2]:
            check_cancel()
            if year:
                progress(f'Searching Discogs for “{variant}” ({year})…')
            else:
                progress(f'Searching Discogs for “{variant}”…')
            items = collect_queries(variant)
            result.candidate_count += len(items)

            # A single master release groups many pressings.  Pick the best
            # member of each master (digital, official, matching year) and show
            # the master's canonical image only once.
            grouped: dict[str, dict] = {}
            for item in items:
                key = self._candidate_key(item)
                existing = grouped.get(key)
                if existing is None or self._search_item_rank(
                    item, artist, year
                ) > self._search_item_rank(existing, artist, year):
                    grouped[key] = item

            ordered = sorted(
                grouped.values(),
                key=lambda item: self._search_item_rank(item, artist, year),
                reverse=True,
            )

            candidates: list[dict] = []
            for item in ordered:
                key = self._candidate_key(item)
                if key in seen_candidate_keys:
                    continue
                seen_candidate_keys.add(key)
                candidates.append(item)
                if len(candidates) >= self.max_releases:
                    break

            if not candidates:
                continue

            images = self._collect_and_download(
                candidates, progress, result.warnings, check_cancel, year
            )
            if images:
                result.images = images
                break

        return result

    def cover_for(
        self,
        entity: str,
        source_id: str,
        title: str = "",
        artist: str = "",
        year: str = "",
        source_url: str = "",
    ) -> Optional[CoverImage]:
        """Fetches the primary image for one already-chosen master/release."""
        detail = (
            self.get_master(source_id)
            if str(entity).lower() == "master"
            else self.get_release(source_id)
        )
        if not detail:
            return None
        info = self._primary_image(detail)
        if not info:
            return None
        url = _secure_discogs_url(str(info.get("uri") or "").strip())
        if not url.startswith(("http://", "https://")):
            return None
        data = self._fetch_bytes(url)
        width, height = image_dimensions(data) if data else (0, 0)
        if not data or width <= 0 or height <= 0:
            return None
        return CoverImage(
            full_url=url,
            thumb_url=url,
            thumb_urls=(url,),
            types=("Front",),
            front=True,
            entity=str(entity).lower(),
            mbid=str(source_id),
            release_title=title,
            release_artist=artist,
            release_date=year,
            thumbnail=data,
            width=width,
            height=height,
            provider="Discogs",
            source_url=source_url,
            is_official=True,
        )

    @staticmethod
    def _candidate_key(item: dict) -> str:
        master_id = str(item.get("master_id") or "").strip()
        if master_id and master_id != "0":
            return f"master:{master_id}"
        return f"release:{item.get('id')}"

    @staticmethod
    def _search_item_rank(item: dict, artist: str, year: str) -> float:
        formats = _format_values(item)
        digital = _is_digital(formats)
        official = _is_official(formats)
        title = str(item.get("title") or "").lower()
        item_year = _normalize_year(str(item.get("year") or ""))
        score = 0.0
        # For choosing the representative member of a master, an official
        # release is more important than a digital bootleg.
        if official:
            score += 10_000
        if digital:
            score += 5_000
        if year and item_year == year:
            score += 1_000
        if artist and artist.lower() in title:
            score += 100
        return score

    # -- Discogs API --------------------------------------------------------

    def _search_releases(self, title: str, artist: str, year: str = "") -> list[dict]:
        return self.search_database(
            release_title=title,
            artist=artist,
            year=year,
            per_page=max(self.max_releases * 3, 10),
        )

    def search_database(
        self,
        *,
        release_title: str = "",
        artist: str = "",
        year: str = "",
        per_page: int = 25,
    ) -> list[dict]:
        params = {
            "type": "release",
            "per_page": str(max(1, min(100, per_page))),
        }
        if release_title:
            params["release_title"] = release_title
        if artist:
            params["artist"] = artist
        if year:
            params["year"] = year
        url = f"{self.api_base}/database/search?{urllib.parse.urlencode(params)}"
        payload = self._get_json(url)
        if not isinstance(payload, dict):
            return []
        items = payload.get("results") or []
        return [
            item
            for item in items
            if isinstance(item, dict)
            and item.get("id")
            and str(item.get("type") or "").lower() == "release"
        ]

    def get_master(self, master_id: str, allow_404: bool = True) -> dict:
        detail = self._get_json(
            f"{self.api_base}/masters/{master_id}", allow_404=allow_404
        )
        return detail if isinstance(detail, dict) else {}

    def get_release(self, release_id: str, allow_404: bool = True) -> dict:
        detail = self._get_json(
            f"{self.api_base}/releases/{release_id}", allow_404=allow_404
        )
        return detail if isinstance(detail, dict) else {}

    def _collect_and_download(
        self,
        search_results: list[dict],
        progress: ProgressCallback,
        warnings: list[str],
        check_cancel: Callable[[], None],
        year: str = "",
    ) -> list[CoverImage]:
        images: list[CoverImage] = []
        seen_urls: set[str] = set()

        for index, item in enumerate(search_results, start=1):
            check_cancel()
            release_id = str(item.get("id"))
            master_id = str(item.get("master_id") or "").strip()
            is_master = bool(master_id and master_id != "0")
            progress(
                f"Checking Discogs {'master' if is_master else 'release'} "
                f"{index}/{len(search_results)}…"
            )

            master_detail: dict = {}
            release_detail: dict = {}
            if is_master:
                try:
                    master_detail = self._get_json(
                        f"{self.api_base}/masters/{master_id}", allow_404=True
                    ) or {}
                except DiscogsError as exc:
                    warnings.append(f"Discogs master {master_id}: {exc}")
                main_release_id = str(master_detail.get("main_release") or release_id)
                try:
                    release_detail = self._get_json(
                        f"{self.api_base}/releases/{main_release_id}", allow_404=True
                    ) or {}
                except DiscogsError as exc:
                    warnings.append(f"Discogs release {main_release_id}: {exc}")
                if not release_detail and main_release_id != release_id:
                    try:
                        release_detail = self._get_json(
                            f"{self.api_base}/releases/{release_id}", allow_404=True
                        ) or {}
                    except DiscogsError:
                        pass
            else:
                try:
                    release_detail = self._get_json(
                        f"{self.api_base}/releases/{release_id}", allow_404=True
                    ) or {}
                except DiscogsError as exc:
                    warnings.append(f"Discogs release {release_id}: {exc}")

            image_detail = master_detail or release_detail
            metadata_detail = release_detail or master_detail
            if not image_detail or not metadata_detail:
                continue

            image_info = self._primary_image(image_detail)
            if not image_info and image_detail is not release_detail and release_detail:
                image_info = self._primary_image(release_detail)
            if not image_info:
                continue
            image_url = str(image_info.get("uri") or "").strip()
            if not image_url.startswith(("http://", "https://")):
                continue
            image_url = _secure_discogs_url(image_url)
            if image_url in seen_urls:
                continue
            seen_urls.add(image_url)

            release = self._release_info(metadata_detail, release_id, item, year)
            source_id = master_id if is_master else release_id
            if is_master:
                source_url = str(master_detail.get("uri") or "").strip() or (
                    f"https://www.discogs.com/master/{master_id}"
                )
                if master_detail.get("title"):
                    release["title"] = str(master_detail["title"]).strip()
                master_artists = [
                    str(artist.get("name") or "").strip()
                    for artist in (master_detail.get("artists") or [])
                    if isinstance(artist, dict) and artist.get("name")
                ]
                if master_artists:
                    release["artist"] = ", ".join(master_artists)
                if master_detail.get("year"):
                    release["year"] = str(master_detail["year"])
            else:
                source_url = str(release_detail.get("uri") or "").strip() or (
                    f"https://www.discogs.com/release/{release_id}"
                )

            if not release["title"]:
                continue

            images.append(
                CoverImage(
                    full_url=image_url,
                    thumb_url=image_url,
                    thumb_urls=(image_url,),
                    types=("Front",),
                    front=True,
                    entity="master" if is_master else "release",
                    mbid=source_id,
                    release_title=release["title"],
                    release_artist=release["artist"],
                    release_date=release["year"],
                    comment=release["comment"],
                    provider="Discogs",
                    source_url=source_url,
                    is_digital=release["is_digital"],
                    is_official=release["is_official"],
                    rating=release["rating"],
                    rating_count=release["rating_count"],
                    rank_score=release["rank_score"],
                )
            )
            if len(images) >= MAX_IMAGES:
                break

        if not images:
            return []

        # Most relevant first: digital/official releases, matching year and
        # community rating.  This is what makes the first tile the best guess.
        images.sort(key=lambda image: image.rank_score, reverse=True)
        return self._download_images(images, progress, warnings, check_cancel)

    @staticmethod
    def _primary_image(detail: dict) -> Optional[dict]:
        images = detail.get("images") or []
        if not isinstance(images, list):
            return None
        for image in images:
            if (
                isinstance(image, dict)
                and str(image.get("type") or "").lower() == "primary"
                and image.get("uri")
            ):
                return image
        for image in images:
            if isinstance(image, dict) and image.get("uri"):
                return image
        return None

    @staticmethod
    def _release_info(
        detail: dict,
        release_id: str,
        search_item: dict,
        year_hint: str,
    ) -> dict:
        title = str(detail.get("title") or "").strip()
        artists = [
            str(artist.get("name") or "").strip()
            for artist in (detail.get("artists") or [])
            if isinstance(artist, dict) and artist.get("name")
        ]
        artist = ", ".join(artists)
        release_year = detail.get("year") or search_item.get("year")
        year_text = str(release_year) if release_year else ""
        country = str(detail.get("country") or "").strip()

        format_labels: list[str] = []
        for fmt in detail.get("formats") or []:
            if not isinstance(fmt, dict):
                continue
            name = str(fmt.get("name") or "").strip()
            descriptions = ", ".join(
                str(desc) for desc in (fmt.get("descriptions") or []) if desc
            )
            text = " / ".join(part for part in (name, descriptions) if part)
            if text and text not in format_labels:
                format_labels.append(text)
        if not format_labels:
            search_formats = [
                str(value) for value in (search_item.get("format") or []) if value
            ]
            if search_formats:
                format_labels.append(" / ".join(search_formats))

        quality_values = _format_values(detail) + _format_values(search_item)
        is_digital = _is_digital(quality_values)
        is_official = _is_official(quality_values)

        community = detail.get("community") or {}
        rating_info = community.get("rating") or {}
        try:
            rating = float(rating_info.get("average") or 0.0)
        except (TypeError, ValueError):
            rating = 0.0
        try:
            rating_count = int(rating_info.get("count") or 0)
        except (TypeError, ValueError):
            rating_count = 0

        year_match = bool(year_hint and _normalize_year(year_text) == year_hint)
        rank_score = 0.0
        if is_digital:
            rank_score += 10_000
        if is_official:
            rank_score += 1_000
        if year_match:
            rank_score += 1_000
        rank_score += rating * 50
        rank_score += min(rating_count, 50)

        comment_parts: list[str] = []
        if format_labels:
            comment_parts.append(format_labels[0])
        if country:
            comment_parts.append(country)
        comment = " · ".join(comment_parts)

        source_url = str(detail.get("uri") or "").strip()
        if not source_url:
            source_url = f"https://www.discogs.com/release/{release_id}"

        return {
            "title": title,
            "artist": artist,
            "year": year_text,
            "comment": comment,
            "source_url": source_url,
            "is_digital": is_digital,
            "is_official": is_official,
            "rating": rating,
            "rating_count": rating_count,
            "rank_score": rank_score,
        }

    def _download_images(
        self,
        images: list[CoverImage],
        progress: ProgressCallback,
        warnings: list[str],
        check_cancel: Callable[[], None],
    ) -> list[CoverImage]:
        total = len(images)
        progress(f"Downloading {total} Discogs artwork preview{'s' if total != 1 else ''}…")

        def load(image: CoverImage) -> None:
            try:
                data = self._fetch_bytes(image.thumb_url)
            except DiscogsError:
                return
            width, height = image_dimensions(data) if data else (0, 0)
            if data and width > 0 and height > 0:
                image.thumbnail = data
                image.width = width
                image.height = height

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(load, image): image for image in images}
            for done, future in enumerate(as_completed(futures), start=1):
                check_cancel()
                try:
                    future.result()
                except Exception:
                    pass
                if done == total or done % 3 == 0:
                    progress(f"Downloading Discogs artwork ({done}/{total})…")

        usable = [image for image in images if image.thumbnail]
        skipped = len(images) - len(usable)
        if skipped:
            warnings.append(
                f"{skipped} Discogs image{'s' if skipped != 1 else ''} "
                "could not be downloaded and were skipped."
            )
        # If at least one official master is available, do not clutter the
        # gallery with unofficial/bootleg covers.
        official = [image for image in usable if image.is_official]
        if official:
            usable = official
        return usable

    # -- HTTP ---------------------------------------------------------------

    def _get_json(
        self,
        url: str,
        *,
        allow_404: bool = False,
        retries: int = 2,
    ) -> Optional[dict]:
        headers = {
            "User-Agent": DISCOGS_USER_AGENT,
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Discogs token={self.token}"

        last_error: Optional[Exception] = None
        for attempt in range(retries):
            self._wait_api()
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                if not raw:
                    raise DiscogsError("Discogs returned an empty response.")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise DiscogsError("Discogs returned malformed JSON.") from exc
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and allow_404:
                    return None
                if exc.code == 401:
                    raise DiscogsError(
                        "Discogs rejected the access token. Check the DISCOGS_TOKEN "
                        "environment variable."
                    ) from exc
                last_error = exc
                if exc.code == 429 and attempt < retries - 1:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        delay = max(1.0, min(5.0, float(retry_after)))
                    except (TypeError, ValueError):
                        delay = 2.0
                    time.sleep(delay)
                    continue
                if 500 <= exc.code < 600 and attempt < retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if exc.code == 429:
                    raise DiscogsError(
                        "Discogs rate limit reached. Wait a minute or add "
                        "DISCOGS_TOKEN for a higher limit."
                    ) from exc
                raise DiscogsError(f"Discogs API returned HTTP {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                break

        raise DiscogsError(f"Discogs request failed: {last_error}")

    def _fetch_bytes(self, url: str, retries: int = 2) -> bytes:
        headers = {
            "User-Agent": DISCOGS_USER_AGENT,
            "Accept": "image/*",
        }
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read()
                if not data:
                    raise DiscogsError("Discogs returned an empty image.")
                return data
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise DiscogsError(f"Could not download the Discogs image (HTTP {exc.code}).") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                break
        raise DiscogsError(f"Could not download the Discogs image: {last_error}")

    def _wait_api(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_api_request
            if elapsed < DISCOGS_API_INTERVAL:
                time.sleep(DISCOGS_API_INTERVAL - elapsed)
            self._last_api_request = time.monotonic()

