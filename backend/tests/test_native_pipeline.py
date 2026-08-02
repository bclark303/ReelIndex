import json
import struct
from pathlib import Path

import app.services.probe as probe_module
from app.services.container_native import NativeSample, parse_iso_bmff


def atom(kind: str, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, kind.encode("latin-1")) + payload


def fullbox(body: bytes) -> bytes:
    return b"\0\0\0\0" + body


def sample_mp4(with_cover: bool = False) -> bytes:
    video = bytearray(78)
    struct.pack_into(">H", video, 24, 1280)
    struct.pack_into(">H", video, 26, 720)
    audio = bytearray(28)
    struct.pack_into(">H", audio, 16, 2)
    struct.pack_into(">I", audio, 24, 48000 << 16)

    def track(handler: bytes, entry: bytes) -> bytes:
        mdhd = atom("mdhd", fullbox(struct.pack(">IIIIHH", 0, 0, 1000, 5000, 0x15C7, 0)))
        hdlr = atom("hdlr", fullbox(struct.pack(">I4s", 0, handler) + b"\0" * 12))
        stsd = atom("stsd", fullbox(struct.pack(">I", 1) + entry))
        return atom("trak", atom("mdia", mdhd + hdlr + atom("minf", atom("stbl", stsd))))

    mvhd = atom("mvhd", fullbox(struct.pack(">IIII", 0, 0, 1000, 5000) + b"\0" * 80))
    metadata = b""
    if with_cover:
        jpeg = b"\xff\xd8\xff" + b"cover" * 30
        data = atom("data", b"\0" * 8 + jpeg)
        metadata = atom("udta", atom("meta", b"\0" * 4 + atom("ilst", atom("covr", data))))
    return atom("ftyp", b"isom\0\0\0\0") + atom(
        "moov",
        mvhd + track(b"vide", atom("avc1", bytes(video))) + track(b"soun", atom("mp4a", bytes(audio))) + metadata,
    )


def test_probe_media_native_mp4_avoids_ffprobe(monkeypatch, tmp_path):
    source = tmp_path / "Movie.mp4"
    source.write_bytes(b"source")
    staged = tmp_path / "sample.mp4"
    staged.write_bytes(sample_mp4())

    def fake_stage(path, head_limit, tail_limit, timeout, cancel_event=None):
        assert path == source
        return staged, staged.stat().st_size, 0, 0.01, None

    def fail_ffprobe(*args, **kwargs):
        raise AssertionError("ffprobe should not run for complete native MP4 metadata")

    monkeypatch.setattr(probe_module, "_stage_container_sample", fake_stage)
    monkeypatch.setattr(probe_module, "_run_hidden", fail_ffprobe)
    result, error = probe_module.probe_media(
        source,
        profile="standard",
        native_container=True,
        source_size_bytes=10_000_000,
    )
    assert error is None
    assert result["probe_transport"] == "native-mp4"
    assert result["video_codec"] == "h264"
    assert result["audio_codec"] == "aac"
    assert not staged.exists()


def test_mp4_embedded_cover_is_extracted_from_covr():
    payload = sample_mp4(with_cover=True)
    result = parse_iso_bmff(NativeSample(head=payload, source_size=len(payload)), ".mp4")
    cover = result["_embedded_cover"]
    assert cover["mime"] == "image/jpeg"
    assert cover["data"].startswith(b"\xff\xd8\xff")


def test_native_failure_falls_back_to_ffprobe(monkeypatch, tmp_path):
    source = tmp_path / "Broken.mp4"
    source.write_bytes(b"broken")
    staged = tmp_path / "sample.mp4"
    staged.write_bytes(b"not an mp4 header" * 100)

    def fake_stage(path, head_limit, tail_limit, timeout, cancel_event=None):
        staged.write_bytes(b"not an mp4 header" * 100)
        return staged, staged.stat().st_size, 0, 0.01, None

    def fake_run(command, timeout, cancel_event=None):
        payload = {
            "format": {"format_name": "mov,mp4", "duration": "5"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2},
            ],
        }
        return probe_module.subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(probe_module, "_stage_container_sample", fake_stage)
    monkeypatch.setattr(probe_module, "_run_hidden", fake_run)
    result, error = probe_module.probe_media(source, native_container=True, source_size_bytes=10_000_000)
    assert error is None
    assert result["video_codec"] == "h264"
    assert result["probe_transport"].endswith("ffprobe")
