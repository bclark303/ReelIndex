#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

entities = ROOT / "backend" / "app" / "models" / "entities.py"
text = entities.read_text(encoding="utf-8")
text = text.replace('        UniqueConstraint("source_id", "movie_id", name="uq_movie_source_link_movie"),\n', "")
text = text.replace('        UniqueConstraint("source_id", "media_file_id", name="uq_file_source_link_file"),\n', "")
entities.write_text(text, encoding="utf-8")

identity = ROOT / "backend" / "app" / "services" / "library_identity.py"
text = identity.read_text(encoding="utf-8")
old = '''        ordered = sorted(keys, key=lambda key: (0 if key.startswith(("imdb:", "tmdb:")) else 2, key))
        for key in ordered:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None
        for file_candidate in getattr(candidate, "files", []) or []:
            for key in file_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None:
                    return media_file.movie, None
        for key in ordered:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None
'''
new = '''        external_keys = sorted(key for key in keys if key.startswith(("imdb:", "tmdb:")))
        fallback_keys = sorted(key for key in keys if key not in external_keys)
        for key in external_keys:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None
        for file_candidate in getattr(candidate, "files", []) or []:
            for key in file_identity_keys(file_candidate):
                media_file = self.file_keys.get(key)
                if media_file is not None:
                    return media_file.movie, None
        for key in fallback_keys:
            movie = self.movie_keys.get(key)
            if movie is not None:
                return movie, None
'''
if old not in text and new not in text:
    raise RuntimeError("movie match ordering block not found")
text = text.replace(old, new, 1)
identity.write_text(text, encoding="utf-8")
