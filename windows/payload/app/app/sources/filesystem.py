from __future__ import annotations

import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.services.media_utils import clean_title, normalized_movie_key, stable_id
from app.sources.base import AdapterConnectionResult, DiscoveryCallback, FileCandidate, MovieCandidate


_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


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

        ``os.scandir`` keeps the number of SMB round trips low. Local artwork and
        sidecar metadata are resolved from the same directory lookup rather than
        performing another directory walk for every movie file.
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

            if not media_entries:
                continue

            folder_is_movie = len(media_entries) <= 3
            folder_name = Path(directory).name
            stems = [Path(entry.name).stem for entry in media_entries]
            shared_sidecar = self._read_local_metadata_from_lookup(file_lookup, stems) if folder_is_movie else {}
            shared_poster = (
                self._find_local_poster_from_lookup(file_lookup, stems, folder_name, include_generic=True)
                if folder_is_movie
                else None
            )

            for entry in media_entries:
                try:
                    stat = entry.stat(follow_symlinks=self.follow_symlinks)
                except (FileNotFoundError, PermissionError, OSError):
                    continue

                path = Path(entry.path)
                sidecar = (
                    shared_sidecar
                    if folder_is_movie
                    else self._read_local_metadata_from_lookup(file_lookup, [path.stem])
                )
                folder_poster = (
                    shared_poster
                    if folder_is_movie
                    else self._find_local_poster_from_lookup(
                        file_lookup, [path.stem], "", include_generic=False
                    )
                )
                raw_title_source = folder_name if folder_is_movie else entry.name
                title, year, folder_edition = clean_title(raw_title_source)
                _, _, file_edition = clean_title(entry.name)
                edition = file_edition or folder_edition or sidecar.get("edition")
                key = normalized_movie_key(sidecar.get("title") or title, sidecar.get("year") or year)
                movie = grouped.get(key)

                if not movie:
                    metadata = {"origin": "filesystem", **sidecar}
                    movie = MovieCandidate(
                        source_movie_id=stable_id(key),
                        title=sidecar.get("title") or title,
                        year=sidecar.get("year") or year,
                        runtime_seconds=sidecar.get("runtime_seconds"),
                        overview=sidecar.get("overview"),
                        poster_ref=os.fspath(folder_poster) if folder_poster else None,
                        metadata=metadata,
                    )
                    grouped[key] = movie

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
    def _find_local_poster_from_lookup(
        file_lookup: dict[str, os.DirEntry[str]], stems: Iterable[str], folder_name: str, include_generic: bool
    ) -> Path | None:
        """Find common Kodi/Jellyfin/Plex-style poster sidecars without extra I/O."""
        bases = ["poster", "folder", "cover", "movie", "front", "thumb"]
        candidates: list[str] = []

        # Generic names win in a one-movie-per-folder layout. They are skipped
        # for a flat directory because one generic image cannot represent every file.
        if include_generic:
            for base in bases:
                candidates.extend(f"{base}{extension}" for extension in _IMAGE_EXTENSIONS)

        # Then consider names tied to the folder or media file.
        specific_bases = [folder_name, f"{folder_name}-poster"] if folder_name else []
        for stem in stems:
            specific_bases.extend((stem, f"{stem}-poster", f"{stem}.poster"))
        for base in specific_bases:
            candidates.extend(f"{base}{extension}" for extension in _IMAGE_EXTENSIONS)

        for name in candidates:
            entry = file_lookup.get(name.lower())
            if entry:
                return Path(entry.path)
        return None

    @classmethod
    def _read_local_metadata_from_lookup(
        cls, file_lookup: dict[str, os.DirEntry[str]], stems: Iterable[str]
    ) -> dict[str, Any]:
        """Read common JSON or Kodi/Jellyfin NFO sidecars from the movie folder."""
        stem_list = list(stems)
        json_names = ["movie.json", "metadata.json"] + [f"{stem}.json" for stem in stem_list]
        nfo_names = ["movie.nfo"] + [f"{stem}.nfo" for stem in stem_list]

        for name in json_names:
            entry = file_lookup.get(name.lower())
            if entry:
                data = cls._read_json(Path(entry.path))
                if data:
                    data["metadata_sidecar"] = entry.name
                    return data

        for name in nfo_names:
            entry = file_lookup.get(name.lower())
            if entry:
                data = cls._read_nfo(Path(entry.path))
                if data:
                    data["metadata_sidecar"] = entry.name
                    return data
        return {}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}

        result = dict(data)
        if result.get("runtime_seconds") is None and result.get("runtime") is not None:
            result["runtime_seconds"] = FilesystemAdapter._parse_runtime(result.get("runtime"))
        if result.get("overview") is None:
            result["overview"] = result.get("plot") or result.get("description")
        result["year"] = FilesystemAdapter._parse_year(result.get("year"))
        return {key: value for key, value in result.items() if value not in (None, "")}

    @staticmethod
    def _read_nfo(path: Path) -> dict[str, Any]:
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, ET.ParseError):
            return {}

        def first_text(*tags: str) -> str | None:
            for tag in tags:
                node = root.find(f".//{tag}")
                if node is not None and node.text and node.text.strip():
                    return node.text.strip()
            return None

        result: dict[str, Any] = {
            "title": first_text("title"),
            "original_title": first_text("originaltitle"),
            "sort_title": first_text("sorttitle"),
            "year": FilesystemAdapter._parse_year(first_text("year", "premiered", "releasedate")),
            "runtime_seconds": FilesystemAdapter._parse_runtime(first_text("runtime", "duration")),
            "overview": first_text("plot", "outline", "description"),
            "edition": first_text("edition"),
            "tagline": first_text("tagline"),
        }
        unique_ids: dict[str, str] = {}
        for node in root.findall(".//uniqueid"):
            if node.text and node.text.strip():
                unique_ids[node.attrib.get("type", "unknown")] = node.text.strip()
        if unique_ids:
            result["unique_ids"] = unique_ids
        return {key: value for key, value in result.items() if value not in (None, "", {})}

    @staticmethod
    def _parse_year(value: Any) -> int | None:
        if value is None:
            return None
        match = re.search(r"(?:19|20)\d{2}", str(value))
        return int(match.group(0)) if match else None

    @staticmethod
    def _parse_runtime(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        try:
            number = float(text)
            # NFO runtimes are conventionally minutes. JSON can use runtime_seconds.
            return number * 60
        except ValueError:
            pass

        hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hour)", text)
        minutes = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|min|minute)", text)
        seconds = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|second)", text)
        total = 0.0
        if hours:
            total += float(hours.group(1)) * 3600
        if minutes:
            total += float(minutes.group(1)) * 60
        if seconds:
            total += float(seconds.group(1))
        return total or None
