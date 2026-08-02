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
