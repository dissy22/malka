"""Discogs API settings used by the metadata/artwork integration."""

from __future__ import annotations

import os

DISCOGS_API_BASE = os.environ.get("COVERART_DISCOGS_API", "https://api.discogs.com").rstrip("/")
DISCOGS_USER_AGENT = "Malka/1.0 +https://github.com/dissy22/malka"
DISCOGS_MAX_RELEASES_PER_QUERY = 6
DISCOGS_API_INTERVAL = 0.35
DISCOGS_DEADLINE = 60.0
HTTP_TIMEOUT = 15.0
MAX_IMAGES = 40


def discogs_token() -> str:
    env_token = os.environ.get("DISCOGS_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        from malka.config import config

        return str(getattr(config, "discogs_token", "") or "").strip()
    except Exception:
        return ""
