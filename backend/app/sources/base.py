from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol


@dataclass
class FileCandidate:
    source_file_id: str
    path: str
    filename: str
    local_path: Path | None = None
    size_bytes: int | None = None
    modified_ts: float | None = None
    edition: str | None = None
    technical: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps({"id": self.source_file_id, "path": self.path, "size": self.size_bytes, "modified": self.modified_ts, "technical": self.technical}, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


@dataclass
class MovieCandidate:
    source_movie_id: str
    title: str
    year: int | None = None
    runtime_seconds: float | None = None
    overview: str | None = None
    poster_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    files: list[FileCandidate] = field(default_factory=list)


@dataclass
class AdapterConnectionResult:
    ok: bool
    message: str
    libraries: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    def test_connection(self) -> AdapterConnectionResult: ...
    def scan(self) -> list[MovieCandidate]: ...
    def fetch_poster(self, candidate: MovieCandidate, destination: Path) -> bool: ...
