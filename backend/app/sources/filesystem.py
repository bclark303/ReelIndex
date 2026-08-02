from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

from app.core.config import settings
from app.services.media_utils import clean_title, normalized_movie_key, stable_id
from app.sources.base import AdapterConnectionResult, FileCandidate, MovieCandidate


class FilesystemAdapter:
    def __init__(self, root: str, config: dict):
        self.root = Path(root)
        self.config = config
        configured = config.get("extensions")
        self.extensions = {str(item).lower() for item in configured} if configured else settings.extension_set
        self.follow_symlinks = bool(config.get("follow_symlinks", False))

    def test_connection(self) -> AdapterConnectionResult:
        if not self.root.exists():
            return AdapterConnectionResult(False, f"Path does not exist inside the container: {self.root}")
        if not self.root.is_dir():
            return AdapterConnectionResult(False, f"Path is not a directory: {self.root}")
        try:
            next(self.root.iterdir(), None)
        except PermissionError:
            return AdapterConnectionResult(False, f"Permission denied: {self.root}")
        return AdapterConnectionResult(True, f"Readable media path: {self.root}", [{"id": str(self.root), "name": self.root.name or str(self.root)}])

    def scan(self) -> list[MovieCandidate]:
        grouped: dict[str, MovieCandidate] = {}
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=self.follow_symlinks):
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix.lower() not in self.extensions:
                    continue
                try:
                    stat = path.stat()
                except (FileNotFoundError, PermissionError, OSError):
                    continue

                raw_title_source = path.parent.name if self._folder_is_movie(path.parent, path) else path.name
                title, year, folder_edition = clean_title(raw_title_source)
                _, _, file_edition = clean_title(path.name)
                edition = file_edition or folder_edition
                key = normalized_movie_key(title, year)
                movie = grouped.get(key)
                if not movie:
                    poster = self._find_local_poster(path.parent, path.stem)
                    nfo = self._read_nfo_json(path.parent)
                    movie = MovieCandidate(
                        source_movie_id=stable_id(key),
                        title=nfo.get("title") or title,
                        year=nfo.get("year") or year,
                        runtime_seconds=nfo.get("runtime_seconds"),
                        overview=nfo.get("overview"),
                        poster_ref=str(poster) if poster else None,
                        metadata={"origin": "filesystem", **nfo},
                    )
                    grouped[key] = movie
                movie.files.append(
                    FileCandidate(
                        source_file_id=stable_id(str(path.resolve())),
                        path=str(path),
                        filename=filename,
                        local_path=path,
                        size_bytes=stat.st_size,
                        modified_ts=stat.st_mtime,
                        edition=edition,
                    )
                )
        return sorted(grouped.values(), key=lambda movie: (movie.title.lower(), movie.year or 0))

    def fetch_poster(self, candidate: MovieCandidate, destination: Path) -> bool:
        if not candidate.poster_ref:
            return False
        source = Path(candidate.poster_ref)
        if not source.exists():
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return True

    def _folder_is_movie(self, folder: Path, current: Path) -> bool:
        try:
            media = [item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in self.extensions]
        except (PermissionError, OSError):
            return False
        return len(media) <= 3 and current in media

    @staticmethod
    def _find_local_poster(folder: Path, stem: str) -> Path | None:
        names = ["poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "cover.jpg", f"{stem}.jpg", f"{stem}.png"]
        for name in names:
            candidate = folder / name
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _read_nfo_json(folder: Path) -> dict:
        # Optional lightweight sidecar supported for local testing and portability.
        path = folder / "movie.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
