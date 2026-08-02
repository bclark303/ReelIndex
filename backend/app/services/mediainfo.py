from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.media_utils import resolution_label


class MediaInfoCancelled(RuntimeError):
    """Raised when an active MediaInfo process is cancelled by the scan manager."""


def _hidden_process_options() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def _run_hidden(
    command: list[str],
    timeout: int,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_process_options(),
    )
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if cancel_event and cancel_event.is_set():
                process.kill()
                process.communicate()
                raise MediaInfoCancelled("MediaInfo analysis cancelled")
            if time.monotonic() >= deadline:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
            time.sleep(0.1)
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.communicate()
        raise


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(round(number)) if number is not None else None


def _duration_seconds(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    # Current MediaInfo JSON uses seconds, while some older/raw outputs use
    # milliseconds. Values over one day are safely treated as milliseconds for
    # a movie inventory application.
    return number / 1000.0 if number > 86_400 else number


def _first(track: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = track.get(key)
        if value not in (None, ""):
            return value
    return None


def _codec_name(value: Any, *, audio: bool = False) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    key = raw.upper().replace(" ", "")
    video_map = {
        "AVC": "h264",
        "H.264": "h264",
        "HEVC": "hevc",
        "H.265": "hevc",
        "MPEG-4VISUAL": "mpeg4",
        "MPEGVIDEO": "mpeg2video",
        "VP9": "vp9",
        "VP8": "vp8",
        "AV1": "av1",
        "VC-1": "vc1",
    }
    audio_map = {
        "AAC": "aac",
        "AC-3": "ac3",
        "E-AC-3": "eac3",
        "DTS": "dts",
        "MLPFBA": "truehd",
        "TRUEHD": "truehd",
        "FLAC": "flac",
        "OPUS": "opus",
        "MPEGAUDIO": "mp3",
        "PCM": "pcm",
    }
    return (audio_map if audio else video_map).get(key, raw.lower())


def _container_name(value: Any, path: Path) -> str | None:
    if value not in (None, ""):
        raw = str(value).strip()
        key = raw.upper()
        mappings = {
            "MATROSKA": "matroska",
            "WEBM": "webm",
            "MPEG-4": "mp4",
            "QUICKTIME": "mov",
            "AVI": "avi",
            "MPEG-TS": "mpegts",
            "MPEG-PS": "mpeg",
            "WINDOWS MEDIA": "asf",
        }
        if key in mappings:
            return mappings[key]
        return raw.lower()
    return path.suffix.lower().lstrip(".") or None


def normalize_mediainfo(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    tracks = raw.get("media", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]
    general = next((track for track in tracks if track.get("@type") == "General"), {})
    videos = [track for track in tracks if track.get("@type") == "Video"]
    audios = [track for track in tracks if track.get("@type") == "Audio"]
    video = videos[0] if videos else {}
    audio = audios[0] if audios else {}

    width = _integer(_first(video, "Width", "Sampled_Width", "Stored_Width"))
    height = _integer(_first(video, "Height", "Sampled_Height", "Stored_Height"))
    duration = _duration_seconds(_first(general, "Duration", "Duration/String3", "Duration/String"))
    if duration is None:
        duration = _duration_seconds(_first(video, "Duration", "Duration/String3", "Duration/String"))

    languages = sorted(
        {
            str(language).strip()
            for track in audios
            for language in [track.get("Language") or track.get("Language/String")]
            if language not in (None, "")
        }
    )

    return {
        "container": _container_name(_first(general, "Format", "Format/String"), path),
        "duration_seconds": duration,
        "video_codec": _codec_name(_first(video, "Format", "CodecID", "CodecID/Hint")),
        "width": width,
        "height": height,
        "resolution_label": resolution_label(width, height),
        "video_bitrate": _integer(_first(video, "BitRate", "BitRate_Nominal", "BitRate_Maximum")),
        "audio_codec": _codec_name(_first(audio, "Format", "CodecID", "CodecID/Hint"), audio=True),
        "audio_channels": _number(_first(audio, "Channels", "Channel(s)", "ChannelLayout")),
        "audio_languages": ", ".join(languages) or None,
        "raw": raw,
    }


def analyze_media_quick(
    path: Path,
    cancel_event: threading.Event | None = None,
) -> tuple[dict[str, Any], str | None]:
    command = [
        settings.mediainfo_path,
        "--Output=JSON",
        "--Language=raw",
        "--ParseSpeed=0",
        "--File_TestContinuousFileNames=0",
        str(path),
    ]
    try:
        result = _run_hidden(command, settings.max_mediainfo_seconds, cancel_event)
    except FileNotFoundError:
        return {}, "MediaInfo is not installed"
    except subprocess.TimeoutExpired:
        return {}, f"MediaInfo timed out after {settings.max_mediainfo_seconds} seconds"
    if result.returncode != 0:
        return {}, (result.stderr or "MediaInfo failed").strip()[:2000]
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid MediaInfo output: {exc}"
    normalized = normalize_mediainfo(raw, path)
    if not any(
        normalized.get(key) not in (None, "")
        for key in ("container", "duration_seconds", "video_codec", "width", "height", "audio_codec")
    ):
        return {}, "MediaInfo returned no usable technical metadata"
    return normalized, None


def mediainfo_version() -> str:
    try:
        result = _run_hidden([settings.mediainfo_path, "--Version"], 5)
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return lines[0] if lines else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unavailable"
