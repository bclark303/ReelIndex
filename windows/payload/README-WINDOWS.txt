ReelIndex Windows v1.4.2

IMDb-aware poster matching release.

Poster resolution now:
- Detects IMDb title IDs such as tt0078748 in movie titles, folder names,
  filenames, paths, JSON metadata, and Kodi/Jellyfin NFO unique IDs.
- Resolves those IDs directly through TMDB before attempting title search.
- Removes appended IMDb IDs and common cp(...) markers from title-search text.
- Retries title search without the year when a release-folder year is wrong.
- Records the TMDB ID, IMDb ID, and poster match method in movie metadata.

Use Sources > Posters after upgrading. Existing databases, source credentials,
poster caches, scan history, and resumable Deep Scan queues are stored under
%LOCALAPPDATA%\ReelIndex and are preserved during an upgrade.
