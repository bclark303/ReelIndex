from __future__ import annotations

import math
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.services.media_utils import resolution_label


class NativeContainerError(ValueError):
    """Raised when a bounded native sample is not a supported container."""


@dataclass(slots=True)
class NativeSample:
    head: bytes
    tail: bytes = b""
    source_size: int | None = None


VIDEO_CODECS = {
    "avc1": "h264", "avc3": "h264", "h264": "h264", "x264": "h264",
    "hvc1": "hevc", "hev1": "hevc", "hevc": "hevc", "h265": "hevc",
    "av01": "av1", "vp09": "vp9", "vp08": "vp8", "mp4v": "mpeg4",
    "dvhe": "hevc", "dvh1": "hevc", "dva1": "h264", "dvav": "h264",
    "wmv1": "wmv1", "wmv2": "wmv2", "wmv3": "wmv3", "wvc1": "vc1",
    "xvid": "mpeg4", "divx": "mpeg4", "dx50": "mpeg4", "fmp4": "mpeg4",
    "mpg1": "mpeg1video", "mpg2": "mpeg2video", "mpeg": "mpeg2video",
    "mjpg": "mjpeg", "jpeg": "mjpeg", "theo": "theora",
}
AUDIO_CODECS = {
    "mp4a": "aac", "aac ": "aac", "ac-3": "ac3", "dac3": "ac3",
    "ec-3": "eac3", "dec3": "eac3", "ac-4": "ac4", "alac": "alac",
    "opus": "opus", "flac": "flac", "flaC": "flac", ".mp3": "mp3",
    "mp3 ": "mp3", "mp2 ": "mp2", "twos": "pcm_s16be", "sowt": "pcm_s16le",
    "lpcm": "pcm", "wmap": "wmav1", "wma2": "wmav2", "wma3": "wmapro",
}
WAVE_FORMATS = {
    0x0001: "pcm", 0x0002: "adpcm_ms", 0x0050: "mp2", 0x0055: "mp3",
    0x00FF: "aac", 0x0160: "wmav1", 0x0161: "wmav2", 0x0162: "wmapro",
    0x0163: "wmalossless", 0x2000: "ac3", 0x2001: "dts", 0xFFFE: "pcm",
}


