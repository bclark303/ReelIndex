#!/usr/bin/env python3
"""Apply the canonical-library indexing changes to the large scanner module.

This script is intentionally strict: every replacement must match exactly once.
It is kept in the repository as a readable record of the focused scanner change
and as protection against accidentally applying the patch to a drifted file.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "backend" / "app" / "services" / "scanner.py"


def replace_once(text: str, label: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = SCANNER.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "identity import",
        "from app.services.deep_queue import deep_queue_store\nfrom app.services.media_utils import sort_title\n",
        "from app.services.deep_queue import deep_queue_store\n"
        "from app.services.library_identity import LibraryIdentityIndex, candidate_fingerprint\n"
        "from app.services.media_utils import sort_title\n",
    )

    text = replace_once(
        text,
        "source-local movie index",
        '''            existing_movies = {
                item.source_movie_id: item
                for item in db.scalars(
                    select(Movie)
                    .options(selectinload(Movie.files))
                    .where(Movie.source_id == source_id)
                ).all()
            }
            seen_movie_ids: set[str] = set()
            processed_files = 0
''',
        '''            identity = LibraryIdentityIndex(db)
            seen_movie_link_ids: set[str] = set()
            seen_file_link_ids: set[str] = set()
            processed_files = 0
''',
    )

    text = replace_once(
        text,
        "canonical movie lookup",
        '''                movie = existing_movies.get(candidate.source_movie_id)
                if not movie:
                    movie = Movie(
                        source_id=source_id,
                        source_movie_id=candidate.source_movie_id,
                        title=candidate.title,
                        sort_title=sort_title(candidate.title),
                    )
                    db.add(movie)
                    db.flush()
                seen_movie_ids.add(movie.id)
''',
        '''                movie, movie_link = identity.movie_for_candidate(source_id, candidate)
                if not movie:
                    movie = Movie(
                        source_id=source_id,
                        source_movie_id=candidate.source_movie_id,
                        title=candidate.title,
                        sort_title=sort_title(candidate.title),
                    )
                    db.add(movie)
                    db.flush()
                movie_link = identity.ensure_movie_link(movie, source_id, candidate.source_movie_id)
                seen_movie_link_ids.add(movie_link.id)
''',
    )

    text = replace_once(
        text,
        "canonical poster destination",
        '''                movie.metadata_json = json.dumps(merged_metadata, default=str)
                movie.active = True

                destination = settings.data_dir / "posters" / source_id / f"{movie.id}.jpg"
''',
        '''                movie.metadata_json = json.dumps(merged_metadata, default=str)
                movie.active = True
                identity.register_movie(movie)

                destination = (
                    Path(movie.poster_path)
                    if movie.poster_path
                    else settings.data_dir / "posters" / "library" / f"{movie.id}.jpg"
                )
''',
    )

    text = replace_once(
        text,
        "canonical file lookup",
        '''                existing_files = {item.source_file_id: item for item in movie.files}
                seen_file_ids: set[str] = set()
                for file_candidate in candidate.files:
                    self._raise_if_cancelled(cancel_event)
                    file_record = existing_files.get(file_candidate.source_file_id)
                    if not file_record:
                        file_record = MediaFile(
                            movie_id=movie.id,
                            source_file_id=file_candidate.source_file_id,
                            path=file_candidate.path,
                            filename=file_candidate.filename,
                        )
                        db.add(file_record)
                        db.flush()
                    seen_file_ids.add(file_record.id)
                    same_fingerprint = file_record.fingerprint == file_candidate.fingerprint
''',
        '''                for file_candidate in candidate.files:
                    self._raise_if_cancelled(cancel_event)
                    file_record, file_link = identity.file_for_candidate(source_id, movie, file_candidate)
                    if not file_record:
                        file_record = MediaFile(
                            movie_id=movie.id,
                            source_file_id=file_candidate.source_file_id,
                            path=str(file_candidate.local_path or file_candidate.path),
                            filename=file_candidate.filename,
                        )
                        db.add(file_record)
                        db.flush()
                    file_link = identity.ensure_file_link(
                        file_record,
                        source_id,
                        file_candidate.source_file_id,
                        file_candidate.path,
                    )
                    seen_file_link_ids.add(file_link.id)
                    stable_fingerprint = candidate_fingerprint(file_candidate)
                    same_fingerprint = file_record.fingerprint == stable_fingerprint
''',
    )

    text = replace_once(
        text,
        "canonical file metadata",
        '''                    file_record.path = file_candidate.path
                    file_record.filename = file_candidate.filename
                    file_record.size_bytes = file_candidate.size_bytes
                    file_record.modified_ts = file_candidate.modified_ts
                    file_record.fingerprint = file_candidate.fingerprint
                    file_record.edition = file_candidate.edition
                    file_record.active = True
''',
        '''                    if file_candidate.local_path or not file_record.path:
                        file_record.path = str(file_candidate.local_path or file_candidate.path)
                    file_record.filename = file_candidate.filename
                    file_record.size_bytes = file_candidate.size_bytes
                    file_record.modified_ts = file_candidate.modified_ts
                    file_record.fingerprint = stable_fingerprint
                    file_record.edition = file_candidate.edition
                    file_record.active = True
                    identity.register_file(file_record)
''',
    )

    text = replace_once(
        text,
        "per-movie file deactivation",
        '''                for file_record in movie.files:
                    if file_record.id not in seen_file_ids:
                        file_record.active = False

                if movie_index % settings.scan_commit_interval == 0:
''',
        '''                if movie_index % settings.scan_commit_interval == 0:
''',
    )

    text = replace_once(
        text,
        "source-local movie deactivation",
        '''            for movie in existing_movies.values():
                if movie.id not in seen_movie_ids:
                    movie.active = False
                    for file_record in movie.files:
                        file_record.active = False

            run.current_item = (
''',
        '''            identity.deactivate_unseen(source_id, seen_movie_link_ids, seen_file_link_ids)

            run.current_item = (
''',
    )

    SCANNER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
