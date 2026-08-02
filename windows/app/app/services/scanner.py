from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import reveal_config
from app.models import MediaFile, Movie, ScanRun, Source
from app.services.deep_queue import deep_queue_store
from app.services.media_utils import sort_title
from app.services.mediainfo import MediaInfoCancelled, analyze_media_quick
from app.services.probe import ProbeCancelled, probe_media
from app.services.scan_events import scan_event_store
from app.services.runtime_settings import runtime_settings
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


class AnalyzerCircuitBreaker:
    """Bound analyzer attempts and stop after repeated timeouts.

    ``begin_attempt`` reserves one of the timeout budget slots. This prevents a
    worker that just timed out from immediately launching another network probe
    while the remaining workers are still timing out. A four-worker scan now
    performs at most four doomed attempts instead of seven or more.
    """

    def __init__(self, name: str, threshold: int = 4):
        self.name = name
        self.threshold = max(1, threshold)
        self._timeouts = 0
        self._in_flight = 0
        self._disabled = False
        self._lock = threading.Lock()

    def begin_attempt(self) -> bool:
        with self._lock:
            if self._disabled or self._timeouts + self._in_flight >= self.threshold:
                return False
            self._in_flight += 1
            return True

    def available(self) -> bool:
        with self._lock:
            return not self._disabled and self._timeouts + self._in_flight < self.threshold

    def record_success(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._timeouts = 0

    def release_attempt(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def record_error(self, error: str | None) -> bool:
        """Release an attempt and report a transition to the disabled state."""
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            if not error or "timed out" not in error.lower():
                return False
            if self._disabled:
                return False
            self._timeouts += 1
            if self._timeouts >= self.threshold:
                self._disabled = True
                return True
        return False


class ScanManager:
    def __init__(self):
        self._active: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    DEEP_SCOPES = {"incomplete", "failed", "missing", "4k", "all"}

    def start(self, source_id: str, mode: str = "quick", scope: str = "incomplete") -> str:
        if mode not in {"quick", "deep"}:
            raise ValueError("Scan mode must be quick or deep")
        if scope not in self.DEEP_SCOPES:
            raise ValueError("Unsupported deep-scan scope")
        if mode == "quick":
            scope = "incomplete"
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
        scan_event_store.start_run(run_id)
        scan_event_store.append(
            run_id,
            "info",
            "queue",
            f"{mode.title()} scan queued" + (f" · {scope}" if mode == "deep" else ""),
            source_id=source_id,
            mode=mode,
            scope=scope,
        )
        self._launch(self._run_scan, source_id, run_id, mode, scope)
        return run_id

    def resume(self, run_id: str) -> str:
        manifest = deep_queue_store.load(run_id)
        if not manifest or not manifest.get("pending"):
            raise ValueError("No resumable deep-analysis queue exists")
        source_id = str(manifest.get("source_id") or "")
        with self._lock:
            if source_id in self._active:
                return self._active[source_id]
            with SessionLocal() as db:
                source = db.get(Source, source_id)
                run = db.get(ScanRun, run_id)
                if not source or not run:
                    raise ValueError("Source or scan run no longer exists")
                run.status = "queued"
                run.current_item = f"Resuming deep analysis · {len(manifest.get('pending') or []):,} files remaining"
                run.completed_at = None
                run.error_message = None
                db.commit()
            self._active[source_id] = run_id
            self._cancel_events[run_id] = threading.Event()
        scan_event_store.append(
            run_id,
            "info",
            "queue",
            f"Resuming deep-analysis queue with {len(manifest.get('pending') or []):,} files",
            mode="deep",
            scope=manifest.get("scope") or "incomplete",
        )
        self._launch(self._run_resume, source_id, run_id)
        return run_id

    @staticmethod
    def _launch(operation: Any, *args: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(operation, *args))
        except RuntimeError:
            threading.Thread(target=operation, args=args, daemon=True).start()

    def active_run(self, source_id: str) -> str | None:
        with self._lock:
            return self._active.get(source_id)

    def active_runs(self) -> dict[str, str]:
        """Return a snapshot of source IDs and their active scan run IDs."""
        with self._lock:
            return dict(self._active)

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
            if not cancel_event:
                return False
            cancel_event.set()
        scan_event_store.append(run_id, "warning", "cancel", "Cancellation requested by user")
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

    def _run_scan(self, source_id: str, run_id: str, mode: str = "quick", scope: str = "incomplete") -> None:
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
        if cancel_event is None:
            cancel_event = threading.Event()
        try:
            self._execute_scan(source_id, run_id, cancel_event, mode, scope)
        except ScanCancelled:
            queue_info = deep_queue_store.info(run_id)
            message = "Deep analysis paused; queue can be resumed" if queue_info["resumable"] else "Scan cancelled"
            scan_event_store.append(run_id, "warning", "complete", message)
            with SessionLocal() as db:
                run = db.get(ScanRun, run_id)
                if run:
                    run.status = "cancelled"
                    run.current_item = "Deep analysis paused" if queue_info["resumable"] else "Scan cancelled"
                    run.completed_at = utcnow()
                    db.commit()
        except Exception as exc:
            logger.exception("Scan failed for source %s", source_id)
            scan_event_store.append(run_id, "error", "complete", f"Scan failed: {exc}")
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

    def _run_resume(self, source_id: str, run_id: str) -> None:
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
        if cancel_event is None:
            cancel_event = threading.Event()
        try:
            self._execute_resume(source_id, run_id, cancel_event)
        except ScanCancelled:
            scan_event_store.append(run_id, "warning", "complete", "Deep analysis paused; queue can be resumed")
            with SessionLocal() as db:
                run = db.get(ScanRun, run_id)
                if run:
                    run.status = "cancelled"
                    run.current_item = "Deep analysis paused"
                    run.completed_at = utcnow()
                    db.commit()
        except Exception as exc:
            logger.exception("Deep-analysis resume failed for source %s", source_id)
            scan_event_store.append(run_id, "error", "complete", f"Deep-analysis resume failed: {exc}")
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

    def _execute_scan(
        self, source_id: str, run_id: str, cancel_event: threading.Event, mode: str, scope: str = "incomplete"
    ) -> None:
        self._raise_if_cancelled(cancel_event)
        scan_started = time.perf_counter()
        verbose = runtime_settings.verbose_scan_logging()
        with SessionLocal() as db:
            source = db.get(Source, source_id)
            run = db.get(ScanRun, run_id)
            if not source or not run:
                raise ValueError("Source or scan run no longer exists")
            run.status = "running"
            run.current_item = f"{mode.title()} scan · discovering movies…"
            db.commit()
            config = reveal_config(json.loads(source.config_json or "{}"))
            adapter = create_adapter(source.type, source.url_or_path, source.library_id, config)
            source_name = source.name
            source_type = source.type

        scan_event_store.append(
            run_id,
            "info",
            "start",
            f"Starting {mode} scan for {source_name}" + (f" · scope={scope}" if mode == "deep" else ""),
            source_type=source_type,
            mode=mode,
            scope=scope,
            verbose=verbose,
            discovery_workers=getattr(adapter, "discovery_workers", settings.discovery_workers),
            probe_workers=settings.probe_workers,
            poster_workers=settings.poster_workers,
        )

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
            scan_event_store.append(
                run_id,
                "info",
                "discovery",
                f"Discovered {movie_count:,} movies / {file_count:,} files",
                location=label,
            )

        discovery_started = time.perf_counter()
        candidates = self._run_cancellable_call(
            lambda: adapter.scan(progress=discovery_progress),
            cancel_event,
            "discovery",
        )
        self._raise_if_cancelled(cancel_event)
        total_files = sum(len(movie.files) for movie in candidates)
        discovery_elapsed = time.perf_counter() - discovery_started
        scan_event_store.append(
            run_id,
            "success",
            "discovery",
            f"Discovery complete: {len(candidates):,} movies and {total_files:,} files in {discovery_elapsed:.2f}s",
            elapsed_ms=round(discovery_elapsed * 1000),
            files_per_second=round(total_files / discovery_elapsed, 2) if discovery_elapsed else None,
            workers=getattr(adapter, "discovery_workers", 1),
        )
        tmdb_token = config.get("tmdb_token") or settings.tmdb_api_token
        probe_jobs: list[ProbeJob] = []
        poster_jobs: list[PosterJob] = []

        # Phase 1: make the complete inventory visible quickly. Technical probing and
        # poster enrichment are deliberately deferred until after this transaction.
        index_started = time.perf_counter()
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
                if verbose or movie_index == 1 or movie_index == len(candidates) or movie_index % 100 == 0:
                    scan_event_store.append(
                        run_id,
                        "debug" if verbose else "info",
                        "index",
                        f"Indexing {candidate.title}" if verbose else f"Indexing progress: {movie_index:,}/{len(candidates):,} movies",
                        movie=movie_index,
                        total_movies=len(candidates),
                        files=len(candidate.files),
                    )
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
                    same_fingerprint = file_record.fingerprint == file_candidate.fingerprint
                    cached_valid = (
                        same_fingerprint
                        and not file_record.probe_error
                        and self._cached_analysis_satisfies(file_record.probe_json, mode)
                    )
                    file_record.path = file_candidate.path
                    file_record.filename = file_candidate.filename
                    file_record.size_bytes = file_candidate.size_bytes
                    file_record.modified_ts = file_candidate.modified_ts
                    file_record.fingerprint = file_candidate.fingerprint
                    file_record.edition = file_candidate.edition
                    file_record.active = True

                    if self._has_server_technical(file_candidate.technical):
                        # Plex/Jellyfin/Emby already provide the fields needed by the
                        # competition. Do not reopen every media file over the network.
                        server_technical = dict(file_candidate.technical)
                        server_technical["analysis_source"] = "media-server"
                        server_technical["analysis_mode"] = "deep"
                        server_technical["analysis_status"] = "complete"
                        server_technical["analysis_version"] = settings.deep_analysis_version
                        self._apply_technical(file_record, server_technical, None)
                        run.analyzed_count += 1
                        scan_event_store.append(
                            run_id,
                            "success",
                            "analyze",
                            f"Used media-server metadata: {file_candidate.filename}",
                        )
                    elif mode == "deep" and self._should_queue_deep(
                        file_record, file_candidate, scope, same_fingerprint
                    ):
                        probe_jobs.append(ProbeJob(file_record.id, file_candidate.filename, file_candidate))
                    elif mode == "quick" and not cached_valid:
                        probe_jobs.append(ProbeJob(file_record.id, file_candidate.filename, file_candidate))
                    else:
                        run.cached_count += 1
                        if verbose:
                            scan_event_store.append(
                                run_id,
                                "debug",
                                "cache",
                                f"Cache hit: {file_candidate.filename}",
                            )

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
                f"{mode} analysis for {len(probe_jobs):,} changed files"
            )
            db.commit()

        index_elapsed = time.perf_counter() - index_started
        scan_event_store.append(
            run_id,
            "success",
            "index",
            f"Indexing complete in {index_elapsed:.2f}s: {len(probe_jobs):,} changed files, {len(poster_jobs):,} poster jobs",
            elapsed_ms=round(index_elapsed * 1000),
            changed_files=len(probe_jobs),
            cached_files=total_files - len(probe_jobs),
        )

        self._raise_if_cancelled(cancel_event)
        if mode == "deep" and probe_jobs:
            deep_queue_store.create(
                run_id=run_id,
                source_id=source_id,
                record_ids=[job.record_id for job in probe_jobs],
                scope=scope,
                total_files=total_files,
            )
            scan_event_store.append(
                run_id,
                "info",
                "deep-queue",
                f"Persistent deep-analysis queue created with {len(probe_jobs):,} files",
                queue_total=len(probe_jobs),
                scope=scope,
            )
        self._run_probe_jobs(
            run_id, probe_jobs, cancel_event, mode, verbose=verbose, persistent_queue=(mode == "deep")
        )
        if mode == "deep" and not cancel_event.is_set():
            deep_queue_store.remove(run_id)
        self._raise_if_cancelled(cancel_event)
        self._fill_missing_runtimes(source_id, cancel_event)
        self._raise_if_cancelled(cancel_event)
        self._run_poster_jobs(run_id, poster_jobs, adapter, tmdb_token, cancel_event, verbose=verbose)
        self._raise_if_cancelled(cancel_event)

        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if not run:
                return
            run.status = "completed"
            run.current_item = None
            run.completed_at = utcnow()
            db.commit()
        scan_event_store.append(
            run_id,
            "success",
            "complete",
            f"Scan completed in {time.perf_counter() - scan_started:.2f}s",
            elapsed_ms=round((time.perf_counter() - scan_started) * 1000),
        )

    def _execute_resume(
        self, source_id: str, run_id: str, cancel_event: threading.Event
    ) -> None:
        manifest = deep_queue_store.load(run_id)
        if not manifest:
            raise ValueError("Deep-analysis queue is missing")
        pending_ids = [str(item) for item in manifest.get("pending") or []]
        if not pending_ids:
            deep_queue_store.remove(run_id)
            return

        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if not run:
                raise ValueError("Scan run no longer exists")
            records = db.scalars(
                select(MediaFile).where(
                    MediaFile.id.in_(pending_ids),
                    MediaFile.active.is_(True),
                )
            ).all()
            by_id = {record.id: record for record in records}
            jobs: list[ProbeJob] = []
            for record_id in pending_ids:
                record = by_id.get(record_id)
                if not record:
                    continue
                candidate = SimpleNamespace(
                    filename=record.filename,
                    path=record.path,
                    local_path=Path(record.path),
                    size_bytes=record.size_bytes,
                    modified_ts=record.modified_ts,
                    fingerprint=record.fingerprint,
                    edition=record.edition,
                    technical={},
                )
                jobs.append(ProbeJob(record.id, record.filename, candidate))
            deep_queue_store.keep_only(run_id, [job.record_id for job in jobs])
            run.status = "running"
            run.current_item = f"Resuming deep analysis · 0/{len(jobs):,}"
            db.commit()

        scan_event_store.append(
            run_id,
            "info",
            "deep-queue",
            f"Resumed persistent queue with {len(jobs):,} remaining files",
            queue_remaining=len(jobs),
            scope=manifest.get("scope") or "incomplete",
        )
        self._run_probe_jobs(
            run_id, jobs, cancel_event, "deep", verbose=runtime_settings.verbose_scan_logging(), persistent_queue=True
        )
        self._raise_if_cancelled(cancel_event)
        deep_queue_store.remove(run_id)
        self._fill_missing_runtimes(source_id, cancel_event)
        with SessionLocal() as db:
            run = db.get(ScanRun, run_id)
            if run:
                run.status = "completed"
                run.current_item = None
                run.completed_at = utcnow()
                db.commit()
        scan_event_store.append(run_id, "success", "complete", "Resumed deep-analysis queue completed")

    def _run_probe_jobs(
        self,
        run_id: str,
        jobs: list[ProbeJob],
        cancel_event: threading.Event,
        mode: str,
        verbose: bool = False,
        persistent_queue: bool = False,
    ) -> None:
        if not jobs:
            scan_event_store.append(run_id, "info", "analyze", "No changed files require analysis")
            return
        stage_started = time.perf_counter()
        workers = max(1, min(settings.probe_workers, len(jobs)))
        logger.info("Running %s analysis for %d files with %d workers", mode, len(jobs), workers)
        mediainfo_circuit = AnalyzerCircuitBreaker("MediaInfo", threshold=workers)
        ffprobe_circuit = AnalyzerCircuitBreaker("ffprobe", threshold=workers)

        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="reelindex-probe")
        scan_event_store.append(
            run_id,
            "info",
            "analyze",
            f"Analyzing {len(jobs):,} changed files with {workers} workers",
            mode=mode,
        )
        futures: dict[Future[tuple[dict[str, Any], str | None]], ProbeJob] = {
            executor.submit(
                self._analyze_file,
                job.candidate,
                cancel_event,
                mode,
                lambda level, stage, message, run_id=run_id: scan_event_store.append(
                    run_id, level, stage, message
                ),
                verbose,
                mediainfo_circuit,
                ffprobe_circuit,
            ): job
            for job in jobs
        }
        submitted_at = {future: time.perf_counter() for future in futures}
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
                        queued_elapsed = time.perf_counter() - submitted_at.get(future, time.perf_counter())
                        try:
                            technical, error = future.result()
                        except (ProbeCancelled, MediaInfoCancelled) as exc:
                            raise ScanCancelled(str(exc)) from exc
                        except Exception as exc:  # Defensive: a single file must not abort the scan.
                            technical, error = {}, str(exc)
                        record = db.get(MediaFile, job.record_id)
                        if record:
                            self._apply_technical(record, technical, error)
                        if error:
                            run.error_count += 1
                            outcome = "deferred" if "timed out" in error.lower() or "deferred" in error.lower() else "failed"
                            scan_event_store.append(
                                run_id,
                                "warning" if outcome == "deferred" else "error",
                                "analyze",
                                f"Analysis {outcome} for {job.filename}: {error}",
                                outcome=outcome,
                            )
                        else:
                            outcome = "succeeded"
                            run.analyzed_count += 1
                            source = technical.get("analysis_source") or "analyzer"
                            scan_event_store.append(
                                run_id,
                                "success",
                                "analyze",
                                f"Analyzed {job.filename} with {source}",
                            )
                        if persistent_queue:
                            queue_state = deep_queue_store.mark_complete(run_id, job.record_id, outcome)
                        else:
                            queue_state = None
                        if verbose:
                            scan_event_store.append(
                                run_id,
                                "debug",
                                "timing",
                                f"Analysis job finished in {queued_elapsed:.3f}s: {job.filename}",
                                elapsed_ms=round(queued_elapsed * 1000),
                            )
                        elapsed_stage = max(time.perf_counter() - stage_started, 0.001)
                        average_seconds = elapsed_stage / completed
                        remaining = len(jobs) - completed
                        eta_seconds = round(average_seconds * remaining)
                        run.current_item = (
                            f"Deep analysis · {completed:,}/{len(jobs):,} · "
                            f"{remaining:,} remaining · ETA {self._format_eta(eta_seconds)} · {job.filename}"
                            if mode == "deep"
                            else f"Analyzing · {completed:,}/{len(jobs):,} · {job.filename}"
                        )
                        if mode == "deep" and (completed == 1 or completed % 10 == 0 or completed == len(jobs)):
                            scan_event_store.append(
                                run_id,
                                "info",
                                "deep-queue",
                                f"Deep analysis progress: {completed:,}/{len(jobs):,} · {remaining:,} remaining · ETA {self._format_eta(eta_seconds)}",
                                completed=completed,
                                remaining=remaining,
                                total=len(jobs),
                                average_ms=round(average_seconds * 1000),
                                eta_seconds=eta_seconds,
                                queue_remaining=len(queue_state.get("pending") or []) if queue_state else remaining,
                            )
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
        if not cancel_event.is_set():
            elapsed = time.perf_counter() - stage_started
            scan_event_store.append(
                run_id,
                "success",
                "analyze",
                f"Analysis stage complete in {elapsed:.2f}s ({len(jobs):,} files)",
                elapsed_ms=round(elapsed * 1000),
                files_per_second=round(len(jobs) / elapsed, 2) if elapsed else None,
                workers=workers,
            )

    def _run_poster_jobs(
        self,
        run_id: str,
        jobs: list[PosterJob],
        adapter: Any,
        tmdb_token: str | None,
        cancel_event: threading.Event,
        verbose: bool = False,
    ) -> None:
        if not jobs:
            scan_event_store.append(run_id, "info", "poster", "No poster work is required")
            return
        stage_started = time.perf_counter()
        workers = max(1, min(settings.poster_workers, len(jobs)))
        logger.info("Fetching %d posters with %d workers", len(jobs), workers)
        scan_event_store.append(
            run_id,
            "info",
            "poster",
            f"Resolving {len(jobs):,} posters with {workers} workers",
        )

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
        submitted_at = {future: time.perf_counter() for future in futures}
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
                        queued_elapsed = time.perf_counter() - submitted_at.get(future, time.perf_counter())
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
                            scan_event_store.append(
                                run_id,
                                "success",
                                "poster",
                                f"Poster ready: {job.title}",
                            )
                        elif not result.found and verbose:
                            scan_event_store.append(
                                run_id,
                                "debug",
                                "poster",
                                f"No poster found: {job.title}",
                            )
                        if verbose:
                            scan_event_store.append(
                                run_id,
                                "debug",
                                "timing",
                                f"Poster job finished in {queued_elapsed:.3f}s: {job.title}",
                                elapsed_ms=round(queued_elapsed * 1000),
                                found=result.found,
                            )
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
        if not cancel_event.is_set():
            elapsed = time.perf_counter() - stage_started
            scan_event_store.append(
                run_id,
                "success",
                "poster",
                f"Poster stage complete in {elapsed:.2f}s ({len(jobs):,} jobs)",
                elapsed_ms=round(elapsed * 1000),
                jobs_per_second=round(len(jobs) / elapsed, 2) if elapsed else None,
                workers=workers,
            )

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
    def _format_eta(seconds: int | float) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}s"
        minutes, remaining = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {remaining:02d}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m"

    @staticmethod
    def _analysis_marker(probe_json: str | None) -> dict[str, Any]:
        if not probe_json:
            return {}
        try:
            payload = json.loads(probe_json)
        except json.JSONDecodeError:
            return {}
        marker = payload.get("_reelindex", {}) if isinstance(payload, dict) else {}
        return marker if isinstance(marker, dict) else {}

    @staticmethod
    def _should_queue_deep(
        record: MediaFile, file_candidate: Any, scope: str, same_fingerprint: bool
    ) -> bool:
        marker = ScanManager._analysis_marker(record.probe_json)
        status = str(marker.get("status") or "").lower()
        missing = ScanManager._needs_deep_fallback(
            {
                "container": record.container,
                "duration_seconds": record.duration_seconds,
                "video_codec": record.video_codec,
                "width": record.width,
                "height": record.height,
                "audio_codec": record.audio_codec,
                "audio_channels": record.audio_channels,
            }
        )
        if scope == "all":
            return True
        if scope == "failed":
            return same_fingerprint and (bool(record.probe_error) or status in {"failed", "deferred"})
        if scope == "missing":
            return missing
        if scope == "4k":
            label = str(record.resolution_label or "").lower()
            name = str(file_candidate.filename or "").lower()
            return label == "4k" or bool(re.search(r"(?:2160p|\b4k\b|hdr10|dolby[ ._-]?vision|\bdv\b)", name))
        # Incomplete/changed is the default competition-safe deep scan.
        return (
            not same_fingerprint
            or bool(record.probe_error)
            or missing
            or not ScanManager._cached_analysis_satisfies(record.probe_json, "deep")
            or status in {"failed", "deferred"}
        )

    @staticmethod
    def _cached_analysis_satisfies(probe_json: str, mode: str) -> bool:
        if not probe_json:
            return False
        if mode == "quick":
            return True
        try:
            payload = json.loads(probe_json)
        except json.JSONDecodeError:
            # Older ReelIndex records were created by a full ffprobe pass.
            return True
        marker = payload.get("_reelindex", {}) if isinstance(payload, dict) else {}
        if not marker:
            # Pre-v1.2 records came from the old full ffprobe-only pipeline.
            return True
        cached_mode = marker.get("mode")
        source = marker.get("source")
        status = marker.get("status")
        if status in {"failed", "deferred"}:
            return False
        return cached_mode in {"deep", "server"} or source in {"ffprobe", "media-server", "mediainfo+ffprobe", "ffprobe-standard", "ffprobe-extended"}

    @staticmethod
    def _needs_deep_fallback(technical: dict[str, Any]) -> bool:
        required = (
            "container",
            "duration_seconds",
            "video_codec",
            "width",
            "height",
            "audio_codec",
            "audio_channels",
        )
        return any(technical.get(key) in (None, "") for key in required)

    @staticmethod
    def _merge_technical(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        merged = dict(primary)
        for key, value in fallback.items():
            if key == "raw":
                continue
            if merged.get(key) in (None, "") and value not in (None, ""):
                merged[key] = value
        merged["raw"] = {
            "mediainfo": primary.get("raw"),
            "ffprobe": fallback.get("raw"),
        }
        return merged

    @staticmethod
    def _basic_file_technical(file_candidate: Any, mode: str, warning: str | None = None) -> dict[str, Any]:
        """Return zero-I/O metadata so a Quick scan can cache an analyzer failure."""
        suffix = Path(file_candidate.filename).suffix.lower().lstrip(".")
        container_map = {
            "mkv": "matroska",
            "webm": "webm",
            "mp4": "mp4",
            "m4v": "mp4",
            "mov": "mov",
            "avi": "avi",
            "ts": "mpegts",
            "m2ts": "mpegts",
            "mpg": "mpeg",
            "mpeg": "mpeg",
            "wmv": "asf",
        }
        filename = file_candidate.filename.lower()
        resolution = None
        for pattern, label in (
            (r"(?:^|[^0-9])2160p(?:[^0-9]|$)|(?:^|[^0-9])4k(?:[^a-z0-9]|$)", "4K"),
            (r"(?:^|[^0-9])1080p(?:[^0-9]|$)", "1080p"),
            (r"(?:^|[^0-9])720p(?:[^0-9]|$)", "720p"),
            (r"(?:^|[^0-9])576p(?:[^0-9]|$)", "576p"),
            (r"(?:^|[^0-9])480p(?:[^0-9]|$)", "480p"),
        ):
            if re.search(pattern, filename):
                resolution = label
                break
        return {
            "container": container_map.get(suffix, suffix or None),
            "resolution_label": resolution,
            "analysis_source": "filesystem-fallback",
            "analysis_mode": mode,
            "analysis_warning": warning,
            "raw": {"warning": warning, "inferred_from_filename": True},
        }

    @staticmethod
    def _analyze_file(
        file_candidate: Any,
        cancel_event: threading.Event | None = None,
        mode: str = "quick",
        event_callback: Any | None = None,
        verbose: bool = False,
        mediainfo_circuit: AnalyzerCircuitBreaker | None = None,
        ffprobe_circuit: AnalyzerCircuitBreaker | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        def event(level: str, stage: str, message: str) -> None:
            if event_callback:
                event_callback(level, stage, message)

        analysis_started = time.perf_counter()

        def finish(technical: dict[str, Any], error: str | None):
            if verbose:
                elapsed = time.perf_counter() - analysis_started
                event("debug", "timing", f"Total analysis {elapsed:.3f}s: {file_candidate.filename}")
            return technical, error

        if cancel_event and cancel_event.is_set():
            raise ProbeCancelled("media analysis cancelled")
        if ScanManager._has_server_technical(file_candidate.technical):
            event("info", "analyze", f"Using media-server metadata: {file_candidate.filename}")
            technical = dict(file_candidate.technical)
            technical["analysis_source"] = "media-server"
            technical["analysis_mode"] = "deep"
            return finish(technical, None)
        if not file_candidate.local_path:
            return finish({}, "Media file is not locally accessible and the server supplied no technical metadata")

        # Quick scan stays intentionally lightweight: MediaInfo gets one bounded
        # header read and there is never an ffprobe escalation.
        if mode == "quick":
            quick: dict[str, Any] = {}
            quick_error: str | None = None
            media_attempt = mediainfo_circuit is None or mediainfo_circuit.begin_attempt()
            if media_attempt:
                event("info", "mediainfo", f"Reading headers: {file_candidate.filename}")
                mediainfo_started = time.perf_counter()
                try:
                    quick, quick_error = analyze_media_quick(file_candidate.local_path, cancel_event)
                except BaseException:
                    if mediainfo_circuit:
                        mediainfo_circuit.release_attempt()
                    raise
                if verbose:
                    elapsed = time.perf_counter() - mediainfo_started
                    event("debug", "timing", f"MediaInfo {elapsed:.3f}s: {file_candidate.filename}")
                if quick:
                    if mediainfo_circuit:
                        mediainfo_circuit.record_success()
                    quick.update({
                        "analysis_source": "mediainfo",
                        "analysis_mode": "quick",
                        "analysis_status": "complete",
                        "analysis_version": settings.deep_analysis_version,
                    })
                    return finish(quick, None)
                if mediainfo_circuit and mediainfo_circuit.record_error(quick_error):
                    event(
                        "warning",
                        "mediainfo",
                        f"MediaInfo timed out on {mediainfo_circuit.threshold} files; skipping it for the rest of this scan",
                    )
            else:
                quick_error = "MediaInfo skipped after repeated timeouts in this scan"
            warning = quick_error or "MediaInfo returned incomplete metadata"
            event("warning", "analyze", f"Quick metadata fallback: {file_candidate.filename} ({warning})")
            technical = ScanManager._basic_file_technical(file_candidate, mode, warning)
            technical.update({
                "analysis_status": "complete",
                "analysis_version": settings.deep_analysis_version,
            })
            return finish(technical, None)

        # Deep analysis goes straight to a bounded, minimal ffprobe query. This
        # avoids paying the known MediaInfo SMB timeout before every deep probe.
        ffprobe_attempt = ffprobe_circuit is None or ffprobe_circuit.begin_attempt()
        if not ffprobe_attempt:
            error = "Deep analysis deferred after repeated ffprobe timeouts in this scan"
            technical = ScanManager._basic_file_technical(file_candidate, mode, error)
            technical.update({
                "analysis_status": "deferred",
                "analysis_version": settings.deep_analysis_version,
                "analysis_profile": "standard",
            })
            return finish(technical, error)

        event("info", "ffprobe", f"Standard deep probe: {file_candidate.filename}")
        standard_started = time.perf_counter()
        try:
            standard, standard_error = probe_media(
                file_candidate.local_path, cancel_event, profile="standard"
            )
        except BaseException:
            if ffprobe_circuit:
                ffprobe_circuit.release_attempt()
            raise
        if verbose:
            elapsed = time.perf_counter() - standard_started
            event("debug", "timing", f"ffprobe standard {elapsed:.3f}s: {file_candidate.filename}")

        if not standard:
            disabled = ffprobe_circuit.record_error(standard_error) if ffprobe_circuit else False
            if disabled:
                event(
                    "warning",
                    "ffprobe",
                    f"ffprobe timed out on {ffprobe_circuit.threshold} files; deferring the remaining deep queue",
                )
            status = "deferred" if standard_error and "timed out" in standard_error.lower() else "failed"
            technical = ScanManager._basic_file_technical(file_candidate, mode, standard_error)
            technical.update({
                "analysis_status": status,
                "analysis_version": settings.deep_analysis_version,
                "analysis_profile": "standard",
            })
            return finish(technical, standard_error)

        if ffprobe_circuit:
            ffprobe_circuit.record_success()
        standard.update({
            "analysis_source": "ffprobe-standard",
            "analysis_mode": "deep",
            "analysis_status": "complete",
            "analysis_version": settings.deep_analysis_version,
            "analysis_profile": "standard",
        })
        if not ScanManager._needs_deep_fallback(standard):
            return finish(standard, None)

        # Only a successful-but-incomplete standard probe is allowed to escalate.
        # A timeout is never followed by another longer network probe.
        extended_attempt = ffprobe_circuit is None or ffprobe_circuit.begin_attempt()
        if not extended_attempt:
            standard["analysis_warning"] = "Extended probe skipped after repeated timeouts"
            return finish(standard, None)
        event("info", "ffprobe", f"Extended deep probe for missing fields: {file_candidate.filename}")
        extended_started = time.perf_counter()
        try:
            extended, extended_error = probe_media(
                file_candidate.local_path, cancel_event, profile="extended"
            )
        except BaseException:
            if ffprobe_circuit:
                ffprobe_circuit.release_attempt()
            raise
        if verbose:
            elapsed = time.perf_counter() - extended_started
            event("debug", "timing", f"ffprobe extended {elapsed:.3f}s: {file_candidate.filename}")
        if extended:
            if ffprobe_circuit:
                ffprobe_circuit.record_success()
            technical = ScanManager._merge_technical(standard, extended)
            technical.update({
                "analysis_source": "ffprobe-extended",
                "analysis_mode": "deep",
                "analysis_status": "complete",
                "analysis_version": settings.deep_analysis_version,
                "analysis_profile": "extended",
            })
            return finish(technical, None)

        if ffprobe_circuit:
            ffprobe_circuit.record_error(extended_error)
        standard["analysis_warning"] = extended_error
        return finish(standard, None)

    @staticmethod
    def _apply_technical(record: MediaFile, technical: dict[str, Any], error: str | None) -> None:
        previous = ScanManager._analysis_marker(record.probe_json)
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
        status = technical.get("analysis_status") or (
            "deferred" if error and "timed out" in error.lower() else "failed" if error else "complete"
        )
        payload = {
            "_reelindex": {
                "source": technical.get("analysis_source") or "unknown",
                "mode": technical.get("analysis_mode") or "unknown",
                "status": status,
                "version": technical.get("analysis_version") or settings.deep_analysis_version,
                "profile": technical.get("analysis_profile") or technical.get("probe_profile"),
                "warning": technical.get("analysis_warning"),
                "attempt_count": int(previous.get("attempt_count") or 0) + 1,
                "attempted_at": utcnow().isoformat(),
            },
            "extended": technical.get("extended") or {},
            "raw": technical.get("raw", technical),
        }
        record.probe_json = json.dumps(payload, default=str)
        record.probe_error = error


scan_manager = ScanManager()
