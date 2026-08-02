from pathlib import Path

import app.services.scanner as scanner_module
from app.services.scanner import ScanManager
from app.sources.base import FileCandidate


def candidate() -> FileCandidate:
    return FileCandidate(
        source_file_id="file-1",
        path="X:/Movies/Test.mkv",
        filename="Test.mkv",
        local_path=Path("X:/Movies/Test.mkv"),
    )


def complete_quick_result():
    return {
        "container": "matroska",
        "duration_seconds": 7200.0,
        "video_codec": "hevc",
        "width": 3840,
        "height": 2160,
        "resolution_label": "4K",
        "video_bitrate": 10_000_000,
        "audio_codec": "eac3",
        "audio_channels": 6,
        "audio_languages": "en",
        "raw": {"media": {"track": []}},
    }


def test_quick_scan_never_runs_ffprobe_when_mediainfo_succeeds(monkeypatch):
    monkeypatch.setattr(scanner_module, "analyze_media_quick", lambda *_: (complete_quick_result(), None))

    def forbidden_probe(*_args, **_kwargs):
        raise AssertionError("ffprobe should not run during a successful quick scan")

    monkeypatch.setattr(scanner_module, "probe_media", forbidden_probe)
    result, error = ScanManager._analyze_file(candidate(), mode="quick")

    assert error is None
    assert result["analysis_source"] == "mediainfo"
    assert result["analysis_mode"] == "quick"


def test_deep_scan_uses_standard_ffprobe_without_mediainfo(monkeypatch):
    def forbidden_mediainfo(*_args, **_kwargs):
        raise AssertionError("Deep analysis should not pay the MediaInfo SMB timeout first")

    monkeypatch.setattr(scanner_module, "analyze_media_quick", forbidden_mediainfo)
    monkeypatch.setattr(
        scanner_module,
        "probe_media",
        lambda *_args, profile="standard", **_kwargs: (complete_quick_result() | {"probe_profile": profile}, None),
    )

    result, error = ScanManager._analyze_file(candidate(), mode="deep")

    assert error is None
    assert result["analysis_source"] == "ffprobe-standard"
    assert result["analysis_mode"] == "deep"
    assert result["analysis_profile"] == "standard"


def test_deep_scan_escalates_only_after_partial_standard_success(monkeypatch):
    calls = []

    def probe(*_args, profile="standard", **_kwargs):
        calls.append(profile)
        if profile == "standard":
            result = complete_quick_result()
            result["audio_channels"] = None
            return result, None
        return {"audio_channels": 8, "audio_codec": "truehd", "raw": {"streams": []}}, None

    monkeypatch.setattr(scanner_module, "probe_media", probe)
    result, error = ScanManager._analyze_file(candidate(), mode="deep")

    assert error is None
    assert calls == ["standard", "extended"]
    assert result["analysis_source"] == "ffprobe-extended"
    assert result["analysis_profile"] == "extended"
    assert result["audio_channels"] == 8
    assert result["audio_codec"] == "eac3"


def test_deep_timeout_is_deferred_without_extended_retry(monkeypatch):
    calls = []

    def timeout(*_args, profile="standard", **_kwargs):
        calls.append(profile)
        return {}, "ffprobe standard timed out after 12 seconds"

    monkeypatch.setattr(scanner_module, "probe_media", timeout)
    result, error = ScanManager._analyze_file(candidate(), mode="deep")

    assert calls == ["standard"]
    assert error and "timed out" in error
    assert result["analysis_status"] == "deferred"


def test_quick_cache_is_reused_but_deep_scan_upgrades_it():
    quick_payload = '{"_reelindex":{"source":"mediainfo","mode":"quick"},"raw":{}}'
    deep_payload = '{"_reelindex":{"source":"mediainfo","mode":"deep"},"raw":{}}'
    legacy_ffprobe_payload = '{"streams":[],"format":{}}'

    assert ScanManager._cached_analysis_satisfies(quick_payload, "quick")
    assert not ScanManager._cached_analysis_satisfies(quick_payload, "deep")
    assert ScanManager._cached_analysis_satisfies(deep_payload, "deep")
    assert ScanManager._cached_analysis_satisfies(legacy_ffprobe_payload, "deep")


