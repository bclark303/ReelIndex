import threading

import pytest

from app.services.probe import ProbeCancelled
from app.services.scanner import ScanCancelled, ScanManager
from app.sources.base import FileCandidate


def test_raise_if_cancelled():
    event = threading.Event()
    event.set()
    with pytest.raises(ScanCancelled):
        ScanManager._raise_if_cancelled(event)


def test_analyze_file_stops_before_probe_when_cancelled(monkeypatch):
    monkeypatch.setattr(
        "app.services.scanner.probe_media",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ffprobe should not start")),
    )
    candidate = FileCandidate(
        source_file_id="1",
        path="movie.mkv",
        filename="movie.mkv",
        local_path=None,
    )
    event = threading.Event()
    event.set()

    with pytest.raises(ProbeCancelled):
        ScanManager._analyze_file(candidate, event)


def test_hidden_process_can_be_cancelled():
    import sys
    import time

    from app.services.probe import _run_hidden

    event = threading.Event()
    timer = threading.Timer(0.15, event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ProbeCancelled):
            _run_hidden([sys.executable, "-c", "import time; time.sleep(10)"], 20, event)
    finally:
        timer.cancel()
    assert time.monotonic() - started < 2
