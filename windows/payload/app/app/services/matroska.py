from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any, Iterator

from app.services.media_utils import resolution_label

# Matroska/EBML element identifiers needed for movie technical metadata.
SEGMENT = 0x18538067
INFO = 0x1549A966
TRACKS = 0x1654AE6B
CLUSTER = 0x1F43B675
TIMECODE_SCALE = 0x2AD7B1
DURATION = 0x4489
TITLE = 0x7BA9
TRACK_ENTRY = 0xAE
TRACK_TYPE = 0x83
DEFAULT_DURATION = 0x23E383
NAME = 0x536E
LANGUAGE = 0x22B59C
LANGUAGE_IETF = 0x22B59D
CODEC_ID = 0x86
VIDEO = 0xE0
AUDIO = 0xE1
PIXEL_WIDTH = 0xB0
PIXEL_HEIGHT = 0xBA
DISPLAY_WIDTH = 0x54B0
DISPLAY_HEIGHT = 0x54BA
FRAME_RATE = 0x2383E3
COLOUR = 0x55B0
BITS_PER_CHANNEL = 0x55B2
TRANSFER_CHARACTERISTICS = 0x55BA
PRIMARIES = 0x55BB
CHANNELS = 0x9F
SAMPLING_FREQUENCY = 0xB5
AUDIO_BIT_DEPTH = 0x6264


class MatroskaParseError(ValueError):
    """Raised when a staged fragment is not a readable Matroska header."""


def _read_vint(data: bytes, offset: int, *, identifier: bool = False) -> tuple[int, int, bool]:
    if offset >= len(data):
        raise MatroskaParseError("unexpected end of EBML data")
    first = data[offset]
    mask = 0x80
    length = 1
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8 or offset + length > len(data):
        raise MatroskaParseError("invalid EBML variable-length integer")
    if identifier and length > 4:
        raise MatroskaParseError("invalid EBML element identifier")

    if identifier:
        value = first
    else:
        value = first & (mask - 1)
    for index in range(1, length):
        value = (value << 8) | data[offset + index]

    unknown = False
    if not identifier:
        unknown = value == (1 << (7 * length)) - 1
    return value, length, unknown


def _elements(data: bytes, start: int, end: int) -> Iterator[tuple[int, int, int, bool]]:
    position = max(0, start)
    end = min(len(data), end)
    while position < end:
        try:
            element_id, id_length, _ = _read_vint(data, position, identifier=True)
            size, size_length, unknown = _read_vint(data, position + id_length)
        except MatroskaParseError:
            return
        payload_start = position + id_length + size_length
        if payload_start > end:
            return
        payload_end = end if unknown else min(end, payload_start + size)
        if payload_end < payload_start:
            return
        yield element_id, payload_start, payload_end, unknown
        if unknown:
            return
        next_position = payload_start + size
        if next_position <= position or next_position > end:
            return
        position = next_position


def _uint(data: bytes, start: int, end: int) -> int | None:
    if end <= start or end - start > 8:
        return None
    return int.from_bytes(data[start:end], "big", signed=False)


def _float(data: bytes, start: int, end: int) -> float | None:
    size = end - start
    try:
        if size == 4:
            value = struct.unpack(">f", data[start:end])[0]
        elif size == 8:
            value = struct.unpack(">d", data[start:end])[0]
        else:
            return None
    except struct.error:
        return None
    return value if math.isfinite(value) else None


def _text(data: bytes, start: int, end: int) -> str | None:
    if end <= start:
        return None
    value = data[start:end].decode("utf-8", errors="replace").strip("\x00 \t\r\n")
    return value or None


def _codec_name(codec_id: str | None) -> str | None:
    if not codec_id:
        return None
    upper = codec_id.upper()
    exact = {
        "V_MPEG4/ISO/AVC": "h264",
        "V_MPEGH/ISO/HEVC": "hevc",
        "V_AV1": "av1",
        "V_VP9": "vp9",
        "V_VP8": "vp8",
        "V_MPEG2": "mpeg2video",
        "V_MPEG1": "mpeg1video",
        "V_MPEG4/ISO/ASP": "mpeg4",
        "V_THEORA": "theora",
        "V_PRORES": "prores",
        "A_AAC": "aac",
        "A_AC3": "ac3",
        "A_EAC3": "eac3",
        "A_TRUEHD": "truehd",
        "A_DTS": "dts",
        "A_MPEG/L3": "mp3",
        "A_MPEG/L2": "mp2",
        "A_FLAC": "flac",
        "A_OPUS": "opus",
        "A_VORBIS": "vorbis",
        "A_ALAC": "alac",
        "A_WAVPACK4": "wavpack",
        "A_PCM/INT/LIT": "pcm_s16le",
        "A_PCM/INT/BIG": "pcm_s16be",
        "A_PCM/FLOAT/IEEE": "pcm_f32le",
    }
    if upper in exact:
        return exact[upper]
    if upper.startswith("V_REAL/RV"):
        return upper.rsplit("/", 1)[-1].lower()
    if upper.startswith("A_PCM"):
        return "pcm"
    return codec_id.lower().replace("/", "_")


