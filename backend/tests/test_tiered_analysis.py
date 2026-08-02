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


def test_deep_scan_skips_ffprobe_when_mediainfo_is_complete(monkeypatch):
    monkeypatch.setattr(scanner_module, "analyze_media_quick", lambda *_: (complete_quick_result(), None))

    def forbidden_probe(*_args, **_kwargs):
        raise AssertionError("ffprobe should not run when MediaInfo has all core fields")

    monkeypatch.setattr(scanner_module, "probe_media", forbidden_probe)
    result, error = ScanManager._analyze_file(candidate(), mode="deep")

    assert error is None
    assert result["analysis_source"] == "mediainfo"
    assert result["analysis_mode"] == "deep"


def test_deep_scan_uses_ffprobe_only_for_missing_fields(monkeypatch):
    quick = complete_quick_result()
    quick["audio_channels"] = None
    monkeypatch.setattr(scanner_module, "analyze_media_quick", lambda *_: (quick, None))
    monkeypatch.setattr(
        scanner_module,
        "probe_media",
        lambda *_: ({"audio_channels": 8, "audio_codec": "truehd", "raw": {"streams": []}}, None),
    )

    result, error = ScanManager._analyze_file(candidate(), mode="deep")

    assert error is None
    assert result["analysis_source"] == "mediainfo+ffprobe"
    assert result["analysis_mode"] == "deep"
    assert result["audio_channels"] == 8
    # MediaInfo remains authoritative for fields it already supplied.
    assert result["audio_codec"] == "eac3"


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
