from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.probes as probes_api
from app.models import Base, MediaFile, Movie, Source
from app.schemas.api import ProbeRetryRequest
from app.services.probe_failures import diagnose_probe_failure


def _factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'failures.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed(factory, path: Path, error: str = "ffprobe standard timed out after 8 seconds"):
    with factory() as db:
        source = Source(name="NAS", type="filesystem", url_or_path=str(path.parent), config_json="{}")
        db.add(source)
        db.flush()
        movie = Movie(
            source_id=source.id,
            source_movie_id="movie-1",
            title="Failure Test",
            sort_title="failure test",
            year=2020,
        )
        db.add(movie)
        db.flush()
        media = MediaFile(
            movie_id=movie.id,
            source_file_id="file-1",
            path=str(path),
            filename=path.name,
            size_bytes=path.stat().st_size if path.exists() else 100,
            probe_error=error,
            probe_json=json.dumps({
                "_reelindex": {
                    "source": "ffprobe-standard",
                    "status": "deferred",
                    "profile": "standard",
                    "attempt_count": 2,
                    "deep_attempt_count": 2,
                    "attempted_at": "2026-08-01T20:00:00+00:00",
                }
            }),
        )
        db.add(media)
        db.commit()
        return source.id, movie.id, media.id


def test_failure_classifier_distinguishes_common_remedies():
    assert diagnose_probe_failure("timed out after 8 seconds", {}, "movie.mkv").category == "timeout"
    assert diagnose_probe_failure("Access is denied", {}, "movie.mp4").category == "permission"
    assert diagnose_probe_failure("moov atom not found", {}, "movie.mp4").recommended_action == "retry_ffprobe"
    assert diagnose_probe_failure("returned no usable technical metadata", {}, "movie.avi").recommended_action == "retry_extended"


def test_failure_list_returns_structured_diagnosis(tmp_path):
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"x" * 100)
    factory = _factory(tmp_path)
    _seed(factory, path)
    with factory() as db:
        result = probes_api.list_probe_failures(page=1, page_size=50, db=db)
    assert result.total == 1
    item = result.items[0]
    assert item.category == "timeout"
    assert item.retryable is True
    assert item.recommended_action == "retry_auto"
    assert result.summary.by_category == {"timeout": 1}


def test_manual_retry_clears_failure(monkeypatch, tmp_path):
    path = tmp_path / "movie.mp4"
    path.write_bytes(b"x" * 100)
    factory = _factory(tmp_path)
    _source_id, _movie_id, file_id = _seed(factory, path)
    monkeypatch.setattr(probes_api.scan_manager, "active_run", lambda _source_id: None)
    monkeypatch.setattr(
        probes_api,
        "probe_media",
        lambda *_a, **_k: ({
            "container": "mov,mp4",
            "duration_seconds": 100.0,
            "video_codec": "h264",
            "width": 1920,
            "height": 1080,
            "resolution_label": "1080p",
            "video_bitrate": 8_000_000,
            "audio_codec": "aac",
            "audio_channels": 2.0,
            "audio_languages": "eng",
            "probe_transport": "native-mp4",
        }, None),
    )
    with factory() as db:
        result = probes_api.retry_probe(file_id, ProbeRetryRequest(strategy="auto"), db)
        media = db.get(MediaFile, file_id)
        assert result.resolved is True
        assert media.probe_error is None
        marker = json.loads(media.probe_json)["_reelindex"]
        assert marker["retry_strategy"] == "auto"
        assert marker["status"] == "complete"


def test_manual_retry_records_unavailable_path(tmp_path):
    path = tmp_path / "missing.mkv"
    factory = _factory(tmp_path)
    _source_id, _movie_id, file_id = _seed(factory, path, "previous failure")
    with factory() as db:
        result = probes_api.retry_probe(file_id, ProbeRetryRequest(strategy="auto"), db)
        media = db.get(MediaFile, file_id)
        assert result.resolved is False
        assert "does not exist" in media.probe_error
        probe = json.loads(media.probe_json)
        assert probe["failure_history"][-1]["strategy"] == "auto"


def test_manual_retry_is_blocked_during_source_scan(monkeypatch, tmp_path):
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"x" * 100)
    factory = _factory(tmp_path)
    _source_id, _movie_id, file_id = _seed(factory, path)
    monkeypatch.setattr(probes_api.scan_manager, "active_run", lambda _source_id: "run-1")
    with factory() as db, pytest.raises(HTTPException) as exc:
        probes_api.retry_probe(file_id, ProbeRetryRequest(strategy="auto"), db)
    assert exc.value.status_code == 409
