from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import MediaFile, Movie, MovieSource, Source
from app.schemas.api import (
    PaginatedProbeFailures,
    ProbeFailureItem,
    ProbeFailureSummary,
    ProbeRetryRequest,
    ProbeRetryResponse,
)
from app.services.probe import ProbeCancelled, probe_media
from app.services.probe_failures import decode_probe_json, diagnose_probe_failure, marker_from_probe
from app.services.scanner import ScanManager, scan_manager

router = APIRouter(tags=["probe failures"])


def _failure_item(file: MediaFile, movie: Movie, source: Source) -> ProbeFailureItem:
    probe = decode_probe_json(file.probe_json)
    marker = marker_from_probe(probe)
    error = file.probe_error or str(marker.get("warning") or "Unknown analyzer error")
    diagnosis = diagnose_probe_failure(error, probe, file.path)
    return ProbeFailureItem(
        file_id=file.id,
        movie_id=movie.id,
        movie_title=movie.title,
        movie_year=movie.year,
        source_id=source.id,
        source_name=source.name,
        filename=file.filename,
        path=file.path,
        size_bytes=file.size_bytes,
        container=file.container or Path(file.filename).suffix.lower().lstrip(".") or None,
        error=error,
        category=diagnosis.category,
        diagnosis_title=diagnosis.title,
        diagnosis_summary=diagnosis.summary,
        severity=diagnosis.severity,
        retryable=diagnosis.retryable,
        recommended_action=diagnosis.recommended_action,
        suggestions=list(diagnosis.suggestions),
        analysis_source=marker.get("source"),
        analysis_profile=marker.get("profile"),
        analysis_status=marker.get("status"),
        attempt_count=int(marker.get("attempt_count") or 0),
        deep_attempt_count=int(marker.get("deep_attempt_count") or 0),
        attempted_at=marker.get("attempted_at"),
        updated_at=file.updated_at,
    )


def _all_failure_rows(db: Session, source_id: str | None = None):
    conditions = [MediaFile.active.is_(True), Movie.active.is_(True), MediaFile.probe_error.is_not(None)]
    if source_id:
        conditions.append(
            select(MovieSource.id)
            .where(
                MovieSource.movie_id == Movie.id,
                MovieSource.source_id == source_id,
                MovieSource.active.is_(True),
            )
            .exists()
        )
    return db.execute(
        select(MediaFile, Movie, Source)
        .join(Movie, MediaFile.movie_id == Movie.id)
        .join(Source, Movie.source_id == Source.id)
        .where(and_(*conditions))
    ).all()


