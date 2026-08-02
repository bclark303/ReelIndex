from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.models import MediaFile, Movie, ScanRun, Source
from app.services.scanner import scan_manager
from app.services.scan_events import scan_event_store


class MaintenanceBlocked(RuntimeError):
    """Raised when destructive maintenance is unsafe to run."""


def _clear_directory(directory: Path) -> tuple[int, int]:
    """Remove generated files below *directory* and recreate it.

    Returns the number of files and bytes removed. Failures are allowed to
    propagate so the UI never claims that a partial reset completed.
    """
    directory.mkdir(parents=True, exist_ok=True)
    files = 0
    total_bytes = 0
    for child in list(directory.iterdir()):
        if child.is_dir():
            for nested in child.rglob("*"):
                if nested.is_file():
                    files += 1
                    try:
                        total_bytes += nested.stat().st_size
                    except OSError:
                        pass
            shutil.rmtree(child)
            continue
        files += 1
        try:
            total_bytes += child.stat().st_size
        except OSError:
            pass
        child.unlink()
    directory.mkdir(parents=True, exist_ok=True)
    return files, total_bytes


def _vacuum_sqlite() -> None:
    if not settings.db_url.startswith("sqlite"):
        return
    # VACUUM must run outside a transaction. It is best-effort: the reset is
    # still valid if another short-lived reader prevents immediate compaction.
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.exec_driver_sql("VACUUM")
    except Exception:
        pass


def reset_application_data(*, include_sources: bool) -> dict[str, Any]:
    active = scan_manager.active_runs()
    if active:
        raise MaintenanceBlocked("Cancel all running scans before clearing application data")

    with SessionLocal() as db:
        removed = {
            "sources": db.scalar(select(func.count(Source.id))) or 0,
            "movies": db.scalar(select(func.count(Movie.id))) or 0,
            "media_files": db.scalar(select(func.count(MediaFile.id))) or 0,
            "scan_runs": db.scalar(select(func.count(ScanRun.id))) or 0,
        }

        # Explicit ordering keeps this safe even if a non-SQLite database is
        # used without ON DELETE CASCADE enabled.
        db.execute(delete(MediaFile))
        db.execute(delete(Movie))
        db.execute(delete(ScanRun))
        if include_sources:
            db.execute(delete(Source))
        db.commit()

    poster_files, poster_bytes = _clear_directory(settings.data_dir / "posters")
    event_files, event_bytes = scan_event_store.clear_all(settings.data_dir / "scan-events")
    _vacuum_sqlite()

    if not include_sources:
        removed["sources"] = 0
    removed["poster_files"] = poster_files
    removed["poster_bytes"] = poster_bytes
    removed["scan_event_files"] = event_files
    removed["scan_event_bytes"] = event_bytes

    return {
        "status": "ok",
        "mode": "factory_reset" if include_sources else "inventory_cache",
        "removed": removed,
        "message": (
            "ReelIndex was reset to first-run state"
            if include_sources
            else "Cached inventory, scan history, and posters were cleared"
        ),
    }
