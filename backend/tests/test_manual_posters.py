from __future__ import annotations

import asyncio
import json
import threading
from io import BytesIO
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

import app.api.movies as movies_api
import app.services.scanner as scanner_module
from app.models import Base, Movie, ScanRun, Source
from app.services.scanner import ScanManager
from app.sources.base import FileCandidate, MovieCandidate


def _factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'manual.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed(factory):
    with factory() as db:
        source = Source(
            name="Movies",
            type="filesystem",
            url_or_path="M:/Movies",
            config_json=json.dumps({"tmdb_token": "token"}),
        )
        db.add(source)
        db.flush()
        movie = Movie(
            source_id=source.id,
            source_movie_id="movie-1",
            title="Cloud Atlas READNFO BRRip",
            sort_title="cloud atlas readnfo brrip",
            year=2012,
            metadata_json="{}",
        )
        db.add(movie)
        db.commit()
        return source.id, movie.id


def test_manual_tmdb_selection_is_cached_and_locked(monkeypatch, tmp_path):
    factory = _factory(tmp_path)
    _source_id, movie_id = _seed(factory)
    monkeypatch.setattr(movies_api.settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        movies_api.TmdbClient,
        "get_title",
        lambda self, tmdb_id, media_type: {
            "id": tmdb_id,
            "title": "Cloud Atlas",
            "overview": "Overview",
            "poster_path": "/cloud.jpg",
        },
    )

    def download(self, poster_path, destination):
        destination.write_bytes(b"\xff\xd8\xff" + b"x" * 200)
        return True

    monkeypatch.setattr(movies_api.TmdbClient, "download_poster", download)
    with factory() as db:
        result = movies_api.select_tmdb_poster(
            movie_id,
            movies_api.PosterSelection(tmdb_id=83542, media_type="movie"),
            db,
        )
        movie = db.get(Movie, movie_id)
        metadata = json.loads(movie.metadata_json)
        assert result["ok"] is True
        assert Path(movie.poster_path).exists()
        assert metadata["poster_source"] == "manual-tmdb"
        assert metadata["poster_locked"] is True
        assert metadata["tmdb_id"] == 83542


def test_manual_upload_accepts_png(monkeypatch, tmp_path):
    factory = _factory(tmp_path)
    _source_id, movie_id = _seed(factory)
    monkeypatch.setattr(movies_api.settings, "data_dir", tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    upload = UploadFile(filename="custom.png", file=BytesIO(png))
    with factory() as db:
        result = asyncio.run(movies_api.upload_movie_poster(movie_id, upload, db))
        movie = db.get(Movie, movie_id)
        metadata = json.loads(movie.metadata_json)
        assert result["ok"] is True
        assert Path(movie.poster_path).read_bytes() == png
        assert metadata["poster_source"] == "manual-upload"
        assert metadata["poster_locked"] is True


def test_scan_preserves_locked_manual_poster(monkeypatch, tmp_path):
    factory = _factory(tmp_path)
    source_id, movie_id = _seed(factory)
    destination = tmp_path / "posters" / source_id / f"{movie_id}.jpg"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"\xff\xd8\xff" + b"m" * 200)
    with factory() as db:
        movie = db.get(Movie, movie_id)
        movie.poster_path = str(destination)
        movie.metadata_json = json.dumps({"poster_source": "manual-upload", "poster_locked": True})
        run = ScanRun(source_id=source_id, status="queued")
        db.add(run)
        db.commit()
        run_id = run.id

    candidate = MovieCandidate(
        source_movie_id="movie-1",
        title="Cloud Atlas READNFO BRRip",
        poster_ref="poster.jpg",
        metadata={"origin": "filesystem"},
        files=[
            FileCandidate(
                source_file_id="file-1",
                path="M:/Movies/Cloud Atlas/Cloud Atlas.mkv",
                filename="Cloud Atlas.mkv",
                size_bytes=100,
                modified_ts=1.0,
            )
        ],
    )

    class Adapter:
        discovery_workers = 1

        def scan(self, progress=None):
            if progress:
                progress(1, 1, "M:/Movies")
            return [candidate]

    seen = {}
    monkeypatch.setattr(scanner_module, "SessionLocal", factory)
    monkeypatch.setattr(scanner_module, "create_adapter", lambda *_a, **_k: Adapter())
    monkeypatch.setattr(scanner_module.settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        ScanManager,
        "_run_poster_jobs",
        lambda self, _run, jobs, *_a, **_k: seen.update(poster_jobs=len(jobs)),
    )
    monkeypatch.setattr(
        ScanManager,
        "_run_probe_jobs",
        lambda self, _run, jobs, *_a, **_k: {"paused": False},
    )
    monkeypatch.setattr(ScanManager, "_fill_missing_runtimes", lambda *_a, **_k: None)

    ScanManager()._execute_scan(source_id, run_id, threading.Event(), "posters")

    with factory() as db:
        movie = db.get(Movie, movie_id)
        metadata = json.loads(movie.metadata_json)
        assert seen["poster_jobs"] == 0
        assert Path(movie.poster_path).read_bytes().startswith(b"\xff\xd8\xff")
        assert metadata["poster_locked"] is True
        assert metadata["poster_source"] == "manual-upload"