def _codec(value: str | bytes | None, audio: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("latin-1", errors="replace")
    text = value.strip("\x00").lower()
    mapping = AUDIO_CODECS if audio else VIDEO_CODECS
    return mapping.get(text, text or None)


def _base_result(container: str, *, duration: float | None = None, source_size: int | None = None) -> dict[str, Any]:
    bitrate = int(source_size * 8 / duration) if source_size and duration and duration > 0 else None
    return {
        "container": container,
        "duration_seconds": duration,
        "video_codec": None,
        "width": None,
        "height": None,
        "resolution_label": None,
        "video_bitrate": bitrate,
        "audio_codec": None,
        "audio_channels": None,
        "audio_languages": None,
        "probe_profile": "standard",
        "extended": {
            "video_profile": None,
            "video_level": None,
            "pixel_format": None,
            "bit_depth": None,
            "frame_rate": None,
            "color_space": None,
            "color_transfer": None,
            "color_primaries": None,
            "hdr_format": None,
            "audio_stream_count": 0,
            "subtitle_stream_count": 0,
            "chapter_count": None,
        },
        "raw": {},
    }


def _finish(result: dict[str, Any], source_size: int | None = None) -> dict[str, Any]:
    result["resolution_label"] = resolution_label(result.get("width"), result.get("height"))
    duration = result.get("duration_seconds")
    if not result.get("video_bitrate") and source_size and duration:
        result["video_bitrate"] = int(source_size * 8 / float(duration))
    if not any(result.get(key) not in (None, "") for key in (
        "duration_seconds", "video_codec", "width", "height", "audio_codec"
    )):
        raise NativeContainerError("Native container parser found no usable technical metadata")
    return result


# ---- ISO Base Media / QuickTime -------------------------------------------------


def _be16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _be32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _be64(data: bytes, offset: int) -> int:
    return struct.unpack_from(">Q", data, offset)[0]


def _atoms(data: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[str, int, int, int]]:
    end = len(data) if end is None else min(len(data), end)
    pos = max(0, start)
    while pos + 8 <= end:
        size = _be32(data, pos)
        kind = data[pos + 4:pos + 8].decode("latin-1", errors="replace")
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = _be64(data, pos + 8)
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        atom_end = pos + size
        if atom_end > end:
            return
        yield kind, pos + header, atom_end, pos
        pos = atom_end


def _find_atoms_recursive(data: bytes, wanted: set[str], start: int = 0, end: int | None = None) -> Iterator[tuple[str, int, int]]:
    containers = {"moov", "trak", "mdia", "minf", "stbl", "udta", "ilst", "edts", "dinf", "mvex"}
    for kind, payload, atom_end, _ in _atoms(data, start, end):
        if kind in wanted:
            yield kind, payload, atom_end
        child_start = payload + 4 if kind == "meta" else payload
        if kind in containers or kind == "meta":
            yield from _find_atoms_recursive(data, wanted, child_start, atom_end)


def _mp4_duration(payload: bytes) -> tuple[int | None, int | None]:
    if len(payload) < 20:
        return None, None
    version = payload[0]
    try:
        if version == 1:
            return _be32(payload, 20), _be64(payload, 24)
        return _be32(payload, 12), _be32(payload, 16)
    except (struct.error, IndexError):
        return None, None


def _mdhd_language(payload: bytes) -> str | None:
    if len(payload) < 24:
        return None
    version = payload[0]
    offset = 32 if version == 1 else 20
    if offset + 2 > len(payload):
        return None
    packed = _be16(payload, offset)
    chars = [((packed >> shift) & 0x1F) + 0x60 for shift in (10, 5, 0)]
    value = bytes(chars).decode("ascii", errors="ignore")
    return value if value.isalpha() else None


def _parse_stsd(data: bytes, start: int, end: int, handler: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if start + 8 > end:
        return result
    count = _be32(data, start + 4)
    pos = start + 8
    entries: list[dict[str, Any]] = []
    for _ in range(count):
        if pos + 8 > end:
            break
        size = _be32(data, pos)
        kind = data[pos + 4:pos + 8].decode("latin-1", errors="replace")
        if size < 8 or pos + size > end:
            break
        payload = pos + 8
        entry: dict[str, Any] = {"type": kind}
        if handler == "vide" and payload + 28 <= pos + size:
            entry["codec"] = _codec(kind)
            entry["width"] = _be16(data, payload + 24)
            entry["height"] = _be16(data, payload + 26)
            entry["bit_depth"] = _be16(data, payload + 74) if payload + 76 <= pos + size else None
            child_start = min(pos + size, payload + 78)
            for child, child_payload, child_end, _ in _atoms(data, child_start, pos + size):
                if child == "colr" and child_payload + 11 <= child_end:
                    method = data[child_payload:child_payload + 4]
                    if method in {b"nclx", b"nclc"}:
                        entry["primaries"] = _be16(data, child_payload + 4)
                        entry["transfer"] = _be16(data, child_payload + 6)
                elif child in {"dvcC", "dvvC", "dvwC"}:
                    entry["hdr_format"] = "Dolby Vision"
            if kind in {"dvhe", "dvh1", "dva1", "dvav"}:
                entry["hdr_format"] = "Dolby Vision"
        elif handler == "soun" and payload + 28 <= pos + size:
            entry["codec"] = _codec(kind, audio=True)
            entry["channels"] = _be16(data, payload + 16)
            entry["bit_depth"] = _be16(data, payload + 18)
            entry["sample_rate"] = _be32(data, payload + 24) / 65536.0
        entries.append(entry)
        pos += size
    result["entries"] = entries
    return result


def _parse_mp4_track(data: bytes, start: int, end: int) -> dict[str, Any]:
    track: dict[str, Any] = {}
    mdia_bounds: tuple[int, int] | None = None
    for kind, payload, atom_end, _ in _atoms(data, start, end):
        if kind == "tkhd" and atom_end - payload >= 8:
            tkhd = data[payload:atom_end]
            if len(tkhd) >= 8:
                track["width"] = _be32(tkhd, len(tkhd) - 8) / 65536.0
                track["height"] = _be32(tkhd, len(tkhd) - 4) / 65536.0
        elif kind == "mdia":
            mdia_bounds = (payload, atom_end)
    if not mdia_bounds:
        return track
    timescale = duration_ticks = None
    stbl_bounds: tuple[int, int] | None = None
    for kind, payload, atom_end, _ in _atoms(data, *mdia_bounds):
        if kind == "mdhd":
            mdhd = data[payload:atom_end]
            timescale, duration_ticks = _mp4_duration(mdhd)
            track["language"] = _mdhd_language(mdhd)
        elif kind == "hdlr" and payload + 12 <= atom_end:
            track["handler"] = data[payload + 8:payload + 12].decode("latin-1", errors="replace")
        elif kind == "minf":
            for child, child_payload, child_end, _ in _atoms(data, payload, atom_end):
                if child == "stbl":
                    stbl_bounds = (child_payload, child_end)
    if timescale and duration_ticks:
        track["duration"] = duration_ticks / timescale
    if stbl_bounds:
        for kind, payload, atom_end, _ in _atoms(data, *stbl_bounds):
            if kind == "stsd":
                track.update(_parse_stsd(data, payload, atom_end, track.get("handler")))
            elif kind == "stts" and payload + 16 <= atom_end and timescale:
                count = _be32(data, payload + 4)
                pos = payload + 8
                samples = ticks = 0
                for _ in range(min(count, 64)):
                    if pos + 8 > atom_end:
                        break
                    sample_count = _be32(data, pos)
                    sample_delta = _be32(data, pos + 4)
                    samples += sample_count
                    ticks += sample_count * sample_delta
                    pos += 8
                if samples and ticks:
                    track["frame_rate"] = timescale * samples / ticks
    return track


def _extract_mp4_cover(data: bytes) -> tuple[bytes, str, str] | None:
    # iTunes-style covr/data atoms. Searching is intentionally bounded to the
    # staged moov sample and validates magic bytes before returning anything.
    for _, covr_start, covr_end in _find_atoms_recursive(data, {"covr"}):
        for kind, payload, atom_end, _ in _atoms(data, covr_start, covr_end):
            if kind != "data" or payload + 8 > atom_end:
                continue
            blob = data[payload + 8:atom_end]
            if blob.startswith(b"\xff\xd8\xff"):
                return blob, "image/jpeg", ".jpg"
            if blob.startswith(b"\x89PNG\r\n\x1a\n"):
                return blob, "image/png", ".png"
    return None


def parse_iso_bmff(sample: NativeSample, suffix: str) -> dict[str, Any]:
    candidates = [sample.head]
    if sample.tail:
        candidates.append(sample.tail)
    moov_data = None
    for data in candidates:
        if any(kind == "moov" for kind, *_ in _atoms(data)):
            moov_data = data
            break
    if moov_data is None:
        # A tail sample can begin before the moov atom; locate a plausible atom.
        for data in candidates:
            position = data.find(b"moov")
            if position >= 4:
                size = _be32(data, position - 4)
                if size >= 8 and position - 4 + size <= len(data):
                    moov_data = data[position - 4:position - 4 + size]
                    break
    if moov_data is None:
        raise NativeContainerError("MP4/QuickTime moov metadata was not found in bounded samples")

    result = _base_result("mov" if suffix == ".mov" else "mp4", source_size=sample.source_size)
    tracks: list[dict[str, Any]] = []
    movie_duration = None
    movie_timescale = None
    for kind, payload, atom_end, _ in _atoms(moov_data):
        if kind != "moov":
            continue
        for child, child_payload, child_end, _ in _atoms(moov_data, payload, atom_end):
            if child == "mvhd":
                movie_timescale, ticks = _mp4_duration(moov_data[child_payload:child_end])
                if movie_timescale and ticks:
                    movie_duration = ticks / movie_timescale
            elif child == "trak":
                tracks.append(_parse_mp4_track(moov_data, child_payload, child_end))
    video_tracks = [track for track in tracks if track.get("handler") == "vide"]
    audio_tracks = [track for track in tracks if track.get("handler") == "soun"]
    subtitle_tracks = [track for track in tracks if track.get("handler") in {"subt", "text", "sbtl", "clcp"}]
    video = video_tracks[0] if video_tracks else {}
    audio = audio_tracks[0] if audio_tracks else {}
    video_entry = (video.get("entries") or [{}])[0]
    audio_entry = (audio.get("entries") or [{}])[0]
    duration = movie_duration or max((track.get("duration") or 0 for track in tracks), default=0) or None
    result.update({
        "duration_seconds": duration,
        "video_codec": video_entry.get("codec"),
        "width": int(video_entry.get("width") or video.get("width") or 0) or None,
        "height": int(video_entry.get("height") or video.get("height") or 0) or None,
        "audio_codec": audio_entry.get("codec"),
        "audio_channels": float(audio_entry["channels"]) if audio_entry.get("channels") else None,
        "audio_languages": ", ".join(sorted({t["language"] for t in audio_tracks if t.get("language")})) or None,
    })
    transfer = video_entry.get("transfer")
    primaries = video_entry.get("primaries")
    hdr = video_entry.get("hdr_format")
    if not hdr and transfer == 16:
        hdr = "HDR10/PQ"
    elif not hdr and transfer == 18:
        hdr = "HLG"
    result["extended"].update({
        "bit_depth": video_entry.get("bit_depth"),
        "frame_rate": video.get("frame_rate"),
        "color_transfer": transfer,
        "color_primaries": primaries,
        "hdr_format": hdr,
        "audio_stream_count": len(audio_tracks),
        "subtitle_stream_count": len(subtitle_tracks),
    })
    cover = _extract_mp4_cover(moov_data)
    if cover:
        result["_embedded_cover"] = {"data": cover[0], "mime": cover[1], "extension": cover[2]}
    result["raw"] = {"iso_bmff": {"tracks": tracks, "movie_timescale": movie_timescale}}
    return _finish(result, sample.source_size)


# ---- AVI / RIFF ----------------------------------------------------------------


def _riff_chunks(data: bytes, start: int, end: int) -> Iterator[tuple[bytes, int, int, bytes | None]]:
    pos = start
    while pos + 8 <= end:
        kind = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        payload = pos + 8
        chunk_end = min(end, payload + size)
        list_type = None
        if kind == b"LIST" and payload + 4 <= chunk_end:
            list_type = data[payload:payload + 4]
            payload += 4
        yield kind, payload, chunk_end, list_type
        pos = (pos + 8 + size + 1) & ~1


def _parse_avi_stream(data: bytes, start: int, end: int) -> dict[str, Any]:
    stream: dict[str, Any] = {}
    strf = b""
    for kind, payload, chunk_end, _ in _riff_chunks(data, start, end):
        blob = data[payload:chunk_end]
        if kind == b"strh" and len(blob) >= 40:
            stream["type"] = blob[0:4].decode("latin-1", errors="replace")
            stream["handler"] = blob[4:8].decode("latin-1", errors="replace")
            stream["scale"] = struct.unpack_from("<I", blob, 20)[0]
            stream["rate"] = struct.unpack_from("<I", blob, 24)[0]
            stream["length"] = struct.unpack_from("<I", blob, 32)[0]
        elif kind == b"strf":
            strf = blob
    if stream.get("type") == "vids" and len(strf) >= 20:
        stream["width"] = abs(struct.unpack_from("<i", strf, 4)[0])
        stream["height"] = abs(struct.unpack_from("<i", strf, 8)[0])
        stream["codec"] = _codec(strf[16:20] or stream.get("handler"))
    elif stream.get("type") == "auds" and len(strf) >= 16:
        tag, channels, sample_rate, avg_bytes, _, bits = struct.unpack_from("<HHIIHH", strf, 0)
        stream.update({
            "codec": WAVE_FORMATS.get(tag, f"wave-0x{tag:04x}"),
            "channels": channels,
            "sample_rate": sample_rate,
            "audio_bitrate": avg_bytes * 8 if avg_bytes else None,
            "bit_depth": bits,
        })
    scale = stream.get("scale")
    rate = stream.get("rate")
    length = stream.get("length")
    if scale and rate and length:
        stream["duration"] = length * scale / rate
        if stream.get("type") == "vids":
            stream["frame_rate"] = rate / scale
    return stream


def parse_avi(sample: NativeSample) -> dict[str, Any]:
    data = sample.head
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"AVI ":
        raise NativeContainerError("AVI RIFF header was not found")
    avih: dict[str, Any] = {}
    streams: list[dict[str, Any]] = []
    for kind, payload, chunk_end, list_type in _riff_chunks(data, 12, len(data)):
        if kind == b"LIST" and list_type == b"hdrl":
            for child, child_payload, child_end, child_list in _riff_chunks(data, payload, chunk_end):
                if child == b"avih" and child_end - child_payload >= 40:
                    blob = data[child_payload:child_end]
                    avih = {
                        "microseconds_per_frame": struct.unpack_from("<I", blob, 0)[0],
                        "total_frames": struct.unpack_from("<I", blob, 16)[0],
                        "stream_count": struct.unpack_from("<I", blob, 24)[0],
                        "width": struct.unpack_from("<I", blob, 32)[0],
                        "height": struct.unpack_from("<I", blob, 36)[0],
                    }
                elif child == b"LIST" and child_list == b"strl":
                    streams.append(_parse_avi_stream(data, child_payload, child_end))
    video_streams = [s for s in streams if s.get("type") == "vids"]
    audio_streams = [s for s in streams if s.get("type") == "auds"]
    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}
    duration = max((s.get("duration") or 0 for s in streams), default=0) or None
    if not duration and avih.get("microseconds_per_frame") and avih.get("total_frames"):
        duration = avih["microseconds_per_frame"] * avih["total_frames"] / 1_000_000
    result = _base_result("avi", duration=duration, source_size=sample.source_size)
    result.update({
        "video_codec": video.get("codec") or _codec(video.get("handler")),
        "width": video.get("width") or avih.get("width"),
        "height": video.get("height") or avih.get("height"),
        "audio_codec": audio.get("codec"),
        "audio_channels": float(audio["channels"]) if audio.get("channels") else None,
    })
    result["extended"].update({
        "frame_rate": video.get("frame_rate") or (
            1_000_000 / avih["microseconds_per_frame"] if avih.get("microseconds_per_frame") else None
        ),
        "bit_depth": video.get("bit_depth"),
        "audio_stream_count": len(audio_streams),
        "subtitle_stream_count": max(0, len(streams) - len(video_streams) - len(audio_streams)),
    })
    result["raw"] = {"avi": {"main_header": avih, "streams": streams}}
    return _finish(result, sample.source_size)


# ---- ASF / WMV -----------------------------------------------------------------


def _guid(value: str) -> bytes:
    return uuid.UUID(value).bytes_le


ASF_HEADER = _guid("75B22630-668E-11CF-A6D9-00AA0062CE6C")
ASF_FILE_PROPERTIES = _guid("8CABDCA1-A947-11CF-8EE4-00C00C205365")
ASF_STREAM_PROPERTIES = _guid("B7DC0791-A9B7-11CF-8EE6-00C00C205365")
ASF_AUDIO_MEDIA = _guid("F8699E40-5B4D-11CF-A8FD-00805F5C442B")
ASF_VIDEO_MEDIA = _guid("BC19EFC0-5B4D-11CF-A8FD-00805F5C442B")


def parse_asf(sample: NativeSample) -> dict[str, Any]:
    data = sample.head
    if len(data) < 30 or data[:16] != ASF_HEADER:
        raise NativeContainerError("ASF header object was not found")
    object_count = struct.unpack_from("<I", data, 24)[0]
    pos = 30
    duration = bitrate = None
    streams: list[dict[str, Any]] = []
    for _ in range(min(object_count, 256)):
        if pos + 24 > len(data):
            break
        guid = data[pos:pos + 16]
        size = struct.unpack_from("<Q", data, pos + 16)[0]
        if size < 24 or pos + size > len(data):
            break
        blob = data[pos + 24:pos + size]
        if guid == ASF_FILE_PROPERTIES and len(blob) >= 80:
            play_duration = struct.unpack_from("<Q", blob, 40)[0]
            preroll = struct.unpack_from("<Q", blob, 56)[0]
            duration = max(0.0, play_duration / 10_000_000 - preroll / 1000)
            bitrate = struct.unpack_from("<I", blob, 76)[0]
        elif guid == ASF_STREAM_PROPERTIES and len(blob) >= 54:
            stream_type = blob[:16]
            type_length = struct.unpack_from("<I", blob, 40)[0]
            flags = struct.unpack_from("<H", blob, 48)[0]
            specific = blob[54:54 + type_length]
            stream: dict[str, Any] = {"stream_number": flags & 0x7F}
            if stream_type == ASF_AUDIO_MEDIA and len(specific) >= 16:
                tag, channels, sample_rate, avg_bytes, _, bits = struct.unpack_from("<HHIIHH", specific, 0)
                stream.update({
                    "type": "audio", "codec": WAVE_FORMATS.get(tag, f"wave-0x{tag:04x}"),
                    "channels": channels, "sample_rate": sample_rate,
                    "audio_bitrate": avg_bytes * 8 if avg_bytes else None, "bit_depth": bits,
                })
            elif stream_type == ASF_VIDEO_MEDIA and len(specific) >= 31:
                width = struct.unpack_from("<I", specific, 0)[0]
                height = struct.unpack_from("<I", specific, 4)[0]
                format_size = struct.unpack_from("<H", specific, 9)[0]
                bitmap = specific[11:11 + format_size]
                codec_fourcc = bitmap[16:20] if len(bitmap) >= 20 else b""
                stream.update({
                    "type": "video", "codec": _codec(codec_fourcc), "width": width,
                    "height": height, "bit_depth": struct.unpack_from("<H", bitmap, 14)[0] if len(bitmap) >= 16 else None,
                })
            streams.append(stream)
        pos += size
    video_streams = [s for s in streams if s.get("type") == "video"]
    audio_streams = [s for s in streams if s.get("type") == "audio"]
    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}
    result = _base_result("asf", duration=duration, source_size=sample.source_size)
    result.update({
        "video_codec": video.get("codec"), "width": video.get("width"), "height": video.get("height"),
        "video_bitrate": bitrate or result.get("video_bitrate"),
        "audio_codec": audio.get("codec"),
        "audio_channels": float(audio["channels"]) if audio.get("channels") else None,
    })
    result["extended"].update({
        "bit_depth": video.get("bit_depth"),
        "audio_stream_count": len(audio_streams),
        "subtitle_stream_count": max(0, len(streams) - len(video_streams) - len(audio_streams)),
    })
    result["raw"] = {"asf": {"streams": streams, "max_bitrate": bitrate}}
    return _finish(result, sample.source_size)


