from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import MediaFile, Movie
from app.services.scanner import scan_manager


class InventoryRecordNotFound(LookupError):
    """Raised when an inventory movie record no longer exists."""


class InventoryRecordBlocked(RuntimeError):
    """Raised when deleting an inventory record would race an active scan."""


def _managed_poster_paths(movie: Movie) -> list[Path]:
    """Return only poster files managed inside ReelIndex application data.

    A movie's ``poster_path`` can originate from a sidecar or another read-only
    media location. Record deletion must never remove those external files.
    """
    poster_root = (settings.data_dir / "posters").resolve(strict=False)
    candidates = {settings.data_dir / "posters" / "library" / f"{movie.id}.jpg"}
    if movie.poster_path:
        candidates.add(Path(movie.poster_path))

    managed: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(poster_root)
        except (OSError, ValueError):
            continue
        managed.append(resolved)
    return managed


def delete_movie_inventory_record(db: Session, movie_id: str) -> dict[str, Any]:
    """Delete one canonical movie and its generated inventory relationships.

    The operation removes only ReelIndex database/cache state. Source
    definitions, media files, sidecars, and media-server libraries are never
    mutated. A later scan can therefore rediscover every underlying item using
    the current identity rules.
    """
    movie = db.scalar(
        select(Movie)
        .options(
            selectinload(Movie.source_links),
            selectinload(Movie.files).selectinload(MediaFile.source_links),
        )
        .where(Movie.id == movie_id)
    )
    if movie is None or not movie.active:
        raise InventoryRecordNotFound("Movie not found")

    if scan_manager.active_runs():
        raise InventoryRecordBlocked(
            "Wait for all running scans to finish or cancel them before deleting an inventory record"
        )

    source_ids = {movie.source_id}
    source_ids.update(link.source_id for link in movie.source_links)
    for media_file in movie.files:
        source_ids.update(link.source_id for link in media_file.source_links)

    poster_paths = _managed_poster_paths(movie)
    result = {
        "status": "ok",
        "movie_id": movie.id,
        "title": movie.title,
        "files_removed": len(movie.files),
        "source_ids": sorted(source_id for source_id in source_ids if source_id),
        "message": "Inventory record deleted; run the associated source scans to rediscover it",
    }

    db.delete(movie)
    db.commit()

    for path in poster_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # The database deletion is authoritative. A locked cache file can
            # be removed later by normal cache maintenance.
            pass

    return result
