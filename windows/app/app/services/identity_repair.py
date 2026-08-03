from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import selectinload

from app.models import MediaFile, MediaFileSource, Movie
from app.services import library_identity as core


def _is_live(media_file: MediaFile) -> bool:
    state = inspect(media_file)
    return not state.deleted and not state.detached


def _unique_compatible_movie(candidate: Any, files: list[MediaFile]) -> Movie | None:
    matches = {
        media_file.movie.id: media_file.movie
        for media_file in files
        if _is_live(media_file)
        and media_file.movie is not None
        and core.content_identity_compatible(candidate, media_file.movie)
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def apply_identity_repair() -> None:
    """Harden canonical matching without changing the persisted schema.

    Older filesystem scans could collapse punctuation-bearing folders such as
    ``Dr. No`` and ``Dr. Strangelove`` into one ``Dr`` movie. Those scans left
    exact-path source aliases pointing at the malformed row. The patched index
    validates a source alias and path match against the corrected title/year,
    then moves the alias to the compatible canonical media-server record.
    """

    cls = core.LibraryIdentityIndex
    if getattr(cls, "_reelindex_identity_repair", False):
        return

    original_init = cls.__init__
    original_register_file = cls.register_file
    original_ensure_movie_link = cls.ensure_movie_link
    original_ensure_file_link = cls.ensure_file_link

    def repaired_init(self: core.LibraryIdentityIndex, db: Any) -> None:
        original_init(self, db)
        self.file_key_candidates: dict[str, list[MediaFile]] = defaultdict(list)
        files = db.scalars(
            select(MediaFile).options(
                selectinload(MediaFile.movie),
                selectinload(MediaFile.source_links),
            )
        ).all()
        for media_file in files:
            for key in core.file_identity_keys(media_file):
                self.file_key_candidates[key].append(media_file)

    def repaired_register_file(self: core.LibraryIdentityIndex, media_file: MediaFile) -> None:
        original_register_file(self, media_file)
        for key in core.file_identity_keys(media_file):
            bucket = self.file_key_candidates[key]
            if not any(existing.id == media_file.id for existing in bucket):
                bucket.append(media_file)

    def repaired_movie_for_candidate(
        self: core.LibraryIdentityIndex,
        source_id: str,
        candidate: Any,
    ) -> tuple[Movie | None, Any | None]:
        source_link = self.source_movies.get((source_id, str(candidate.source_movie_id)))
        if source_link and core.content_identity_compatible(candidate, source_link.movie):
            return source_link.movie, source_link

        metadata = dict(getattr(candidate, "metadata", {}) or {})
        keys = core.movie_identity_keys(
            getattr(candidate, "title", None),
            getattr(candidate, "year", None),
            getattr(candidate, "runtime_seconds", None),
            metadata,
        )
        external_keys = sorted(key for key in keys if key.startswith(("imdb:", "tmdb:")))
        fallback_keys = sorted(key for key in keys if key not in external_keys)

        for key in external_keys:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None

        for file_candidate in getattr(candidate, "files", []) or []:
            for key in core.strong_file_identity_keys(file_candidate):
                movie = _unique_compatible_movie(
                    candidate,
                    self.file_key_candidates.get(key, []),
                )
                if movie is not None:
                    return movie, None

        for file_candidate in getattr(candidate, "files", []) or []:
            for key in core.trusted_content_identity_keys(file_candidate):
                movie = _unique_compatible_movie(
                    candidate,
                    self.file_key_candidates.get(key, []),
                )
                if movie is not None:
                    return movie, None

        for key in fallback_keys:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None

        # Exact source aliases remain authoritative when no better compatible
        # canonical record exists. This preserves manual metadata and avoids
        # inserting a duplicate row with the same legacy source identity.
        if source_link:
            return source_link.movie, source_link
        return None, None

    def repaired_ensure_movie_link(
        self: core.LibraryIdentityIndex,
        movie: Movie,
        source_id: str,
        source_movie_id: str,
    ) -> Any:
        key = (source_id, str(source_movie_id))
        link = self.source_movies.get(key)
        if link and link.movie_id != movie.id:
            link.movie = movie
            self.db.flush()
        return original_ensure_movie_link(self, movie, source_id, source_movie_id)

    def repaired_file_for_candidate(
        self: core.LibraryIdentityIndex,
        source_id: str,
        movie: Movie,
        candidate: Any,
    ) -> tuple[MediaFile | None, Any | None]:
        source_link = self.source_files.get((source_id, str(candidate.source_file_id)))
        if source_link and source_link.media_file.movie_id == movie.id:
            return source_link.media_file, source_link

        for key in core.file_identity_keys(candidate):
            matches = {
                media_file.id: media_file
                for media_file in self.file_key_candidates.get(key, [])
                if _is_live(media_file) and media_file.movie_id == movie.id
            }
            if len(matches) == 1:
                return next(iter(matches.values())), source_link
        return None, source_link

    def repaired_ensure_file_link(
        self: core.LibraryIdentityIndex,
        media_file: MediaFile,
        source_id: str,
        source_file_id: str,
        path: str,
    ) -> Any:
        key = (source_id, str(source_file_id))
        existing = self.source_files.get(key)
        old_file = existing.media_file if existing else None

        # Move the ORM relationship before the old file is deleted. Updating
        # only media_file_id leaves the relationship attached to the old parent,
        # allowing delete-orphan cascading to delete the source link itself.
        if existing is not None and old_file is not None and old_file.id != media_file.id:
            existing.media_file = media_file

        link = original_ensure_file_link(
            self,
            media_file,
            source_id,
            source_file_id,
            path,
        )
        if old_file is not None and old_file.id != media_file.id:
            self.db.flush()
            remaining = self.db.scalar(
                select(func.count(MediaFileSource.id)).where(
                    MediaFileSource.media_file_id == old_file.id
                )
            )
            if not remaining and _is_live(old_file):
                self.db.delete(old_file)
                self.db.flush()
        return link

    cls.__init__ = repaired_init
    cls.register_file = repaired_register_file
    cls.movie_for_candidate = repaired_movie_for_candidate
    cls.ensure_movie_link = repaired_ensure_movie_link
    cls.file_for_candidate = repaired_file_for_candidate
    cls.ensure_file_link = repaired_ensure_file_link
    cls._reelindex_identity_repair = True
