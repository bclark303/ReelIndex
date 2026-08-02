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


identity = ROOT / "backend" / "app" / "services" / "library_identity.py"
replace_once(
    identity,
    '''def normalize_title(value: str | None) -> str:
    """Return a stable title token suitable for cross-source comparisons."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())
''',
    '''def normalize_title(value: str | None) -> str:
    """Return a stable title token suitable for cross-source comparisons."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    # Filesystem folder names commonly preserve an IMDb ID and sort articles at
    # the end (for example ``12 Angry Men tt0050083`` or ``Abyss, The``).
    text = re.sub(r"\\btt\\d{5,}\\b", " ", text)
    article = re.fullmatch(r"\\s*(.*?)\\s*,\\s*(the|an|a)\\s*", text)
    if article:
        text = f"{article.group(2)} {article.group(1)}"
    return "".join(character for character in text if character.isalnum())
''',
    "title alias normalization",
)
replace_once(
    identity,
    '''def strong_file_identity_keys(candidate_or_file: Any) -> set[str]:
    """Physical-path keys safe enough to establish movie identity."""
    return {key for key in file_identity_keys(candidate_or_file) if key.startswith("path:")}


def candidate_fingerprint(candidate: Any) -> str:
''',
    '''def strong_file_identity_keys(candidate_or_file: Any) -> set[str]:
    """Physical-path keys safe enough to establish movie identity."""
    return {key for key in file_identity_keys(candidate_or_file) if key.startswith("path:")}


_MIN_TRUSTED_CONTENT_SIZE = 64 * 1024 * 1024
_GENERIC_CONTENT_STEMS = {
    "movie", "video", "feature", "main", "title", "file", "media",
    "sample", "trailer", "preview", "teaser", "extra", "extras", "bonus",
    "disc1", "disc2", "disk1", "disk2", "cd1", "cd2", "part1", "part2",
}
_EXCLUDED_CONTENT_TOKENS = {"sample", "trailer", "preview", "teaser", "featurette", "extras", "bonus"}


def trusted_content_identity_keys(candidate_or_file: Any) -> set[str]:
    """Exact filename/size keys suitable for cross-source movie matching.

    Paths exposed by Plex/Jellyfin/Emby often differ from the container's
    filesystem path. An exact basename and byte count is therefore the shared
    physical signal, but only for substantial, non-generic feature files.
    """
    _paths, filename, size, _modified = _file_values(candidate_or_file)
    if not filename or size is None or size < _MIN_TRUSTED_CONTENT_SIZE:
        return set()
    normalized_name = Path(filename.replace("\\\\", "/")).name.casefold()
    stem = Path(normalized_name).stem
    compact = re.sub(r"[^a-z0-9]+", "", stem)
    tokens = {token for token in re.split(r"[^a-z0-9]+", stem) if token}
    if len(compact) < 4 or compact in _GENERIC_CONTENT_STEMS or tokens & _EXCLUDED_CONTENT_TOKENS:
        return set()
    return {f"name-size:{normalized_name}:{int(size)}"}


def content_identity_compatible(left: Any, right: Any) -> bool:
    """Guard a content-signature match against conflicting movie metadata."""
    left_year = getattr(left, "year", None)
    right_year = getattr(right, "year", None)
    if left_year and right_year:
        return int(left_year) == int(right_year)
    left_title = normalize_title(getattr(left, "title", None))
    right_title = normalize_title(getattr(right, "title", None))
    return bool(left_title and left_title == right_title)


def candidate_fingerprint(candidate: Any) -> str:
''',
    "trusted content identity helpers",
)
replace_once(
    identity,
    '''        # Provider IDs are strongest, followed by a physical-file match and then
        # normalized title/year or title/runtime.
''',
    '''        # Provider IDs are strongest, followed by a physical path, a guarded
        # exact filename/byte-size signature, and finally normalized title metadata.
''',
    "identity priority comment",
)
replace_once(
    identity,
    '''        for file_candidate in getattr(candidate, "files", []) or []:
            for key in strong_file_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None:
                    return media_file.movie, None
        for key in fallback_keys:
''',
    '''        for file_candidate in getattr(candidate, "files", []) or []:
            for key in strong_file_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None:
                    return media_file.movie, None
        for file_candidate in getattr(candidate, "files", []) or []:
            for key in trusted_content_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None and content_identity_compatible(candidate, media_file.movie):
                    return media_file.movie, None
        for key in fallback_keys:
''',
    "candidate content signature match",
)
replace_once(
    identity,
    '''    title_groups: dict[str, list[Movie]] = defaultdict(list)
    for movie in movies:
''',
    '''    # Repair already-created cross-source duplicates whose server and
    # filesystem paths differ but whose substantial feature file has the exact
    # same basename and byte count. Conflicting years and generic extras remain
    # separate.
    content_groups: dict[str, list[Movie]] = defaultdict(list)
    for movie in movies:
        for media_file in movie.files:
            for key in trusted_content_identity_keys(media_file):
                content_groups[key].append(movie)
    for group in content_groups.values():
        unique = list({movie.id: movie for movie in group}.values())
        if len(unique) < 2:
            continue
        canonical = unique[0]
        for duplicate in unique[1:]:
            if canonical not in db or duplicate not in db:
                continue
            if _source_ids(canonical) & _source_ids(duplicate):
                continue
            if not content_identity_compatible(canonical, duplicate):
                continue
            canonical = merge_movies(db, canonical, duplicate)
            merged_count += 1

    db.flush()
    movies = db.scalars(
        select(Movie)
        .options(
            selectinload(Movie.source_links),
            selectinload(Movie.files).selectinload(MediaFile.source_links),
        )
        .order_by(Movie.created_at, Movie.id)
    ).all()
    title_groups: dict[str, list[Movie]] = defaultdict(list)
    for movie in movies:
''',
    "existing content signature consolidation",
)

