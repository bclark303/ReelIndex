from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeepQueueStore:
    """Small persistent manifest store for resumable deep-analysis work.

    Queue manifests intentionally live outside SQLite so no database migration is
    required for upgrades. They contain ReelIndex media-file record IDs and scan
    bookkeeping only; credentials and source configuration are never written.
    """

    def __init__(self, root: Path | None = None):
        self.root = root or (settings.data_dir / "deep-queues")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path_for(self, run_id: str) -> Path:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
        return self.root / f"{safe}.json"

    def create(
        self,
        *,
        run_id: str,
        source_id: str,
        record_ids: list[str],
        scope: str,
        total_files: int,
    ) -> dict[str, Any]:
        now = utcnow_iso()
        payload: dict[str, Any] = {
            "version": 1,
            "run_id": run_id,
            "source_id": source_id,
            "mode": "deep",
            "scope": scope,
            "created_at": now,
            "updated_at": now,
            "total": len(record_ids),
            "source_file_count": total_files,
            "completed": 0,
            "succeeded": 0,
            "failed": 0,
            "deferred": 0,
            "pending": list(record_ids),
        }
        self._write(run_id, payload)
        return payload

    def load(self, run_id: str) -> dict[str, Any] | None:
        path = self.path_for(run_id)
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
                payload = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                return None
        return payload if isinstance(payload, dict) else None

    def info(self, run_id: str) -> dict[str, Any]:
        payload = self.load(run_id)
        if not payload:
            return {
                "resumable": False,
                "queue_remaining": 0,
                "queue_total": 0,
                "scan_mode": None,
                "scan_scope": None,
            }
        pending = payload.get("pending") or []
        return {
            "resumable": bool(pending),
            "queue_remaining": len(pending),
            "queue_total": int(payload.get("total") or len(pending)),
            "scan_mode": payload.get("mode") or "deep",
            "scan_scope": payload.get("scope") or "incomplete",
        }

    def mark_complete(self, run_id: str, record_id: str, outcome: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self.load(run_id)
            if not payload:
                return None
            pending = list(payload.get("pending") or [])
            try:
                pending.remove(record_id)
            except ValueError:
                return payload
            payload["pending"] = pending
            payload["completed"] = int(payload.get("completed") or 0) + 1
            if outcome not in {"succeeded", "failed", "deferred"}:
                outcome = "failed"
            payload[outcome] = int(payload.get(outcome) or 0) + 1
            payload["updated_at"] = utcnow_iso()
            self._write(run_id, payload)
            return payload

    def keep_only(self, run_id: str, record_ids: list[str]) -> dict[str, Any] | None:
        """Replace pending work after reconstruction removes deleted/inactive files."""
        with self._lock:
            payload = self.load(run_id)
            if not payload:
                return None
            payload["pending"] = list(record_ids)
            payload["updated_at"] = utcnow_iso()
            self._write(run_id, payload)
            return payload

    def remove(self, run_id: str) -> None:
        with self._lock:
            try:
                self.path_for(run_id).unlink(missing_ok=True)
            except OSError:
                pass

    def clear_all(self) -> tuple[int, int]:
        files = 0
        total_bytes = 0
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for path in list(self.root.glob("*.json")):
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    pass
                try:
                    path.unlink()
                    files += 1
                except OSError:
                    pass
        return files, total_bytes

    def _write(self, run_id: str, payload: dict[str, Any]) -> None:
        path = self.path_for(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".tmp-{os.getpid()}-{threading.get_ident()}")
        data = json.dumps(payload, indent=2, sort_keys=True)
        with self._lock:
            temporary.write_text(data, encoding="utf-8")
            os.replace(temporary, path)


deep_queue_store = DeepQueueStore()
