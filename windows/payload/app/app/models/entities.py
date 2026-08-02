from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    url_or_path: Mapped[str] = mapped_column(Text, nullable=False)
    library_id: Mapped[str | None] = mapped_column(String(200))
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schedule_minutes: Mapped[int] = mapped_column(Integer, default=360, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    movies: Mapped[list[Movie]] = relationship(back_populates="source", cascade="all, delete-orphan")
    scan_runs: Mapped[list[ScanRun]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Movie(Base):
    __tablename__ = "movies"
    __table_args__ = (
        UniqueConstraint("source_id", "source_movie_id", name="uq_movie_source_external"),
        Index("ix_movies_title", "title"),
        Index("ix_movies_active", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    source_movie_id: Mapped[str] = mapped_column(String(250), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sort_title: Mapped[str] = mapped_column(String(300), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    runtime_seconds: Mapped[float | None] = mapped_column(Float)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_path: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    source: Mapped[Source] = relationship(back_populates="movies")
    files: Mapped[list[MediaFile]] = relationship(back_populates="movie", cascade="all, delete-orphan")


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (
        UniqueConstraint("movie_id", "source_file_id", name="uq_file_movie_external"),
        Index("ix_media_files_active", "active"),
        Index("ix_media_files_resolution", "resolution_label"),
        Index("ix_media_files_codec", "video_codec"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    source_file_id: Mapped[str] = mapped_column(String(300), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    modified_ts: Mapped[float | None] = mapped_column(Float)
    fingerprint: Mapped[str | None] = mapped_column(String(300))
    edition: Mapped[str | None] = mapped_column(String(160))
    container: Mapped[str | None] = mapped_column(String(40))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    video_codec: Mapped[str | None] = mapped_column(String(80))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    resolution_label: Mapped[str | None] = mapped_column(String(30))
    video_bitrate: Mapped[int | None] = mapped_column(Integer)
    audio_codec: Mapped[str | None] = mapped_column(String(80))
    audio_channels: Mapped[float | None] = mapped_column(Float)
    audio_languages: Mapped[str | None] = mapped_column(String(300))
    probe_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    probe_error: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    movie: Mapped[Movie] = relationship(back_populates="files")


class ScanRun(Base):
    __tablename__ = "scan_runs"
    __table_args__ = (Index("ix_scan_runs_started", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_item: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[Source] = relationship(back_populates="scan_runs")
