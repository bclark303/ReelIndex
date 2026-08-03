from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.api.inventory_records import router as inventory_records_router
from app.models import Base, MediaFile, MediaFileSource, Movie, MovieSource, Source
from app.services import inventory_records


def _temporary_database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed_grouped_record(session_factory, tmp_path: Path, *, external_poster: bool = False):
    media_root = tmp_path / "media"
    media_root.mkdir()
    first_media = media_root / "First Movie.mkv"
    second_media = media_root / "Second Movie.mkv"
    first_media.write_bytes(b"first movie")
    second_media.write_bytes(b"second movie")

    with session_factory() as db:
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path=str(media_root))
        plex = Source(name="Plex", type="plex", url_or_path="http://plex.local")
        movie = Movie(
            source=filesystem,
            source_movie_id="legacy-group",
            title="Faulty Group",
            sort_title="faulty group",
        )
        first = MediaFile(
            source_file_id="filesystem-first",
            path=str(first_media),
            filename=first_media.name,
        )
        second = MediaFile(
            source_file_id="plex-second",
            path=str(second_media),
            filename=second_media.name,
        )
        movie.files.extend((first, second))
        movie.source_links.extend(
            (
                MovieSource(source=filesystem, source_movie_id="filesystem-group"),
                MovieSource(source=plex, source_movie_id="plex-group"),
            )
        )
        first.source_links.append(
            MediaFileSource(
                source=filesystem,
                source_file_id="filesystem-first",
                path=str(first_media),
            )
        )
        second.source_links.append(
            MediaFileSource(
                source=plex,
                source_file_id="plex-second",
                path=str(second_media),
            )
        )
        db.add_all((filesystem, plex))
        db.flush()

        poster_root = tmp_path / "posters" / "library"
        poster_root.mkdir(parents=True)
        managed_poster = poster_root / f"{movie.id}.jpg"
        managed_poster.write_bytes(b"managed poster")
        if external_poster:
            sidecar = media_root / "poster.jpg"
            sidecar.write_bytes(b"sidecar poster")
            movie.poster_path = str(sidecar)
        else:
            sidecar = None
            movie.poster_path = str(managed_poster)

        movie_id = movie.id
        source_ids = {filesystem.id, plex.id}
        db.commit()

    return movie_id, source_ids, managed_poster, sidecar, first_media, second_media


def _count(session_factory, model) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def test_delete_grouped_record_removes_only_reelindex_inventory(tmp_path, monkeypatch):
    session_factory = _temporary_database(tmp_path)
    movie_id, source_ids, managed_poster, _sidecar, first_media, second_media = _seed_grouped_record(
        session_factory,
        tmp_path,
    )
    monkeypatch.setattr(inventory_records.settings, "data_dir", tmp_path)
    monkeypatch.setattr(inventory_records.scan_manager, "active_runs", lambda: {})

    with session_factory() as db:
        result = inventory_records.delete_movie_inventory_record(db, movie_id)

    assert result["movie_id"] == movie_id
    assert result["files_removed"] == 2
    assert set(result["source_ids"]) == source_ids
    assert _count(session_factory, Source) == 2
    assert _count(session_factory, Movie) == 0
    assert _count(session_factory, MovieSource) == 0
    assert _count(session_factory, MediaFile) == 0
    assert _count(session_factory, MediaFileSource) == 0
    assert not managed_poster.exists()
    assert first_media.read_bytes() == b"first movie"
    assert second_media.read_bytes() == b"second movie"


def test_delete_record_never_removes_external_sidecar(tmp_path, monkeypatch):
    session_factory = _temporary_database(tmp_path)
    movie_id, _source_ids, managed_poster, sidecar, first_media, second_media = _seed_grouped_record(
        session_factory,
        tmp_path,
        external_poster=True,
    )
    monkeypatch.setattr(inventory_records.settings, "data_dir", tmp_path)
    monkeypatch.setattr(inventory_records.scan_manager, "active_runs", lambda: {})

    with session_factory() as db:
        inventory_records.delete_movie_inventory_record(db, movie_id)

    assert not managed_poster.exists()
    assert sidecar is not None and sidecar.read_bytes() == b"sidecar poster"
    assert first_media.exists()
    assert second_media.exists()


def test_delete_record_is_blocked_while_any_scan_is_active(tmp_path, monkeypatch):
    session_factory = _temporary_database(tmp_path)
    movie_id, source_ids, _managed_poster, _sidecar, _first_media, _second_media = _seed_grouped_record(
        session_factory,
        tmp_path,
    )
    active_source = next(iter(source_ids))
    monkeypatch.setattr(inventory_records.settings, "data_dir", tmp_path)
    monkeypatch.setattr(inventory_records.scan_manager, "active_runs", lambda: {active_source: "run-id"})

    with session_factory() as db:
        with pytest.raises(inventory_records.InventoryRecordBlocked, match="running scans"):
            inventory_records.delete_movie_inventory_record(db, movie_id)

    assert _count(session_factory, Movie) == 1
    assert _count(session_factory, MediaFile) == 2


def test_delete_record_router_exposes_delete_method():
    matching = [
        route
        for route in inventory_records_router.routes
        if getattr(route, "path", None) == "/movies/{movie_id}"
    ]
    assert any("DELETE" in (getattr(route, "methods", set()) or set()) for route in matching)
