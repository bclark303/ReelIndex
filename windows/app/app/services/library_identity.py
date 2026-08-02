from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import MediaFile, MediaFileSource, Movie, MovieSource, Source


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_title(value: str | None) -> str:
    """Return a stable title token suitable for cross-source comparisons."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def normalize_path(value: str | Path | None) -> str:
    """Normalize Windows, Unix, UNC, and mapped paths into one comparison form."""
    text = str(value or "").strip().replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    while "/./" in text:
        text = text.replace("/./", "/")
    return text.rstrip("/").casefold()


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _external_identity_keys(metadata: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    imdb = metadata.get("imdb_id") or metadata.get("imdb")
    if imdb:
        match = re.search(r"tt\d+", str(imdb), re.IGNORECASE)
        if match:
            keys.add(f"imdb:{match.group(0).lower()}")
    tmdb = metadata.get("tmdb_id") or metadata.get("tmdb")
    if tmdb is not None and str(tmdb).strip().isdigit():
        media_type = str(metadata.get("tmdb_media_type") or metadata.get("media_type") or "movie").casefold()
        keys.add(f"tmdb:{media_type}:{int(str(tmdb).strip())}")

    raw_guids = metadata.get("guids") or metadata.get("provider_ids") or []
    if isinstance(raw_guids, dict):
        raw_guids = [f"{key}:{value}" for key, value in raw_guids.items()]
    if not isinstance(raw_guids, list):
        raw_guids = [raw_guids]
    for raw in raw_guids:
        value = str(raw or "")
        imdb_match = re.search(r"tt\d+", value, re.IGNORECASE)
        if imdb_match:
            keys.add(f"imdb:{imdb_match.group(0).lower()}")
        tmdb_match = re.search(r"tmdb(?:movie)?[:/]+(\d+)", value, re.IGNORECASE)
        if tmdb_match:
            keys.add(f"tmdb:movie:{int(tmdb_match.group(1))}")
    return keys


def movie_identity_keys(title: str | None, year: int | None, runtime_seconds: float | None, metadata: dict[str, Any]) -> set[str]:
    keys = _external_identity_keys(metadata)
    normalized = normalize_title(title)
    if normalized and year:
        keys.add(f"title-year:{normalized}:{int(year)}")
    elif normalized and runtime_seconds:
        # A coarse runtime bucket is a fallback only when a source omits year.
        runtime_bucket = int(round(float(runtime_seconds) / 120.0))
        keys.add(f"title-runtime:{normalized}:{runtime_bucket}")
    return keys


def _file_values(candidate_or_file: Any) -> tuple[list[str], str, int | None, float | None]:
    paths: list[str] = []
    local_path = getattr(candidate_or_file, "local_path", None)
    if local_path:
        paths.append(str(local_path))
    path = getattr(candidate_or_file, "path", None)
    if path:
        paths.append(str(path))
    for link in getattr(candidate_or_file, "source_links", []) or []:
        if getattr(link, "path", None):
            paths.append(str(link.path))
    filename = str(getattr(candidate_or_file, "filename", "") or "")
    size = getattr(candidate_or_file, "size_bytes", None)
    modified = getattr(candidate_or_file, "modified_ts", None)
    return paths, filename, int(size) if size is not None else None, float(modified) if modified is not None else None


def file_identity_keys(candidate_or_file: Any) -> set[str]:
    paths, filename, size, _modified = _file_values(candidate_or_file)
    keys = {f"path:{normalized}" for value in paths if (normalized := normalize_path(value))}
    normalized_name = Path(filename.replace("\\", "/")).name.casefold()
    if normalized_name and size and size > 0:
        keys.add(f"name-size:{normalized_name}:{size}")
    return keys


def candidate_fingerprint(candidate: Any) -> str:
    """Fingerprint content independently of the adapter's external IDs."""
    paths, filename, size, modified = _file_values(candidate)
    preferred_path = normalize_path(getattr(candidate, "local_path", None) or (paths[0] if paths else ""))
    payload = json.dumps(
        {
            "path": preferred_path,
            "filename": Path(filename.replace("\\", "/")).name.casefold(),
            "size": size,
            "modified": modified,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


class LibraryIdentityIndex:
    """Resolve adapter records to canonical Movie and MediaFile rows."""

    def __init__(self, db: Session):
        self.db = db
        self.source_movies: dict[tuple[str, str], MovieSource] = {}
        self.source_files: dict[tuple[str, str], MediaFileSource] = {}
        self.movie_keys: dict[str, Movie | None] = {}
        self.file_keys: dict[str, MediaFile | None] = {}
        self._load()

    @staticmethod
    def _put_unique(mapping: dict[str, Any | None], key: str, value: Any) -> None:
        current = mapping.get(key)
        if key not in mapping:
            mapping[key] = value
        elif current is not None and getattr(current, "id", None) != getattr(value, "id", None):
            mapping[key] = None

    def _register_movie_keys(self, movie: Movie) -> None:
        metadata = _json_object(movie.metadata_json)
        for key in movie_identity_keys(movie.title, movie.year, movie.runtime_seconds, metadata):
            self._put_unique(self.movie_keys, key, movie)
        for media_file in movie.files:
            for key in file_identity_keys(media_file):
                self._put_unique(self.file_keys, key, media_file)

    def _load(self) -> None:
        movies = self.db.scalars(
            select(Movie).options(
                selectinload(Movie.source_links),
                selectinload(Movie.files).selectinload(MediaFile.source_links),
            )
        ).all()
        for movie in movies:
            for link in movie.source_links:
                self.source_movies[(link.source_id, link.source_movie_id)] = link
            for media_file in movie.files:
                for link in media_file.source_links:
                    self.source_files[(link.source_id, link.source_file_id)] = link
            self._register_movie_keys(movie)

    def register_movie(self, movie: Movie) -> None:
        self._register_movie_keys(movie)

    def register_file(self, media_file: MediaFile) -> None:
        for key in file_identity_keys(media_file):
            self._put_unique(self.file_keys, key, media_file)

    def movie_for_candidate(self, source_id: str, candidate: Any) -> tuple[Movie | None, MovieSource | None]:
        source_link = self.source_movies.get((source_id, str(candidate.source_movie_id)))
        if source_link:
            return source_link.movie, source_link

        metadata = dict(getattr(candidate, "metadata", {}) or {})
        keys = movie_identity_keys(
            getattr(candidate, "title", None),
            getattr(candidate, "year", None),
            getattr(candidate, "runtime_seconds", None),
            metadata,
        )
        # Provider IDs are strongest, followed by a physical-file match and then
        # normalized title/year or title/runtime.
        ordered = sorted(keys, key=lambda key: (0 if key.startswith(("imdb:", "tmdb:")) else 2, key))
        for key in ordered:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None
        for file_candidate in getattr(candidate, "files", []) or []:
            for key in file_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None:
                    return media_file.movie, None
        for key in ordered:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None
        return None, None

    def ensure_movie_link(self, movie: Movie, source_id: str, source_movie_id: str) -> MovieSource:
        key = (source_id, str(source_movie_id))
        link = self.source_movies.get(key)
        if link:
            link.active = True
            link.last_seen_at = utcnow()
            return link
        link = MovieSource(
            source_id=source_id,
            movie_id=movie.id,
            source_movie_id=str(source_movie_id),
            active=True,
            last_seen_at=utcnow(),
        )
        self.db.add(link)
        self.db.flush()
        self.source_movies[key] = link
        return link

    def file_for_candidate(self, source_id: str, movie: Movie, candidate: Any) -> tuple[MediaFile | None, MediaFileSource | None]:
        source_link = self.source_files.get((source_id, str(candidate.source_file_id)))
        if source_link:
            return source_link.media_file, source_link
        for key in file_identity_keys(candidate):
            media_file = self.file_keys.get(key)
            if media_file is not None and media_file.movie_id == movie.id:
                return media_file, None
        return None, None

    def ensure_file_link(self, media_file: MediaFile, source_id: str, source_file_id: str, path: str) -> MediaFileSource:
        key = (source_id, str(source_file_id))
        link = self.source_files.get(key)
        if link:
            link.media_file_id = media_file.id
            link.path = str(path)
            link.active = True
            link.last_seen_at = utcnow()
            return link
        link = MediaFileSource(
            source_id=source_id,
            media_file_id=media_file.id,
            source_file_id=str(source_file_id),
            path=str(path),
            active=True,
            last_seen_at=utcnow(),
        )
        self.db.add(link)
        self.db.flush()
        self.source_files[key] = link
        return link

    def deactivate_unseen(
        self,
        source_id: str,
        seen_movie_link_ids: set[str],
        seen_file_link_ids: set[str],
    ) -> None:
        movie_links = self.db.scalars(select(MovieSource).where(MovieSource.source_id == source_id)).all()
        file_links = self.db.scalars(select(MediaFileSource).where(MediaFileSource.source_id == source_id)).all()
        movie_ids = {link.movie_id for link in movie_links}
        file_ids = {link.media_file_id for link in file_links}
        for link in movie_links:
            link.active = link.id in seen_movie_link_ids
        for link in file_links:
            link.active = link.id in seen_file_link_ids
        self.db.flush()
        for movie_id in movie_ids:
            movie = self.db.get(Movie, movie_id)
            if movie:
                movie.active = bool(
                    self.db.scalar(
                        select(func.count(MovieSource.id)).where(
                            MovieSource.movie_id == movie_id,
                            MovieSource.active.is_(True),
                        )
                    )
                )
        for file_id in file_ids:
            media_file = self.db.get(MediaFile, file_id)
            if media_file:
                media_file.active = bool(
                    self.db.scalar(
                        select(func.count(MediaFileSource.id)).where(
                            MediaFileSource.media_file_id == file_id,
                            MediaFileSource.active.is_(True),
                        )
                    )
                )


def _source_ids(movie: Movie) -> set[str]:
    return {link.source_id for link in movie.source_links}


def _merge_metadata(canonical: Movie, duplicate: Movie) -> None:
    left = _json_object(canonical.metadata_json)
    right = _json_object(duplicate.metadata_json)
    merged = dict(right)
    merged.update(left)
    if right.get("poster_locked") and not left.get("poster_locked"):
        for key in (
            "poster_locked",
            "poster_source",
            "poster_match",
            "poster_selected_title",
            "poster_upload_name",
            "tmdb_id",
            "imdb_id",
            "tmdb_media_type",
        ):
            if key in right:
                merged[key] = right[key]
        if duplicate.poster_path:
            canonical.poster_path = duplicate.poster_path
    canonical.metadata_json = json.dumps(merged, default=str)
    canonical.year = canonical.year or duplicate.year
    canonical.runtime_seconds = canonical.runtime_seconds or duplicate.runtime_seconds
    canonical.overview = canonical.overview or duplicate.overview
    canonical.poster_path = canonical.poster_path or duplicate.poster_path
    canonical.active = canonical.active or duplicate.active


def _copy_technical(target: MediaFile, source: MediaFile) -> None:
    for field in (
        "container",
        "duration_seconds",
        "video_codec",
        "width",
        "height",
        "resolution_label",
        "video_bitrate",
        "audio_codec",
        "audio_channels",
        "audio_languages",
        "probe_json",
        "probe_error",
        "fingerprint",
        "edition",
        "size_bytes",
        "modified_ts",
    ):
        if getattr(target, field) in (None, "", "{}") and getattr(source, field) not in (None, "", "{}"):
            setattr(target, field, getattr(source, field))
    target.active = target.active or source.active


def merge_movies(db: Session, canonical: Movie, duplicate: Movie) -> Movie:
    if canonical.id == duplicate.id:
        return canonical
    if _source_ids(canonical) & _source_ids(duplicate):
        return canonical

    _merge_metadata(canonical, duplicate)
    canonical_files: dict[str, MediaFile] = {}
    for media_file in canonical.files:
        for key in file_identity_keys(media_file):
            canonical_files.setdefault(key, media_file)

    for link in list(duplicate.source_links):
        link.movie = canonical
    for media_file in list(duplicate.files):
        target = next((canonical_files.get(key) for key in file_identity_keys(media_file) if canonical_files.get(key)), None)
        if target:
            _copy_technical(target, media_file)
            for link in list(media_file.source_links):
                link.media_file = target
            db.delete(media_file)
        else:
            media_file.movie = canonical
            for key in file_identity_keys(media_file):
                canonical_files.setdefault(key, media_file)
    db.delete(duplicate)
    db.flush()
    return canonical


def backfill_source_links(db: Session) -> None:
    movies = db.scalars(
        select(Movie).options(
            selectinload(Movie.source_links),
            selectinload(Movie.files).selectinload(MediaFile.source_links),
        )
    ).all()
    for movie in movies:
        if not any(link.source_id == movie.source_id and link.source_movie_id == movie.source_movie_id for link in movie.source_links):
            db.add(
                MovieSource(
                    source_id=movie.source_id,
                    movie_id=movie.id,
                    source_movie_id=movie.source_movie_id,
                    active=movie.active,
                    last_seen_at=movie.updated_at or movie.created_at,
                )
            )
        for media_file in movie.files:
            if not any(
                link.source_id == movie.source_id and link.source_file_id == media_file.source_file_id
                for link in media_file.source_links
            ):
                db.add(
                    MediaFileSource(
                        source_id=movie.source_id,
                        media_file_id=media_file.id,
                        source_file_id=media_file.source_file_id,
                        path=media_file.path,
                        active=media_file.active,
                        last_seen_at=media_file.updated_at or media_file.created_at,
                    )
                )
    db.flush()


def consolidate_existing_duplicates(db: Session) -> int:
    """Merge cross-source duplicates using strong IDs/files, then title and year."""
    movies = db.scalars(
        select(Movie)
        .options(
            selectinload(Movie.source_links),
            selectinload(Movie.files).selectinload(MediaFile.source_links),
        )
        .order_by(Movie.created_at, Movie.id)
    ).all()
    merged_count = 0

    # Strong provider/file identities.
    identity_owner: dict[str, Movie] = {}
    for movie in list(movies):
        if movie not in db:
            continue
        metadata = _json_object(movie.metadata_json)
        keys = {key for key in movie_identity_keys(movie.title, movie.year, movie.runtime_seconds, metadata) if key.startswith(("imdb:", "tmdb:"))}
        for media_file in movie.files:
            keys.update(file_identity_keys(media_file))
        owners = [identity_owner[key] for key in keys if key in identity_owner and identity_owner[key] in db]
        canonical = owners[0] if owners else movie
        if canonical.id != movie.id and not (_source_ids(canonical) & _source_ids(movie)):
            canonical = merge_movies(db, canonical, movie)
            merged_count += 1
        for key in keys:
            identity_owner[key] = canonical

    db.flush()
    movies = db.scalars(
        select(Movie)
        .options(
            selectinload(Movie.source_links),
            selectinload(Movie.files).selectinload(MediaFile.source_links),
        )
        .order_by(Movie.created_at, Movie.id)
    ).all()
    title_groups: dict[str, list[Movie]] = defaultdict(list)
    for movie in movies:
        if movie.year and (normalized := normalize_title(movie.title)):
            title_groups[f"{normalized}:{movie.year}"].append(movie)
    for group in title_groups.values():
        if len(group) < 2:
            continue
        all_sources = [source_id for movie in group for source_id in _source_ids(movie)]
        if len(all_sources) != len(set(all_sources)):
            continue
        canonical = group[0]
        for duplicate in group[1:]:
            canonical = merge_movies(db, canonical, duplicate)
            merged_count += 1
    db.flush()
    return merged_count


def upgrade_library_identity(db: Session) -> int:
    backfill_source_links(db)
    merged = consolidate_existing_duplicates(db)
    db.commit()
    return merged


def detach_source(db: Session, source: Source) -> None:
    """Delete a source without deleting canonical movies owned by another source."""
    source_id = source.id
    owner_movies = db.scalars(
        select(Movie)
        .options(selectinload(Movie.source_links), selectinload(Movie.files).selectinload(MediaFile.source_links))
        .where(Movie.source_id == source_id)
    ).all()
    for movie in owner_movies:
        replacement = next((link for link in movie.source_links if link.source_id != source_id), None)
        if replacement:
            movie.source_id = replacement.source_id
            legacy_id = replacement.source_movie_id
            conflict = db.scalar(
                select(Movie.id).where(
                    Movie.source_id == replacement.source_id,
                    Movie.source_movie_id == legacy_id,
                    Movie.id != movie.id,
                )
            )
            movie.source_movie_id = legacy_id if not conflict else f"{legacy_id}#{movie.id[:8]}"
        else:
            db.delete(movie)

    file_links = db.scalars(
        select(MediaFileSource)
        .options(selectinload(MediaFileSource.media_file).selectinload(MediaFile.source_links))
        .where(MediaFileSource.source_id == source_id)
    ).all()
    for link in file_links:
        media_file = link.media_file
        if media_file and not any(other.source_id != source_id for other in media_file.source_links):
            db.delete(media_file)
    db.delete(source)
    db.commit()
