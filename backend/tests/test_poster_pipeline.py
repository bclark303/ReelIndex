from __future__ import annotations

import json
import threading
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.scanner as scanner_module
from app.models import Base, Movie, ScanRun, Source
from app.services.scanner import ScanManager
from app.sources.base import FileCandidate, MovieCandidate


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed(factory):
    with factory() as db:
        source = Source(
            name="Movies",
            type="filesystem",
            url_or_path="X:/Movies",
            config_json="{}",
            enabled=True,
        )
        db.add(source)
        db.flush()
        run = ScanRun(source_id=source.id, status="queued")
        db.add(run)
        db.commit()
        return source.id, run.id


def _candidate(tmp_path: Path) -> MovieCandidate:
    movie_path = tmp_path / "Movie.mkv"
    return MovieCandidate(
        source_movie_id="movie-1",
        title="Movie",
        poster_ref="poster.jpg",
        metadata={"origin": "filesystem"},
        files=[
            FileCandidate(
                source_file_id="file-1",
                path=str(movie_path),
                filename="Movie.mkv",
                local_path=movie_path,
                size_bytes=123,
                modified_ts=1.0,
            )
        ],
    )


class _Adapter:
    def __init__(self, candidate):
        self.candidate = candidate
        self.discovery_workers = 1

    def scan(self, progress=None):
        if progress:
            progress(1, 1, "X:/Movies")
        return [self.candidate]


def test_posters_run_before_technical_analysis(monkeypatch, tmp_path):
    factory = _session_factory(tmp_path)
    source_id, run_id = _seed(factory)
    candidate = _candidate(tmp_path)
    order = []

    monkeypatch.setattr(scanner_module, "SessionLocal", factory)
    monkeypatch.setattr(scanner_module, "create_adapter", lambda *_args, **_kwargs: _Adapter(candidate))
    monkeypatch.setattr(scanner_module.settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        ScanManager,
        "_run_poster_jobs",
        lambda self, _run, jobs, *_args, **_kwargs: order.append(("posters", len(jobs))),
    )
    monkeypatch.setattr(
        ScanManager,
        "_run_probe_jobs",
        lambda self, _run, jobs, *_args, **_kwargs: order.append(("analysis", len(jobs))) or {"paused": False},
    )
    monkeypatch.setattr(ScanManager, "_fill_missing_runtimes", lambda *_args, **_kwargs: None)

    ScanManager()._execute_scan(source_id, run_id, threading.Event(), "quick")

    assert order == [("posters", 1), ("analysis", 1)]


def test_poster_only_refresh_does_not_queue_media_analysis(monkeypatch, tmp_path):
    factory = _session_factory(tmp_path)
    source_id, run_id = _seed(factory)
    candidate = _candidate(tmp_path)
    seen = {}

    monkeypatch.setattr(scanner_module, "SessionLocal", factory)
    monkeypatch.setattr(scanner_module, "create_adapter", lambda *_args, **_kwargs: _Adapter(candidate))
    monkeypatch.setattr(scanner_module.settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        ScanManager,
        "_run_poster_jobs",
        lambda self, _run, jobs, *_args, **_kwargs: seen.update(poster_jobs=len(jobs)),
    )
    monkeypatch.setattr(
        ScanManager,
        "_run_probe_jobs",
        lambda self, _run, jobs, *_args, **_kwargs: seen.update(probe_jobs=len(jobs)) or {"paused": False},
    )
    monkeypatch.setattr(ScanManager, "_fill_missing_runtimes", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("poster refresh must not recompute runtimes")))

    ScanManager()._execute_scan(source_id, run_id, threading.Event(), "posters")

    assert seen == {"poster_jobs": 1, "probe_jobs": 0}
    with factory() as db:
        run = db.get(ScanRun, run_id)
        assert run.status == "completed"
        assert run.cached_count == 1


def test_embedded_cover_does_not_replace_existing_poster(monkeypatch, tmp_path):
    factory = _session_factory(tmp_path)
    source_id, _ = _seed(factory)
    existing = tmp_path / "existing.jpg"
    existing.write_bytes(b"x" * 200)

    with factory() as db:
        movie = Movie(
            source_id=source_id,
            source_movie_id="movie",
            title="Movie",
            sort_title="movie",
            poster_path=str(existing),
            metadata_json=json.dumps({"poster_source": "sidecar"}),
        )
        db.add(movie)
        db.flush()
        from app.models import MediaFile
        record = MediaFile(
            movie_id=movie.id,
            source_file_id="file",
            path="Movie.mp4",
            filename="Movie.mp4",
        )
        db.add(record)
        db.flush()
        technical = {"_embedded_cover": {"data": b"y" * 300, "mime": "image/jpeg"}}
        ScanManager._apply_embedded_cover(db, record, technical)
        db.commit()

    assert existing.read_bytes() == b"x" * 200
    assert "_embedded_cover" not in technical
