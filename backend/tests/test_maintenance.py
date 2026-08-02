from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, MediaFile, Movie, ScanRun, Source
from app.services import maintenance


def _temporary_database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed(session_factory, poster_path: Path):
    with session_factory() as db:
        source = Source(name="Movies", type="filesystem", url_or_path=r"\\server\movies")
        movie = Movie(
            source=source,
            source_movie_id="movie-1",
            title="Example Movie",
            sort_title="example movie",
            poster_path=str(poster_path),
        )
        movie.files.append(MediaFile(source_file_id="file-1", path="movie.mkv", filename="movie.mkv"))
        source.scan_runs.append(ScanRun(status="completed"))
        db.add(source)
        db.commit()


def _count(session_factory, model) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def test_clear_inventory_retains_sources_and_removes_generated_data(tmp_path, monkeypatch):
    engine, session_factory = _temporary_database(tmp_path)
    posters = tmp_path / "posters"
    posters.mkdir()
    poster = posters / "poster.jpg"
    poster.write_bytes(b"cached-poster")
    _seed(session_factory, poster)

    monkeypatch.setattr(maintenance, "SessionLocal", session_factory)
    monkeypatch.setattr(maintenance, "engine", engine)
    monkeypatch.setattr(maintenance.settings, "data_dir", tmp_path)
    monkeypatch.setattr(maintenance.scan_manager, "active_runs", lambda: {})

    result = maintenance.reset_application_data(include_sources=False)

    assert result["mode"] == "inventory_cache"
    assert result["removed"]["sources"] == 0
    assert _count(session_factory, Source) == 1
    assert _count(session_factory, Movie) == 0
    assert _count(session_factory, MediaFile) == 0
    assert _count(session_factory, ScanRun) == 0
    assert list(posters.iterdir()) == []


def test_factory_reset_removes_sources_credentials_inventory_and_posters(tmp_path, monkeypatch):
    engine, session_factory = _temporary_database(tmp_path)
    posters = tmp_path / "posters"
    posters.mkdir()
    poster = posters / "poster.jpg"
    poster.write_bytes(b"cached-poster")
    _seed(session_factory, poster)

    monkeypatch.setattr(maintenance, "SessionLocal", session_factory)
    monkeypatch.setattr(maintenance, "engine", engine)
    monkeypatch.setattr(maintenance.settings, "data_dir", tmp_path)
    monkeypatch.setattr(maintenance.scan_manager, "active_runs", lambda: {})

    result = maintenance.reset_application_data(include_sources=True)

    assert result["mode"] == "factory_reset"
    assert result["removed"]["sources"] == 1
    assert _count(session_factory, Source) == 0
    assert _count(session_factory, Movie) == 0
    assert _count(session_factory, MediaFile) == 0
    assert _count(session_factory, ScanRun) == 0
    assert list(posters.iterdir()) == []


def test_maintenance_is_blocked_while_scan_is_active(monkeypatch):
    monkeypatch.setattr(maintenance.scan_manager, "active_runs", lambda: {"source": "run"})

    with pytest.raises(maintenance.MaintenanceBlocked, match="Cancel all running scans"):
        maintenance.reset_application_data(include_sources=False)