def _parse_colour(data: bytes, start: int, end: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for element_id, payload_start, payload_end, _ in _elements(data, start, end):
        if element_id == BITS_PER_CHANNEL:
            result["bit_depth"] = _uint(data, payload_start, payload_end)
        elif element_id == TRANSFER_CHARACTERISTICS:
            result["transfer_characteristics"] = _uint(data, payload_start, payload_end)
        elif element_id == PRIMARIES:
            result["primaries"] = _uint(data, payload_start, payload_end)
    return result


def _parse_video(data: bytes, start: int, end: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for element_id, payload_start, payload_end, _ in _elements(data, start, end):
        if element_id == PIXEL_WIDTH:
            result["width"] = _uint(data, payload_start, payload_end)
        elif element_id == PIXEL_HEIGHT:
            result["height"] = _uint(data, payload_start, payload_end)
        elif element_id == DISPLAY_WIDTH:
            result["display_width"] = _uint(data, payload_start, payload_end)
        elif element_id == DISPLAY_HEIGHT:
            result["display_height"] = _uint(data, payload_start, payload_end)
        elif element_id == FRAME_RATE:
            result["frame_rate"] = _float(data, payload_start, payload_end)
        elif element_id == COLOUR:
            result.update(_parse_colour(data, payload_start, payload_end))
    return result


def _parse_audio(data: bytes, start: int, end: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for element_id, payload_start, payload_end, _ in _elements(data, start, end):
        if element_id == CHANNELS:
            result["channels"] = _uint(data, payload_start, payload_end)
        elif element_id == SAMPLING_FREQUENCY:
            result["sample_rate"] = _float(data, payload_start, payload_end)
        elif element_id == AUDIO_BIT_DEPTH:
            result["bit_depth"] = _uint(data, payload_start, payload_end)
    return result


def _parse_track(data: bytes, start: int, end: int) -> dict[str, Any]:
    track: dict[str, Any] = {}
    for element_id, payload_start, payload_end, _ in _elements(data, start, end):
        if element_id == TRACK_TYPE:
            track["type"] = _uint(data, payload_start, payload_end)
        elif element_id == CODEC_ID:
            track["codec_id"] = _text(data, payload_start, payload_end)
        elif element_id == DEFAULT_DURATION:
            track["default_duration_ns"] = _uint(data, payload_start, payload_end)
        elif element_id == NAME:
            track["name"] = _text(data, payload_start, payload_end)
        elif element_id in {LANGUAGE, LANGUAGE_IETF}:
            language = _text(data, payload_start, payload_end)
            if language:
                track["language"] = language
        elif element_id == VIDEO:
            track["video"] = _parse_video(data, payload_start, payload_end)
        elif element_id == AUDIO:
            track["audio"] = _parse_audio(data, payload_start, payload_end)
    track["codec"] = _codec_name(track.get("codec_id"))
    return track


def _parse_info(data: bytes, start: int, end: int) -> dict[str, Any]:
    result: dict[str, Any] = {"timecode_scale": 1_000_000}
    for element_id, payload_start, payload_end, _ in _elements(data, start, end):
        if element_id == TIMECODE_SCALE:
            result["timecode_scale"] = _uint(data, payload_start, payload_end) or 1_000_000
        elif element_id == DURATION:
            result["duration_ticks"] = _float(data, payload_start, payload_end)
        elif element_id == TITLE:
            result["title"] = _text(data, payload_start, payload_end)
    return result


def _find_segment(data: bytes) -> tuple[int, int]:
    for element_id, payload_start, payload_end, _ in _elements(data, 0, len(data)):
        if element_id == SEGMENT:
            return payload_start, payload_end
    marker = SEGMENT.to_bytes(4, "big")
    position = data.find(marker)
    if position < 0:
        raise MatroskaParseError("Matroska Segment element was not found")
    _, id_length, _ = _read_vint(data, position, identifier=True)
    size, size_length, unknown = _read_vint(data, position + id_length)
    payload_start = position + id_length + size_length
    payload_end = len(data) if unknown else min(len(data), payload_start + size)
    return payload_start, payload_end


def parse_matroska_bytes(data: bytes) -> dict[str, Any]:
    if len(data) < 32:
        raise MatroskaParseError("Matroska fragment is too small")
    segment_start, segment_end = _find_segment(data)
    info: dict[str, Any] = {}
    tracks: list[dict[str, Any]] = []

    for element_id, payload_start, payload_end, _ in _elements(data, segment_start, segment_end):
        if element_id == INFO:
            info = _parse_info(data, payload_start, payload_end)
        elif element_id == TRACKS:
            tracks = [
                _parse_track(data, entry_start, entry_end)
                for child_id, entry_start, entry_end, _ in _elements(data, payload_start, payload_end)
                if child_id == TRACK_ENTRY
            ]
        elif element_id == CLUSTER:
            # Info and Tracks should precede the first Cluster. A staged header
            # intentionally stops here rather than interpreting media payload.
            break
        if info and tracks:
            break

    # Some muxers place large padding/seek data before Info or Tracks. Search the
    # bounded fragment for their identifiers as a fallback without reading media.
    if not info:
        marker = INFO.to_bytes(4, "big")
        position = data.find(marker, segment_start)
        if position >= 0:
            try:
                _, id_length, _ = _read_vint(data, position, identifier=True)
                size, size_length, unknown = _read_vint(data, position + id_length)
                payload_start = position + id_length + size_length
                payload_end = len(data) if unknown else min(len(data), payload_start + size)
                info = _parse_info(data, payload_start, payload_end)
            except MatroskaParseError:
                pass
    if not tracks:
        marker = TRACKS.to_bytes(4, "big")
        position = data.find(marker, segment_start)
        if position >= 0:
            try:
                _, id_length, _ = _read_vint(data, position, identifier=True)
                size, size_length, unknown = _read_vint(data, position + id_length)
                payload_start = position + id_length + size_length
                payload_end = len(data) if unknown else min(len(data), payload_start + size)
                tracks = [
                    _parse_track(data, entry_start, entry_end)
                    for child_id, entry_start, entry_end, _ in _elements(data, payload_start, payload_end)
                    if child_id == TRACK_ENTRY
                ]
            except MatroskaParseError:
                pass

    video_tracks = [track for track in tracks if track.get("type") == 1]
    audio_tracks = [track for track in tracks if track.get("type") == 2]
    subtitle_tracks = [track for track in tracks if track.get("type") == 17]
    video = video_tracks[0] if video_tracks else {}
    audio = audio_tracks[0] if audio_tracks else {}
    video_info = video.get("video") or {}
    audio_info = audio.get("audio") or {}

    duration = None
    duration_ticks = info.get("duration_ticks")
    if duration_ticks is not None:
        duration = float(duration_ticks) * float(info.get("timecode_scale") or 1_000_000) / 1_000_000_000

    frame_rate = video_info.get("frame_rate")
    if not frame_rate and video.get("default_duration_ns"):
        frame_rate = 1_000_000_000 / float(video["default_duration_ns"])

    transfer = video_info.get("transfer_characteristics")
    primaries = video_info.get("primaries")
    hdr_format = None
    if transfer == 16:
        hdr_format = "HDR10/PQ"
    elif transfer == 18:
        hdr_format = "HLG"
    elif primaries == 9:
        hdr_format = "HDR/BT.2020"

    languages = sorted({
        str(track.get("language")).strip()
        for track in audio_tracks
        if track.get("language")
    })
    width = video_info.get("width") or video_info.get("display_width")
    height = video_info.get("height") or video_info.get("display_height")
    result = {
        "container": "matroska",
        "duration_seconds": duration,
        "video_codec": video.get("codec"),
        "width": width,
        "height": height,
        "resolution_label": resolution_label(width, height),
        "video_bitrate": None,
        "audio_codec": audio.get("codec"),
        "audio_channels": float(audio_info["channels"]) if audio_info.get("channels") is not None else None,
        "audio_languages": ", ".join(languages) or None,
        "probe_profile": "standard",
        "extended": {
            "video_profile": None,
            "video_level": None,
            "pixel_format": None,
            "bit_depth": video_info.get("bit_depth"),
            "frame_rate": frame_rate,
            "color_space": None,
            "color_transfer": transfer,
            "color_primaries": primaries,
            "hdr_format": hdr_format,
            "audio_stream_count": len(audio_tracks),
            "subtitle_stream_count": len(subtitle_tracks),
            "chapter_count": None,
        },
        "raw": {
            "matroska_header": {
                "title": info.get("title"),
                "timecode_scale": info.get("timecode_scale"),
                "duration_ticks": duration_ticks,
                "tracks": tracks,
            }
        },
    }
    if not any(result.get(key) not in (None, "") for key in (
        "duration_seconds", "video_codec", "width", "height", "audio_codec"
    )):
        raise MatroskaParseError("Matroska header contained no usable technical metadata")
    return result


def parse_matroska_header(path: Path) -> dict[str, Any]:
    return parse_matroska_bytes(path.read_bytes())