def test_quick_scan_never_runs_ffprobe_when_mediainfo_fails(monkeypatch):
    monkeypatch.setattr(scanner_module, "analyze_media_quick", lambda *_: ({}, "MediaInfo timed out after 8 seconds"))

    def forbidden_probe(*_args, **_kwargs):
        raise AssertionError("ffprobe must not run during Quick scan fallback")

    monkeypatch.setattr(scanner_module, "probe_media", forbidden_probe)
    result, error = ScanManager._analyze_file(candidate(), mode="quick")

    assert error is None
    assert result["analysis_source"] == "filesystem-fallback"
    assert result["analysis_mode"] == "quick"
    assert result["container"] == "matroska"
    assert "timed out" in result["analysis_warning"]


def test_mediainfo_circuit_breaker_skips_later_quick_jobs(monkeypatch):
    calls = {"count": 0}

    def timeout(*_args, **_kwargs):
        calls["count"] += 1
        return {}, "MediaInfo timed out after 8 seconds"

    monkeypatch.setattr(scanner_module, "analyze_media_quick", timeout)
    circuit = scanner_module.AnalyzerCircuitBreaker("MediaInfo", threshold=2)

    ScanManager._analyze_file(candidate(), mode="quick", mediainfo_circuit=circuit)
    ScanManager._analyze_file(candidate(), mode="quick", mediainfo_circuit=circuit)
    result, error = ScanManager._analyze_file(candidate(), mode="quick", mediainfo_circuit=circuit)

    assert calls["count"] == 2
    assert error is None
    assert result["analysis_source"] == "filesystem-fallback"


def test_circuit_breaker_caps_simultaneous_timeout_attempts(monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    calls = {"count": 0}
    lock = threading.Lock()

    def timeout(*_args, **_kwargs):
        with lock:
            calls["count"] += 1
        time.sleep(0.03)
        return {}, "MediaInfo timed out after 8 seconds"

    monkeypatch.setattr(scanner_module, "analyze_media_quick", timeout)
    circuit = scanner_module.AnalyzerCircuitBreaker("MediaInfo", threshold=4)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                ScanManager._analyze_file,
                candidate(),
                None,
                "quick",
                None,
                False,
                circuit,
            )
            for _ in range(20)
        ]
        [future.result() for future in futures]

    assert calls["count"] == 4


def test_deep_scope_selection_uses_cached_failure_and_missing_fields():
    from types import SimpleNamespace
    from app.models import MediaFile

    record = MediaFile(
        movie_id="movie",
        source_file_id="file",
        path="Movie.mkv",
        filename="Movie.mkv",
        fingerprint="same",
        container="matroska",
        duration_seconds=7200,
        video_codec="hevc",
        width=3840,
        height=2160,
        resolution_label="4K",
        audio_codec="eac3",
        audio_channels=6,
        probe_json='{"_reelindex":{"mode":"deep","source":"ffprobe-standard","status":"complete"}}',
    )
    candidate_obj = SimpleNamespace(filename="Movie.2160p.HDR10.mkv")

    assert not ScanManager._should_queue_deep(record, candidate_obj, "incomplete", True)
    assert ScanManager._should_queue_deep(record, candidate_obj, "4k", True)
    assert ScanManager._should_queue_deep(record, candidate_obj, "all", True)

    record.probe_error = "ffprobe standard timed out"
    record.probe_json = '{"_reelindex":{"mode":"deep","status":"deferred"}}'
    assert ScanManager._should_queue_deep(record, candidate_obj, "failed", True)

    record.probe_error = None
    record.audio_channels = None
    assert ScanManager._should_queue_deep(record, candidate_obj, "missing", True)