# ---- MPEG transport/program streams --------------------------------------------

TS_STREAM_TYPES = {
    0x01: ("video", "mpeg1video"), 0x02: ("video", "mpeg2video"),
    0x10: ("video", "mpeg4"), 0x1B: ("video", "h264"), 0x24: ("video", "hevc"),
    0x27: ("video", "hevc"), 0x33: ("video", "vvc"), 0x42: ("video", "avs"),
    0xEA: ("video", "vc1"),
    0x03: ("audio", "mp2"), 0x04: ("audio", "mp2"), 0x0F: ("audio", "aac"),
    0x11: ("audio", "aac_latm"), 0x81: ("audio", "ac3"), 0x82: ("audio", "dts"),
    0x83: ("audio", "truehd"), 0x84: ("audio", "eac3"), 0x87: ("audio", "eac3"),
}
FRAME_RATES = {1: 23.976, 2: 24.0, 3: 25.0, 4: 29.97, 5: 30.0, 6: 50.0, 7: 59.94, 8: 60.0}


def _pts(data: bytes, offset: int) -> int | None:
    if offset + 5 > len(data):
        return None
    b = data[offset:offset + 5]
    if not (b[0] & 1 and b[2] & 1 and b[4] & 1):
        return None
    return (((b[0] >> 1) & 0x07) << 30) | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)


