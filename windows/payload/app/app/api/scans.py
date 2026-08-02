from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import ScanRun, Source
from app.schemas.api import ScanRunOut
from app.services.scanner import scan_manager

router = APIRouter(prefix="/scans", tags=["scans"])


def _out(run: ScanRun, source_name: str | None = None) -> ScanRunOut:
    return ScanRunOut(
        id=run.id,
        source_id=run.source_id,
        source_name=source_name,
        status=run.status,
        discovered_count=run.discovered_count,
        analyzed_count=run.analyzed_count,
        cached_count=run.cached_count,
        error_count=run.error_count,
        current_item=run.current_item,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.post("/{source_id}", response_model=ScanRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_scan(source_id: str, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        run_id = scan_manager.start(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = db.get(ScanRun, run_id)
    return _out(run, source.name)


@router.post("/{run_id}/cancel", response_model=ScanRunOut, status_code=status.HTTP_202_ACCEPTED)
def cancel_scan(run_id: str, db: Session = Depends(get_db)):
    run = db.get(ScanRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Scan not found")
    if not scan_manager.cancel(run_id):
        raise HTTPException(status_code=409, detail="Scan is no longer running")
    db.refresh(run)
    source = db.get(Source, run.source_id)
    return _out(run, source.name if source else None)


@router.get("", response_model=list[ScanRunOut])
def list_scans(limit: int = 30, db: Session = Depends(get_db)):
    runs = db.scalars(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(min(max(limit, 1), 100))).all()
    source_names = {source.id: source.name for source in db.scalars(select(Source)).all()}
    return [_out(run, source_names.get(run.source_id)) for run in runs]


@router.get("/{run_id}", response_model=ScanRunOut)
def get_scan(run_id: str, db: Session = Depends(get_db)):
    run = db.get(ScanRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Scan not found")
    source = db.get(Source, run.source_id)
    return _out(run, source.name if source else None)
