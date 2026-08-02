from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings


class RuntimeSettingsStore:
    """Small persistent settings store for options that can change without restart."""

    DEFAULTS: dict[str, Any] = {
        "verbose_scan_logging": False,
    }

    def __init__(self, path: Path | None = None):
        self.path = path or (settings.data_dir / "runtime-settings.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def get_all(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {}
            try:
                if self.path.exists():
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        payload = loaded
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = {}

            result = dict(self.DEFAULTS)
            result.update({key: payload[key] for key in self.DEFAULTS if key in payload})

            env_verbose = os.environ.get("REELINDEX_SCAN_VERBOSE")
            if env_verbose is not None:
                result["verbose_scan_logging"] = env_verbose.strip().lower() in {
                    "1", "true", "yes", "on",
                }
            return result

    def update(self, **changes: Any) -> dict[str, Any]:
        with self._lock:
            current = self.get_all()
            for key, value in changes.items():
                if key not in self.DEFAULTS:
                    continue
                if key == "verbose_scan_logging":
                    current[key] = bool(value)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
            return current

    def verbose_scan_logging(self) -> bool:
        return bool(self.get_all().get("verbose_scan_logging", False))


runtime_settings = RuntimeSettingsStore()
