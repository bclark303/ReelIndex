from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import ScanRun, Source
from app.services.scanner import scan_manager

logger = logging.getLogger(__name__)


class ScanScheduler:
    """Small interval scheduler that avoids an external service or writable system cron."""

    def __init__(self):
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="reelindex-scheduler", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)

    def sync(self) -> None:
        # Source changes are stored in SQLite; waking the loop applies them immediately.
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("Scheduled scan check failed")
            self._wake.wait(timeout=60)
            self._wake.clear()

    @staticmethod
    def _tick() -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            sources = db.scalars(
                select(Source).where(
                    Source.enabled.is_(True),
                    Source.schedule_enabled.is_(True),
                )
            ).all()
            due_ids: list[str] = []
            for source in sources:
                last = db.scalar(
                    select(ScanRun)
                    .where(ScanRun.source_id == source.id)
                    .order_by(ScanRun.started_at.desc())
                    .limit(1)
                )
                if last:
                    started_at = last.started_at if last.started_at.tzinfo else last.started_at.replace(tzinfo=timezone.utc)
                    due_at = started_at + timedelta(minutes=source.schedule_minutes)
                else:
                    due_at = now
                if due_at <= now and not scan_manager.active_run(source.id):
                    due_ids.append(source.id)
        for source_id in due_ids:
            try:
                scan_manager.start(source_id)
            except Exception:
                logger.exception("Could not start scheduled scan for %s", source_id)


scan_scheduler = ScanScheduler()
