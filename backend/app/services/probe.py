from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.media_utils import resolution_label


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_media(path: Path) -> tuple[dict[str, Any], str | None]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=settings.max_probe_seconds, check=False)
    except FileNotFoundError:
        return {}, "ffprobe is not installed"
    except subprocess.TimeoutExpired:
        return {}, f"ffprobe timed out after {settings.max_probe_seconds} seconds"
    if result.returncode != 0:
        return {}, (result.stderr or "ffprobe failed").strip()[:2000]
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid ffprobe output: {exc}"

    streams = raw.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}
    format_info = raw.get("format", {})
    languages = sorted({stream.get("tags", {}).get("language") for stream in audio_streams if stream.get("tags", {}).get("language")})
    width = _as_int(video.get("width"))
    height = _as_int(video.get("height"))

    normalized = {
        "container": (format_info.get("format_name") or "").split(",")[0] or None,
        "duration_seconds": _as_float(format_info.get("duration")),
        "video_codec": video.get("codec_name"),
        "width": width,
        "height": height,
        "resolution_label": resolution_label(width, height),
        "video_bitrate": _as_int(video.get("bit_rate")) or _as_int(format_info.get("bit_rate")),
        "audio_codec": audio.get("codec_name"),
        "audio_channels": _as_float(audio.get("channels")),
        "audio_languages": ", ".join(languages) or None,
        "raw": raw,
    }
    return normalized, None


def ffprobe_version() -> str:
    try:
        result = subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, timeout=5, check=False)
        return result.stdout.splitlines()[0] if result.stdout else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unavailable"
