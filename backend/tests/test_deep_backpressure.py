import threading
import time
from pathlib import Path
from types import SimpleNamespace

import app.services.scanner as scanner_module
from app.services.deep_queue import DeepQueueStore
from app.services.scanner import ProbeJob, ScanManager


class FakeEventStore:
    def __init__(self):
        self.events = []

    def append(self, run_id, level, stage, message, **details):
        self.events.append((run_id, level, stage, message, details))


class FakeDB:
    def __init__(self, run, records):
        self.run = run
        self.records = records

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, record_id):
        if model is scanner_module.ScanRun:
            return self.run
        return self.records.get(record_id)

    def commit(self):
        pass


def build_jobs(total: int, suffix: str = ".mkv"):
    jobs = [
        ProbeJob(
            record_id=f"file-{index}",
            filename=f"Movie {index}{suffix}",
            candidate=SimpleNamespace(filename=f"Movie {index}{suffix}", local_path=f"Movie {index}{suffix}"),
        )
        for index in range(total)
    ]
    records = {
        job.record_id: SimpleNamespace(
            probe_json=None,
            probe_error=None,
            container=None,
            duration_seconds=None,
            video_codec=None,
            width=None,
            height=None,
            resolution_label=None,
            video_bitrate=None,
            audio_codec=None,
            audio_channels=None,
            audio_languages=None,
        )
        for job in jobs
    }
    return jobs, records


def configure(monkeypatch, tmp_path, run_id, jobs, records, run, events):
    store = DeepQueueStore(tmp_path / "queues")
    store.create(
        run_id=run_id,
        source_id="source",
        record_ids=[job.record_id for job in jobs],
        scope="failed",
        total_files=len(jobs),
    )
    monkeypatch.setattr(scanner_module, "deep_queue_store", store)
    monkeypatch.setattr(scanner_module, "scan_event_store", events)
    monkeypatch.setattr(scanner_module, "SessionLocal", lambda: FakeDB(run, records))
    monkeypatch.setattr(scanner_module.settings, "probe_workers", 4)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_pause_after_timeouts", 6)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_ramp_successes", 4)
    return store


def timeout_result():
    return (
        {
            "analysis_status": "deferred",
            "analysis_mode": "deep",
            "analysis_source": "filesystem-fallback",
        },
        "ffprobe standard timed out after 4 seconds",
    )


def success_result():
    return (
        {
            "analysis_status": "complete",
            "analysis_mode": "deep",
            "analysis_source": "ffprobe-standard",
            "container": "matroska",
            "video_codec": "h264",
        },
        None,
    )


def test_unreachable_source_pauses_after_bounded_timeouts(monkeypatch, tmp_path):
    run_id = "run-unreachable"
    jobs, records = build_jobs(100)
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    events = FakeEventStore()
    store = configure(monkeypatch, tmp_path, run_id, jobs, records, run, events)
    calls = []

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit, attempt_count=0):
        assert probe_circuit is None
        calls.append(candidate.filename)
        time.sleep(0.005)
        return timeout_result()

    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))

    result = ScanManager()._run_probe_jobs(
        run_id, jobs, threading.Event(), "deep", verbose=True, persistent_queue=True
    )

    # Matroska starts at two workers, then reduces to one and pauses after
    # six serial timeouts. The bounded queue therefore touches only eight files.
    assert len(calls) == 8
    assert result["paused"] is True
    assert result["deferred"] == len(calls)
    assert result["remaining"] == len(jobs)
    assert store.info(run_id)["queue_remaining"] == len(jobs)
    messages = [message for _, _, _, message, _ in events.events]
    assert any("reducing deep-scan concurrency" in message for message in messages)
    assert any("consecutive serial timeouts" in message for message in messages)
    assert not any("waiting 2.0s" in message for message in messages)


def test_isolated_timeouts_rotate_without_recovery_waits(monkeypatch, tmp_path):
    run_id = "run-isolated"
    total = 40
    jobs, records = build_jobs(total)
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    events = FakeEventStore()
    store = configure(monkeypatch, tmp_path, run_id, jobs, records, run, events)
    lock = threading.Lock()
    calls = 0
    timeout_calls = {1, 2, 3, 4, 10, 17, 25, 34}

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit, attempt_count=0):
        nonlocal calls
        assert probe_circuit is None
        with lock:
            calls += 1
            number = calls
        time.sleep(0.003)
        return timeout_result() if number in timeout_calls else success_result()

    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))

    result = ScanManager()._run_probe_jobs(
        run_id, jobs, threading.Event(), "deep", verbose=True, persistent_queue=True
    )

    assert calls == total
    assert result["succeeded"] == total - len(timeout_calls)
    assert result["deferred"] == len(timeout_calls)
    assert result["remaining"] == len(timeout_calls)
    assert store.info(run_id)["queue_remaining"] == len(timeout_calls)
    messages = [message for _, _, _, message, _ in events.events]
    assert not any("waiting 2.0s" in message for message in messages)
    assert not any("consecutive serial timeouts" in message for message in messages)


