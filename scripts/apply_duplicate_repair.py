from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one replacement, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{relative}: missing expected text {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# Preserve punctuation-bearing folder names. pathlib.Path.stem treats every final
# dot in a folder name as an extension separator, so titles such as "Dr. No" and
# "Kill Bill Vol. 1" were truncated before their year could be parsed.
replace_once(
    "backend/app/services/media_utils.py",
    "\n\ndef clean_title(raw: str) -> tuple[str, int | None, str | None]:\n    name = Path(raw).stem\n",
    '''\n\n_MEDIA_FILE_EXTENSIONS = {\n    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".asf",\n    ".ts", ".m2ts", ".mts", ".webm", ".mpg", ".mpeg",\n}\n\n\ndef _title_input_name(raw: str) -> str:\n    """Strip only a recognized media extension, never title punctuation."""\n    name = str(raw or "").replace("\\\\", "/").rsplit("/", 1)[-1]\n    suffix = Path(name).suffix.lower()\n    if suffix in _MEDIA_FILE_EXTENSIONS:\n        return name[: -len(suffix)]\n    return name\n\n\ndef clean_title(raw: str) -> tuple[str, int | None, str | None]:\n    name = _title_input_name(raw)\n''',
)
replace_once(
    "backend/app/services/media_utils.py",
    "    return (name or Path(raw).stem, year, edition)\n",
    "    return (name or _title_input_name(raw), year, edition)\n",
)

# Keep every file owner for ambiguous identity keys. This lets a corrected
# filesystem candidate choose the metadata-compatible Plex/Jellyfin/Emby movie
# instead of being trapped by an older malformed exact-path record.
replace_once(
    "backend/app/services/library_identity.py",
    "        self.file_keys: dict[str, MediaFile | None] = {}\n        self._load()\n",
    "        self.file_keys: dict[str, MediaFile | None] = {}\n        self.file_key_candidates: dict[str, list[MediaFile]] = defaultdict(list)\n        self._load()\n",
)
replace_once(
    "backend/app/services/library_identity.py",
    '''    def _register_movie_keys(self, movie: Movie) -> None:\n        metadata = _json_object(movie.metadata_json)\n        for key in movie_identity_keys(movie.title, movie.year, movie.runtime_seconds, metadata):\n            self._put_unique(self.movie_keys, key, movie)\n        for media_file in movie.files:\n            for key in file_identity_keys(media_file):\n                self._put_unique(self.file_keys, key, media_file)\n\n    def _load(self) -> None:\n''',
    '''    def _register_file_keys(self, media_file: MediaFile) -> None:\n        for key in file_identity_keys(media_file):\n            bucket = self.file_key_candidates[key]\n            if not any(existing.id == media_file.id for existing in bucket):\n                bucket.append(media_file)\n            self._put_unique(self.file_keys, key, media_file)\n\n    def _register_movie_keys(self, movie: Movie) -> None:\n        metadata = _json_object(movie.metadata_json)\n        for key in movie_identity_keys(movie.title, movie.year, movie.runtime_seconds, metadata):\n            self._put_unique(self.movie_keys, key, movie)\n        for media_file in movie.files:\n            self._register_file_keys(media_file)\n\n    def _load(self) -> None:\n''',
)
replace_once(
    "backend/app/services/library_identity.py",
    '''    def register_file(self, media_file: MediaFile) -> None:\n        for key in file_identity_keys(media_file):\n            self._put_unique(self.file_keys, key, media_file)\n''',
    '''    def register_file(self, media_file: MediaFile) -> None:\n        self._register_file_keys(media_file)\n''',
)
replace_once(
    "backend/app/services/library_identity.py",
    '''        for file_candidate in getattr(candidate, "files", []) or []:\n            for key in strong_file_identity_keys(file_candidate):\n                media_file = self.file_keys.get(key)\n                if media_file is not None:\n                    return media_file.movie, None\n        for file_candidate in getattr(candidate, "files", []) or []:\n            for key in trusted_content_identity_keys(file_candidate):\n                media_file = self.file_keys.get(key)\n                if media_file is not None and content_identity_compatible(candidate, media_file.movie):\n                    return media_file.movie, None\n        for key in fallback_keys:\n            movie = self.movie_keys.get(key)\n            if movie is not None:\n                return movie, None\n        return None, None\n''',
    '''        deferred_path_movies: dict[str, Movie] = {}\n        for file_candidate in getattr(candidate, "files", []) or []:\n            for key in strong_file_identity_keys(file_candidate):\n                matches = self.file_key_candidates.get(key, [])\n                compatible = {\n                    media_file.movie.id: media_file.movie\n                    for media_file in matches\n                    if content_identity_compatible(candidate, media_file.movie)\n                }\n                if len(compatible) == 1:\n                    return next(iter(compatible.values())), None\n                unique = {media_file.movie.id: media_file.movie for media_file in matches}\n                if len(unique) == 1:\n                    deferred_path_movies.update(unique)\n        for file_candidate in getattr(candidate, "files", []) or []:\n            for key in trusted_content_identity_keys(file_candidate):\n                compatible = {\n                    media_file.movie.id: media_file.movie\n                    for media_file in self.file_key_candidates.get(key, [])\n                    if content_identity_compatible(candidate, media_file.movie)\n                }\n                if len(compatible) == 1:\n                    return next(iter(compatible.values())), None\n        for key in fallback_keys:\n            movie = self.movie_keys.get(key)\n            if movie is not None:\n                return movie, None\n        if len(deferred_path_movies) == 1:\n            return next(iter(deferred_path_movies.values())), None\n        return None, None\n''',
)
replace_once(
    "backend/app/services/library_identity.py",
    '''    def file_for_candidate(self, source_id: str, movie: Movie, candidate: Any) -> tuple[MediaFile | None, MediaFileSource | None]:\n        source_link = self.source_files.get((source_id, str(candidate.source_file_id)))\n        if source_link:\n            return source_link.media_file, source_link\n        for key in file_identity_keys(candidate):\n            media_file = self.file_keys.get(key)\n            if media_file is not None and media_file.movie_id == movie.id:\n                return media_file, None\n        return None, None\n''',
    '''    def file_for_candidate(self, source_id: str, movie: Movie, candidate: Any) -> tuple[MediaFile | None, MediaFileSource | None]:\n        source_link = self.source_files.get((source_id, str(candidate.source_file_id)))\n        if source_link and source_link.media_file.movie_id == movie.id:\n            return source_link.media_file, source_link\n        for key in file_identity_keys(candidate):\n            matches = [\n                media_file\n                for media_file in self.file_key_candidates.get(key, [])\n                if media_file.movie_id == movie.id\n            ]\n            if len(matches) == 1:\n                return matches[0], source_link\n        if source_link:\n            linked_file = source_link.media_file\n            if not any(link.id != source_link.id for link in linked_file.source_links):\n                linked_file.movie = movie\n                self.db.flush()\n                return linked_file, source_link\n        return None, source_link\n''',
)

# Re-run canonical consolidation only after the scan has refreshed filenames and
# byte counts. Previously startup was the only repair opportunity.
replace_once(
    "backend/app/services/scanner.py",
    "from app.services.library_identity import LibraryIdentityIndex, candidate_fingerprint\n",
    "from app.services.library_identity import (\n    LibraryIdentityIndex,\n    candidate_fingerprint,\n    consolidate_existing_duplicates,\n)\n",
)
replace_once(
    "backend/app/services/scanner.py",
    '''        if mode != "posters":\n            self._fill_missing_runtimes(source_id, cancel_event)\n        self._raise_if_cancelled(cancel_event)\n\n        queue_info = deep_queue_store.info(run_id) if mode == "deep" else {"resumable": False, "queue_remaining": 0}\n''',
    '''        if mode != "posters":\n            self._fill_missing_runtimes(source_id, cancel_event)\n        self._raise_if_cancelled(cancel_event)\n\n        reconcile_started = time.perf_counter()\n        with SessionLocal() as db:\n            reconciled_movies = consolidate_existing_duplicates(db)\n            db.commit()\n        reconcile_elapsed = time.perf_counter() - reconcile_started\n        scan_event_store.append(\n            run_id,\n            "success" if reconciled_movies else "info",\n            "reconcile",\n            (\n                f"Canonical reconciliation merged {reconciled_movies:,} duplicate movie entries "\n                f"in {reconcile_elapsed:.2f}s"\n                if reconciled_movies\n                else f"Canonical reconciliation found no mergeable duplicates in {reconcile_elapsed:.2f}s"\n            ),\n            merged_movies=reconciled_movies,\n            elapsed_ms=round(reconcile_elapsed * 1000),\n        )\n        self._raise_if_cancelled(cancel_event)\n\n        queue_info = deep_queue_store.info(run_id) if mode == "deep" else {"resumable": False, "queue_remaining": 0}\n''',
)

# Release identity. Windows uses an independent packaging revision while the
# backend/UI/Docker application advances to 1.4.9.
(ROOT / "VERSION").write_text("1.4.9\n", encoding="utf-8")
for relative in (
    "README.md",
    "Dockerfile",
    "docker-compose.yml",
    "backend/app/version.py",
    "backend/pyproject.toml",
    "backend/tests/test_release_identity.py",
    "web/index.html",
):
    replace_all(relative, "1.4.8.2", "1.4.9.0") if "1.4.8.2" in (ROOT / relative).read_text(encoding="utf-8") else None
    replace_all(relative, "1.4.8", "1.4.9")
replace_all("windows/installer/installer.go", 'const appVersion = "1.4.8"', 'const appVersion = "1.4.9"')
replace_all("windows/installer/installer.go", 'const packageVersion = "1.4.8.2"', 'const packageVersion = "1.4.9.0"')

# Focused regressions based on the uploaded filesystem and Plex logs.
test_path = ROOT / "backend/tests/test_filesystem_identity_repair.py"
test_path.write_text(r'''from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models import Base, MediaFile, MediaFileSource, Movie, MovieSource, ScanRun, Source
from app.services import scanner as scanner_module
from app.services.library_identity import LibraryIdentityIndex
from app.services.media_utils import clean_title
from app.services.scanner import ScanManager
from app.sources.base import FileCandidate, MovieCandidate
from app.sources.filesystem import FilesystemAdapter


class FakeAdapter:
    discovery_workers = 1

    def __init__(self, candidates: list[MovieCandidate]):
        self.candidates = candidates

    def scan(self, progress=None):
        if progress:
            progress(len(self.candidates), sum(len(movie.files) for movie in self.candidates), "fake")
        return self.candidates

    def fetch_poster(self, candidate, destination):
        return False


def make_session(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'identity-repair.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_clean_title_preserves_dotted_movie_names():
    assert clean_title("Dr. No (1962)")[:2] == ("Dr No", 1962)
    assert clean_title("Mr. Deeds (2002)")[:2] == ("Mr Deeds", 2002)
    assert clean_title("Mrs. Doubtfire (1993)")[:2] == ("Mrs Doubtfire", 1993)
    assert clean_title("Kill Bill Vol. 1 (2003)")[:2] == ("Kill Bill Vol 1", 2003)
    assert clean_title("S. Darko (2009).mkv")[:2] == ("S Darko", 2009)
    assert clean_title("Jackass 3.5 (2011).mkv")[:2] == ("Jackass 3 5", 2011)


def test_filesystem_scan_does_not_collapse_dotted_titles(tmp_path):
    folders = {
        "Dr. No (1962)": "Dr. No (1962) Bluray-1080p.mkv",
        "Dr. Strangelove (1964)": "Dr. Strangelove (1964) Bluray-1080p.mkv",
        "Mr. Deeds (2002)": "Mr. Deeds (2002) Bluray-1080p.mkv",
        "Kill Bill Vol. 1 (2003)": "Kill Bill Vol. 1 (2003) Bluray-1080p.mkv",
        "Kill Bill Vol. 2 (2004)": "Kill Bill Vol. 2 (2004) Bluray-1080p.mkv",
    }
    for folder, filename in folders.items():
        path = tmp_path / folder
        path.mkdir()
        (path / filename).write_bytes(b"movie")

    movies = FilesystemAdapter(str(tmp_path), {"discovery_workers": 1}).scan()
    assert {(movie.title, movie.year, len(movie.files)) for movie in movies} == {
        ("Dr No", 1962, 1),
        ("Dr Strangelove", 1964, 1),
        ("Mr Deeds", 2002, 1),
        ("Kill Bill Vol 1", 2003, 1),
        ("Kill Bill Vol 2", 2004, 1),
    }


def test_corrected_candidate_escapes_legacy_collapsed_movie(tmp_path):
    engine, LocalSession = make_session(tmp_path)
    with LocalSession() as db:
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path=str(tmp_path))
        plex = Source(name="Plex", type="plex", url_or_path="http://plex")
        db.add_all([filesystem, plex])
        db.flush()

        malformed = Movie(
            source_id=filesystem.id,
            source_movie_id="legacy-dr",
            title="Dr",
            sort_title="dr",
            year=None,
        )
        dr_no = Movie(
            source_id=plex.id,
            source_movie_id="plex-dr-no",
            title="Dr. No",
            sort_title="dr. no",
            year=1962,
        )
        strangelove = Movie(
            source_id=plex.id,
            source_movie_id="plex-strangelove",
            title="Dr. Strangelove",
            sort_title="dr. strangelove",
            year=1964,
        )
        db.add_all([malformed, dr_no, strangelove])
        db.flush()
        db.add_all([
            MovieSource(source_id=filesystem.id, movie_id=malformed.id, source_movie_id="legacy-dr"),
            MovieSource(source_id=plex.id, movie_id=dr_no.id, source_movie_id="plex-dr-no"),
            MovieSource(source_id=plex.id, movie_id=strangelove.id, source_movie_id="plex-strangelove"),
        ])

        rows = [
            ("Dr. No (1962) Bluray-1080p.mkv", 8_000_000_000, "fs-dr-no", dr_no, "plex-dr-no-file"),
            ("Dr. Strangelove (1964) Bluray-1080p.mkv", 9_000_000_000, "fs-strangelove", strangelove, "plex-strangelove-file"),
        ]
        for filename, size, fs_file_id, plex_movie, plex_file_id in rows:
            local_path = tmp_path / filename
            malformed_file = MediaFile(
                movie_id=malformed.id,
                source_file_id=fs_file_id,
                path=str(local_path),
                filename=filename,
                size_bytes=size,
            )
            plex_file = MediaFile(
                movie_id=plex_movie.id,
                source_file_id=plex_file_id,
                path=f"/server/{filename}",
                filename=filename,
                size_bytes=size,
            )
            db.add_all([malformed_file, plex_file])
            db.flush()
            db.add_all([
                MediaFileSource(
                    source_id=filesystem.id,
                    media_file_id=malformed_file.id,
                    source_file_id=fs_file_id,
                    path=str(local_path),
                ),
                MediaFileSource(
                    source_id=plex.id,
                    media_file_id=plex_file.id,
                    source_file_id=plex_file_id,
                    path=f"/server/{filename}",
                ),
            ])
        db.commit()

        identity = LibraryIdentityIndex(db)
        seen_movies: set[str] = set()
        seen_files: set[str] = set()
        candidates = [
            MovieCandidate(
                source_movie_id="fixed-dr-no",
                title="Dr No",
                year=1962,
                files=[FileCandidate(
                    source_file_id="fs-dr-no",
                    path=str(tmp_path / rows[0][0]),
                    local_path=tmp_path / rows[0][0],
                    filename=rows[0][0],
                    size_bytes=rows[0][1],
                )],
            ),
            MovieCandidate(
                source_movie_id="fixed-strangelove",
                title="Dr Strangelove",
                year=1964,
                files=[FileCandidate(
                    source_file_id="fs-strangelove",
                    path=str(tmp_path / rows[1][0]),
                    local_path=tmp_path / rows[1][0],
                    filename=rows[1][0],
                    size_bytes=rows[1][1],
                )],
            ),
        ]
        expected = [dr_no.id, strangelove.id]
        for candidate, expected_movie_id in zip(candidates, expected, strict=True):
            movie, _ = identity.movie_for_candidate(filesystem.id, candidate)
            assert movie is not None and movie.id == expected_movie_id
            movie_link = identity.ensure_movie_link(movie, filesystem.id, candidate.source_movie_id)
            seen_movies.add(movie_link.id)
            media_file, source_link = identity.file_for_candidate(filesystem.id, movie, candidate.files[0])
            assert media_file is not None and media_file.movie_id == expected_movie_id
            source_link = identity.ensure_file_link(
                media_file,
                filesystem.id,
                candidate.files[0].source_file_id,
                candidate.files[0].path,
            )
            seen_files.add(source_link.id)

        identity.deactivate_unseen(filesystem.id, seen_movies, seen_files)
        db.commit()
        db.refresh(malformed)
        assert malformed.active is False
        assert db.scalar(select(func.count(Movie.id)).where(Movie.active.is_(True))) == 2
        for target_id in expected:
            active_sources = db.scalars(
                select(MovieSource.source_id).where(
                    MovieSource.movie_id == target_id,
                    MovieSource.active.is_(True),
                )
            ).all()
            assert set(active_sources) == {filesystem.id, plex.id}

    engine.dispose()


def test_post_scan_reconciliation_uses_refreshed_file_sizes(tmp_path, monkeypatch):
    engine, LocalSession = make_session(tmp_path)
    filename = "Alien (1979) Bluray-1080p.mkv"
    size = 42_000_000_000
    local_path = tmp_path / filename
    source_candidates: dict[str, list[MovieCandidate]] = {
        "filesystem": [MovieCandidate(
            source_movie_id="fs-alien",
            title="Alien",
            year=1979,
            files=[FileCandidate(
                source_file_id="fs-file",
                path=str(local_path),
                local_path=local_path,
                filename=filename,
                size_bytes=size,
            )],
        )],
        "plex": [MovieCandidate(
            source_movie_id="plex-alien",
            title="Alien",
            year=1979,
            files=[FileCandidate(
                source_file_id="plex-file",
                path=f"/server/{filename}",
                local_path=local_path,
                filename=filename,
                size_bytes=size,
                technical={"container": "mkv", "video_codec": "h264", "width": 1920, "height": 1080},
            )],
        )],
    }

    with LocalSession() as db:
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path=str(tmp_path))
        plex = Source(name="Plex", type="plex", url_or_path="http://plex")
        db.add_all([filesystem, plex])
        db.flush()
        fs_movie = Movie(source_id=filesystem.id, source_movie_id="fs-alien", title="Alien", sort_title="alien", year=1979)
        plex_movie = Movie(source_id=plex.id, source_movie_id="plex-alien", title="Alien", sort_title="alien", year=1979)
        db.add_all([fs_movie, plex_movie])
        db.flush()
        fs_file = MediaFile(movie_id=fs_movie.id, source_file_id="fs-file", path=str(local_path), filename=filename, size_bytes=None)
        plex_file = MediaFile(movie_id=plex_movie.id, source_file_id="plex-file", path=f"/server/{filename}", filename=filename, size_bytes=None)
        db.add_all([fs_file, plex_file])
        db.flush()
        db.add_all([
            MovieSource(source_id=filesystem.id, movie_id=fs_movie.id, source_movie_id="fs-alien"),
            MovieSource(source_id=plex.id, movie_id=plex_movie.id, source_movie_id="plex-alien"),
            MediaFileSource(source_id=filesystem.id, media_file_id=fs_file.id, source_file_id="fs-file", path=str(local_path)),
            MediaFileSource(source_id=plex.id, media_file_id=plex_file.id, source_file_id="plex-file", path=f"/server/{filename}"),
        ])
        first_run = ScanRun(source_id=filesystem.id)
        second_run = ScanRun(source_id=plex.id)
        db.add_all([first_run, second_run])
        db.commit()
        ids = filesystem.id, plex.id, first_run.id, second_run.id

    monkeypatch.setattr(scanner_module, "SessionLocal", LocalSession)
    monkeypatch.setattr(scanner_module.scan_event_store, "directory", tmp_path / "scan-events")
    monkeypatch.setattr(scanner_module.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(scanner_module.settings, "tmdb_api_token", None)
    monkeypatch.setattr(
        scanner_module,
        "create_adapter",
        lambda source_type, *_args, **_kwargs: FakeAdapter(source_candidates[source_type]),
    )

    manager = ScanManager()
    filesystem_id, plex_id, first_run_id, second_run_id = ids
    manager._execute_scan(filesystem_id, first_run_id, threading.Event(), "posters", "incomplete")
    with LocalSession() as db:
        assert db.scalar(select(func.count(Movie.id))) == 2
    manager._execute_scan(plex_id, second_run_id, threading.Event(), "posters", "incomplete")
    with LocalSession() as db:
        assert db.scalar(select(func.count(Movie.id))) == 1
        assert db.scalar(select(func.count(MediaFile.id))) == 1
        assert db.scalar(select(func.count(MovieSource.id))) == 2
        assert db.scalar(select(func.count(MediaFileSource.id))) == 2

    engine.dispose()
''', encoding="utf-8")

print("Applied filesystem identity and post-scan reconciliation repair")
