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
