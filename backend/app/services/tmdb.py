from __future__ import annotations

from pathlib import Path

import httpx

from app.core.config import settings


class TmdbClient:
    def __init__(self, token: str | None = None):
        self.token = token or settings.tmdb_api_token

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def find_movie(self, title: str, year: int | None = None) -> dict | None:
        if not self.token:
            return None
        params = {"query": title, "include_adult": "false", "language": "en-US"}
        if year:
            params["year"] = str(year)
        try:
            response = httpx.get(
                "https://api.themoviedb.org/3/search/movie",
                params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            return results[0] if results else None
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