# Regression tests based on the user's filesystem/Plex scan mismatch patterns.
tests = ROOT / "backend" / "tests" / "test_global_library_identity.py"
replace_once(
    tests,
    "from app.services.library_identity import upgrade_library_identity\n",
    "from app.services.library_identity import LibraryIdentityIndex, upgrade_library_identity\n",
    "identity index test import",
)
marker = "\ndef test_filename_and_size_alone_do_not_merge_different_movies(tmp_path):\n"
text = tests.read_text(encoding="utf-8")
if marker not in text:
    raise RuntimeError("identity test insertion point not found")
new_tests = r'''

def test_trusted_content_signature_matches_title_aliases(tmp_path):
    engine, LocalSession = make_session(tmp_path)
    with LocalSession() as db:
        plex = Source(name="Plex", type="plex", url_or_path="http://plex")
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path="/media")
        db.add_all([plex, filesystem])
        db.flush()
        movie = Movie(
            source_id=plex.id,
            source_movie_id="plex-wave",
            title="The 5th Wave",
            sort_title="5th wave",
            year=2016,
        )
        db.add(movie)
        db.flush()
        db.add(
            MediaFile(
                movie_id=movie.id,
                source_file_id="plex-part",
                path="/server/movies/The 5th Wave (2016) Bluray-1080p.mkv",
                filename="The 5th Wave (2016) Bluray-1080p.mkv",
                size_bytes=8_765_432_100,
            )
        )
        db.commit()
        upgrade_library_identity(db)

        candidate = MovieCandidate(
            source_movie_id="filesystem-wave",
            title="5th Wave, The",
            year=2016,
            files=[
                FileCandidate(
                    source_file_id="filesystem-file",
                    path="/media/The 5th Wave (2016) Bluray-1080p.mkv",
                    filename="The 5th Wave (2016) Bluray-1080p.mkv",
                    size_bytes=8_765_432_100,
                )
            ],
        )
        matched, source_link = LibraryIdentityIndex(db).movie_for_candidate(filesystem.id, candidate)
        assert matched is not None and matched.id == movie.id
        assert source_link is None

    engine.dispose()


def test_startup_merges_exact_content_despite_title_aliases(tmp_path):
    engine, LocalSession = make_session(tmp_path)
    with LocalSession() as db:
        plex = Source(name="Plex", type="plex", url_or_path="http://plex")
        filesystem = Source(name="Filesystem", type="filesystem", url_or_path="/media")
        db.add_all([plex, filesystem])
        db.flush()
        first = Movie(
            source_id=plex.id,
            source_movie_id="plex-angry-men",
            title="12 Angry Men",
            sort_title="12 angry men",
            year=1957,
        )
        second = Movie(
            source_id=filesystem.id,
            source_movie_id="fs-angry-men",
            title="12 Angry Men tt0050083",
            sort_title="12 angry men tt0050083",
            year=1957,
        )
        db.add_all([first, second])
        db.flush()
        filename = "12 Angry Men (1957) Bluray-1080p.mkv"
        db.add_all([
            MediaFile(
                movie_id=first.id,
                source_file_id="plex-file",
                path=f"/server/movies/{filename}",
                filename=filename,
                size_bytes=9_000_000_000,
            ),
            MediaFile(
                movie_id=second.id,
                source_file_id="fs-file",
                path=f"/media/{filename}",
                filename=filename,
                size_bytes=9_000_000_000,
            ),
        ])
        db.commit()

        assert upgrade_library_identity(db) == 1
        assert db.scalar(select(func.count(Movie.id))) == 1
        assert db.scalar(select(func.count(MediaFile.id))) == 1

    engine.dispose()


def test_generic_extra_signature_never_merges_movies(tmp_path):
    engine, LocalSession = make_session(tmp_path)
    with LocalSession() as db:
        first_source = Source(name="One", type="filesystem", url_or_path="/one")
        second_source = Source(name="Two", type="plex", url_or_path="http://plex")
        db.add_all([first_source, second_source])
        db.flush()
        first = Movie(source_id=first_source.id, source_movie_id="one", title="Alpha", sort_title="alpha", year=2020)
        second = Movie(source_id=second_source.id, source_movie_id="two", title="Beta", sort_title="beta", year=2020)
        db.add_all([first, second])
        db.flush()
        db.add_all([
            MediaFile(movie_id=first.id, source_file_id="one-file", path="/one/sample.avi", filename="sample.avi", size_bytes=500_000_000),
            MediaFile(movie_id=second.id, source_file_id="two-file", path="/two/sample.avi", filename="sample.avi", size_bytes=500_000_000),
        ])
        db.commit()

        assert upgrade_library_identity(db) == 0
        assert db.scalar(select(func.count(Movie.id))) == 2

    engine.dispose()
'''
tests.write_text(text.replace(marker, new_tests + marker, 1), encoding="utf-8")

# Publish as v1.4.8. Docker workflow assertions are updated separately through
# the repository API because workflow files require distinct GitHub permission.
release_files = (
    "VERSION",
    "README.md",
    "Dockerfile",
    "docker-compose.yml",
    "backend/app/version.py",
    "backend/pyproject.toml",
    "backend/tests/test_release_identity.py",
    "web/index.html",
    "windows/installer/installer.go",
    "windows/installer/install-runtime.ps1",
)
for relative in release_files:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if "1.4.7" not in text:
        raise RuntimeError(f"{relative}: expected v1.4.7 release identity")
    path.write_text(text.replace("1.4.7", "1.4.8"), encoding="utf-8")
