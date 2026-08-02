from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings


IMDB_ID_RE = re.compile(r"(?i)\b(tt\d{7,10})\b")
_IMDB_TOKEN_RE = re.compile(r"(?i)(?:\bimdb\b[\s._:/-]*)?\btt\d{7,10}\b")
_TRAILING_CP_RE = re.compile(r"(?i)(?:^|[\s._-])cp\s*$")
_DISC_RE = re.compile(r"(?i)\b(?:cd|disc|disk)\s*0?\d+\b")
_DIMENSIONS_RE = re.compile(r"(?i)\b\d{3,4}\s*[x×]\s*\d{3,4}\b")
_RESOLUTION_RE = re.compile(r"(?i)\b(?:480|576|720|1080|1440|2160)p\b|\b4k\b")
_RELEASE_TOKEN_RE = re.compile(
    r"(?ix)\b(?:"
    r"readnfo|cropped|rerip|repack|proper|limited|internal|unrated|remastered|"
    r"bdrip|brrip|brrip|dvdrip|hdrip|hdtv|dvdscr|webrip|web[ ._-]?dl|r5|"
    r"xvid(?:hd)?|x26[45]|h[ ._-]?26[45]|hevc|10bit|ac3|aac|dts|ntsc|pal|"
    r"swesub|norar|dvdr|eng|maxspeed|fxg|vision|santi|mc8|omnidvd"
    r")\b"
)
_SITE_TRAIL_RE = re.compile(r"(?i)\bwww(?:\s|[._-]).*$")
_RELEASE_GROUP_RE = re.compile(r"(?i)\s+-\s*[a-z0-9][a-z0-9-]{1,18}\s*$")
_TRAILING_ARTICLE_RE = re.compile(r"(?i)^(.*?),\s*(the|a|an)$")
_FRANCHISE_ORDER_RE = re.compile(r"(?i)\b(Star\s+Trek|Harry\s+Potter)\s+0?\d{1,2}\b")
_AKA_TRAIL_RE = re.compile(r"(?i)\s+aka\s+.*$")


