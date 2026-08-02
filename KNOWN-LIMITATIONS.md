# Known Limitations

- Initial filesystem scans run ffprobe once for every new or changed file and can take time on very large or slow network libraries.
- Filesystem title recognition is heuristic. Unusual naming can produce an imperfect title, year, or edition; a lightweight optional `movie.json` sidecar is supported for local correction without modifying media files.
- Plex, Jellyfin, and Emby installations can differ by version and permission policy. The provided adapters target their common read APIs and require validation against the competition servers.
- Exact ffprobe details require the media file to be visible inside the backend container. Without a valid path mapping, ReelIndex displays the technical metadata supplied by the server.
- The current path-mapping UI supports one prefix pair per source, although the backend configuration format accepts an array and can be extended easily.
- Scheduled scans use interval scheduling and require the backend container to remain running.
- SQLite is intentionally selected for portability. A very large multi-user deployment would benefit from PostgreSQL, but that complexity is unnecessary for the competition target.
- There is no user authentication because the intended deployment is a trusted local network. Do not expose the application directly to the public internet without adding an authenticated reverse proxy.
- Poster matching through TMDB uses the best title/year search result and can occasionally choose the wrong film when metadata is ambiguous.
