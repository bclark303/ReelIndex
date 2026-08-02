from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SourceType = Literal["filesystem", "plex", "jellyfin", "emby"]


class SourceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: SourceType
    url_or_path: str = Field(min_length=1)
    library_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    schedule_enabled: bool = False
    schedule_minutes: int = Field(default=360, ge=60, le=10080)
    enabled: bool = True

    @field_validator("url_or_path")
    @classmethod
    def trim_location(cls, value: str) -> str:
        return value.strip().rstrip("/") if value.startswith(("http://", "https://")) else value.strip()


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    type: SourceType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url_or_path: str | None = None
    library_id: str | None = None
    config: dict[str, Any] | None = None
    schedule_enabled: bool | None = None
    schedule_minutes: int | None = Field(default=None, ge=60, le=10080)
    enabled: bool | None = None


class SourceOut(SourceBase):
    id: str
    created_at: datetime
    updated_at: datetime
    movie_count: int = 0
    last_scan_status: str | None = None
    last_scan_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ConnectionTest(BaseModel):
    type: SourceType
    url_or_path: str
    library_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionResult(BaseModel):
    ok: bool
    message: str
    libraries: list[dict[str, str]] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class MediaFileOut(BaseModel):
    id: str
    path: str
    filename: str
    size_bytes: int | None
    modified_ts: float | None
    edition: str | None
    container: str | None
    duration_seconds: float | None
    video_codec: str | None
    width: int | None
    height: int | None
    resolution_label: str | None
    video_bitrate: int | None
    audio_codec: str | None
    audio_channels: float | None
    audio_languages: str | None
    probe_error: str | None
    probe_failure_category: str | None = None
    probe_failure_title: str | None = None
    probe_failure_summary: str | None = None
    probe_failure_suggestions: list[str] = Field(default_factory=list)
    probe_recommended_action: str | None = None
    probe: dict[str, Any] = Field(default_factory=dict)


class MovieListItem(BaseModel):
    id: str
    title: str
    year: int | None
    runtime_seconds: float | None
    overview: str | None
    poster_url: str | None
    source_id: str
    source_name: str
    source_type: str
    file_count: int
    total_size_bytes: int
    resolutions: list[str]
    video_codecs: list[str]
    containers: list[str]
    has_probe_error: bool
    updated_at: datetime


class MovieDetail(MovieListItem):
    metadata: dict[str, Any] = Field(default_factory=dict)
    files: list[MediaFileOut] = Field(default_factory=list)


class PaginatedMovies(BaseModel):
    items: list[MovieListItem]
    total: int
    page: int
    page_size: int
    facets: dict[str, list[str]]


class ScanRunOut(BaseModel):
    id: str
    source_id: str
    source_name: str | None = None
    status: str
    discovered_count: int
    analyzed_count: int
    cached_count: int
    error_count: int
    current_item: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    resumable: bool = False
    queue_remaining: int = 0
    queue_total: int = 0
    scan_mode: str | None = None
    scan_scope: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DashboardStats(BaseModel):
    movies: int
    files: int
    total_size_bytes: int
    missing_posters: int
    probe_errors: int
    sources: int
    resolutions: dict[str, int]


class DiagnosticsOut(BaseModel):
    app: dict[str, Any]
    system: dict[str, Any]
    database: dict[str, Any]
    sources: list[dict[str, Any]]
    recent_scans: list[dict[str, Any]]
    logging: dict[str, Any] = {}


class PosterSearchResult(BaseModel):
    tmdb_id: int
    media_type: Literal["movie", "tv"]
    title: str
    original_title: str | None = None
    year: int | None = None
    overview: str | None = None
    poster_path: str | None = None
    poster_url: str | None = None
    score: float | None = None


class PosterSearchResponse(BaseModel):
    query: str
    year: int | None = None
    results: list[PosterSearchResult] = Field(default_factory=list)


class PosterSelection(BaseModel):
    tmdb_id: int = Field(gt=0)
    media_type: Literal["movie", "tv"] = "movie"


class ProbeFailureItem(BaseModel):
    file_id: str
    movie_id: str
    movie_title: str
    movie_year: int | None = None
    source_id: str
    source_name: str
    filename: str
    path: str
    size_bytes: int | None = None
    container: str | None = None
    error: str
    category: str
    diagnosis_title: str
    diagnosis_summary: str
    severity: Literal["info", "warning", "error"]
    retryable: bool
    recommended_action: str
    suggestions: list[str] = Field(default_factory=list)
    analysis_source: str | None = None
    analysis_profile: str | None = None
    analysis_status: str | None = None
    attempt_count: int = 0
    deep_attempt_count: int = 0
    attempted_at: str | None = None
    updated_at: datetime


class ProbeFailureSummary(BaseModel):
    total: int
    by_category: dict[str, int] = Field(default_factory=dict)
    by_container: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)


class PaginatedProbeFailures(BaseModel):
    items: list[ProbeFailureItem]
    total: int
    page: int
    page_size: int
    summary: ProbeFailureSummary


class ProbeRetryRequest(BaseModel):
    strategy: Literal["auto", "extended", "ffprobe"] = "auto"


class ProbeRetryResponse(BaseModel):
    ok: bool
    file_id: str
    strategy: str
    message: str
    resolved: bool
    error: str | None = None
    analysis_source: str | None = None
