from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models import Base, MediaFile, MediaFileSource, Movie, MovieSource, ScanRun, Source
from app.services.library_identity import LibraryIdentityIndex
from app.services.media_utils import clean_title
from app.services.scan_events import ScanEventStore
from app.sources.base import FileCandidate, MovieCandidate
from app.sources.filesystem import FilesystemAdapter


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'duplicate-repair.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_clean_title_preserves_dotted_movie_names():
    assert clean_title("Dr. No (1962)")[:2] == ("Dr No", 1962)
    assert clean_title("Mr. Deeds (2002)")[:2] == ("Mr Deeds", 2002)
    assert clean_title("Mrs. Doubtfire (1993)")[:2] == ("Mrs Doubtfire", 1993)
    assert clean_title("Kill Bill Vol. 1 (2003)")[:2] == ("Kill Bill Vol 1", 2003)
    assert clean_title("S. Darko (2009).mkv")[:2] == ("S Darko", 2009)
    assert clean_title("Jackass 3.5 (2011).mkv")[:2] == ("Jackass 3 5", 2011)


def test_filesystem_scan_keeps_dotted_titles_separate(tmp_path: Path):
    folders = {
        "Dr. No (1962)": "Dr. No (1962) Bluray-1080p.mkv",
        "Dr. Strangelove (1964)": "Dr. Strangelove (1964) Bluray-1080p.mkv",
        "Mr. Deeds (2002)": "Mr. Deeds (2002) Bluray-1080p.mkv",
        "Kill Bill Vol. 1 (2003)": "Kill Bill Vol. 1 (2003) Bluray-1080p.mkv",
        "Kill Bill Vol. 2 (2004)": "Kill Bill Vol. 2 (2004) Bluray-1080p.mkv",
    }
    for folder, filename in folders.items():
        directory = tmp_path / folder
        directory.mkdir()
        (directory / filename).write_bytes(b"movie")

    movies = FilesystemAdapter(str(tmp_path), {"discovery_workers": 1}).scan()

    assert {(movie.title, movie.year, len(movie.files)) for movie in movies} == {
        ("Dr No", 1962, 1),
        ("Dr Strangelove", 1964, 1),
        ("Mr Deeds", 2002, 1),
        ("Kill Bill Vol 1", 2003, 1),
        ("Kill Bill Vol 2", 2004, 1),
    }


def test_corrected_filesystem_alias_moves_to_compatible_canonical_movie(tmp_path: Path):
    engine, LocalSession = _session_factory(tmp_path)
    filename = "Dr. No (1962) Bluray-1080p.mkv"
    size = 8_000_000_000
    local_path = tmp_path / filename

    with LocalSession() as db:
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path=str(tmp_path))
        plex = Source(name="Plex", type="plex", url_or_path="http://plex")
        db.add_all([filesystem, plex])
        db.flush()

        malformed = Movie(
            source_id=filesystem.id,
            source_movie_id="legacy-dr",
            title="Dr",
            sort_title="dr",
        )
        canonical = Movie(
            source_id=plex.id,
            source_movie_id="plex-dr-no",
            title="Dr. No",
            sort_title="dr. no",
            year=1962,
        )
        db.add_all([malformed, canonical])
        db.flush()
        old_movie_link = MovieSource(
            source_id=filesystem.id,
            movie_id=malformed.id,
            source_movie_id="legacy-dr",
        )
        plex_movie_link = MovieSource(
            source_id=plex.id,
            movie_id=canonical.id,
            source_movie_id="plex-dr-no",
        )
        db.add_all([old_movie_link, plex_movie_link])

        malformed_file = MediaFile(
            movie_id=malformed.id,
            source_file_id="filesystem-file",
            path=str(local_path),
            filename=filename,
            size_bytes=size,
        )
        canonical_file = MediaFile(
            movie_id=canonical.id,
            source_file_id="plex-file",
            path=f"/server/{filename}",
            filename=filename,
            size_bytes=size,
        )
        db.add_all([malformed_file, canonical_file])
        db.flush()
        malformed_file_id = malformed_file.id
        filesystem_file_link = MediaFileSource(
            source_id=filesystem.id,
            media_file_id=malformed_file.id,
            source_file_id="filesystem-file",
            path=str(local_path),
        )
        plex_file_link = MediaFileSource(
            source_id=plex.id,
            media_file_id=canonical_file.id,
            source_file_id="plex-file",
            path=f"/server/{filename}",
        )
        db.add_all([filesystem_file_link, plex_file_link])
        db.commit()

        candidate = MovieCandidate(
            source_movie_id="fixed-dr-no",
            title="Dr No",
            year=1962,
            files=[
                FileCandidate(
                    source_file_id="filesystem-file",
                    path=str(local_path),
                    local_path=local_path,
                    filename=filename,
                    size_bytes=size,
                )
            ],
        )
        identity = LibraryIdentityIndex(db)
        movie, _ = identity.movie_for_candidate(filesystem.id, candidate)
        assert movie is not None and movie.id == canonical.id

        movie_link = identity.ensure_movie_link(
            movie,
            filesystem.id,
            candidate.source_movie_id,
        )
        media_file, stale_file_link = identity.file_for_candidate(
            filesystem.id,
            movie,
            candidate.files[0],
        )
        assert media_file is not None and media_file.id == canonical_file.id
        assert stale_file_link is not None and stale_file_link.id == filesystem_file_link.id
        file_link = identity.ensure_file_link(
            media_file,
            filesystem.id,
            candidate.files[0].source_file_id,
            candidate.files[0].path,
        )
        identity.deactivate_unseen(
            filesystem.id,
            {movie_link.id},
            {file_link.id},
        )
        db.commit()

        db.refresh(malformed)
        db.refresh(file_link)
        assert malformed.active is False
        assert file_link.media_file_id == canonical_file.id
        assert db.get(MediaFile, malformed_file_id) is None
        assert db.scalar(select(func.count(Movie.id)).where(Movie.active.is_(True))) == 1

    engine.dispose()