def _remove_emulation(data: bytes) -> bytes:
    out = bytearray()
    zeros = 0
    for byte in data:
        if zeros >= 2 and byte == 3:
            zeros = 0
            continue
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


class _Bits:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, count: int) -> int:
        if self.pos + count > len(self.data) * 8:
            raise NativeContainerError("Truncated codec bitstream")
        value = 0
        for _ in range(count):
            value = (value << 1) | ((self.data[self.pos // 8] >> (7 - self.pos % 8)) & 1)
            self.pos += 1
        return value

    def ue(self) -> int:
        zeros = 0
        while self.read(1) == 0:
            zeros += 1
            if zeros > 31:
                raise NativeContainerError("Invalid exponential Golomb code")
        return (1 << zeros) - 1 + (self.read(zeros) if zeros else 0)

    def se(self) -> int:
        code = self.ue()
        return (code + 1) // 2 if code & 1 else -(code // 2)


def _h264_sps_dimensions(nal: bytes) -> tuple[int, int] | None:
    try:
        rbsp = _remove_emulation(nal[1:])
        bits = _Bits(rbsp)
        profile = bits.read(8)
        bits.read(8); bits.read(8); bits.ue()
        chroma_format_idc = 1
        if profile in {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}:
            chroma_format_idc = bits.ue()
            if chroma_format_idc == 3:
                bits.read(1)
            bits.ue(); bits.ue(); bits.read(1)
            if bits.read(1):
                count = 8 if chroma_format_idc != 3 else 12
                for index in range(count):
                    if bits.read(1):
                        size = 16 if index < 6 else 64
                        last = nxt = 8
                        for _ in range(size):
                            if nxt:
                                nxt = (last + bits.se() + 256) % 256
                            last = nxt or last
        bits.ue()
        poc_type = bits.ue()
        if poc_type == 0:
            bits.ue()
        elif poc_type == 1:
            bits.read(1); bits.se(); bits.se()
            for _ in range(bits.ue()): bits.se()
        bits.ue(); bits.read(1)
        width_mbs = bits.ue() + 1
        height_map = bits.ue() + 1
        frame_mbs_only = bits.read(1)
        if not frame_mbs_only:
            bits.read(1)
        bits.read(1)
        crop_left = crop_right = crop_top = crop_bottom = 0
        if bits.read(1):
            crop_left, crop_right, crop_top, crop_bottom = bits.ue(), bits.ue(), bits.ue(), bits.ue()
        sub_width = 1 if chroma_format_idc in {0, 3} else 2
        sub_height = 2 if chroma_format_idc == 1 else 1
        crop_x = sub_width
        crop_y = sub_height * (2 - frame_mbs_only)
        width = width_mbs * 16 - (crop_left + crop_right) * crop_x
        height = height_map * 16 * (2 - frame_mbs_only) - (crop_top + crop_bottom) * crop_y
        return width, height
    except (NativeContainerError, IndexError, ValueError):
        return None


def _find_start_codes(payload: bytes) -> Iterator[tuple[int, int]]:
    pos = 0
    while True:
        a = payload.find(b"\x00\x00\x01", pos)
        b = payload.find(b"\x00\x00\x00\x01", pos)
        choices = [x for x in (a, b) if x >= 0]
        if not choices:
            return
        start = min(choices)
        prefix = 4 if payload[start:start + 4] == b"\x00\x00\x00\x01" else 3
        yield start, prefix
        pos = start + prefix


def _video_headers(payload: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {}
    sequence = payload.find(b"\x00\x00\x01\xb3")
    if sequence >= 0 and sequence + 8 <= len(payload):
        value = int.from_bytes(payload[sequence + 4:sequence + 8], "big")
        result.update({
            "codec": "mpeg2video", "width": (value >> 20) & 0xFFF,
            "height": (value >> 8) & 0xFFF, "frame_rate": FRAME_RATES.get(value & 0xF),
        })
        return result
    for start, prefix in _find_start_codes(payload):
        nal_start = start + prefix
        if nal_start >= len(payload):
            continue
        nal_type = payload[nal_start] & 0x1F
        if nal_type == 7:
            next_start = payload.find(b"\x00\x00\x01", nal_start + 1)
            nal = payload[nal_start:next_start if next_start >= 0 else len(payload)]
            dimensions = _h264_sps_dimensions(nal)
            result["codec"] = "h264"
            if dimensions:
                result["width"], result["height"] = dimensions
            break
    return result


def _ts_packet_layout(data: bytes) -> tuple[int, int]:
    for packet_size, prefix in ((188, 0), (192, 4), (204, 0)):
        for offset in range(min(packet_size, len(data))):
            if offset + prefix + packet_size * 4 >= len(data):
                break
            if all(data[offset + prefix + packet_size * n] == 0x47 for n in range(4)):
                return packet_size, offset + prefix
    raise NativeContainerError("MPEG-TS sync packets were not found")


def _audio_header_details(codec: str | None, payload: bytes) -> dict[str, Any]:
    if not codec or not payload:
        return {}
    if codec in {"ac3", "eac3"}:
        offset = payload.find(b"\x0b\x77")
        if offset >= 0 and offset + 8 <= len(payload):
            try:
                bits = _Bits(payload[offset + 4:offset + 12])
                bits.read(2); bits.read(6); bits.read(5); bits.read(3)
                acmod = bits.read(3)
                if (acmod & 1) and acmod != 1:
                    bits.read(2)
                if acmod & 4:
                    bits.read(2)
                if acmod == 2:
                    bits.read(2)
                lfe = bits.read(1)
                base = {0: 2, 1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 5}.get(acmod)
                return {"channels": (base + lfe) if base is not None else None}
            except NativeContainerError:
                return {}
    if codec in {"aac", "aac_latm"}:
        offset = payload.find(b"\xff\xf1")
        if offset < 0:
            offset = payload.find(b"\xff\xf9")
        if offset >= 0 and offset + 4 <= len(payload):
            channels = ((payload[offset + 2] & 1) << 2) | ((payload[offset + 3] >> 6) & 3)
            return {"channels": channels or None}
    if codec in {"mp1", "mp2", "mp3"}:
        for offset in range(max(0, len(payload) - 4)):
            if payload[offset] == 0xFF and payload[offset + 1] & 0xE0 == 0xE0:
                mode = (payload[offset + 3] >> 6) & 3
                return {"channels": 1 if mode == 3 else 2}
    return {}


def _parse_ts_segment(data: bytes) -> dict[str, Any]:
    packet_size, sync_offset = _ts_packet_layout(data)
    pmt_pids: set[int] = set()
    streams: dict[int, tuple[str, str]] = {}
    pts_values: list[int] = []
    video_payloads: list[bytes] = []
    audio_payloads: dict[int, bytearray] = {}
    pos = sync_offset
    while pos + 188 <= len(data):
        packet = data[pos:pos + 188]
        pos += packet_size
        if packet[0] != 0x47 or packet[1] & 0x80:
            continue
        pusi = bool(packet[1] & 0x40)
        pid = ((packet[1] & 0x1F) << 8) | packet[2]
        adaptation = (packet[3] >> 4) & 0x03
        payload_pos = 4
        if adaptation in {2, 3}:
            if payload_pos >= len(packet):
                continue
            payload_pos += 1 + packet[payload_pos]
        if adaptation not in {1, 3} or payload_pos >= len(packet):
            continue
        payload = packet[payload_pos:]
        if pid == 0 and pusi and payload:
            pointer = payload[0]
            section = payload[1 + pointer:]
            if len(section) >= 12 and section[0] == 0x00:
                section_length = ((section[1] & 0x0F) << 8) | section[2]
                end = min(len(section) - 4, 3 + section_length - 4)
                cursor = 8
                while cursor + 4 <= end:
                    program = _be16(section, cursor)
                    map_pid = ((section[cursor + 2] & 0x1F) << 8) | section[cursor + 3]
                    if program:
                        pmt_pids.add(map_pid)
                    cursor += 4
        elif pid in pmt_pids and pusi and payload:
            pointer = payload[0]
            section = payload[1 + pointer:]
            if len(section) >= 16 and section[0] == 0x02:
                section_length = ((section[1] & 0x0F) << 8) | section[2]
                program_info_length = ((section[10] & 0x0F) << 8) | section[11]
                cursor = 12 + program_info_length
                end = min(len(section) - 4, 3 + section_length - 4)
                while cursor + 5 <= end:
                    stream_type = section[cursor]
                    elementary_pid = ((section[cursor + 1] & 0x1F) << 8) | section[cursor + 2]
                    es_info_length = ((section[cursor + 3] & 0x0F) << 8) | section[cursor + 4]
                    kind_codec = TS_STREAM_TYPES.get(stream_type)
                    if kind_codec:
                        streams[elementary_pid] = kind_codec
                    cursor += 5 + es_info_length
        elif pid in streams and pusi and payload.startswith(b"\x00\x00\x01") and len(payload) >= 14:
            flags = payload[7]
            header_length = payload[8]
            if flags & 0x80:
                value = _pts(payload, 9)
                if value is not None:
                    pts_values.append(value)
            start = 9 + header_length
            if start < len(payload):
                if streams[pid][0] == "video":
                    video_payloads.append(payload[start:])
                elif streams[pid][0] == "audio":
                    audio_payloads.setdefault(pid, bytearray()).extend(payload[start:start + 8192])
    headers = _video_headers(b"".join(video_payloads[:64]))
    audio_details = {}
    for audio_pid, audio_payload in audio_payloads.items():
        codec = streams.get(audio_pid, (None, None))[1]
        details = _audio_header_details(codec, bytes(audio_payload))
        if details:
            audio_details[audio_pid] = details
    return {
        "packet_size": packet_size,
        "streams": streams,
        "pts": pts_values,
        "video_headers": headers,
        "audio_details": audio_details,
    }


def _pts_duration(head_pts: list[int], tail_pts: list[int]) -> float | None:
    if not head_pts or not tail_pts:
        return None
    start = min(head_pts)
    end = max(tail_pts)
    if end < start:
        end += 1 << 33
    duration = (end - start) / 90_000
    return duration if duration > 0 else None


def parse_mpeg_ts(sample: NativeSample) -> dict[str, Any]:
    head = _parse_ts_segment(sample.head)
    tail = _parse_ts_segment(sample.tail) if sample.tail else {"pts": [], "streams": {}, "video_headers": {}}
    streams = dict(head["streams"])
    streams.update(tail.get("streams") or {})
    video_streams = [value for value in streams.values() if value[0] == "video"]
    audio_streams = [value for value in streams.values() if value[0] == "audio"]
    audio_details = dict(tail.get("audio_details") or {})
    audio_details.update(head.get("audio_details") or {})
    headers = dict(tail.get("video_headers") or {})
    headers.update(head.get("video_headers") or {})
    duration = _pts_duration(head.get("pts") or [], tail.get("pts") or [])
    if duration is None and not sample.tail and sample.source_size and sample.source_size <= len(sample.head):
        values = head.get("pts") or []
        if len(values) >= 2:
            duration = _pts_duration([min(values)], [max(values)])
    result = _base_result("mpegts", duration=duration, source_size=sample.source_size)
    result.update({
        "video_codec": headers.get("codec") or (video_streams[0][1] if video_streams else None),
        "width": headers.get("width"), "height": headers.get("height"),
        "audio_codec": audio_streams[0][1] if audio_streams else None,
        "audio_channels": float(next((item.get("channels") for item in audio_details.values() if item.get("channels")), 0)) or None,
    })
    result["extended"].update({
        "frame_rate": headers.get("frame_rate"),
        "audio_stream_count": len(audio_streams),
        "subtitle_stream_count": 0,
    })
    result["raw"] = {"mpeg_ts": {"packet_size": head["packet_size"], "pids": {str(k): v for k, v in streams.items()}}}
    return _finish(result, sample.source_size)


def _parse_ps_segment(data: bytes) -> dict[str, Any]:
    pts_values: list[int] = []
    audio_codecs: list[str] = []
    audio_details: list[dict[str, Any]] = []
    video_payload = bytearray()
    pos = 0
    while True:
        start = data.find(b"\x00\x00\x01", pos)
        if start < 0 or start + 6 > len(data):
            break
        stream_id = data[start + 3]
        if stream_id in {0xBA, 0xBB, 0xBC, 0xBE, 0xBF, 0xF0, 0xF1, 0xF2, 0xF8, 0xFF}:
            pos = start + 4
            continue
        length = _be16(data, start + 4)
        end = min(len(data), start + 6 + length) if length else min(len(data), start + 65536)
        payload_start = start + 6
        if stream_id in range(0xBD, 0xF0) and payload_start < end:
            # MPEG-2 PES starts with '10', flags and a header length. MPEG-1
            # program streams use stuffing/STD bytes followed directly by a
            # PTS marker nibble (0x2/0x3) or 0x0F.
            es_start = payload_start
            if payload_start + 3 <= end and data[payload_start] & 0xC0 == 0x80:
                flags2 = data[payload_start + 1]
                header_len = data[payload_start + 2]
                if flags2 & 0x80:
                    value = _pts(data, payload_start + 3)
                    if value is not None:
                        pts_values.append(value)
                es_start = payload_start + 3 + header_len
            else:
                cursor = payload_start
                while cursor < end and data[cursor] == 0xFF:
                    cursor += 1
                if cursor + 2 <= end and data[cursor] & 0xC0 == 0x40:
                    cursor += 2
                if cursor < end and data[cursor] & 0xF0 in {0x20, 0x30}:
                    value = _pts(data, cursor)
                    if value is not None:
                        pts_values.append(value)
                    cursor += 10 if data[cursor] & 0xF0 == 0x30 else 5
                elif cursor < end and data[cursor] == 0x0F:
                    cursor += 1
                es_start = cursor
            payload = data[es_start:end]
            if 0xE0 <= stream_id <= 0xEF:
                video_payload.extend(payload[:65536])
            elif 0xC0 <= stream_id <= 0xDF:
                if "mp2" not in audio_codecs:
                    audio_codecs.append("mp2")
                details = _audio_header_details("mp2", payload)
                if details:
                    audio_details.append(details)
            elif stream_id == 0xBD:
                if b"\x0b\x77" in payload[:256]:
                    audio_codecs.append("ac3")
                    details = _audio_header_details("ac3", payload)
                    if details:
                        audio_details.append(details)
                elif b"\x7f\xfe\x80\x01" in payload[:256]:
                    audio_codecs.append("dts")
        pos = max(start + 4, end)
    return {
        "pts": pts_values, "audio_codecs": audio_codecs, "audio_details": audio_details,
        "video_headers": _video_headers(bytes(video_payload)),
    }


def parse_mpeg_ps(sample: NativeSample) -> dict[str, Any]:
    if b"\x00\x00\x01\xba" not in sample.head[:65536]:
        raise NativeContainerError("MPEG program-stream pack header was not found")
    head = _parse_ps_segment(sample.head)
    tail = _parse_ps_segment(sample.tail) if sample.tail else {"pts": [], "audio_codecs": [], "video_headers": {}}
    headers = dict(tail.get("video_headers") or {})
    headers.update(head.get("video_headers") or {})
    audio = (head.get("audio_codecs") or tail.get("audio_codecs") or [None])[0]
    duration = _pts_duration(head.get("pts") or [], tail.get("pts") or [])
    if duration is None and not sample.tail and sample.source_size and sample.source_size <= len(sample.head):
        values = head.get("pts") or []
        if len(values) >= 2:
            duration = _pts_duration([min(values)], [max(values)])
    details = (head.get("audio_details") or tail.get("audio_details") or [{}])[0]
    result = _base_result("mpeg", duration=duration, source_size=sample.source_size)
    result.update({
        "video_codec": headers.get("codec") or "mpeg2video",
        "width": headers.get("width"), "height": headers.get("height"),
        "audio_codec": audio,
        "audio_channels": float(details["channels"]) if details.get("channels") else None,
    })
    result["extended"].update({"frame_rate": headers.get("frame_rate"), "audio_stream_count": 1 if audio else 0})
    result["raw"] = {"mpeg_ps": {"head_pts": len(head.get("pts") or []), "tail_pts": len(tail.get("pts") or [])}}
    return _finish(result, sample.source_size)


NATIVE_SUFFIXES = {
    ".mp4", ".m4v", ".mov", ".avi", ".wmv", ".asf",
    ".ts", ".m2ts", ".mts", ".mpg", ".mpeg",
}


def parse_native_container(path: Path, sample: NativeSample) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".m4v", ".mov"}:
        return parse_iso_bmff(sample, suffix)
    if suffix == ".avi":
        return parse_avi(sample)
    if suffix in {".wmv", ".asf"}:
        return parse_asf(sample)
    if suffix in {".ts", ".m2ts", ".mts"}:
        return parse_mpeg_ts(sample)
    if suffix in {".mpg", ".mpeg"}:
        # Some .mpg files are transport streams; prefer sync-packet detection.
        try:
            return parse_mpeg_ts(sample)
        except NativeContainerError:
            return parse_mpeg_ps(sample)
    raise NativeContainerError(f"No native parser is registered for {suffix or 'this file'}")
