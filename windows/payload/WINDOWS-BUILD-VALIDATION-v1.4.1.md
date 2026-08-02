# ReelIndex Windows v1.4.1 Validation

## Purpose

v1.4.1 repairs poster enrichment after the resumable Deep Scan redesign.
In v1.4.0, poster work still existed but ran only after all technical analysis,
and the Resume Deep path never performed poster enrichment. Cancelling or
repeatedly resuming Deep Scan could therefore leave artwork unprocessed.

## Changes validated

- Poster jobs run immediately after inventory indexing and before technical
  analysis.
- A persistent Deep Scan queue is created before poster work, so cancellation
  during poster processing does not lose resumable technical work.
- A new poster-only scan mode discovers the source and resolves artwork without
  opening or analyzing media files.
- The Sources page exposes a **Posters** action for each source.
- Existing sidecar, media-server, or TMDB artwork is protected from replacement
  by embedded container artwork found later during Deep Scan.
- Poster sources remain ordered as local sidecar, existing cache/media-server,
  media-server adapter, and optional TMDB fallback. Embedded container artwork
  remains a missing-poster fallback.

## Automated checks

- Backend test suite: **63 passed**.
- Added integration coverage confirms poster jobs execute before technical jobs.
- Added integration coverage confirms poster-only refresh queues zero media
  analysis jobs and preserves runtime metadata.
- Added coverage confirms embedded cover art does not overwrite an existing
  authoritative poster.
- Python import/compilation checks passed.
- `node --check` passed for the Windows application script.
- Runtime health endpoint returned version `1.4.1`.
- Static UI served cache-busted v1.4.1 assets and included the new poster action.
- Patch ZIP integrity passed.

## Upgrade behavior

The in-place patch performs no downloads and preserves `%LOCALAPPDATA%\ReelIndex`,
including the SQLite database, encrypted source credentials, scan history,
cached posters, logs, and resumable Deep Scan queue manifests.

For artwork skipped by an older cancelled/resumed Deep Scan, use
**Sources → Posters** once after updating.
