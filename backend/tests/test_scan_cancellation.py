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


def test_blocking_discovery_can_be_abandoned_immediately():
    import time

    event = threading.Event()
    timer = threading.Timer(0.15, event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ScanCancelled):
            ScanManager._run_cancellable_call(lambda: time.sleep(10), event, "discovery")
    finally:
        timer.cancel()
    assert time.monotonic() - started < 1.5


def test_cancelled_poster_worker_does_not_replace_cached_poster(tmp_path):
    import time

    from app.sources.base import MovieCandidate

    destination = tmp_path / "poster.jpg"
    destination.write_bytes(b"existing-poster")
    event = threading.Event()

    class SlowAdapter:
        @staticmethod
        def fetch_poster(candidate, target):
            time.sleep(0.25)
            target.write_bytes(b"late-poster")
            return True

    candidate = MovieCandidate(
        source_movie_id="movie",
        title="Movie",
        poster_ref="remote",
        metadata={"origin": "plex"},
    )
    worker = threading.Thread(
        target=ScanManager._fetch_poster,
        args=(SlowAdapter(), candidate, destination, None, event),
    )
    worker.start()
    time.sleep(0.05)
    event.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert destination.read_bytes() == b"existing-poster"
    assert not list(tmp_path.glob(".*.tmp.jpg"))
