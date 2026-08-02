from __future__ import annotations

import hashlib
import re
from pathlib import Path

YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
EDITION_PATTERNS = [
    (re.compile(r"\bextended(?:\s+edition|\s+cut)?\b", re.I), "Extended Edition"),
    (re.compile(r"\bdirector'?s\s+cut\b", re.I), "Director's Cut"),
    (re.compile(r"\btheatrical(?:\s+cut)?\b", re.I), "Theatrical Cut"),
    (re.compile(r"\bunrated\b", re.I), "Unrated"),
    (re.compile(r"\bremaster(?:ed)?\b", re.I), "Remastered"),
    (re.compile(r"\bimax\b", re.I), "IMAX"),
    (re.compile(r"\bopen\s*matte\b", re.I), "Open Matte"),
    (re.compile(r"\bfinal\s+cut\b", re.I), "Final Cut"),
]
NOISE_RE = re.compile(
    r"\b(?:2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|web[- .]?dl|webrip|hdr10\+?|dolby[ .]?vision|dv|x26[45]|h\.?26[45]|hevc|avc|remux|aac|dts(?:-hd)?|truehd|atmos|proper|repack)\b.*$",
    re.I,
)


def clean_title(raw: str) -> tuple[str, int | None, str | None]:
    name = Path(raw).stem
    name = re.sub(r"[._]+", " ", name)
    edition = None
    for pattern, label in EDITION_PATTERNS:
        if pattern.search(name):
            edition = label
            name = pattern.sub(" ", name)
            break
    year_matches = list(YEAR_RE.finditer(name))
    year_match = year_matches[-1] if year_matches else None
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        name = name[: year_match.start()] + " " + name[year_match.end() :]
    name = NOISE_RE.sub("", name)
    name = re.sub(r"[\[\](){}]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" -")
    return (name or Path(raw).stem, year, edition)


def normalized_movie_key(title: str, year: int | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", title.lower())
    return f"{normalized}:{year or 0}"


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def sort_title(title: str) -> str:
    lowered = title.strip().lower()
    for article in ("the ", "a ", "an "):
        if lowered.startswith(article):
            return lowered[len(article) :] + ", " + article.strip()
    return lowered


def resolution_label(width: int | None, height: int | None) -> str | None:
    if not width and not height:
        return None
    value = max(width or 0, height or 0)
    vertical = min(width or 99999, height or 99999)
    if value >= 7000 or vertical >= 4000:
        return "8K"
    if value >= 3800 or vertical >= 2000:
        return "4K"
    if vertical >= 1000:
        return "1080p"
    if vertical >= 700:
        return "720p"
    if vertical >= 560:
        return "576p"
    if vertical >= 460:
        return "480p"
    return f"{vertical}p" if vertical and vertical < 99999 else None


def map_remote_path(path: str, mappings: list[dict[str, str]]) -> Path | None:
    normalized = path.replace("\\", "/")
    for mapping in mappings:
        remote = str(mapping.get("remote", "")).replace("\\", "/").rstrip("/")
        local = str(mapping.get("local", "")).rstrip("/")
        if remote and normalized.lower().startswith(remote.lower()):
            suffix = normalized[len(remote) :].lstrip("/")
            return Path(local) / suffix
    candidate = Path(path)
    return candidate if candidate.exists() else None