def test_completed_scan_reconciles_after_file_sizes_are_refreshed(tmp_path: Path, monkeypatch):
    engine, LocalSession = _session_factory(tmp_path)
    filename = "Alien (1979) Bluray-1080p.mkv"
    size = 42_000_000_000

    with LocalSession() as db:
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path=str(tmp_path))
        plex = Source(name="Plex", type="plex", url_or_path="http://plex")
        db.add_all([filesystem, plex])
        db.flush()
        first = Movie(
            source_id=filesystem.id,
            source_movie_id="fs-alien",
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
        db.add_all([
            MovieSource(source_id=filesystem.id, movie_id=first.id, source_movie_id="fs-alien"),
            MovieSource(source_id=plex.id, movie_id=second.id, source_movie_id="plex-alien"),
        ])
        first_file = MediaFile(
            movie_id=first.id,
            source_file_id="fs-file",
            path=str(tmp_path / filename),
            filename=filename,
            size_bytes=size,
        )
        second_file = MediaFile(
            movie_id=second.id,
            source_file_id="plex-file",
            path=f"/server/{filename}",
            filename=filename,
            size_bytes=size,
        )
        db.add_all([first_file, second_file])
        db.flush()
        db.add_all([
            MediaFileSource(
                source_id=filesystem.id,
                media_file_id=first_file.id,
                source_file_id="fs-file",
                path=str(tmp_path / filename),
            ),
            MediaFileSource(
                source_id=plex.id,
                media_file_id=second_file.id,
                source_file_id="plex-file",
                path=f"/server/{filename}",
            ),
        ])
        run = ScanRun(source_id=filesystem.id, status="completed")
        db.add(run)
        db.commit()
        run_id = run.id

    import app.core.database as database_module

    monkeypatch.setattr(database_module, "SessionLocal", LocalSession)
    store = ScanEventStore(tmp_path / "events")
    store.start_run(run_id)
    store.append(run_id, "success", "complete", "Scan completed")

    with LocalSession() as db:
        assert db.scalar(select(func.count(Movie.id))) == 1
        assert db.scalar(select(func.count(MediaFile.id))) == 1
        assert db.scalar(select(func.count(MovieSource.id))) == 2
        assert db.scalar(select(func.count(MediaFileSource.id))) == 2

    exported = store.export_text(run_id)
    assert '"stage": "reconcile"' in exported
    assert '"merged_movies": 1' in exported
    engine.dispose()
