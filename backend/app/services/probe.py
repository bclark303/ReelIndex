from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings
from app.services.media_utils import resolution_label
from app.services.matroska import MatroskaParseError, parse_matroska_header

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


def _stage_header_copy(
    source: Path,
    byte_limit: int,
    timeout: int,
    cancel_event: threading.Event | None = None,
) -> tuple[Path | None, int, float, str | None]:
    """Copy a bounded, sequential header window to local storage.

    The copy runs in a child Python process so a blocked SMB read can be killed
    at the timeout instead of pinning a scanner worker indefinitely.
    """
    stage_dir = settings.data_dir / "probe-stage"
    stage_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix="reelindex-header-", suffix=source.suffix.lower(), dir=stage_dir
    )
    os.close(fd)
    temporary = Path(temporary_name)
    script = (
        "import sys\n"
        "source, destination, remaining = sys.argv[1], sys.argv[2], int(sys.argv[3])\n"
        "with open(source, 'rb', buffering=0) as src, open(destination, 'wb', buffering=0) as dst:\n"
        "    while remaining > 0:\n"
        "        block = src.read(min(262144, remaining))\n"
        "        if not block: break\n"
        "        dst.write(block)\n"
        "        remaining -= len(block)\n"
    )
    started = time.perf_counter()
    try:
        result = _run_hidden(
            [sys.executable, "-c", script, str(source), str(temporary), str(byte_limit)],
            timeout,
            cancel_event,
        )
    except subprocess.TimeoutExpired:
        temporary.unlink(missing_ok=True)
        return None, 0, time.perf_counter() - started, (
            f"Matroska header staging timed out after {timeout} seconds"
        )
    except FileNotFoundError as exc:
        temporary.unlink(missing_ok=True)
        return None, 0, time.perf_counter() - started, str(exc)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        return None, 0, time.perf_counter() - started, (
            result.stderr or "Matroska header staging failed"
        ).strip()[:2000]
    copied = temporary.stat().st_size if temporary.exists() else 0
    if copied < 4096:
        temporary.unlink(missing_ok=True)
        return None, copied, time.perf_counter() - started, (
            "Matroska header staging returned too little data"
        )
    return temporary, copied, time.perf_counter() - started, None


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
        return (
            "96M" if transport else "64M",
            "40M" if transport else "25M",
            settings.deep_probe_retry_seconds,
        )

    # Standard deep analysis only needs container and track headers. Matroska
    # stores these near the beginning of the file, so a smaller bounded read is
    # substantially friendlier to SMB shares than the previous generic 12M/6M
    # limits. A successful-but-incomplete result can still escalate to extended.
    if suffix in {".mkv", ".webm"}:
        return ("4M", "2M", settings.deep_probe_standard_seconds)
    if suffix in {".mp4", ".m4v", ".mov", ".avi", ".wmv"}:
        return ("8M", "4M", settings.deep_probe_standard_seconds)
    return (
        "32M" if transport else "12M",
        "12M" if transport else "6M",
        settings.deep_probe_standard_seconds,
    )


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


def _matroska_core_complete(value: dict[str, Any]) -> bool:
    required = (
        "duration_seconds",
        "video_codec",
        "width",
        "height",
        "audio_codec",
        "audio_channels",
    )
    return all(value.get(key) not in (None, "") for key in required)


