# ReelIndex Windows v1.1.5 Validation

## Feature

Version 1.1.5 adds application-data maintenance controls under **Diagnostics → Maintenance**.

### Clear inventory cache

- Removes indexed movies and media-file technical metadata.
- Removes scan history.
- Removes generated/cached poster files.
- Retains source connections, schedules, and encrypted credentials.
- The next scan behaves like an initial inventory scan.

### Factory reset ReelIndex

- Removes all source connections and encrypted credential records.
- Removes all movies, media files, scan history, and cached posters.
- Leaves the installed application, runtime, logs, and encryption-key file in place.
- Empties and compacts the SQLite database, producing first-run application state.

Both operations require a typed confirmation phrase and are rejected while any scan is queued, running, or cancelling. Media files and sidecar metadata are never modified.

## Validation

Backend test suite:

```text
18 passed in 0.96s
```

Coverage includes:

- Cache clearing preserves source configuration while removing generated records.
- Factory reset removes sources, inventory, scans, and poster files.
- Destructive maintenance is blocked while a scan is active.
- Existing scan cancellation, hidden ffprobe, local metadata, poster, security, and parsing tests.

A live FastAPI check confirmed:

```text
Clear inventory: 1 source retained, 0 movies, 0 files, 0 scans
Factory reset:   0 sources, 0 movies, 0 files, 0 scans
```

The JavaScript bundle passed `node --check`, and the production server returned v1.1.5 assets with cache-busted URLs.
