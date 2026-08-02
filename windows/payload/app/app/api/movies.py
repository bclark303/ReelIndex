from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models import MediaFile, Movie, Source
from app.schemas.api import DashboardStats, MediaFileOut, MovieDetail, MovieListItem, PaginatedMovies

router = APIRouter(tags=["movies"])


def _poster_url(movie: Movie) -> str | None:
    return f"/api/posters/{movie.id}" if movie.poster_path else None


def _list_item(movie: Movie, source: Source) -> MovieListItem:
    files = [item for item in movie.files if item.active]
    return MovieListItem(
        id=movie.id,
        title=movie.title,
        year=movie.year,
        runtime_seconds=movie.runtime_seconds,
        overview=movie.overview,
        poster_url=_poster_url(movie),
        source_id=source.id,
        source_name=source.name,
        source_type=source.type,
        file_count=len(files),
        total_size_bytes=sum(item.size_bytes or 0 for item in files),
        resolutions=sorted({item.resolution_label for item in files if item.resolution_label}),
        video_codecs=sorted({item.video_codec for item in files if item.video_codec}),
        containers=sorted({item.container for item in files if item.container}),
        has_probe_error=any(bool(item.probe_error) for item in files),
        updated_at=movie.updated_at,
    )


@router.get("/movies", response_model=PaginatedMovies)
def list_movies(
    search: str | None = None,
    source_id: str | None = None,
    resolution: str | None = None,
    codec: str | None = None,
    container: str | None = None,
    missing_poster: bool | None = None,
    multiple_versions: bool | None = None,
    probe_errors: bool | None = None,
    sort: str = Query(default="title", pattern="^(title|year|size|updated)$"),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=48, ge=1, le=200),
    db: Session = Depends(get_db),
):
    conditions = [Movie.active.is_(True)]
    if search:
        terms = [term.strip() for term in search.split() if term.strip()]
        conditions.extend(Movie.title.ilike(f"%{term}%") for term in terms)
    if source_id:
        conditions.append(Movie.source_id == source_id)
    if missing_poster is True:
        conditions.append(Movie.poster_path.is_(None))
    if resolution or codec or container or probe_errors is True:
        file_conditions = [MediaFile.movie_id == Movie.id, MediaFile.active.is_(True)]
        if resolution:
            file_conditions.append(MediaFile.resolution_label == resolution)
        if codec:
            file_conditions.append(MediaFile.video_codec == codec)
        if container:
            file_conditions.append(MediaFile.container == container)
        if probe_errors is True:
            file_conditions.append(MediaFile.probe_error.is_not(None))
        conditions.append(select(MediaFile.id).where(and_(*file_conditions)).exists())
    if multiple_versions is True:
        conditions.append(
            select(func.count(MediaFile.id))
            .where(MediaFile.movie_id == Movie.id, MediaFile.active.is_(True))
            .scalar_subquery()
            > 1
        )

    total = db.scalar(select(func.count(Movie.id)).where(and_(*conditions))) or 0
    stmt = (
        select(Movie)
        .options(selectinload(Movie.files), selectinload(Movie.source))
        .where(and_(*conditions))
    )

    if sort == "year":
        order_columns = [func.coalesce(Movie.year, 0), Movie.sort_title]
    elif sort == "updated":
        order_columns = [Movie.updated_at, Movie.sort_title]
    elif sort == "size":
        size_value = (
            select(func.coalesce(func.sum(MediaFile.size_bytes), 0))
            .where(MediaFile.movie_id == Movie.id, MediaFile.active.is_(True))
            .scalar_subquery()
        )
        order_columns = [size_value, Movie.sort_title]
    else:
        order_columns = [Movie.sort_title]

    order = [column.desc() if direction == "desc" else column.asc() for column in order_columns]
    stmt = stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
    movies = db.scalars(stmt).unique().all()
    items = [_list_item(movie, movie.source) for movie in movies]

    facets = {
        "resolutions": db.scalars(
            select(MediaFile.resolution_label)
            .where(MediaFile.active.is_(True), MediaFile.resolution_label.is_not(None))
            .distinct()
            .order_by(MediaFile.resolution_label)
        ).all(),
        "codecs": db.scalars(
            select(MediaFile.video_codec)
            .where(MediaFile.active.is_(True), MediaFile.video_codec.is_not(None))
            .distinct()
            .order_by(MediaFile.video_codec)
        ).all(),
        "containers": db.scalars(
            select(MediaFile.container)
            .where(MediaFile.active.is_(True), MediaFile.container.is_not(None))
            .distinct()
            .order_by(MediaFile.container)
        ).all(),
    }
    return PaginatedMovies(items=items, total=total, page=page, page_size=page_size, facets=facets)


@router.get("/movies/{movie_id}", response_model=MovieDetail)
def get_movie(movie_id: str, db: Session = Depends(get_db)):
    movie = db.scalar(select(Movie).options(selectinload(Movie.files), selectinload(Movie.source)).where(Movie.id == movie_id))
    if not movie or not movie.active:
        raise HTTPException(status_code=404, detail="Movie not found")
    item = _list_item(movie, movie.source)
    files = []
    for file in movie.files:
        if not file.active:
            continue
        try:
            probe = json.loads(file.probe_json or "{}")
        except json.JSONDecodeError:
            probe = {}
        files.append(
            MediaFileOut(
                id=file.id,
                path=file.path,
                filename=file.filename,
                size_bytes=file.size_bytes,
                modified_ts=file.modified_ts,
                edition=file.edition,
                container=file.container,
                duration_seconds=file.duration_seconds,
                video_codec=file.video_codec,
                width=file.width,
                height=file.height,
                resolution_label=file.resolution_label,
                video_bitrate=file.video_bitrate,
                audio_codec=file.audio_codec,
                audio_channels=file.audio_channels,
                audio_languages=file.audio_languages,
                probe_error=file.probe_error,
                probe=probe,
            )
        )
    try:
        metadata = json.loads(movie.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return MovieDetail(**item.model_dump(), metadata=metadata, files=files)


@router.get("/stats", response_model=DashboardStats)
def stats(db: Session = Depends(get_db)):
    movies = db.scalar(select(func.count(Movie.id)).where(Movie.active.is_(True))) or 0
    source_count = db.scalar(select(func.count(Source.id)).where(Source.enabled.is_(True))) or 0
    files, total_size, probe_errors = db.execute(
        select(
            func.count(MediaFile.id),
            func.coalesce(func.sum(MediaFile.size_bytes), 0),
            func.count(MediaFile.probe_error),
        ).where(MediaFile.active.is_(True))
    ).one()
    resolution_counts = {
        label: count
        for label, count in db.execute(
            select(MediaFile.resolution_label, func.count(MediaFile.id))
            .where(MediaFile.active.is_(True), MediaFile.resolution_label.is_not(None))
            .group_by(MediaFile.resolution_label)
        ).all()
    }
    return DashboardStats(
        movies=movies,
        files=files or 0,
        total_size_bytes=total_size or 0,
        missing_posters=db.scalar(
            select(func.count(Movie.id)).where(Movie.active.is_(True), Movie.poster_path.is_(None))
        )
        or 0,
        probe_errors=probe_errors or 0,
        sources=source_count,
        resolutions=resolution_counts,
    )

