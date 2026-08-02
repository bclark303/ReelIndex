from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

import httpx

from app.services.media_utils import map_remote_path, resolution_label
from app.sources.base import AdapterConnectionResult, FileCandidate, MovieCandidate


class JellyfinAdapter:
    def __init__(self, base_url: str, library_id: str | None, config: dict, server_type: str = "jellyfin"):
        self.base_url = base_url.rstrip("/") + "/"
        self.library_id = library_id
        self.token = config.get("token")
        self.user_id = config.get("user_id")
        self.verify_ssl = bool(config.get("verify_ssl", True))
        self.path_mappings = config.get("path_mappings", [])
        self.server_type = server_type

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-Emby-Token"] = self.token
        return headers

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        response = httpx.get(
            urljoin(self.base_url, path.lstrip("/")),
            params=params,
            headers=self._headers(),
            verify=self.verify_ssl,
            timeout=30,
        )
        response.raise_for_status()
        return response

    def test_connection(self) -> AdapterConnectionResult:
        try:
            system = self._get("/System/Info/Public").json()
            libraries = []
            if self.token:
                folders = self._get("/Library/MediaFolders").json().get("Items", [])
                libraries = [{"id": item.get("Id", ""), "name": item.get("Name", "Unnamed")} for item in folders]
            details = {"server_name": system.get("ServerName"), "version": system.get("Version")}
            return AdapterConnectionResult(True, f"Connected to {self.server_type.title()} {details.get('server_name') or ''}".strip(), libraries, details)
        except Exception as exc:
            return AdapterConnectionResult(False, f"{self.server_type.title()} connection failed: {exc}")

    def scan(self) -> list[MovieCandidate]:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie",
            "Fields": "Path,MediaSources,ProviderIds,Overview,ProductionYear,RunTimeTicks,ImageTags,DateCreated,Genres,OfficialRating,Studios",
            "EnableImages": "true",
            "ImageTypeLimit": "1",
            "Limit": "100000",
        }
        if self.library_id:
            params["ParentId"] = self.library_id
        endpoint = f"/Users/{self.user_id}/Items" if self.user_id else "/Items"
        items = self._get(endpoint, params=params).json().get("Items", [])
        movies: list[MovieCandidate] = []
        for item in items:
            item_id = item.get("Id")
            if not item_id:
                continue
            candidate = MovieCandidate(
                source_movie_id=item_id,
                title=item.get("Name") or "Untitled",
                year=item.get("ProductionYear"),
                runtime_seconds=(item.get("RunTimeTicks") or 0) / 10_000_000 or None,
                overview=item.get("Overview"),
                poster_ref=item_id if item.get("ImageTags", {}).get("Primary") else None,
                metadata={
                    "origin": self.server_type,
                    "provider_ids": item.get("ProviderIds", {}),
                    "genres": item.get("Genres", []),
                    "official_rating": item.get("OfficialRating"),
                    "date_created": item.get("DateCreated"),
                },
            )
            media_sources = item.get("MediaSources") or []
            if not media_sources and item.get("Path"):
                media_sources = [{"Id": item_id, "Path": item.get("Path"), "Size": item.get("Size"), "RunTimeTicks": item.get("RunTimeTicks"), "MediaStreams": item.get("MediaStreams", [])}]
            for source_index, media in enumerate(media_sources):
                path = media.get("Path") or item.get("Path") or f"{self.server_type}:{item_id}:{source_index}"
                streams = media.get("MediaStreams") or []
                video = next((stream for stream in streams if stream.get("Type") == "Video"), {})
                audio = next((stream for stream in streams if stream.get("Type") == "Audio"), {})
                width, height = video.get("Width"), video.get("Height")
                technical = {
                    "container": media.get("Container") or Path(path).suffix.lstrip("."),
                    "duration_seconds": (media.get("RunTimeTicks") or item.get("RunTimeTicks") or 0) / 10_000_000 or None,
                    "video_codec": video.get("Codec"),
                    "width": width,
                    "height": height,
                    "resolution_label": resolution_label(width, height),
                    "video_bitrate": video.get("BitRate") or media.get("Bitrate"),
                    "audio_codec": audio.get("Codec"),
                    "audio_channels": audio.get("Channels"),
                    "audio_languages": audio.get("Language"),
                }
                candidate.files.append(
                    FileCandidate(
                        source_file_id=media.get("Id") or f"{item_id}:{source_index}",
                        path=path,
                        filename=Path(path).name,
                        local_path=map_remote_path(path, self.path_mappings),
                        size_bytes=media.get("Size"),
                        technical=technical,
                    )
                )
            movies.append(candidate)
        return movies

    def fetch_poster(self, candidate: MovieCandidate, destination: Path) -> bool:
        if not candidate.poster_ref:
            return False
        try:
            response = self._get(f"/Items/{candidate.poster_ref}/Images/Primary", params={"maxWidth": 700, "quality": 90})
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return True
        except Exception:
            return False
