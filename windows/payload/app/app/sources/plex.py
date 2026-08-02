from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app.services.media_utils import map_remote_path, resolution_label
from app.sources.base import AdapterConnectionResult, DiscoveryCallback, FileCandidate, MovieCandidate


class PlexAdapter:
    def __init__(self, base_url: str, library_id: str | None, config: dict):
        self.base_url = base_url.rstrip("/") + "/"
        self.library_id = library_id
        self.token = config.get("token")
        self.verify_ssl = bool(config.get("verify_ssl", True))
        self.path_mappings = config.get("path_mappings", [])
        self.timeout = httpx.Timeout(30.0)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/xml"}
        if self.token:
            headers["X-Plex-Token"] = self.token
        return headers

    def _get(self, path: str) -> httpx.Response:
        response = httpx.get(urljoin(self.base_url, path.lstrip("/")), headers=self._headers(), verify=self.verify_ssl, timeout=self.timeout)
        response.raise_for_status()
        return response

    def test_connection(self) -> AdapterConnectionResult:
        try:
            response = self._get("/library/sections")
            root = ET.fromstring(response.text)
            libraries = [
                {"id": item.attrib.get("key", ""), "name": item.attrib.get("title", "Unnamed")}
                for item in root.findall("Directory")
                if item.attrib.get("type") == "movie"
            ]
            return AdapterConnectionResult(True, f"Connected to Plex ({len(libraries)} movie libraries)", libraries)
        except Exception as exc:
            return AdapterConnectionResult(False, f"Plex connection failed: {exc}")

    def scan(self, progress: DiscoveryCallback | None = None) -> list[MovieCandidate]:
        if not self.library_id:
            raise ValueError("A Plex movie library must be selected")
        response = self._get(f"/library/sections/{self.library_id}/all?type=1&includeGuids=1")
        root = ET.fromstring(response.text)
        movies: list[MovieCandidate] = []
        discovered_files = 0
        for video in root.findall("Video"):
            rating_key = video.attrib.get("ratingKey")
            if not rating_key:
                continue
            candidate = MovieCandidate(
                source_movie_id=rating_key,
                title=video.attrib.get("title") or "Untitled",
                year=_int(video.attrib.get("year")),
                runtime_seconds=(_float(video.attrib.get("duration")) or 0) / 1000 or None,
                overview=video.attrib.get("summary"),
                poster_ref=video.attrib.get("thumb"),
                metadata={
                    "origin": "plex",
                    "rating_key": rating_key,
                    "content_rating": video.attrib.get("contentRating"),
                    "studio": video.attrib.get("studio"),
                    "added_at": video.attrib.get("addedAt"),
                    "updated_at": video.attrib.get("updatedAt"),
                },
            )
            for media_index, media in enumerate(video.findall("Media")):
                technical = {
                    "container": media.attrib.get("container"),
                    "duration_seconds": (_float(media.attrib.get("duration")) or 0) / 1000 or None,
                    "video_codec": media.attrib.get("videoCodec"),
                    "audio_codec": media.attrib.get("audioCodec"),
                    "audio_channels": _float(media.attrib.get("audioChannels")),
                    "video_bitrate": (_int(media.attrib.get("bitrate")) or 0) * 1000 or None,
                    "width": _int(media.attrib.get("width")),
                    "height": _int(media.attrib.get("height")),
                }
                technical["resolution_label"] = resolution_label(technical["width"], technical["height"])
                for part_index, part in enumerate(media.findall("Part")):
                    path = part.attrib.get("file") or part.attrib.get("key") or f"plex:{rating_key}:{media_index}:{part_index}"
                    local_path = map_remote_path(path, self.path_mappings)
                    candidate.files.append(
                        FileCandidate(
                            source_file_id=part.attrib.get("id") or f"{rating_key}:{media_index}:{part_index}",
                            path=path,
                            filename=Path(path).name,
                            local_path=local_path,
                            size_bytes=_int(part.attrib.get("size")),
                            modified_ts=_float(part.attrib.get("updatedAt")),
                            technical=technical,
                        )
                    )
            movies.append(candidate)
            discovered_files += len(candidate.files)
            if progress:
                progress(len(movies), discovered_files, candidate.title)
        return movies

    def fetch_poster(self, candidate: MovieCandidate, destination: Path) -> bool:
        if not candidate.poster_ref:
            return False
        try:
            response = self._get(candidate.poster_ref)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return True
        except Exception:
            return False


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
