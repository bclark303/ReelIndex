from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9-]{1,80}$")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScanEventStore:
    """Append-only JSONL event log used by the live scan console.

    Event files deliberately live outside SQLite so worker threads can emit
    progress without contending with the inventory transaction. The byte-offset
    cursor lets the browser request only new lines on each poll.
    """

    def __init__(self, directory: Path | None = None):
        self.directory = directory or (settings.data_dir / "scan-events")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _path(self, run_id: str) -> Path:
        if not _SAFE_RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid scan run ID")
        return self.directory / f"{run_id}.jsonl"

    def _lock_for(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    def start_run(self, run_id: str, retain: int = 100) -> None:
        """Create a fresh event file and prune the oldest completed-run logs."""
        path = self._path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_for(run_id):
            path.write_bytes(b"")
        files = sorted(
            (item for item in self.directory.glob("*.jsonl") if item != path),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in files[max(retain - 1, 0):]:
            old.unlink(missing_ok=True)

    def append(
        self,
        run_id: str,
        level: str,
        stage: str,
        message: str,
        **details: Any,
    ) -> None:
        event = {
            "timestamp": _utc_iso(),
            "level": level,
            "stage": stage,
            "message": " ".join(str(message).splitlines()).strip(),
        }
        clean_details = {key: value for key, value in details.items() if value is not None}
        if clean_details:
            event["details"] = clean_details
        encoded = (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        path = self._path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_for(run_id):
            with path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()

    def read(
        self,
        run_id: str,
        cursor: int = 0,
        limit: int = 300,
        tail: bool = False,
    ) -> dict[str, Any]:
        path = self._path(run_id)
        limit = min(max(int(limit), 1), 1000)
        cursor = max(int(cursor), 0)
        if not path.exists():
            return {"events": [], "next_cursor": 0, "has_more": False}

        size = path.stat().st_size
        if cursor > size:
            cursor = 0

        if tail and cursor == 0:
            raw_lines = path.read_bytes().splitlines()[-limit:]
            events: list[dict[str, Any]] = []
            for raw in raw_lines:
                try:
                    events.append(json.loads(raw.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            return {"events": events, "next_cursor": size, "has_more": False}

        events = []
        with path.open("rb") as handle:
            handle.seek(cursor)
            for _ in range(limit):
                raw = handle.readline()
                if not raw:
                    break
                try:
                    events.append(json.loads(raw.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    events.append(
                        {
                            "timestamp": _utc_iso(),
                            "level": "warning",
                            "stage": "log",
                            "message": "A malformed scan-log entry was skipped",
                        }
                    )
            next_cursor = handle.tell()

        return {
            "events": events,
            "next_cursor": next_cursor,
            "has_more": next_cursor < size,
        }

    def clear_all(self, directory: Path | None = None) -> tuple[int, int]:
        target = directory or self.directory
        target.mkdir(parents=True, exist_ok=True)
        files = 0
        total_bytes = 0
        for path in target.glob("*.jsonl"):
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass
            path.unlink(missing_ok=True)
            files += 1
        if target == self.directory:
            with self._locks_guard:
                self._locks.clear()
        return files, total_bytes


scan_event_store = ScanEventStore()
