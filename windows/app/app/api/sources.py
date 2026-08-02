from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import protect_config, reveal_config, sanitize_config
from app.models import Movie, ScanRun, Source
from app.schemas.api import ConnectionResult, ConnectionTest, SourceCreate, SourceOut, SourceUpdate
from app.services.scheduler import scan_scheduler
from app.sources.factory import create_adapter

router = APIRouter(prefix="/sources", tags=["sources"])


def _source_out(db: Session, source: Source) -> SourceOut:
    movie_count = db.scalar(select(func.count(Movie.id)).where(Movie.source_id == source.id, Movie.active.is_(True))) or 0
    last_scan = db.scalar(select(ScanRun).where(ScanRun.source_id == source.id).order_by(ScanRun.started_at.desc()).limit(1))
    return SourceOut(
        id=source.id,
        name=source.name,
        type=source.type,
        url_or_path=source.url_or_path,
        library_id=source.library_id,
        config=sanitize_config(reveal_config(json.loads(source.config_json or "{}"))),
        schedule_enabled=source.schedule_enabled,
        schedule_minutes=source.schedule_minutes,
        enabled=source.enabled,
        created_at=source.created_at,
        updated_at=source.updated_at,
        movie_count=movie_count,
        last_scan_status=last_scan.status if last_scan else None,
        last_scan_at=last_scan.started_at if last_scan else None,
    )


@router.get("", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    sources = db.scalars(select(Source).order_by(Source.created_at)).all()
    return [_source_out(db, source) for source in sources]


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    source = Source(
        name=payload.name,
        type=payload.type,
        url_or_path=payload.url_or_path,
        library_id=payload.library_id,
        config_json=json.dumps(protect_config(payload.config)),
        schedule_enabled=payload.schedule_enabled,
        schedule_minutes=payload.schedule_minutes,
        enabled=payload.enabled,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    scan_scheduler.sync()
    return _source_out(db, source)


@router.put("/{source_id}", response_model=SourceOut)
def update_source(source_id: str, payload: SourceUpdate, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    updates = payload.model_dump(exclude_unset=True)
    if "config" in updates:
        current = reveal_config(json.loads(source.config_json or "{}"))
        incoming = updates.pop("config") or {}
        for key, value in incoming.items():
            if value == "••••••••":
                continue
            current[key] = value
        source.config_json = json.dumps(protect_config(current))
    for key, value in updates.items():
        setattr(source, key, value)
    db.commit()
    db.refresh(source)
    scan_scheduler.sync()
    return _source_out(db, source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: str, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete(source)
    db.commit()
    scan_scheduler.sync()


@router.post("/test", response_model=ConnectionResult)
def test_connection(payload: ConnectionTest):
    try:
        adapter = create_adapter(payload.type, payload.url_or_path, payload.library_id, payload.config)
        result = adapter.test_connection()
        return ConnectionResult(ok=result.ok, message=result.message, libraries=result.libraries, details=result.details)
    except Exception as exc:
        return ConnectionResult(ok=False, message=str(exc))