def test_concurrency_recovers_after_healthy_streak(monkeypatch, tmp_path):
    run_id = "run-ramp"
    total = 30
    jobs, records = build_jobs(total)
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    events = FakeEventStore()
    configure(monkeypatch, tmp_path, run_id, jobs, records, run, events)
    lock = threading.Lock()
    calls = 0

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit, attempt_count=0):
        nonlocal calls
        with lock:
            calls += 1
            number = calls
        time.sleep(0.003)
        return timeout_result() if number <= 4 else success_result()

    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))

    result = ScanManager()._run_probe_jobs(
        run_id, jobs, threading.Event(), "deep", verbose=True, persistent_queue=True
    )

    assert calls == total
    assert result["succeeded"] == total - 4
    assert result["deferred"] == 4
    assert result["worker_reductions"] >= 1
    assert result["worker_increases"] >= 1
    messages = [message for _, _, stage, message, _ in events.events if stage == "ffprobe"]
    assert any("reducing deep-scan concurrency" in message for message in messages)
    assert any("increasing" in message and "concurrency" in message for message in messages)


def test_deep_queue_prioritizes_fast_containers_and_lower_attempts(monkeypatch, tmp_path):
    run_id = "run-priority"
    jobs = [
        ProbeJob("retry-mp4", "Retry.mp4", SimpleNamespace(filename="Retry.mp4", local_path="Retry.mp4"), 1),
        ProbeJob("new-mkv", "New.mkv", SimpleNamespace(filename="New.mkv", local_path="New.mkv"), 0),
        ProbeJob("new-mp4", "New.mp4", SimpleNamespace(filename="New.mp4", local_path="New.mp4"), 0),
        ProbeJob("new-avi", "New.avi", SimpleNamespace(filename="New.avi", local_path="New.avi"), 0),
    ]
    records = {
        job.record_id: SimpleNamespace(
            probe_json=None,
            probe_error=None,
            container=None,
            duration_seconds=None,
            video_codec=None,
            width=None,
            height=None,
            resolution_label=None,
            video_bitrate=None,
            audio_codec=None,
            audio_channels=None,
            audio_languages=None,
        )
        for job in jobs
    }
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    events = FakeEventStore()
    configure(monkeypatch, tmp_path, run_id, jobs, records, run, events)
    monkeypatch.setattr(scanner_module.settings, "probe_workers", 1)
    order = []

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit, attempt_count=0):
        order.append((candidate.filename, attempt_count))
        return success_result()

    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))
    ScanManager()._run_probe_jobs(
        run_id, jobs, threading.Event(), "deep", verbose=True, persistent_queue=True
    )

    assert order == [
        ("New.mp4", 0),
        ("New.avi", 0),
        ("New.mkv", 0),
        ("Retry.mp4", 1),
    ]


def test_matroska_group_never_exceeds_two_workers(monkeypatch, tmp_path):
    run_id = "run-matroska-cap"
    jobs, records = build_jobs(20, ".mkv")
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    events = FakeEventStore()
    configure(monkeypatch, tmp_path, run_id, jobs, records, run, events)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_matroska_workers", 2)
    lock = threading.Lock()
    active = 0
    maximum = 0

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit, attempt_count=0):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return success_result()

    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))
    result = ScanManager()._run_probe_jobs(
        run_id, jobs, threading.Event(), "deep", verbose=True, persistent_queue=True
    )

    assert result["succeeded"] == len(jobs)
    assert maximum == 2
    messages = [message for _, _, stage, message, _ in events.events if stage == "deep-queue"]
    assert any("matroska" in message and "2 workers" in message for message in messages)


def test_deep_attempt_count_excludes_quick_scan_history():
    quick = '{"_reelindex":{"mode":"quick","attempt_count":7}}'
    old_deep = '{"_reelindex":{"mode":"deep","attempt_count":2}}'
    explicit = '{"_reelindex":{"mode":"quick","attempt_count":9,"deep_attempt_count":3}}'

    assert ScanManager._deep_attempt_count(quick) == 0
    assert ScanManager._deep_attempt_count(old_deep) == 1
    assert ScanManager._deep_attempt_count(explicit) == 3
