import threading
import time
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


def test_timeout_circuit_stops_submission_and_preserves_queue(monkeypatch, tmp_path):
    run_id = "run-backpressure"
    total = 100
    jobs = [
        ProbeJob(
            record_id=f"file-{index}",
            filename=f"Movie {index}.mkv",
            candidate=SimpleNamespace(filename=f"Movie {index}.mkv", local_path=f"Movie {index}.mkv"),
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
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    store = DeepQueueStore(tmp_path / "queues")
    store.create(
        run_id=run_id,
        source_id="source",
        record_ids=[job.record_id for job in jobs],
        scope="incomplete",
        total_files=total,
    )
    events = FakeEventStore()
    calls = []

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit):
        assert probe_circuit.begin_attempt()
        calls.append(candidate.filename)
        time.sleep(0.02)
        probe_circuit.record_error("ffprobe standard timed out after 12 seconds")
        return (
            {
                "analysis_status": "deferred",
                "analysis_mode": "deep",
                "analysis_source": "filesystem-fallback",
            },
            "ffprobe standard timed out after 12 seconds",
        )

    monkeypatch.setattr(scanner_module, "deep_queue_store", store)
    monkeypatch.setattr(scanner_module, "scan_event_store", events)
    monkeypatch.setattr(scanner_module, "SessionLocal", lambda: FakeDB(run, records))
    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))
    monkeypatch.setattr(scanner_module.settings, "probe_workers", 4)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_recovery_attempts", 3)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_recovery_delay_seconds", 0)

    result = ScanManager()._run_probe_jobs(
        run_id,
        jobs,
        threading.Event(),
        "deep",
        verbose=True,
        persistent_queue=True,
    )

    assert len(calls) == 7
    assert result["paused"] is True
    assert result["deferred"] == 7
    assert result["remaining"] == total
    assert store.info(run_id)["queue_remaining"] == total
    assert run.error_count == 7
    assert any("paused" in message.lower() for _, _, _, message, _ in events.events)


def test_serial_recovery_continues_after_isolated_timeout_batch(monkeypatch, tmp_path):
    run_id = "run-recovery"
    total = 20
    jobs = [
        ProbeJob(
            record_id=f"file-{index}",
            filename=f"Movie {index}.mkv",
            candidate=SimpleNamespace(filename=f"Movie {index}.mkv", local_path=f"Movie {index}.mkv"),
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
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    store = DeepQueueStore(tmp_path / "queues")
    store.create(
        run_id=run_id,
        source_id="source",
        record_ids=[job.record_id for job in jobs],
        scope="incomplete",
        total_files=total,
    )
    events = FakeEventStore()
    call_lock = threading.Lock()
    calls = 0

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit):
        nonlocal calls
        assert probe_circuit.begin_attempt()
        with call_lock:
            calls += 1
            call_number = calls
        time.sleep(0.01)
        if call_number <= 4:
            probe_circuit.record_error("ffprobe standard timed out after 12 seconds")
            return (
                {
                    "analysis_status": "deferred",
                    "analysis_mode": "deep",
                    "analysis_source": "filesystem-fallback",
                },
                "ffprobe standard timed out after 12 seconds",
            )
        probe_circuit.record_success()
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

    monkeypatch.setattr(scanner_module, "deep_queue_store", store)
    monkeypatch.setattr(scanner_module, "scan_event_store", events)
    monkeypatch.setattr(scanner_module, "SessionLocal", lambda: FakeDB(run, records))
    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))
    monkeypatch.setattr(scanner_module.settings, "probe_workers", 4)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_recovery_attempts", 1)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_recovery_delay_seconds", 0)

    result = ScanManager()._run_probe_jobs(
        run_id,
        jobs,
        threading.Event(),
        "deep",
        verbose=True,
        persistent_queue=True,
    )

    assert calls == total
    assert result["succeeded"] == total - 4
    assert result["deferred"] == 4
    assert result["remaining"] == 4
    assert store.info(run_id)["queue_remaining"] == 4
    assert any("Serial recovery probe succeeded" in message for _, _, _, message, _ in events.events)


def test_multiple_timeout_clusters_reduce_to_serial_and_continue(monkeypatch, tmp_path):
    run_id = "run-multiple-clusters"
    total = 30
    jobs = [
        ProbeJob(
            record_id=f"file-{index}",
            filename=f"Movie {index}.mkv",
            candidate=SimpleNamespace(filename=f"Movie {index}.mkv", local_path=f"Movie {index}.mkv"),
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
    run = SimpleNamespace(error_count=0, analyzed_count=0, current_item=None)
    store = DeepQueueStore(tmp_path / "queues")
    store.create(
        run_id=run_id,
        source_id="source",
        record_ids=[job.record_id for job in jobs],
        scope="failed",
        total_files=total,
    )
    events = FakeEventStore()
    call_lock = threading.Lock()
    calls = 0

    # Mirrors the uploaded v1.3.1 trace: the initial four files time out, a
    # serial canary succeeds, several files complete, then both reduced workers
    # time out. A second canary should succeed and the rest must continue
    # serially instead of pausing the untouched queue.
    timeout_calls = {1, 2, 3, 4, 14, 15}

    def fake_analyze(candidate, cancel_event, mode, callback, verbose, media_circuit, probe_circuit):
        nonlocal calls
        assert probe_circuit.begin_attempt()
        with call_lock:
            calls += 1
            call_number = calls
        time.sleep(0.005)
        if call_number in timeout_calls:
            probe_circuit.record_error("ffprobe standard timed out after 8 seconds")
            return (
                {
                    "analysis_status": "deferred",
                    "analysis_mode": "deep",
                    "analysis_source": "filesystem-fallback",
                },
                "ffprobe standard timed out after 8 seconds",
            )
        probe_circuit.record_success()
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

    monkeypatch.setattr(scanner_module, "deep_queue_store", store)
    monkeypatch.setattr(scanner_module, "scan_event_store", events)
    monkeypatch.setattr(scanner_module, "SessionLocal", lambda: FakeDB(run, records))
    monkeypatch.setattr(ScanManager, "_analyze_file", staticmethod(fake_analyze))
    monkeypatch.setattr(scanner_module.settings, "probe_workers", 4)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_recovery_attempts", 3)
    monkeypatch.setattr(scanner_module.settings, "deep_probe_recovery_delay_seconds", 0)

    result = ScanManager()._run_probe_jobs(
        run_id,
        jobs,
        threading.Event(),
        "deep",
        verbose=True,
        persistent_queue=True,
    )

    assert calls == total
    assert result["succeeded"] == total - len(timeout_calls)
    assert result["deferred"] == len(timeout_calls)
    assert result["remaining"] == len(timeout_calls)
    assert store.info(run_id)["queue_remaining"] == len(timeout_calls)
    recovery_messages = [message for _, _, stage, message, _ in events.events if stage == "ffprobe"]
    assert sum("Serial recovery probe succeeded" in message for message in recovery_messages) >= 2
    assert any("continuing with 1 worker" in message for message in recovery_messages)
