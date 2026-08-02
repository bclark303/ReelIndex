from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings
from app.services.media_utils import resolution_label

ProbeProfile = Literal["standard", "extended"]


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


def _ratio(value: Any) -> float | None:
    if not value:
        return None
    text = str(value)
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            denominator = float(right)
            return float(left) / denominator if denominator else None
        except ValueError:
            return None
    return _as_float(value)


def _hidden_process_options() -> dict[str, Any]:
    """Return subprocess options that keep ffprobe invisible on Windows."""
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


class ProbeCancelled(RuntimeError):
    """Raised when an active ffprobe process is cancelled by the scan manager."""


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
                raise ProbeCancelled("ffprobe cancelled")
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


def _probe_limits(path: Path, profile: ProbeProfile) -> tuple[str, str, int]:
    suffix = path.suffix.lower()
    transport = suffix in {".ts", ".m2ts", ".mts", ".mpg", ".mpeg"}
    if profile == "extended":
        return ("96M" if transport else "64M", "40M" if transport else "25M", settings.deep_probe_retry_seconds)
    return ("32M" if transport else "12M", "12M" if transport else "6M", settings.deep_probe_standard_seconds)


def _show_entries(profile: ProbeProfile) -> str:
    stream = (
        "stream=index,codec_type,codec_name,profile,level,width,height,pix_fmt,"
        "color_space,color_transfer,color_primaries,bits_per_raw_sample,bit_rate,"
        "channels,channel_layout,sample_rate,avg_frame_rate,r_frame_rate:"
        "stream_tags=language,title"
    )
    format_fields = "format=format_name,duration,bit_rate,size,start_time"
    if profile == "extended":
        return f"{format_fields}:{stream}:chapter=start_time,end_time:chapter_tags=title"
    return f"{format_fields}:{stream}"


def normalize_ffprobe(raw: dict[str, Any], profile: ProbeProfile) -> dict[str, Any]:
    streams = raw.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    subtitle_streams = [stream for stream in streams if stream.get("codec_type") == "subtitle"]
    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}
    format_info = raw.get("format", {})
    languages = sorted(
        {
            str(stream.get("tags", {}).get("language")).strip()
            for stream in audio_streams
            if stream.get("tags", {}).get("language")
        }
    )
    width = _as_int(video.get("width"))
    height = _as_int(video.get("height"))
    transfer = str(video.get("color_transfer") or "").lower()
    primaries = str(video.get("color_primaries") or "").lower()
    hdr_format = None
    if transfer in {"smpte2084", "arib-std-b67"}:
        hdr_format = "HDR10/PQ" if transfer == "smpte2084" else "HLG"
    elif "bt2020" in primaries:
        hdr_format = "HDR/BT.2020"

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
        "probe_profile": profile,
        "extended": {
            "video_profile": video.get("profile"),
            "video_level": video.get("level"),
            "pixel_format": video.get("pix_fmt"),
            "bit_depth": _as_int(video.get("bits_per_raw_sample")),
            "frame_rate": _ratio(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "color_space": video.get("color_space"),
            "color_transfer": video.get("color_transfer"),
            "color_primaries": video.get("color_primaries"),
            "hdr_format": hdr_format,
            "audio_stream_count": len(audio_streams),
            "subtitle_stream_count": len(subtitle_streams),
            "chapter_count": len(raw.get("chapters", [])),
        },
        "raw": raw,
    }
    return normalized


def probe_media(
    path: Path,
    cancel_event: threading.Event | None = None,
    *,
    profile: ProbeProfile = "standard",
    timeout_override: int | None = None,
) -> tuple[dict[str, Any], str | None]:
    probe_size, analyze_duration, timeout = _probe_limits(path, profile)
    if timeout_override is not None:
        timeout = max(1, int(timeout_override))
    command = [
        settings.ffprobe_path,
        "-hide_banner",
        "-v",
        "error",
        "-probesize",
        probe_size,
        "-analyzeduration",
        analyze_duration,
        "-show_entries",
        _show_entries(profile),
        "-of",
        "json",
        str(path),
    ]
    if profile == "extended":
        command[command.index("-show_entries"):command.index("-show_entries")] = ["-show_chapters"]
    try:
        result = _run_hidden(command, timeout, cancel_event)
    except FileNotFoundError:
        return {}, "ffprobe is not installed"
    except subprocess.TimeoutExpired:
        return {}, f"ffprobe {profile} timed out after {timeout} seconds"
    if result.returncode != 0:
        return {}, (result.stderr or f"ffprobe {profile} failed").strip()[:2000]
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid ffprobe output: {exc}"

    normalized = normalize_ffprobe(raw, profile)
    if not any(
        normalized.get(key) not in (None, "")
        for key in ("container", "duration_seconds", "video_codec", "width", "height", "audio_codec")
    ):
        return {}, f"ffprobe {profile} returned no usable technical metadata"
    return normalized, None


def ffprobe_version() -> str:
    try:
        result = _run_hidden([settings.ffprobe_path, "-version"], 5)
        return result.stdout.splitlines()[0] if result.stdout else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unavailable"
