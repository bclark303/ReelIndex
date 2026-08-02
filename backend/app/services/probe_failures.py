from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProbeFailureDiagnosis:
    category: str
    title: str
    summary: str
    severity: str
    retryable: bool
    recommended_action: str
    suggestions: tuple[str, ...]


def _text(error: str | None, probe: dict[str, Any] | None = None) -> str:
    values = [error or ""]
    marker = (probe or {}).get("_reelindex") if isinstance(probe, dict) else None
    if isinstance(marker, dict):
        values.extend(str(marker.get(key) or "") for key in ("warning", "status", "source"))
    return " ".join(values).strip().lower()


def decode_probe_json(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def diagnose_probe_failure(
    error: str | None,
    probe: dict[str, Any] | None,
    path: str | Path,
) -> ProbeFailureDiagnosis:
    text = _text(error, probe)
    suffix = Path(path).suffix.lower().lstrip(".") or "unknown"

    if "timed out" in text or "timeout" in text or "deferred" in text:
        return ProbeFailureDiagnosis(
            category="timeout",
            title="Probe timed out",
            summary=f"The analyzer did not finish within the configured limit for this {suffix.upper()} file.",
            severity="warning",
            retryable=True,
            recommended_action="retry_auto",
            suggestions=(
                "Retry once after the source is otherwise idle.",
                "For a network share, verify latency and that the file is not being copied or repaired.",
                "Use the extended retry only when the normal retry still fails.",
            ),
        )
    if any(token in text for token in ("not locally accessible", "no such file", "cannot find", "file not found", "path does not exist")):
        return ProbeFailureDiagnosis(
            category="missing_path",
            title="File path is unavailable",
            summary="ReelIndex cannot open the indexed path from the account running the application.",
            severity="error",
            retryable=False,
            recommended_action="check_source",
            suggestions=(
                "Confirm the file still exists at the displayed path.",
                "For mapped drives, launch ReelIndex under the same Windows account that owns the mapping.",
                "Prefer a UNC path or correct the server-to-local path mapping.",
            ),
        )
    if any(token in text for token in ("permission denied", "access is denied", "errno 13", "winerror 5")):
        return ProbeFailureDiagnosis(
            category="permission",
            title="Read access was denied",
            summary="The ReelIndex process can see the path but cannot read enough of the file to analyze it.",
            severity="error",
            retryable=False,
            recommended_action="check_permissions",
            suggestions=(
                "Grant the current Windows user read permission to the file and parent folders.",
                "Check share permissions as well as NTFS permissions.",
                "Retry after confirming the file opens from the same Windows account.",
            ),
        )
    if "ffprobe is not installed" in text or "ffprobe" in text and "not found" in text:
        return ProbeFailureDiagnosis(
            category="analyzer_missing",
            title="Fallback analyzer is unavailable",
            summary="Native parsing was insufficient and the installed ffprobe fallback could not be launched.",
            severity="error",
            retryable=False,
            recommended_action="repair_install",
            suggestions=(
                "Run the latest ReelIndex installer again to repair the bundled analyzer.",
                "Check Diagnostics to confirm ffprobe reports a version instead of unavailable.",
            ),
        )
    if any(token in text for token in ("invalid data", "moov atom not found", "ebml", "matroska", "riff", "asf", "invalid ffprobe output", "unrecognized", "malformed")):
        return ProbeFailureDiagnosis(
            category="container_parse",
            title="Container headers could not be parsed",
            summary=f"The {suffix.upper()} container is unusual, incomplete, or damaged enough that the bounded parser could not identify it.",
            severity="warning",
            retryable=True,
            recommended_action="retry_ffprobe",
            suggestions=(
                "Try the ffprobe compatibility retry from this page.",
                "Verify the movie plays through the affected section in a media player.",
                "If playback is unreliable, remux the file without re-encoding using a trusted media tool.",
            ),
        )
    if any(token in text for token in ("returned no usable", "incomplete metadata", "missing fields", "no technical metadata")):
        return ProbeFailureDiagnosis(
            category="incomplete",
            title="Technical metadata was incomplete",
            summary="The file opened, but the analyzer did not recover enough core video and audio fields.",
            severity="warning",
            retryable=True,
            recommended_action="retry_extended",
            suggestions=(
                "Run an extended retry to inspect a larger bounded sample.",
                "If the result stays incomplete but playback works, keep the file and treat the missing fields as informational.",
                "Remuxing can rebuild sparse or oddly ordered headers without changing the encoded streams.",
            ),
        )
    if any(token in text for token in ("network", "connection", "host is down", "device is not ready", "i/o error", "input/output error", "broken pipe")):
        return ProbeFailureDiagnosis(
            category="network_io",
            title="Network or storage read failed",
            summary="The source stopped responding while ReelIndex was reading the bounded sample.",
            severity="warning",
            retryable=True,
            recommended_action="retry_auto",
            suggestions=(
                "Confirm the NAS or external disk is online and healthy.",
                "Retry while large transfers or parity checks are not running.",
                "Check the Windows event log and storage health if the same file repeatedly fails.",
            ),
        )
    if re.search(r"cancel|interrupted", text):
        return ProbeFailureDiagnosis(
            category="interrupted",
            title="Analysis was interrupted",
            summary="The probe did not complete because the scan or application stopped.",
            severity="info",
            retryable=True,
            recommended_action="retry_auto",
            suggestions=("Retry the file when no other scan is running.",),
        )
    return ProbeFailureDiagnosis(
        category="unknown",
        title="Analyzer reported an unclassified failure",
        summary="The stored error does not match a known ReelIndex failure pattern.",
        severity="warning",
        retryable=True,
        recommended_action="retry_auto",
        suggestions=(
            "Retry the file and review the new error details.",
            "Use the ffprobe compatibility retry if the native retry repeats the same failure.",
            "Export Diagnostics when reporting a repeatable issue.",
        ),
    )


def marker_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    marker = probe.get("_reelindex") if isinstance(probe, dict) else None
    return marker if isinstance(marker, dict) else {}
