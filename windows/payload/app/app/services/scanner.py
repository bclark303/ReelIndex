from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import reveal_config
from app.models import MediaFile, Movie, ScanRun, Source
from app.services.media_utils import sort_title
from app.services.probe import probe_media
from app.services.tmdb import TmdbClient
from app.sources.factory import create_adapter

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScanManager:
    def __init__(self):
        self._active: dict[str, str] = {}
        self._lock = threading.Lock()

    def start(self, source_id: str) -> str:
        with self._lock:
            if source_id in self._active:
                return self._active[source_id]
            with SessionLocal() as db:
                source = db.get(Source, source_id)
                if not source:
                    raise ValueError("Source not found")
                run = ScanRun(source_id=source_id, status="queued")
                db.add(run)
                db.commit()
                db.refresh(run)
                run_id = run.id
            self._active[source_id] = run_id
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(self._run_scan, source_id, run_id))
        except RuntimeError:
            thread = threading.Thread(target=self._run_scan, args=(source_id, run_id), daemon=True)
            thread.start()
        return run_id

    def active_run(self, source_id: str) -> str | None:
        with self._lock:
            return self._active.get(source_id)

    def _run_scan(self, source_id: str, run_id: str) -> None:
        try:
            self._execute_scan(source_id, run_id)
        except Exception as exc:
            logger.exception("Scan failed for source %s", source_id)
            with SessionLocal() as db:
                run = db.get(ScanRun, run_id)
                if run:
                    run.status = "failed"
                    run.error_message = str(exc)[:4000]
                    run.completed_at = utcnow()
                    db.commit()
        finally:
            with self._lock:
                self._active.pop(source_id, None)

    def _execute_scan(self, source_id: str, run_id: str) -> None:
        with SessionLocal() as db:
            source = db.get(Source, source_id)
            run = db.get(ScanRun, run_id)
            if not source or not run:
                raise ValueError("Source or scan run no longer exists")
            run.status = "running"
            db.commit()
            config = reveal_config(json.loads(source.config_json or "{}"))
            adapter = create_adapter(source.type, source.url_or_path, source.library_id, config)

        candidates = adapter.scan()

        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if not run:
                return
            run.discovered_count = sum(len(movie.files) for movie in candidates)
            db.commit()

            existing_movies = {
                item.source_movie_id: item
                for item in db.scalars(select(Movie).where(Movie.source_id == source_id)).all()
            }
            seen_movie_ids: set[str] = set()
            tmdb = TmdbClient(config.get("tmdb_token"))
            processed_files = 0

            for candidate in candidates:
                run.current_item = candidate.title
                movie = existing_movies.get(candidate.source_movie_id)
                if not movie:
                    movie = Movie(source_id=source_id, source_movie_id=candidate.source_movie_id, title=candidate.title, sort_title=sort_title(candidate.title))
                    db.add(movie)
                    db.flush()
                seen_movie_ids.add(movie.id)
                movie.title = candidate.title
                movie.sort_title = sort_title(candidate.title)
                movie.year = candidate.year
                movie.runtime_seconds = candidate.runtime_seconds
                movie.overview = candidate.overview
                movie.metadata_json = json.dumps(candidate.metadata, default=str)
                movie.active = True

                self._ensure_poster(db, source_id, movie, candidate, adapter, tmdb)

                existing_files = {item.source_file_id: item for item in movie.files}
                seen_file_ids: set[str] = set()
                for file_candidate in candidate.files:
                    file_record = existing_files.get(file_candidate.source_file_id)
                    if not file_record:
                        file_record = MediaFile(movie_id=movie.id, source_file_id=file_candidate.source_file_id, path=file_candidate.path, filename=file_candidate.filename)
                        db.add(file_record)
                        db.flush()
                    seen_file_ids.add(file_record.id)
                    unchanged = file_record.fingerprint == file_candidate.fingerprint and bool(file_record.probe_json)
                    file_record.path = file_candidate.path
                    file_record.filename = file_candidate.filename
                    file_record.size_bytes = file_candidate.size_bytes
                    file_record.modified_ts = file_candidate.modified_ts
                    file_record.fingerprint = file_candidate.fingerprint
                    file_record.edition = file_candidate.edition
                    file_record.active = True

                    if unchanged:
                        run.cached_count += 1
                    else:
                        technical, error = self._analyze_file(file_candidate)
                        self._apply_technical(file_record, technical, error)
                        if error:
                            run.error_count += 1
                        else:
                            run.analyzed_count += 1
                    processed_files += 1
                    if processed_files % 20 == 0:
                        db.commit()

                for file_record in movie.files:
                    if file_record.id not in seen_file_ids:
                        file_record.active = False
                if not movie.runtime_seconds:
                    durations = [item.duration_seconds for item in movie.files if item.active and item.duration_seconds]
                    movie.runtime_seconds = max(durations) if durations else None
                db.flush()

            for movie in existing_movies.values():
                if movie.id not in seen_movie_ids:
                    movie.active = False
                    for file_record in movie.files:
                        file_record.active = False

            run.status = "completed"
            run.current_item = None
            run.completed_at = utcnow()
            db.commit()

    @staticmethod
    def _analyze_file(file_candidate) -> tuple[dict[str, Any], str | None]:
        if file_candidate.local_path and file_candidate.local_path.exists():
            technical, error = probe_media(file_candidate.local_path)
            if technical:
                return technical, error
        if file_candidate.technical:
            return file_candidate.technical, None
        return {}, "Media file is not locally accessible and the server supplied no technical metadata"

    @staticmethod
    def _apply_technical(record: MediaFile, technical: dict[str, Any], error: str | None) -> None:
        record.container = technical.get("container")
        record.duration_seconds = technical.get("duration_seconds")
        record.video_codec = technical.get("video_codec")
        record.width = technical.get("width")
        record.height = technical.get("height")
        record.resolution_label = technical.get("resolution_label")
        record.video_bitrate = technical.get("video_bitrate")
        record.audio_codec = technical.get("audio_codec")
        record.audio_channels = technical.get("audio_channels")
        record.audio_languages = technical.get("audio_languages")
        record.probe_json = json.dumps(technical.get("raw", technical), default=str)
        record.probe_error = error

    @staticmethod
    def _ensure_poster(db: Session, source_id: str, movie: Movie, candidate, adapter, tmdb: TmdbClient) -> None:
        destination = settings.data_dir / "posters" / source_id / f"{movie.id}.jpg"
        if destination.exists() and destination.stat().st_size > 100:
            movie.poster_path = str(destination)
            return
        if adapter.fetch_poster(candidate, destination):
            movie.poster_path = str(destination)
            return
        if tmdb.enabled:
            result = tmdb.find_movie(candidate.title, candidate.year)
            if result:
                if not movie.overview:
                    movie.overview = result.get("overview")
                metadata = json.loads(movie.metadata_json or "{}")
                metadata["tmdb_id"] = result.get("id")
                movie.metadata_json = json.dumps(metadata)
                if tmdb.download_poster(result.get("poster_path"), destination):
                    movie.poster_path = str(destination)


scan_manager = ScanManager()