def extract_imdb_id(*values: Any) -> str | None:
    """Return the first IMDb title ID found in strings or nested metadata."""

    def visit(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            match = IMDB_ID_RE.search(value)
            return match.group(1).lower() if match else None
        if isinstance(value, Mapping):
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


def _collapse_title(value: str) -> str:
    value = re.sub(r"[._]+", " ", value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -._")


def clean_tmdb_search_title(title: str) -> str:
    """Remove appended IMDb IDs and copy markers from a search title."""
    cleaned = _IMDB_TOKEN_RE.sub(" ", title or "")
    cleaned = re.sub(r"[\[\](){}]", " ", cleaned)
    cleaned = _TRAILING_CP_RE.sub(" ", cleaned)
    return _collapse_title(cleaned) or title.strip()


def clean_release_title(title: str) -> str:
    """Remove common scene/release noise without changing meaningful words."""
    cleaned = clean_tmdb_search_title(title)
    cleaned = _DISC_RE.sub(" ", cleaned)
    cleaned = _DIMENSIONS_RE.sub(" ", cleaned)
    cleaned = _RESOLUTION_RE.sub(" ", cleaned)
    cleaned = _RELEASE_TOKEN_RE.sub(" ", cleaned)
    cleaned = _SITE_TRAIL_RE.sub(" ", cleaned)
    cleaned = _RELEASE_GROUP_RE.sub(" ", cleaned)
    cleaned = _AKA_TRAIL_RE.sub(" ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:no\s*rar)\b", " ", cleaned)
    cleaned = _collapse_title(cleaned)
    match = _TRAILING_ARTICLE_RE.match(cleaned)
    if match:
        cleaned = _collapse_title(f"{match.group(2)} {match.group(1)}")
    return cleaned or clean_tmdb_search_title(title)


def generate_search_titles(title: str) -> list[str]:
    """Return safe, ordered title variants for automatic and manual matching."""
    variants: list[str] = []

    def add(value: str) -> None:
        value = _collapse_title(value)
        if value and value.casefold() not in {item.casefold() for item in variants}:
            variants.append(value)

    base = clean_tmdb_search_title(title)
    release = clean_release_title(base)
    add(base)
    add(release)

    match = _TRAILING_ARTICLE_RE.match(release)
    if match:
        add(f"{match.group(2)} {match.group(1)}")

    add(_FRANCHISE_ORDER_RE.sub(r"\1", release))
    return variants or [title.strip()]


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _year(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value[:4])
    except (TypeError, ValueError):
        return None


class TmdbClient:
    def __init__(self, token: str | None = None):
        self.token = token or settings.tmdb_api_token

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict | None:
        if not self.token:
            return None
        try:
            response = httpx.get(
                f"https://api.themoviedb.org/3{path}",
                params=params,
                headers=self._headers,
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def find_movie_by_imdb_id(self, imdb_id: str) -> dict | None:
        normalized = extract_imdb_id(imdb_id)
        if not normalized:
            return None
        payload = self._get(
            f"/find/{normalized}",
            {"external_source": "imdb_id", "language": "en-US"},
        )
        if not payload:
            return None
        results = payload.get("movie_results", [])
        if not results:
            return None
        result = dict(results[0])
        result["_reelindex_match"] = "imdb"
        result["_reelindex_imdb_id"] = normalized
        result["_reelindex_media_type"] = "movie"
        return result

    @staticmethod
    def _result_score(result: dict, query: str, year: int | None) -> float:
        query_key = _normalized(query)
        names = [result.get("title"), result.get("original_title"), result.get("name"), result.get("original_name")]
        ratios = [SequenceMatcher(None, query_key, _normalized(name)).ratio() for name in names if name]
        score = max(ratios or [0.0])
        result_year = _year(result.get("release_date") or result.get("first_air_date"))
        if year and result_year:
            score += 0.15 if year == result_year else -min(abs(year - result_year) * 0.03, 0.18)
        if result.get("poster_path"):
            score += 0.05
        return score

    def _search_endpoint(self, media_type: str, query: str, year: int | None = None) -> list[dict]:
        params = {"query": query, "include_adult": "false", "language": "en-US"}
        if year:
            params["year" if media_type == "movie" else "first_air_date_year"] = str(year)
        payload = self._get(f"/search/{media_type}", params)
        results = payload.get("results", []) if payload else []
        normalized: list[dict] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            record = dict(item)
            record["_reelindex_media_type"] = media_type
            normalized.append(record)
        return normalized

    def search_catalog(
        self,
        query: str,
        year: int | None = None,
        include_tv: bool = True,
        limit: int = 20,
    ) -> list[dict]:
        """Search TMDB movies and optional TV entries for manual poster selection."""
        if not self.token or not query.strip():
            return []

        imdb_id = extract_imdb_id(query)
        collected: list[dict] = []
        if imdb_id:
            payload = self._get(
                f"/find/{imdb_id}",
                {"external_source": "imdb_id", "language": "en-US"},
            ) or {}
            for media_type, key in (("movie", "movie_results"), ("tv", "tv_results")):
                for item in payload.get(key, []) or []:
                    if isinstance(item, dict):
                        record = dict(item)
                        record["_reelindex_media_type"] = media_type
                        record["_reelindex_match"] = "imdb"
                        record["_reelindex_imdb_id"] = imdb_id
                        collected.append(record)
        else:
            variants = generate_search_titles(query)
            for variant in variants:
                collected.extend(self._search_endpoint("movie", variant, year))
                if include_tv:
                    collected.extend(self._search_endpoint("tv", variant, year))

        deduped: dict[tuple[str, int], dict] = {}
        score_query = clean_release_title(query)
        for result in collected:
            try:
                key = (str(result.get("_reelindex_media_type") or "movie"), int(result["id"]))
            except (KeyError, TypeError, ValueError):
                continue
            result["_reelindex_score"] = self._result_score(result, score_query, year)
            if key not in deduped or result["_reelindex_score"] > deduped[key].get("_reelindex_score", 0):
                deduped[key] = result
        ordered = sorted(
            deduped.values(),
            key=lambda item: (bool(item.get("poster_path")), item.get("_reelindex_score", 0), item.get("popularity", 0)),
            reverse=True,
        )
        return ordered[: max(1, min(limit, 50))]

    def get_title(self, tmdb_id: int, media_type: str = "movie") -> dict | None:
        if media_type not in {"movie", "tv"}:
            return None
        result = self._get(f"/{media_type}/{int(tmdb_id)}", {"language": "en-US"})
        if result:
            result["_reelindex_media_type"] = media_type
            result["_reelindex_match"] = "manual-tmdb"
        return result

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
            if direct and direct.get("poster_path"):
                return direct

        for query in generate_search_titles(title):
            for search_year in (year, None) if year else (None,):
                results = self._search_endpoint("movie", query, search_year)
                if not results:
                    continue
                ranked = sorted(results, key=lambda item: self._result_score(item, query, year), reverse=True)
                for result in ranked:
                    if not result.get("poster_path"):
                        continue
                    result = dict(result)
                    result["_reelindex_match"] = "title-year" if search_year else "title-cleaned"
                    result["_reelindex_query"] = query
                    if direct_id:
                        result["_reelindex_imdb_id"] = direct_id
                    return result
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
