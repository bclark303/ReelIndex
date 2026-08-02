from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models import Base, MediaFile, MediaFileSource, Movie, MovieSource, ScanRun, Source
from app.services import scanner as scanner_module
from app.services.library_identity import upgrade_library_identity
from app.services.scanner import ScanManager
from app.sources.base import FileCandidate, MovieCandidate


class FakeAdapter:
    discovery_workers = 1

    def __init__(self, candidates: list[MovieCandidate]):
        self.candidates = candidates

    def scan(self, progress=None):
        if progress:
            progress(len(self.candidates), sum(len(movie.files) for movie in self.candidates), "fake")
        return self.candidates

    def fetch_poster(self, candidate, destination):
        return False


def make_session(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'identity.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def movie_candidate(source_movie_id: str, source_file_id: str, source_path: str, local_path: Path) -> MovieCandidate:
    return MovieCandidate(
        source_movie_id=source_movie_id,
        title="Alien",
        year=1979,
        runtime_seconds=7_020,
        metadata={"origin": "filesystem" if source_movie_id.startswith("fs") else "plex"},
        files=[
            FileCandidate(
                source_file_id=source_file_id,
                path=source_path,
                local_path=local_path,
                filename="Alien (1979).mkv",
                size_bytes=42_000_000_000,
                modified_ts=1_700_000_000.0,
            )
        ],
    )


def test_two_source_scans_share_one_movie_and_file(tmp_path, monkeypatch):
    engine, LocalSession = make_session(tmp_path)
    media_path = tmp_path / "media" / "Alien (1979).mkv"
    source_candidates: dict[str, list[MovieCandidate]] = {
        "filesystem": [movie_candidate("fs-alien", "fs-file", str(media_path), media_path)],
        "plex": [movie_candidate("plex-123", "plex-part-456", "/server/movies/Alien (1979).mkv", media_path)],
    }

    with LocalSession() as db:
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path=str(tmp_path / "media"))
        plex = Source(name="Plex", type="plex", url_or_path="http://plex:32400")
        db.add_all([filesystem, plex])
        db.flush()
        first_run = ScanRun(source_id=filesystem.id)
        second_run = ScanRun(source_id=plex.id)
        db.add_all([first_run, second_run])
        db.commit()
        ids = filesystem.id, plex.id, first_run.id, second_run.id

    monkeypatch.setattr(scanner_module, "SessionLocal", LocalSession)
    monkeypatch.setattr(scanner_module.scan_event_store, "directory", tmp_path / "scan-events")
    monkeypatch.setattr(scanner_module.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(scanner_module.settings, "tmdb_api_token", None)
    monkeypatch.setattr(
        scanner_module,
        "create_adapter",
        lambda source_type, *_args, **_kwargs: FakeAdapter(source_candidates[source_type]),
    )

    manager = ScanManager()
    filesystem_id, plex_id, first_run_id, second_run_id = ids
    manager._execute_scan(filesystem_id, first_run_id, threading.Event(), "posters", "incomplete")
    manager._execute_scan(plex_id, second_run_id, threading.Event(), "posters", "incomplete")

    with LocalSession() as db:
        assert db.scalar(select(func.count(Movie.id))) == 1
        assert db.scalar(select(func.count(MediaFile.id))) == 1
        assert db.scalar(select(func.count(MovieSource.id))) == 2
        assert db.scalar(select(func.count(MediaFileSource.id))) == 2
        movie = db.scalar(select(Movie))
        media_file = db.scalar(select(MediaFile))
        assert movie is not None and movie.active is True
        assert media_file is not None and media_file.active is True
        assert {link.source_id for link in db.scalars(select(MovieSource)).all()} == {filesystem_id, plex_id}
        assert {link.source_id for link in db.scalars(select(MediaFileSource)).all()} == {filesystem_id, plex_id}

    # Removing one source's view must not deactivate the canonical library entry
    # while another source still sees it.
    source_candidates["filesystem"] = []
    with LocalSession() as db:
        third_run = ScanRun(source_id=filesystem_id)
        db.add(third_run)
        db.commit()
        third_run_id = third_run.id
    manager._execute_scan(filesystem_id, third_run_id, threading.Event(), "posters", "incomplete")
    with LocalSession() as db:
        assert db.scalar(select(Movie.active)) is True
        assert db.scalar(select(MediaFile.active)) is True

    engine.dispose()


def test_startup_consolidates_existing_cross_source_duplicates(tmp_path):
    engine, LocalSession = make_session(tmp_path)
    with LocalSession() as db:
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path="/media")
        plex = Source(name="Plex", type="plex", url_or_path="http://plex:32400")
        db.add_all([filesystem, plex])
        db.flush()
        first = Movie(
            source_id=filesystem.id,
            source_movie_id="filesystem-alien",
            title="Alien",
            sort_title="alien",
            year=1979,
        )
        second = Movie(
            source_id=plex.id,
            source_movie_id="plex-alien",
            title="Alien",
            sort_title="alien",
            year=1979,
        )
        db.add_all([first, second])
        db.flush()
        db.add_all(
            [
                MediaFile(
                    movie_id=first.id,
                    source_file_id="filesystem-file",
                    path="/media/Alien (1979).mkv",
                    filename="Alien (1979).mkv",
                    size_bytes=42_000_000_000,
                ),
                MediaFile(
                    movie_id=second.id,
                    source_file_id="plex-part",
                    path="/server/movies/Alien (1979).mkv",
                    filename="Alien (1979).mkv",
                    size_bytes=42_000_000_000,
                ),
            ]
        )
        db.commit()

        merged = upgrade_library_identity(db)
        assert merged == 1
        assert db.scalar(select(func.count(Movie.id))) == 1
        assert db.scalar(select(func.count(MediaFile.id))) == 1
        assert db.scalar(select(func.count(MovieSource.id))) == 2
        assert db.scalar(select(func.count(MediaFileSource.id))) == 2

    engine.dispose()
