import json
import struct
from pathlib import Path

import app.services.probe as probe_module
from app.services.matroska import parse_matroska_bytes


def _id(value: int) -> bytes:
    width = max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(width, "big")


def _size(value: int) -> bytes:
    if value < 0x7F:
        return bytes([0x80 | value])
    if value < 0x3FFF:
        return (0x4000 | value).to_bytes(2, "big")
    raise ValueError("test element too large")


def _element(element_id: int, payload: bytes) -> bytes:
    return _id(element_id) + _size(len(payload)) + payload


def _uint(value: int, width: int | None = None) -> bytes:
    width = width or max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(width, "big")


def _sample_matroska() -> bytes:
    info = _element(0x2AD7B1, _uint(1_000_000, 3)) + _element(0x4489, struct.pack(">d", 7_264_125.0))
    video = _element(0xB0, _uint(3840, 2)) + _element(0xBA, _uint(2160, 2))
    video_track = b"".join([
        _element(0x83, b"\x01"),
        _element(0x86, b"V_MPEGH/ISO/HEVC"),
        _element(0x23E383, _uint(41_666_666, 4)),
        _element(0xE0, video),
    ])
    audio = _element(0x9F, b"\x08") + _element(0xB5, struct.pack(">d", 48000.0))
    audio_track = b"".join([
        _element(0x83, b"\x02"),
        _element(0x86, b"A_TRUEHD"),
        _element(0x22B59C, b"eng"),
        _element(0xE1, audio),
    ])
    tracks = _element(0xAE, video_track) + _element(0xAE, audio_track)
    segment_payload = _element(0x1549A966, info) + _element(0x1654AE6B, tracks)
    return _element(0x1A45DFA3, b"") + _id(0x18538067) + b"\xff" + segment_payload


def test_native_matroska_parser_extracts_core_metadata():
    result = parse_matroska_bytes(_sample_matroska())

    assert result["container"] == "matroska"
    assert result["duration_seconds"] == 7264.125
    assert result["video_codec"] == "hevc"
    assert result["width"] == 3840
    assert result["height"] == 2160
    assert result["resolution_label"] == "4K"
    assert result["audio_codec"] == "truehd"
    assert result["audio_channels"] == 8.0
    assert result["audio_languages"] == "eng"
    assert round(result["extended"]["frame_rate"], 2) == 24.0


def test_staged_matroska_uses_native_parser_without_ffprobe(monkeypatch, tmp_path):
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"source")
    staged = tmp_path / "header.mkv"
    staged.write_bytes(_sample_matroska())

    def fake_stage(path, byte_limit, timeout, cancel_event=None):
        assert path == source
        return staged, staged.stat().st_size, 0.2, None

    def fail_run(*args, **kwargs):
        raise AssertionError("ffprobe should not run when native Matroska metadata is complete")

    monkeypatch.setattr(probe_module, "_stage_header_copy", fake_stage)
    monkeypatch.setattr(probe_module, "_run_hidden", fail_run)

    result, error = probe_module.probe_media(
        source,
        profile="standard",
        stage_matroska=True,
        stage_bytes=1024 * 1024,
        source_size_bytes=8_000_000_000,
    )

    assert error is None
    assert result["probe_transport"] == "native-matroska-header"
    assert result["video_codec"] == "hevc"
    assert result["audio_codec"] == "truehd"
    assert result["probe_diagnostics"]["local_probe_seconds"] == 0.0
    assert result["video_bitrate"] > 0
    assert not staged.exists()
