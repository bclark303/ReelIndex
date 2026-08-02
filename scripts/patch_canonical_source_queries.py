#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: {label}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


movies = ROOT / "backend" / "app" / "api" / "movies.py"
replace_once(
    movies,
    "from app.models import MediaFile, Movie, Source\n",
    "from app.models import MediaFile, Movie, MovieSource, Source\n",
    "movie source import",
)
replace_once(
    movies,
    "    if source_id:\n        conditions.append(Movie.source_id == source_id)\n",
    '''    if source_id:
        conditions.append(
            select(MovieSource.id)
            .where(
                MovieSource.movie_id == Movie.id,
                MovieSource.source_id == source_id,
                MovieSource.active.is_(True),
            )
            .exists()
        )
''',
    "movie source filter",
)
replace_once(
    movies,
    '''def _poster_destination(movie: Movie) -> Path:
    return settings.data_dir / "posters" / movie.source_id / f"{movie.id}.jpg"
''',
    '''def _poster_destination(movie: Movie) -> Path:
    return settings.data_dir / "posters" / "library" / f"{movie.id}.jpg"
''',
    "canonical poster destination",
)

probes = ROOT / "backend" / "app" / "api" / "probes.py"
replace_once(
    probes,
    "from app.models import MediaFile, Movie, Source\n",
    "from app.models import MediaFile, Movie, MovieSource, Source\n",
    "probe source import",
)
replace_once(
    probes,
    "    if source_id:\n        conditions.append(Movie.source_id == source_id)\n",
    '''    if source_id:
        conditions.append(
            select(MovieSource.id)
            .where(
                MovieSource.movie_id == Movie.id,
                MovieSource.source_id == source_id,
                MovieSource.active.is_(True),
            )
            .exists()
        )
''',
    "probe source filter",
)

scanner = ROOT / "backend" / "app" / "services" / "scanner.py"
replace_once(
    scanner,
    "from app.models import MediaFile, Movie, ScanRun, Source\n",
    "from app.models import MediaFile, Movie, MovieSource, ScanRun, Source\n",
    "scanner source import",
)
replace_once(
    scanner,
    '''                select(Movie)
                .options(selectinload(Movie.files))
                .where(Movie.source_id == source_id, Movie.active.is_(True))
''',
    '''                select(Movie)
                .options(selectinload(Movie.files))
                .where(
                    Movie.active.is_(True),
                    select(MovieSource.id)
                    .where(
                        MovieSource.movie_id == Movie.id,
                        MovieSource.source_id == source_id,
                        MovieSource.active.is_(True),
                    )
                    .exists(),
                )
''',
    "runtime source membership",
)

database = ROOT / "backend" / "app" / "core" / "database.py"
replace_once(
    database,
    "from sqlalchemy.orm import Session, sessionmaker\n",
    "from sqlalchemy.orm import Session, sessionmaker\n",
    "database session import check",
)
replace_once(
    database,
    '''    with SessionLocal() as db:
        upgrade_library_identity(db)
''',
    '''    with Session(bind=engine, autoflush=False, expire_on_commit=False) as db:
        upgrade_library_identity(db)
''',
    "database upgrade session binding",
)

docker = ROOT / ".github" / "workflows" / "docker.yml"
replace_once(
    docker,
    "required={'sources','movies','media_files','scan_runs'}",
    "required={'sources','movies','movie_sources','media_files','media_file_sources','scan_runs'}",
    "docker canonical tables",
)
