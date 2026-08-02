# ReelIndex Windows v1.4.2 Validation

## Scope

v1.4.2 improves poster matching for release folders and movie titles that contain IMDb identifiers such as `tt0078748` or `cp(tt1911658)`.

## Implemented behavior

- Extract IMDb IDs recursively from titles, filenames, paths, JSON metadata, and NFO `unique_ids` values.
- Query TMDB's `/find/{external_id}` endpoint using `external_source=imdb_id` before text search.
- Strip IMDb IDs, brackets, and trailing `cp` copy markers from fallback title-search text.
- Retry a failed year-constrained title search without the year.
- Persist `tmdb_id`, `imdb_id`, `poster_source`, and `poster_match` after a successful TMDB poster retrieval.
- Include the IMDb match in live scan output and verbose poster timing records.

## Tests

- 68 backend tests passed.
- Added tests for plain, bracketed, and `cp(...)` IMDb patterns.
- Added direct TMDB external-ID lookup tests.
- Added cleaned title-search fallback tests.
- Added an end-to-end poster job test extracting an IMDb ID from a filename.
- Python compilation passed.
- Runtime health endpoint returned ReelIndex `1.4.2`.
- Static UI served cache-busted v1.4.2 assets.

## Source-log evidence

The supplied poster scan log contains at least 58 distinct IMDb IDs in indexed titles, including `Alien tt0078748`, `12 Angry Men tt0050083`, and folders using `cp(tt...)`. These are now eligible for deterministic external-ID resolution rather than fuzzy title matching.

## Data safety

The patch changes application files only. It does not delete or modify the database, credentials, poster cache, scan history, resumable queues, or media files.
