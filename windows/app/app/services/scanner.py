from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import reveal_config
from app.models import MediaFile, Movie, ScanRun, Source
from app.services.media_utils import sort_title
from app.services.probe import ProbeCancelled, probe_media
from app.services.tmdb import TmdbClient
from app.sources.factory import create_adapter

logger = logging.getLogger(__name__)


class ScanCancelled(RuntimeError):
    """Internal signal used to stop scan work without recording a failure."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ProbeJob:
    record_id: str
    filename: str
    candidate: Any


@dataclass(slots=True)
class PosterJob:
    movie_id: str
    title: str
    candidate: Any
    destination: Path


@dataclass(slots=True)
class PosterResult:
    found: bool
    overview: str | None = None
    tmdb_id: int | None = None


class ScanManager:
    def __init__(self):
        self._active: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
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
            self._cancel_events[run_id] = threading.Event()
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

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
            if not cancel_event:
                return False
            cancel_event.set()
        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if run and run.status in {"queued", "running", "cancelling"}:
                run.status = "cancelling"
                run.current_item = "Cancelling scan…"
                db.commit()
        return True

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise ScanCancelled("Scan cancelled by user")

    @staticmethod
    def _run_cancellable_call(
        operation: Any,
        cancel_event: threading.Event,
        label: str,
    ) -> Any:
        """Run a blocking adapter operation without letting it trap the scan thread.

        Windows network and SMB calls can remain blocked inside the operating system
        even after the user requests cancellation. The adapter call therefore runs in
        a daemon thread while the scan manager polls the cancellation event. The
        abandoned adapter thread cannot update the database and exits at its next
        progress callback or when the underlying network call returns.
        """
        result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                result_queue.put((True, operation()))
            except BaseException as exc:  # Propagate adapter failures to the scan thread.
                result_queue.put((False, exc))

        thread = threading.Thread(
            target=worker,
            name=f"reelindex-{label}",
            daemon=True,
        )
        thread.start()

        while True:
            if cancel_event.wait(0.1):
                raise ScanCancelled(f"Scan cancelled during {label}")
            try:
                ok, result = result_queue.get_nowait()
            except queue.Empty:
                continue
            if ok:
                return result
            raise result

    def _run_scan(self, source_id: str, run_id: str) -> None:
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
        if cancel_event is None:
            cancel_event = threading.Event()
        try:
            self._execute_scan(source_id, run_id, cancel_event)
        except ScanCancelled:
            with SessionLocal() as db:
                run = db.get(ScanRun, run_id)
                if run:
                    run.status = "cancelled"
                    run.current_item = "Scan cancelled"
                    run.completed_at = utcnow()
                    db.commit()
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
                if self._active.get(source_id) == run_id:
                    self._active.pop(source_id, None)
                self._cancel_events.pop(run_id, None)

    def _execute_scan(self, source_id: str, run_id: str, cancel_event: threading.Event) -> None:
        self._raise_if_cancelled(cancel_event)
        with SessionLocal() as db:
            source = db.get(Source, source_id)
            run = db.get(ScanRun, run_id)
            if not source or not run:
                raise ValueError("Source or scan run no longer exists")
            run.status = "running"
            run.current_item = "Discovering movies…"
            db.commit()
            config = reveal_config(json.loads(source.config_json or "{}"))
            adapter = create_adapter(source.type, source.url_or_path, source.library_id, config)

        last_progress_at = 0.0
        last_progress_files = 0

        def discovery_progress(movie_count: int, file_count: int, location: str) -> None:
            nonlocal last_progress_at, last_progress_files
            self._raise_if_cancelled(cancel_event)
            now = time.monotonic()
            if file_count > 1 and file_count - last_progress_files < 25 and now - last_progress_at < 0.75:
                return
            last_progress_at = now
            last_progress_files = file_count
            label = str(location)
            if len(label) > 150:
                label = "…" + label[-149:]
            with SessionLocal() as progress_db:
                progress_run = progress_db.get(ScanRun, run_id)
                if progress_run:
                    progress_run.discovered_count = file_count
                    progress_run.current_item = f"Discovering · {movie_count:,} movies / {file_count:,} files · {label}"
                    progress_db.commit()

        candidates = self._run_cancellable_call(
            lambda: adapter.scan(progress=discovery_progress),
            cancel_event,
            "discovery",
        )
        self._raise_if_cancelled(cancel_event)
        total_files = sum(len(movie.files) for movie in candidates)
        tmdb_token = config.get("tmdb_token") or settings.tmdb_api_token
        probe_jobs: list[ProbeJob] = []
        poster_jobs: list[PosterJob] = []

        # Phase 1: make the complete inventory visible quickly. Technical probing and
        # poster enrichment are deliberately deferred until after this transaction.
        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if not run:
                return
            run.discovered_count = total_files
            run.current_item = f"Indexing · 0/{len(candidates):,} movies"
            db.commit()

            existing_movies = {
                item.source_movie_id: item
                for item in db.scalars(
                    select(Movie)
                    .options(selectinload(Movie.files))
                    .where(Movie.source_id == source_id)
                ).all()
            }
            seen_movie_ids: set[str] = set()
            processed_files = 0

            for movie_index, candidate in enumerate(candidates, start=1):
                self._raise_if_cancelled(cancel_event)
                run.current_item = f"Indexing · {movie_index:,}/{len(candidates):,} · {candidate.title}"
                movie = existing_movies.get(candidate.source_movie_id)
                if not movie:
                    movie = Movie(
                        source_id=source_id,
                        source_movie_id=candidate.source_movie_id,
                        title=candidate.title,
                        sort_title=sort_title(candidate.title),
                    )
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

                destination = settings.data_dir / "posters" / source_id / f"{movie.id}.jpg"
                local_poster = candidate.metadata.get("origin") == "filesystem" and bool(candidate.poster_ref)
                if local_poster:
                    # A local sidecar is authoritative and should replace an older
                    # TMDB/server cache on the next scan.
                    poster_jobs.append(PosterJob(movie.id, candidate.title, candidate, destination))
                elif destination.exists() and destination.stat().st_size > 100:
                    movie.poster_path = str(destination)
                elif candidate.poster_ref or tmdb_token:
                    poster_jobs.append(PosterJob(movie.id, candidate.title, candidate, destination))

                existing_files = {item.source_file_id: item for item in movie.files}
                seen_file_ids: set[str] = set()
                for file_candidate in candidate.files:
                    self._raise_if_cancelled(cancel_event)
                    file_record = existing_files.get(file_candidate.source_file_id)
                    if not file_record:
                        file_record = MediaFile(
                            movie_id=movie.id,
                            source_file_id=file_candidate.source_file_id,
                            path=file_candidate.path,
                            filename=file_candidate.filename,
                        )
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
                    elif self._has_server_technical(file_candidate.technical):
                        # Plex/Jellyfin/Emby already provide the fields needed by the
                        # competition. Do not reopen every media file over the network.
                        self._apply_technical(file_record, file_candidate.technical, None)
                        run.analyzed_count += 1
                    else:
                        probe_jobs.append(ProbeJob(file_record.id, file_candidate.filename, file_candidate))

                    processed_files += 1
                    if processed_files % settings.scan_commit_interval == 0:
                        db.commit()

                for file_record in movie.files:
                    if file_record.id not in seen_file_ids:
                        file_record.active = False

                if movie_index % settings.scan_commit_interval == 0:
                    db.commit()

            for movie in existing_movies.values():
                if movie.id not in seen_movie_ids:
                    movie.active = False
                    for file_record in movie.files:
                        file_record.active = False

            run.current_item = (
                f"Inventory ready · {len(candidates):,} movies / {total_files:,} files · "
                f"analyzing {len(probe_jobs):,} changed files"
            )
            db.commit()

        self._raise_if_cancelled(cancel_event)
        self._run_probe_jobs(run_id, probe_jobs, cancel_event)
        self._raise_if_cancelled(cancel_event)
        self._fill_missing_runtimes(source_id, cancel_event)
        self._raise_if_cancelled(cancel_event)
        self._run_poster_jobs(run_id, poster_jobs, adapter, tmdb_token, cancel_event)
        self._raise_if_cancelled(cancel_event)

        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if not run:
                return
            run.status = "completed"
            run.current_item = None
            run.completed_at = utcnow()
            db.commit()

    def _run_probe_jobs(
        self,
        run_id: str,
        jobs: list[ProbeJob],
        cancel_event: threading.Event,
    ) -> None:
        if not jobs:
            return
        workers = max(1, min(settings.probe_workers, len(jobs)))
        logger.info("Analyzing %d files with %d ffprobe workers", len(jobs), workers)

        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="reelindex-probe")
        futures: dict[Future[tuple[dict[str, Any], str | None]], ProbeJob] = {
            executor.submit(self._analyze_file, job.candidate, cancel_event): job for job in jobs
        }
        pending = set(futures)
        try:
            with SessionLocal() as db:
                run = db.get(ScanRun, run_id)
                if not run:
                    return
                completed = 0
                while pending:
                    self._raise_if_cancelled(cancel_event)
                    done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        self._raise_if_cancelled(cancel_event)
                        completed += 1
                        job = futures[future]
                        try:
                            technical, error = future.result()
                        except ProbeCancelled as exc:
                            raise ScanCancelled(str(exc)) from exc
                        except Exception as exc:  # Defensive: a single file must not abort the scan.
                            technical, error = {}, str(exc)
                        record = db.get(MediaFile, job.record_id)
                        if record:
                            self._apply_technical(record, technical, error)
                        if error:
                            run.error_count += 1
                        else:
                            run.analyzed_count += 1
                        run.current_item = f"Analyzing · {completed:,}/{len(jobs):,} · {job.filename}"
                        if completed % settings.scan_commit_interval == 0:
                            db.commit()
                db.commit()
        finally:
            cancelled = cancel_event.is_set()
            if cancelled:
                for future in futures:
                    future.cancel()
            # Do not let a stuck network-backed subprocess keep the scan row in
            # "cancelling". ffprobe workers observe cancel_event and clean up in
            # the background, while the scan manager can finish immediately.
            executor.shutdown(wait=not cancelled, cancel_futures=cancelled)

    def _run_poster_jobs(
        self,
        run_id: str,
        jobs: list[PosterJob],
        adapter: Any,
        tmdb_token: str | None,
        cancel_event: threading.Event,
    ) -> None:
        if not jobs:
            return
        workers = max(1, min(settings.poster_workers, len(jobs)))
        logger.info("Fetching %d posters with %d workers", len(jobs), workers)

        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="reelindex-poster")
        futures: dict[Future[PosterResult], PosterJob] = {
            executor.submit(
                self._fetch_poster,
                adapter,
                job.candidate,
                job.destination,
                tmdb_token,
                cancel_event,
            ): job
            for job in jobs
        }
        pending = set(futures)
        try:
            with SessionLocal() as db:
                run = db.get(ScanRun, run_id)
                if not run:
                    return
                completed = 0
                while pending:
                    self._raise_if_cancelled(cancel_event)
                    done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        self._raise_if_cancelled(cancel_event)
                        completed += 1
                        job = futures[future]
                        try:
                            result = future.result()
                        except Exception:
                            logger.exception("Poster enrichment failed for %s", job.title)
                            result = PosterResult(False)
                        movie = db.get(Movie, job.movie_id)
                        if movie and result.found:
                            movie.poster_path = str(job.destination)
                            if not movie.overview and result.overview:
                                movie.overview = result.overview
                            if result.tmdb_id:
                                try:
                                    metadata = json.loads(movie.metadata_json or "{}")
                                except json.JSONDecodeError:
                                    metadata = {}
                                metadata["tmdb_id"] = result.tmdb_id
                                movie.metadata_json = json.dumps(metadata)
                        run.current_item = f"Posters · {completed:,}/{len(jobs):,} · {job.title}"
                        if completed % settings.scan_commit_interval == 0:
                            db.commit()
                db.commit()
        finally:
            cancelled = cancel_event.is_set()
            if cancelled:
                for future in futures:
                    future.cancel()
            # Poster HTTP calls cannot be force-killed safely from another Python
            # thread. Abandon them on cancellation instead of blocking the scan
            # manager; each worker writes to a temporary file and will discard it.
            executor.shutdown(wait=not cancelled, cancel_futures=cancelled)

    @staticmethod
    def _fetch_poster(
        adapter: Any,
        candidate: Any,
        destination: Path,
        tmdb_token: str | None,
        cancel_event: threading.Event | None = None,
    ) -> PosterResult:
        if cancel_event and cancel_event.is_set():
            return PosterResult(False)

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.stem}-{uuid.uuid4().hex}.tmp{destination.suffix}"
        )

        def discard_temporary() -> None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

        def commit_temporary() -> bool:
            if cancel_event and cancel_event.is_set():
                discard_temporary()
                return False
            try:
                if not temporary.exists() or temporary.stat().st_size == 0:
                    return False
                os.replace(temporary, destination)
                return True
            except OSError:
                return False

        def fetch_with_adapter() -> bool:
            discard_temporary()
            if cancel_event and cancel_event.is_set():
                return False
            return bool(adapter.fetch_poster(candidate, temporary)) and commit_temporary()

        try:
            local_poster = candidate.metadata.get("origin") == "filesystem" and bool(candidate.poster_ref)
            if local_poster:
                if fetch_with_adapter():
                    return PosterResult(True)
                if cancel_event and cancel_event.is_set():
                    return PosterResult(False)

            try:
                if destination.exists() and destination.stat().st_size > 100:
                    return PosterResult(True)
            except OSError:
                pass

            if fetch_with_adapter():
                return PosterResult(True)
            if cancel_event and cancel_event.is_set():
                return PosterResult(False)

            if tmdb_token:
                tmdb = TmdbClient(tmdb_token)
                result = tmdb.find_movie(candidate.title, candidate.year)
                if cancel_event and cancel_event.is_set():
                    return PosterResult(False)
                if result:
                    discard_temporary()
                    if tmdb.download_poster(result.get("poster_path"), temporary) and commit_temporary():
                        return PosterResult(True, overview=result.get("overview"), tmdb_id=result.get("id"))
            return PosterResult(False)
        finally:
            discard_temporary()

    def _fill_missing_runtimes(
        self,
        source_id: str,
        cancel_event: threading.Event | None = None,
    ) -> None:
        with SessionLocal() as db:
            movies = db.scalars(
                select(Movie)
                .options(selectinload(Movie.files))
                .where(Movie.source_id == source_id, Movie.active.is_(True))
            ).all()
            changed = False
            for index, movie in enumerate(movies, start=1):
                if cancel_event and index % 100 == 0:
                    self._raise_if_cancelled(cancel_event)
                if movie.runtime_seconds:
                    continue
                durations = [item.duration_seconds for item in movie.files if item.active and item.duration_seconds]
                if durations:
                    movie.runtime_seconds = max(durations)
                    changed = True
            if changed:
                db.commit()

    @staticmethod
    def _has_server_technical(technical: dict[str, Any]) -> bool:
        if not technical:
            return False
        useful = (
            "container",
            "duration_seconds",
            "video_codec",
            "width",
            "height",
            "resolution_label",
            "video_bitrate",
            "audio_codec",
            "audio_channels",
        )
        return any(technical.get(key) not in (None, "") for key in useful)

    @staticmethod
    def _analyze_file(
        file_candidate: Any,
        cancel_event: threading.Event | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        if cancel_event and cancel_event.is_set():
            raise ProbeCancelled("ffprobe cancelled")
        # Server metadata is preferred so a Plex/Jellyfin path mapping does not cause
        # a second, much slower pass over every network media file.
        if ScanManager._has_server_technical(file_candidate.technical):
            return file_candidate.technical, None
        if file_candidate.local_path:
            technical, error = probe_media(file_candidate.local_path, cancel_event)
            if technical:
                return technical, error
            return {}, error
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


scan_manager = ScanManager()
