from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import reveal_config, sanitize_config
from app.models import MediaFile, Movie, ScanRun, Source
from app.schemas.api import DiagnosticsOut
from app.services.deep_queue import deep_queue_store
from app.services.maintenance import MaintenanceBlocked, reset_application_data
from app.services.mediainfo import mediainfo_version
from app.services.probe import ffprobe_version
from app.services.runtime_settings import runtime_settings

router = APIRouter(tags=["system"])


class MaintenanceConfirmation(BaseModel):
    confirmation: str


class LoggingSettingsUpdate(BaseModel):
    verbose_scan_logging: bool


def _maintenance_reset(*, confirmation: str, expected: str, include_sources: bool):
    if confirmation.strip() != expected:
        raise HTTPException(status_code=422, detail=f'Type "{expected}" to confirm')
    try:
        return reset_application_data(include_sources=include_sources)
    except MaintenanceBlocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "version": "1.3.6"}


@router.get("/posters/{movie_id}")
def poster(movie_id: str, db: Session = Depends(get_db)):
    movie = db.get(Movie, movie_id)
    if not movie or not movie.poster_path:
        raise HTTPException(status_code=404, detail="Poster not found")
    path = Path(movie.poster_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Poster cache file missing")
    header = path.read_bytes()[:12]
    media_type = "image/png" if header.startswith(b"\x89PNG") else "image/webp" if header.startswith(b"RIFF") and b"WEBP" in header else "image/jpeg"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


def _diagnostics(db: Session) -> dict:
    sources = db.scalars(select(Source).order_by(Source.created_at)).all()
    scans = db.scalars(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(20)).all()
    disk = shutil.disk_usage(settings.data_dir)
    return {
        "app": {"name": settings.app_name, "version": "1.3.6", "demo_mode": settings.demo_mode, "data_dir": str(settings.data_dir)},
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "mediainfo": mediainfo_version(),
            "ffprobe": ffprobe_version(),
            "cpu_count": os.cpu_count(),
            "discovery_workers": settings.discovery_workers,
            "probe_workers": settings.probe_workers,
            "deep_standard_timeout": settings.deep_probe_standard_seconds,
            "deep_retry_timeout": settings.deep_probe_retry_seconds,
            "data_disk_total": disk.total,
            "data_disk_free": disk.free,
        },
        "database": {
            "movies": db.scalar(select(func.count(Movie.id))) or 0,
            "active_movies": db.scalar(select(func.count(Movie.id)).where(Movie.active.is_(True))) or 0,
            "media_files": db.scalar(select(func.count(MediaFile.id))) or 0,
            "scan_runs": db.scalar(select(func.count(ScanRun.id))) or 0,
        },
        "sources": [
            {
                "id": source.id,
                "name": source.name,
                "type": source.type,
                "location": source.url_or_path,
                "library_id": source.library_id,
                "schedule_enabled": source.schedule_enabled,
                "schedule_minutes": source.schedule_minutes,
                "config": sanitize_config(reveal_config(json.loads(source.config_json or "{}"))),
            }
            for source in sources
        ],
        "recent_scans": [
            {
                "id": run.id,
                "source_id": run.source_id,
                "status": run.status,
                "discovered": run.discovered_count,
                "analyzed": run.analyzed_count,
                "cached": run.cached_count,
                "errors": run.error_count,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error_message": run.error_message,
                **deep_queue_store.info(run.id),
            }
            for run in scans
        ],
    }


@router.get("/diagnostics", response_model=DiagnosticsOut)
def diagnostics(db: Session = Depends(get_db)):
    payload = _diagnostics(db)
    payload["logging"] = runtime_settings.get_all()
    return payload


@router.get("/settings/logging")
def get_logging_settings():
    return runtime_settings.get_all()


@router.put("/settings/logging")
def update_logging_settings(payload: LoggingSettingsUpdate):
    return runtime_settings.update(verbose_scan_logging=payload.verbose_scan_logging)


@router.get("/diagnostics/export")
def export_diagnostics(db: Session = Depends(get_db)):
    payload = _diagnostics(db)
    payload["logging"] = runtime_settings.get_all()
    return JSONResponse(payload, headers={"Content-Disposition": "attachment; filename=reelindex-diagnostics.json"})


@router.post("/maintenance/clear-inventory")
def clear_inventory_cache(payload: MaintenanceConfirmation):
    """Remove generated inventory while retaining configured source connections."""
    return _maintenance_reset(
        confirmation=payload.confirmation,
        expected="CLEAR CACHE",
        include_sources=False,
    )


@router.post("/maintenance/factory-reset")
def factory_reset(payload: MaintenanceConfirmation):
    """Remove all database records, credentials, scan history, and poster cache."""
    return _maintenance_reset(
        confirmation=payload.confirmation,
        expected="RESET REELINDEX",
        include_sources=True,
    )
