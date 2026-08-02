from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import reveal_config
from app.models import MediaFile, Movie, MovieSource, Source
from app.schemas.api import (
    DashboardStats, MediaFileOut, MovieDetail, MovieListItem, PaginatedMovies,
    PosterSearchResponse, PosterSearchResult, PosterSelection,
)

from app.services.tmdb import TmdbClient, clean_release_title
from app.services.probe_failures import diagnose_probe_failure

router = APIRouter(tags=["movies"])


def _poster_url(movie: Movie) -> str | None:
    if not movie.poster_path:
        return None
    try:
        revision = int(movie.updated_at.timestamp())
    except Exception:
        revision = 0
    return f"/api/posters/{movie.id}?v={revision}"


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
        conditions.append(
            select(MovieSource.id)
            .where(
                MovieSource.movie_id == Movie.id,
                MovieSource.source_id == source_id,
                MovieSource.active.is_(True),
            )
            .exists()
        )
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
        diagnosis = diagnose_probe_failure(file.probe_error, probe, file.path) if file.probe_error else None
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
                probe_failure_category=diagnosis.category if diagnosis else None,
                probe_failure_title=diagnosis.title if diagnosis else None,
                probe_failure_summary=diagnosis.summary if diagnosis else None,
                probe_failure_suggestions=list(diagnosis.suggestions) if diagnosis else [],
                probe_recommended_action=diagnosis.recommended_action if diagnosis else None,
                probe=probe,
            )
        )
    try:
        metadata = json.loads(movie.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return MovieDetail(**item.model_dump(), metadata=metadata, files=files)


def _movie_metadata(movie: Movie) -> dict:
    try:
        payload = json.loads(movie.metadata_json or "{}")
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _tmdb_for_movie(movie: Movie) -> TmdbClient:
    source = movie.source
    try:
        config = reveal_config(json.loads(source.config_json or "{}")) if source else {}
    except json.JSONDecodeError:
        config = {}
    token = config.get("tmdb_token") or settings.tmdb_api_token
    if not token:
        raise HTTPException(status_code=409, detail="TMDB is not configured for this source")
    return TmdbClient(token)


def _poster_destination(movie: Movie) -> Path:
    return settings.data_dir / "posters" / "library" / f"{movie.id}.jpg"


def _write_manual_poster(movie: Movie, data: bytes, source: str, metadata_update: dict | None = None) -> None:
    destination = _poster_destination(movie)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    movie.poster_path = str(destination)
    metadata = _movie_metadata(movie)
    metadata.update(metadata_update or {})
    metadata["poster_source"] = source
    metadata["poster_match"] = "manual"
    metadata["poster_locked"] = True
    movie.metadata_json = json.dumps(metadata, default=str)


@router.get("/movies/{movie_id}/poster/search", response_model=PosterSearchResponse)
def search_movie_posters(
    movie_id: str,
    q: str | None = None,
    year: int | None = Query(default=None, ge=1870, le=2200),
    include_tv: bool = True,
    limit: int = Query(default=18, ge=1, le=40),
    db: Session = Depends(get_db),
):
    movie = db.scalar(select(Movie).options(selectinload(Movie.source)).where(Movie.id == movie_id))
    if not movie or not movie.active:
        raise HTTPException(status_code=404, detail="Movie not found")
    query = (q or clean_release_title(movie.title)).strip()
    if not query:
        raise HTTPException(status_code=422, detail="Enter a title, IMDb ID, or TMDB ID")
    client = _tmdb_for_movie(movie)
    results = client.search_catalog(query, year if year is not None else movie.year, include_tv=include_tv, limit=limit)
    items: list[PosterSearchResult] = []
    for result in results:
        media_type = str(result.get("_reelindex_media_type") or "movie")
        title = result.get("title") or result.get("name") or "Untitled"
        original = result.get("original_title") or result.get("original_name")
        release = result.get("release_date") or result.get("first_air_date")
        result_year = None
        if release:
            try:
                result_year = int(str(release)[:4])
            except ValueError:
                pass
        poster_path = result.get("poster_path")
        items.append(
            PosterSearchResult(
                tmdb_id=int(result["id"]),
                media_type="tv" if media_type == "tv" else "movie",
                title=str(title),
                original_title=str(original) if original and original != title else None,
                year=result_year,
                overview=result.get("overview"),
                poster_path=poster_path,
                poster_url=f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else None,
                score=round(float(result.get("_reelindex_score") or 0), 4),
            )
        )
    return PosterSearchResponse(query=query, year=year if year is not None else movie.year, results=items)


@router.post("/movies/{movie_id}/poster/tmdb")
def select_tmdb_poster(movie_id: str, payload: PosterSelection, db: Session = Depends(get_db)):
    movie = db.scalar(select(Movie).options(selectinload(Movie.source)).where(Movie.id == movie_id))
    if not movie or not movie.active:
        raise HTTPException(status_code=404, detail="Movie not found")
    client = _tmdb_for_movie(movie)
    result = client.get_title(payload.tmdb_id, payload.media_type)
    if not result:
        raise HTTPException(status_code=404, detail="TMDB title not found")
    poster_path = result.get("poster_path")
    if not poster_path:
        raise HTTPException(status_code=422, detail="The selected TMDB title has no poster")
    destination = _poster_destination(movie)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{movie.id}-{uuid.uuid4().hex}.download")
    try:
        if not client.download_poster(poster_path, temporary):
            raise HTTPException(status_code=502, detail="Could not download the selected poster")
        data = temporary.read_bytes()
    finally:
        temporary.unlink(missing_ok=True)
    title = result.get("title") or result.get("name")
    _write_manual_poster(
        movie,
        data,
        "manual-tmdb",
        {
            "tmdb_id": int(payload.tmdb_id),
            "tmdb_media_type": payload.media_type,
            "poster_selected_title": title,
        },
    )
    if not movie.overview and result.get("overview"):
        movie.overview = result.get("overview")
    db.commit()
    return {"ok": True, "poster_url": _poster_url(movie), "title": title}


@router.post("/movies/{movie_id}/poster/upload")
async def upload_movie_poster(
    movie_id: str,
    poster: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    movie = db.get(Movie, movie_id)
    if not movie or not movie.active:
        raise HTTPException(status_code=404, detail="Movie not found")
    data = await poster.read(10 * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(status_code=422, detail="The selected image is empty")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Poster uploads are limited to 10 MB")
    is_jpeg = data.startswith(b"\xff\xd8\xff")
    is_png = data.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    if not (is_jpeg or is_png or is_webp):
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP image")
    _write_manual_poster(
        movie,
        data,
        "manual-upload",
        {"poster_upload_name": Path(poster.filename or "poster").name[:250]},
    )
    db.commit()
    return {"ok": True, "poster_url": _poster_url(movie)}


@router.delete("/movies/{movie_id}/poster", status_code=204)
def clear_movie_poster(movie_id: str, db: Session = Depends(get_db)):
    movie = db.get(Movie, movie_id)
    if not movie or not movie.active:
        raise HTTPException(status_code=404, detail="Movie not found")
    paths = {Path(movie.poster_path)} if movie.poster_path else set()
    paths.add(_poster_destination(movie))
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    movie.poster_path = None
    metadata = _movie_metadata(movie)
    for key in (
        "poster_source", "poster_match", "poster_locked", "poster_selected_title",
        "poster_upload_name", "tmdb_media_type",
    ):
        metadata.pop(key, None)
    movie.metadata_json = json.dumps(metadata, default=str)
    db.commit()
    return None


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

