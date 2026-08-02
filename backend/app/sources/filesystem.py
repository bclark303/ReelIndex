from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from app.core.config import settings
from app.services.media_utils import clean_title, normalized_movie_key, stable_id
from app.sources.base import AdapterConnectionResult, DiscoveryCallback, FileCandidate, MovieCandidate


class FilesystemAdapter:
    def __init__(self, root: str, config: dict):
        self.root = Path(root)
        self.config = config
        configured = config.get("extensions")
        self.extensions = {str(item).lower() for item in configured} if configured else settings.extension_set
        self.follow_symlinks = bool(config.get("follow_symlinks", False))

    def test_connection(self) -> AdapterConnectionResult:
        if not self.root.exists():
            return AdapterConnectionResult(False, f"Path does not exist: {self.root}")
        if not self.root.is_dir():
            return AdapterConnectionResult(False, f"Path is not a directory: {self.root}")
        try:
            next(self.root.iterdir(), None)
        except PermissionError:
            return AdapterConnectionResult(False, f"Permission denied: {self.root}")
        return AdapterConnectionResult(
            True,
            f"Readable media path: {self.root}",
            [{"id": str(self.root), "name": self.root.name or str(self.root)}],
        )

    def scan(self, progress: DiscoveryCallback | None = None) -> list[MovieCandidate]:
        """Scan using one directory enumeration per folder.

        ``os.walk`` already uses scandir internally, but the old implementation threw
        away DirEntry objects and then issued additional ``stat`` and directory-listing
        calls for every media file. That is especially expensive over SMB. This walker
        reuses DirEntry metadata, determines folder layout once, and never resolves each
        path against the network filesystem.
        """
        grouped: dict[str, MovieCandidate] = {}
        pending = [os.fspath(self.root)]
        discovered_files = 0

        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as iterator:
                    entries = list(iterator)
            except (FileNotFoundError, PermissionError, OSError):
                continue

            media_entries: list[os.DirEntry[str]] = []
            file_lookup: dict[str, os.DirEntry[str]] = {}

            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=self.follow_symlinks):
                        if self.follow_symlinks or not entry.is_symlink():
                            pending.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=self.follow_symlinks):
                        continue
                except OSError:
                    continue

                file_lookup[entry.name.lower()] = entry
                if Path(entry.name).suffix.lower() in self.extensions:
                    media_entries.append(entry)

            folder_is_movie = len(media_entries) <= 3
            folder_name = Path(directory).name
            nfo = self._read_nfo_json_from_lookup(file_lookup)

            for entry in media_entries:
                try:
                    stat = entry.stat(follow_symlinks=self.follow_symlinks)
                except (FileNotFoundError, PermissionError, OSError):
                    continue

                path = Path(entry.path)
                raw_title_source = folder_name if folder_is_movie else entry.name
                title, year, folder_edition = clean_title(raw_title_source)
                _, _, file_edition = clean_title(entry.name)
                edition = file_edition or folder_edition
                key = normalized_movie_key(title, year)
                movie = grouped.get(key)

                if not movie:
                    poster = self._find_local_poster_from_lookup(file_lookup, path.stem)
                    movie = MovieCandidate(
                        source_movie_id=stable_id(key),
                        title=nfo.get("title") or title,
                        year=nfo.get("year") or year,
                        runtime_seconds=nfo.get("runtime_seconds"),
                        overview=nfo.get("overview"),
                        poster_ref=os.fspath(poster) if poster else None,
                        metadata={"origin": "filesystem", **nfo},
                    )
                    grouped[key] = movie

                # abspath/normcase are lexical operations. Path.resolve() may perform
                # expensive network lookups for every file on Windows/SMB.
                stable_path = os.path.normcase(os.path.abspath(entry.path))
                movie.files.append(
                    FileCandidate(
                        source_file_id=stable_id(stable_path),
                        path=os.fspath(path),
                        filename=entry.name,
                        local_path=path,
                        size_bytes=stat.st_size,
                        modified_ts=stat.st_mtime,
                        edition=edition,
                    )
                )
                discovered_files += 1
                if progress:
                    progress(len(grouped), discovered_files, directory)

        return sorted(grouped.values(), key=lambda movie: (movie.title.lower(), movie.year or 0))

    def fetch_poster(self, candidate: MovieCandidate, destination: Path) -> bool:
        if not candidate.poster_ref:
            return False
        source = Path(candidate.poster_ref)
        try:
            if not source.is_file():
                return False
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return True
        except OSError:
            return False

    @staticmethod
    def _find_local_poster_from_lookup(file_lookup: dict[str, os.DirEntry[str]], stem: str) -> Path | None:
        names = [
            "poster.jpg",
            "poster.jpeg",
            "poster.png",
            "folder.jpg",
            "cover.jpg",
            f"{stem}.jpg",
            f"{stem}.png",
        ]
        for name in names:
            entry = file_lookup.get(name.lower())
            if entry:
                return Path(entry.path)
        return None

    @staticmethod
    def _read_nfo_json_from_lookup(file_lookup: dict[str, os.DirEntry[str]]) -> dict:
        entry = file_lookup.get("movie.json")
        if not entry:
            return {}
        try:
            data = json.loads(Path(entry.path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