@router.get("/probe-failures", response_model=PaginatedProbeFailures)
def list_probe_failures(
    search: str | None = None,
    source_id: str | None = None,
    category: str | None = None,
    container: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = _all_failure_rows(db, source_id)
    items = [_failure_item(file, movie, source) for file, movie, source in rows]
    if search:
        needle = search.strip().lower()
        items = [
            item for item in items
            if needle in item.movie_title.lower()
            or needle in item.filename.lower()
            or needle in item.path.lower()
            or needle in item.error.lower()
        ]
    if category:
        items = [item for item in items if item.category == category]
    if container:
        items = [item for item in items if (item.container or "").lower() == container.lower()]

    items.sort(key=lambda item: (item.severity != "error", item.category, item.movie_title.lower(), item.filename.lower()))
    total = len(items)
    summary = ProbeFailureSummary(
        total=total,
        by_category=dict(Counter(item.category for item in items)),
        by_container=dict(Counter((item.container or "unknown").lower() for item in items)),
        by_source=dict(Counter(item.source_name for item in items)),
    )
    start = (page - 1) * page_size
    return PaginatedProbeFailures(
        items=items[start:start + page_size],
        total=total,
        page=page,
        page_size=page_size,
        summary=summary,
    )


def _retry_parameters(path: Path, strategy: str) -> dict:
    suffix = path.suffix.lower()
    is_matroska = suffix in {".mkv", ".webm"}
    native_container = suffix in {
        ".mp4", ".m4v", ".mov", ".avi", ".wmv", ".asf",
        ".ts", ".m2ts", ".mts", ".mpg", ".mpeg",
    }
    if strategy == "ffprobe":
        return {
            "profile": "extended",
            "stage_matroska": False,
            "native_container": False,
            "timeout_override": settings.deep_probe_retry_seconds,
        }
    if strategy == "extended":
        return {
            "profile": "extended",
            "stage_matroska": is_matroska,
            "stage_bytes": settings.deep_probe_retry_stage_bytes,
            "native_container": native_container,
            "timeout_override": settings.deep_probe_retry_seconds,
        }
    return {
        "profile": "standard",
        "stage_matroska": is_matroska,
        "stage_bytes": settings.deep_probe_stage_bytes,
        "native_container": native_container,
        "timeout_override": settings.deep_probe_standard_seconds,
    }


def _record_retry_failure(file: MediaFile, error: str, strategy: str) -> None:
    probe = decode_probe_json(file.probe_json)
    marker = marker_from_probe(probe)
    history = probe.get("failure_history")
    if not isinstance(history, list):
        history = []
    history.append({
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy,
        "error": error,
        "status": "deferred" if "timed out" in error.lower() else "failed",
    })
    marker.update({
        "status": "deferred" if "timed out" in error.lower() else "failed",
        "warning": error,
        "profile": "extended" if strategy in {"extended", "ffprobe"} else "standard",
        "attempt_count": int(marker.get("attempt_count") or 0) + 1,
        "deep_attempt_count": int(marker.get("deep_attempt_count") or 0) + 1,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "retry_strategy": strategy,
    })
    probe["_reelindex"] = marker
    probe["failure_history"] = history[-12:]
    file.probe_json = json.dumps(probe, default=str)
    file.probe_error = error


@router.post("/media-files/{file_id}/probe/retry", response_model=ProbeRetryResponse)
def retry_probe(
    file_id: str,
    payload: ProbeRetryRequest,
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(MediaFile, Movie, Source)
        .join(Movie, MediaFile.movie_id == Movie.id)
        .join(Source, Movie.source_id == Source.id)
        .where(MediaFile.id == file_id, MediaFile.active.is_(True), Movie.active.is_(True))
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Media file not found")
    file, movie, source = row
    if scan_manager.active_run(source.id):
        raise HTTPException(status_code=409, detail="Wait for the active source scan to finish before retrying one file")

    path = Path(file.path)
    try:
        path.stat()
    except PermissionError:
        error = "Access is denied while reading the media file"
        _record_retry_failure(file, error, payload.strategy)
        db.commit()
        return ProbeRetryResponse(
            ok=False, file_id=file.id, strategy=payload.strategy,
            message="ReelIndex does not have read permission", resolved=False, error=error,
        )
    except FileNotFoundError:
        error = "File path does not exist or is not accessible to ReelIndex"
        _record_retry_failure(file, error, payload.strategy)
        db.commit()
        return ProbeRetryResponse(
            ok=False, file_id=file.id, strategy=payload.strategy,
            message="The file path is unavailable", resolved=False, error=error,
        )
    except OSError:
        # Let the bounded analyzer produce the more specific network/storage error.
        pass

    try:
        technical, error = probe_media(
            path,
            source_size_bytes=file.size_bytes,
            **_retry_parameters(path, payload.strategy),
        )
    except ProbeCancelled:
        raise HTTPException(status_code=409, detail="Probe retry was cancelled")
    except OSError as exc:
        technical, error = {}, str(exc)

    if technical:
        technical.update({
            "analysis_source": technical.get("probe_transport") or (
                "ffprobe-manual" if payload.strategy == "ffprobe" else "manual-retry"
            ),
            "analysis_mode": "deep",
            "analysis_status": "complete",
            "analysis_version": settings.deep_analysis_version,
            "analysis_profile": "extended" if payload.strategy in {"extended", "ffprobe"} else "standard",
        })
        ScanManager._apply_technical(file, technical, None)
        probe = decode_probe_json(file.probe_json)
        marker = marker_from_probe(probe)
        marker["retry_strategy"] = payload.strategy
        probe["_reelindex"] = marker
        file.probe_json = json.dumps(probe, default=str)
        db.commit()
        return ProbeRetryResponse(
            ok=True,
            file_id=file.id,
            strategy=payload.strategy,
            message="Probe completed and the failure was cleared",
            resolved=True,
            analysis_source=technical.get("analysis_source"),
        )

    failure = error or "Analyzer returned no usable technical metadata"
    _record_retry_failure(file, failure, payload.strategy)
    db.commit()
    return ProbeRetryResponse(
        ok=False,
        file_id=file.id,
        strategy=payload.strategy,
        message="Probe retry completed but the file still failed",
        resolved=False,
        error=failure,
    )
