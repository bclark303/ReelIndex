from __future__ import annotations

import json
import os
import platform
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import reveal_config, sanitize_config
from app.models import MediaFile, Movie, ScanRun, Source
from app.schemas.api import DiagnosticsOut
from app.services.probe import ffprobe_version

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "version": "1.1.3"}


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
        "app": {"name": settings.app_name, "version": "1.1.3", "demo_mode": settings.demo_mode, "data_dir": str(settings.data_dir)},
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "ffprobe": ffprobe_version(),
            "cpu_count": os.cpu_count(),
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
            }
            for run in scans
        ],
    }


@router.get("/diagnostics", response_model=DiagnosticsOut)
def diagnostics(db: Session = Depends(get_db)):
    return _diagnostics(db)


@router.get("/diagnostics/export")
def export_diagnostics(db: Session = Depends(get_db)):
    return JSONResponse(_diagnostics(db), headers={"Content-Disposition": "attachment; filename=reelindex-diagnostics.json"})
