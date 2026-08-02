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
    '''def candidate_fingerprint(candidate: Any) -> str:
''',
    '''def strong_file_identity_keys(candidate_or_file: Any) -> set[str]:
    """Physical-path keys safe enough to establish movie identity."""
    return {key for key in file_identity_keys(candidate_or_file) if key.startswith("path:")}


def candidate_fingerprint(candidate: Any) -> str:
''',
    "strong file identity helper",
)
replace_once(
    identity,
    '''        for file_candidate in getattr(candidate, "files", []) or []:
            for key in file_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None:
                    return media_file.movie, None
''',
    '''        for file_candidate in getattr(candidate, "files", []) or []:
            for key in strong_file_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None:
                    return media_file.movie, None
''',
    "strong candidate movie match",
)
replace_once(
    identity,
    "            keys.update(file_identity_keys(media_file))\n",
    "            keys.update(strong_file_identity_keys(media_file))\n",
    "strong legacy movie merge",
)

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
    if "1.4.6" not in text:
        raise RuntimeError(f"{relative}: expected v1.4.6 release identity")
    path.write_text(text.replace("1.4.6", "1.4.7"), encoding="utf-8")

test_path = ROOT / "backend" / "tests" / "test_global_library_identity.py"
test_text = test_path.read_text(encoding="utf-8")
marker = "\ndef test_startup_consolidates_existing_cross_source_duplicates(tmp_path):\n"
if marker not in test_text:
    raise RuntimeError("identity test insertion point not found")
new_test = '''

def test_filename_and_size_alone_do_not_merge_different_movies(tmp_path):
    engine, LocalSession = make_session(tmp_path)
    with LocalSession() as db:
        first_source = Source(name="One", type="filesystem", url_or_path="/one")
        second_source = Source(name="Two", type="plex", url_or_path="http://plex")
        db.add_all([first_source, second_source])
        db.flush()
        first = Movie(
            source_id=first_source.id,
            source_movie_id="one",
            title="Alpha",
            sort_title="alpha",
            year=2001,
        )
        second = Movie(
            source_id=second_source.id,
            source_movie_id="two",
            title="Beta",
            sort_title="beta",
            year=2002,
        )
        db.add_all([first, second])
        db.flush()
        db.add_all([
            MediaFile(
                movie_id=first.id,
                source_file_id="one-file",
                path="/one/shared-name.mkv",
                filename="shared-name.mkv",
                size_bytes=123456789,
            ),
            MediaFile(
                movie_id=second.id,
                source_file_id="two-file",
                path="/two/shared-name.mkv",
                filename="shared-name.mkv",
                size_bytes=123456789,
            ),
        ])
        db.commit()

        merged = upgrade_library_identity(db)
        assert merged == 0
        assert db.scalar(select(func.count(Movie.id))) == 2
        assert db.scalar(select(func.count(MediaFile.id))) == 2

    engine.dispose()
'''
test_path.write_text(test_text.replace(marker, new_test + marker, 1), encoding="utf-8")