def _merge_probe_values(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in fallback.items():
        if key == "raw":
            continue
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    merged["raw"] = {
        "matroska_header": primary.get("raw"),
        "ffprobe": fallback.get("raw"),
    }
    return merged


def probe_media(
    path: Path,
    cancel_event: threading.Event | None = None,
    *,
    profile: ProbeProfile = "standard",
    timeout_override: int | None = None,
    stage_matroska: bool = False,
    stage_bytes: int | None = None,
    source_size_bytes: int | None = None,
) -> tuple[dict[str, Any], str | None]:
    probe_size, analyze_duration, timeout = _probe_limits(path, profile)
    if timeout_override is not None:
        timeout = max(1, int(timeout_override))

    staged_path: Path | None = None
    input_path = path
    stage_elapsed = 0.0
    native_elapsed = 0.0
    copied_bytes = 0
    native: dict[str, Any] = {}
    native_error: str | None = None
    is_matroska = path.suffix.lower() in {".mkv", ".webm"}

    if stage_matroska and is_matroska:
        initial_limit = max(65536, int(stage_bytes or settings.deep_probe_stage_bytes))
        limits = [initial_limit]
        retry_limit = max(initial_limit, int(settings.deep_probe_retry_stage_bytes))
        if profile == "standard" and retry_limit > initial_limit:
            limits.append(retry_limit)

        for index, limit in enumerate(limits):
            previous_staged = staged_path
            candidate_path, candidate_bytes, candidate_elapsed, stage_error = _stage_header_copy(
                path, limit, settings.deep_probe_stage_seconds, cancel_event
            )
            if previous_staged and previous_staged != candidate_path:
                previous_staged.unlink(missing_ok=True)
            stage_elapsed += candidate_elapsed
            if stage_error or not candidate_path:
                native_error = stage_error or "Matroska header staging failed"
                if native:
                    native["analysis_warning"] = native_error
                    native["probe_transport"] = "native-matroska-header"
                    return native, None
                return {}, native_error

            staged_path = candidate_path
            copied_bytes = candidate_bytes
            input_path = staged_path
            parse_started = time.perf_counter()
            try:
                parsed = parse_matroska_header(staged_path)
                native_elapsed += time.perf_counter() - parse_started
                if parsed:
                    native = _merge_probe_values(native, parsed) if native else parsed
            except MatroskaParseError as exc:
                native_elapsed += time.perf_counter() - parse_started
                native_error = str(exc)
                # A valid Matroska file always exposes its EBML and Segment
                # headers at the beginning. A larger copy does not repair an
                # unreadable header, so fall back locally without repeating SMB I/O.
                break

            if native:
                duration = native.get("duration_seconds")
                if source_size_bytes and duration:
                    native["video_bitrate"] = int((int(source_size_bytes) * 8) / float(duration))
                native["probe_transport"] = "native-matroska-header"
                native["probe_profile"] = profile
                native["probe_diagnostics"] = {
                    "staged_header_bytes": copied_bytes,
                    "staging_seconds": round(stage_elapsed, 3),
                    "native_parse_seconds": round(native_elapsed, 4),
                    "local_probe_seconds": 0.0,
                    "stage_passes": index + 1,
                }
                if isinstance(native.get("raw"), dict):
                    native["raw"]["reelindex_staging"] = native["probe_diagnostics"]
                if _matroska_core_complete(native):
                    staged_path.unlink(missing_ok=True)
                    return native, None

        # Native parsing was incomplete. Keep the largest local fragment as a
        # compatibility fallback, but never return an empty result when the
        # Matroska header already yielded useful fields.
        timeout = min(timeout, max(1, int(settings.deep_probe_local_seconds)))
        probe_size = f"{max(1, copied_bytes // (1024 * 1024))}M"
        analyze_duration = "0"

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
        str(input_path),
    ]
    if staged_path:
        # A truncated local fragment must not make ffprobe wait for packets that
        # can only exist later in the full movie.
        command[command.index("-show_entries"):command.index("-show_entries")] = [
            "-read_intervals", "%+#1"
        ]
    if profile == "extended":
        command[command.index("-show_entries"):command.index("-show_entries")] = ["-show_chapters"]

    probe_started = time.perf_counter()
    try:
        result = _run_hidden(command, timeout, cancel_event)
    except FileNotFoundError:
        if native:
            native["analysis_warning"] = "ffprobe is not installed; native Matroska metadata is partial"
            return native, None
        return {}, "ffprobe is not installed"
    except subprocess.TimeoutExpired:
        if native:
            native["analysis_warning"] = (
                f"Native Matroska metadata is partial; ffprobe {profile} timed out after {timeout} seconds"
            )
            return native, None
        return {}, f"ffprobe {profile} timed out after {timeout} seconds"
    finally:
        if staged_path:
            staged_path.unlink(missing_ok=True)
    probe_elapsed = time.perf_counter() - probe_started

    if result.returncode != 0:
        error = (result.stderr or f"ffprobe {profile} failed").strip()[:2000]
        if native:
            native["analysis_warning"] = f"Native Matroska metadata is partial; {error}"
            return native, None
        return {}, error
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        if native:
            native["analysis_warning"] = f"Native Matroska metadata is partial; invalid ffprobe output: {exc}"
            return native, None
        return {}, f"Invalid ffprobe output: {exc}"

    normalized = normalize_ffprobe(raw, profile)
    if native:
        normalized = _merge_probe_values(native, normalized)
    if staged_path or native:
        duration = normalized.get("duration_seconds")
        if source_size_bytes and duration:
            normalized["video_bitrate"] = int((int(source_size_bytes) * 8) / float(duration))
        normalized["probe_transport"] = (
            "native-matroska-header+ffprobe" if native else "local-matroska-header"
        )
        normalized["probe_diagnostics"] = {
            "staged_header_bytes": copied_bytes,
            "staging_seconds": round(stage_elapsed, 3),
            "native_parse_seconds": round(native_elapsed, 4),
            "local_probe_seconds": round(probe_elapsed, 3),
        }
        if isinstance(normalized.get("raw"), dict):
            normalized["raw"]["reelindex_staging"] = normalized["probe_diagnostics"]
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
