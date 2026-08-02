from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings


IMDB_ID_RE = re.compile(r"(?i)\b(tt\d{7,10})\b")
_IMDB_TOKEN_RE = re.compile(r"(?i)(?:\bimdb\b[\s._:/-]*)?\btt\d{7,10}\b")
_TRAILING_CP_RE = re.compile(r"(?i)(?:^|[\s._-])cp\s*$")


def extract_imdb_id(*values: Any) -> str | None:
    """Return the first IMDb title ID found in strings or nested metadata.

    Filesystem libraries commonly append identifiers as ``tt1234567``,
    ``(tt1234567)``, or ``cp(tt1234567)``. Kodi/Jellyfin NFO data may instead
    place the same value under ``unique_ids.imdb``. The recursive traversal is
    intentionally bounded to ordinary mappings and iterables used by source
    candidates; arbitrary objects are ignored.
    """

    def visit(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            match = IMDB_ID_RE.search(value)
            return match.group(1).lower() if match else None
        if isinstance(value, Mapping):
            # Prefer explicit IMDb fields before scanning other metadata.
            for key, item in value.items():
                if str(key).lower() in {"imdb", "imdb_id", "imdbid", "imdbnumber"}:
                    found = visit(item)
                    if found:
                        return found
            for item in value.values():
                found = visit(item)
                if found:
                    return found
            return None
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            for item in value:
                found = visit(item)
                if found:
                    return found
        return None

    for value in values:
        found = visit(value)
        if found:
            return found
    return None


def clean_tmdb_search_title(title: str) -> str:
    """Remove appended IMDb IDs and common copy markers from a search title."""
    cleaned = _IMDB_TOKEN_RE.sub(" ", title or "")
    cleaned = re.sub(r"[\[\](){}]", " ", cleaned)
    cleaned = _TRAILING_CP_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[._]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -._")
    return cleaned or title.strip()


class TmdbClient:
    def __init__(self, token: str | None = None):
        self.token = token or settings.tmdb_api_token

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def find_movie_by_imdb_id(self, imdb_id: str) -> dict | None:
        """Resolve an IMDb title ID through TMDB's /find endpoint."""
        normalized = extract_imdb_id(imdb_id)
        if not self.token or not normalized:
            return None
        try:
            response = httpx.get(
                f"https://api.themoviedb.org/3/find/{normalized}",
                params={"external_source": "imdb_id", "language": "en-US"},
                headers=self._headers,
                timeout=20,
            )
            response.raise_for_status()
            results = response.json().get("movie_results", [])
            if not results:
                return None
            result = dict(results[0])
            result["_reelindex_match"] = "imdb"
            result["_reelindex_imdb_id"] = normalized
            return result
        except Exception:
            return None

    def find_movie(
        self,
        title: str,
        year: int | None = None,
        imdb_id: str | None = None,
    ) -> dict | None:
        if not self.token:
            return None

        direct_id = extract_imdb_id(imdb_id, title)
        if direct_id:
            direct = self.find_movie_by_imdb_id(direct_id)
            if direct:
                return direct

        query = clean_tmdb_search_title(title)
        params = {"query": query, "include_adult": "false", "language": "en-US"}
        if year:
            params["year"] = str(year)
        try:
            response = httpx.get(
                "https://api.themoviedb.org/3/search/movie",
                params=params,
                headers=self._headers,
                timeout=20,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if results:
                result = dict(results[0])
                result["_reelindex_match"] = "title-year" if year else "title"
                if direct_id:
                    result["_reelindex_imdb_id"] = direct_id
                return result

            # A wrong or absent year is common in release-folder names. Retry the
            # already-cleaned title without the year before giving up.
            if year:
                response = httpx.get(
                    "https://api.themoviedb.org/3/search/movie",
                    params={"query": query, "include_adult": "false", "language": "en-US"},
                    headers=self._headers,
                    timeout=20,
                )
                response.raise_for_status()
                results = response.json().get("results", [])
                if results:
                    result = dict(results[0])
                    result["_reelindex_match"] = "title"
                    if direct_id:
                        result["_reelindex_imdb_id"] = direct_id
                    return result
            return None
        except Exception:
            return None

    def download_poster(self, poster_path: str, destination: Path) -> bool:
        if not poster_path:
            return False
        try:
            response = httpx.get(f"https://image.tmdb.org/t/p/w{settings.poster_width}{poster_path}", timeout=30)
            response.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return True
        except Exception:
            return False
