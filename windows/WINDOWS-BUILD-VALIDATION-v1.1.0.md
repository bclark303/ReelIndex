# ReelIndex Windows v1.1.0 Build Validation

Build date: August 1, 2026

## Performance changes

- Replaced per-file folder enumeration with a one-pass `os.scandir` directory walker.
- Removed per-file `Path.resolve()` calls that can trigger costly SMB lookups on Windows.
- Added live movie/file discovery progress.
- Split scanning into inventory, technical-analysis, and poster-enrichment phases.
- Added four-worker concurrent `ffprobe` analysis by default.
- Added six-worker concurrent poster retrieval by default.
- Prefer Plex/Jellyfin/Emby technical metadata rather than reopening mapped network files.
- Refresh the Library and Sources pages during an active scan.
- Moved movie pagination, sorting, facets, and dashboard aggregation into SQLite queries.

## Completed checks

- Compiled every Python backend module.
- Ran 7 backend tests successfully.
- Validated JavaScript syntax with Node.js.
- Validated the installer payload ZIP and its CRCs.
- Compiled the setup program as a native Windows x86-64 GUI executable.
- Started the packaged FastAPI/static application through `TestClient`.
- Verified `/`, `/api/health`, source creation, active scan polling, live discovery counts, completion, statistics, and paginated movie results.
- Verified 20 test movies were discovered and analyzed successfully.

## Synthetic concurrency benchmark

A test library containing 80 changed files used a fake `ffprobe` with 50 ms of simulated per-file latency:

| Probe workers | Elapsed time |
|---:|---:|
| 1 | 4.316 seconds |
| 4 | 1.160 seconds |

That test was approximately 3.7 times faster with the new default concurrency. Actual results depend on SMB latency, disk layout, media containers, antivirus scanning, NAS performance, and network bandwidth.

## Environment limitation

The setup executable was built in Linux as a native Windows x86-64 PE executable but was not executed end-to-end on Windows in this environment. The installer remains unsigned, so Windows SmartScreen may show an unknown-publisher warning.
