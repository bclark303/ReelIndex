import json
from pathlib import Path

import app.services.probe as probe_module


def test_standard_probe_uses_minimal_entries_and_bounded_limits(monkeypatch):
    captured = {}

    def fake_run(command, timeout, cancel_event=None):
        captured["command"] = command
        captured["timeout"] = timeout
        payload = {
            "format": {"format_name": "matroska", "duration": "7200"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160},
                {"codec_type": "audio", "codec_name": "eac3", "channels": 6},
            ],
        }
        return probe_module.subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(probe_module, "_run_hidden", fake_run)
    result, error = probe_module.probe_media(Path("Movie.mkv"), profile="standard")

    assert error is None
    assert "-show_entries" in captured["command"]
    assert "-show_streams" not in captured["command"]
    assert "-probesize" in captured["command"]
    assert captured["timeout"] == probe_module.settings.deep_probe_standard_seconds
    assert result["video_codec"] == "hevc"
    assert result["probe_profile"] == "standard"


def test_extended_probe_collects_hdr_and_stream_counts(monkeypatch):
    def fake_run(command, timeout, cancel_event=None):
        payload = {
            "format": {"format_name": "matroska", "duration": "7200"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "color_transfer": "smpte2084",
                    "color_primaries": "bt2020",
                },
                {"codec_type": "audio", "codec_name": "truehd", "channels": 8},
                {"codec_type": "subtitle", "codec_name": "subrip"},
            ],
            "chapters": [{"start_time": "0", "end_time": "60"}],
        }
        return probe_module.subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(probe_module, "_run_hidden", fake_run)
    result, error = probe_module.probe_media(Path("Movie.mkv"), profile="extended")

    assert error is None
    assert result["extended"]["hdr_format"] == "HDR10/PQ"
    assert result["extended"]["subtitle_stream_count"] == 1
    assert result["extended"]["chapter_count"] == 1


def test_standard_probe_accepts_timeout_override(monkeypatch):
    captured = {}

    def fake_run(command, timeout, cancel_event=None):
        captured["timeout"] = timeout
        payload = {
            "format": {"format_name": "matroska", "duration": "120"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}],
        }
        return probe_module.subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(probe_module, "_run_hidden", fake_run)
    result, error = probe_module.probe_media(
        Path("Movie.mkv"), profile="standard", timeout_override=4
    )

    assert error is None
    assert captured["timeout"] == 4
    assert result["video_codec"] == "h264"


def test_standard_probe_uses_smaller_matroska_header_window(monkeypatch):
    captured = {}

    def fake_run(command, timeout, cancel_event=None):
        captured["command"] = command
        payload = {
            "format": {"format_name": "matroska", "duration": "120"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2},
            ],
        }
        return probe_module.subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(probe_module, "_run_hidden", fake_run)
    result, error = probe_module.probe_media(Path("Movie.mkv"), profile="standard")

    assert error is None
    command = captured["command"]
    assert command[command.index("-probesize") + 1] == "4M"
    assert command[command.index("-analyzeduration") + 1] == "2M"
    assert result["container"] == "matroska"


def test_matroska_probe_uses_local_staged_header(monkeypatch, tmp_path):
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"source")
    staged = tmp_path / "staged.mkv"
    staged.write_bytes(b"header" * 2048)
    captured = {}

    def fake_stage(path, byte_limit, timeout, cancel_event=None):
        assert path == source
        captured["stage_limit"] = byte_limit
        captured["stage_timeout"] = timeout
        return staged, staged.stat().st_size, 0.125, None

    def fake_run(command, timeout, cancel_event=None):
        captured["command"] = command
        captured["probe_timeout"] = timeout
        payload = {
            "format": {"format_name": "matroska", "duration": "100"},
            "streams": [
                {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160},
                {"codec_type": "audio", "codec_name": "truehd", "channels": 8},
            ],
        }
        return probe_module.subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(probe_module, "_stage_header_copy", fake_stage)
    monkeypatch.setattr(probe_module, "_run_hidden", fake_run)
    result, error = probe_module.probe_media(
        source,
        profile="standard",
        stage_matroska=True,
        stage_bytes=2 * 1024 * 1024,
        source_size_bytes=1_000_000_000,
    )

    assert error is None
    assert captured["command"][-1] == str(staged)
    assert captured["probe_timeout"] == probe_module.settings.deep_probe_local_seconds
    assert result["probe_transport"] == "local-matroska-header"
    assert result["probe_diagnostics"]["staging_seconds"] == 0.125
    assert result["video_bitrate"] == 80_000_000
    assert not staged.exists()


def test_non_matroska_probe_does_not_stage(monkeypatch, tmp_path):
    source = tmp_path / "Movie.mp4"
    captured = {}

    def fail_stage(*args, **kwargs):
        raise AssertionError("MP4 should not use Matroska staging")

    def fake_run(command, timeout, cancel_event=None):
        captured["command"] = command
        payload = {
            "format": {"format_name": "mov,mp4", "duration": "100"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}],
        }
        return probe_module.subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(probe_module, "_stage_header_copy", fail_stage)
    monkeypatch.setattr(probe_module, "_run_hidden", fake_run)
    result, error = probe_module.probe_media(source, profile="standard", stage_matroska=True)

    assert error is None
    assert captured["command"][-1] == str(source)
    assert "probe_transport" not in result


def test_stage_header_cleanup_on_cancellation(monkeypatch, tmp_path):
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"header")
    monkeypatch.setattr(probe_module.settings, "data_dir", tmp_path / "data")

    def cancelled(*args, **kwargs):
        raise probe_module.ProbeCancelled("cancelled")

    monkeypatch.setattr(probe_module, "_run_hidden", cancelled)
    try:
        probe_module._stage_header_copy(source, 1024, 2)
    except probe_module.ProbeCancelled:
        pass
    else:
        raise AssertionError("expected ProbeCancelled")

    stage_dir = tmp_path / "data" / "probe-stage"
    assert not list(stage_dir.glob("*"))
