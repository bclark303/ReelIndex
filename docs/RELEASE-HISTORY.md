# Release history

ReelIndex preserves the original competition baseline and every public Windows revision as tagged source snapshots and GitHub Releases.

## Windows releases

### v1.0.0 — **competition baseline**

Original competition baseline: local read-only movie inventory with filesystem, Plex, Jellyfin, and Emby sources, searchable library views, technical metadata, posters, diagnostics, and Windows packaging.

### v1.1.0

Parallel scanning, live counts, caching, and pagination performance improvements.

### v1.1.1

Background metadata improvements, hidden ffprobe windows, and local poster/NFO support.

### v1.1.2

Initial scan-cancellation support.

### v1.1.3

Visible and more responsive scan cancellation controls.

### v1.1.4

Cancellation race-condition and shutdown fixes.

### v1.1.5

Clear-cache and factory-reset maintenance controls.

### v1.2.0

Tiered analysis using server metadata, sidecars, MediaInfo, and ffprobe fallback; Quick and Deep scan modes.

### v1.2.1

Live scan-output console.

### v1.2.2

Verbose performance logging and structured JSONL diagnostics.

### v1.2.3

Quick-scan optimization, analyzer timeout circuits, and extras/trailer exclusions.

### v1.2.4

Parallel SMB directory discovery.

### v1.3.0

Persistent resumable Deep Scan queue, scan scopes, and adaptive ffprobe profiles.

### v1.3.1

Bounded submission/backpressure and serial recovery.

### v1.3.2

Adaptive continuation through repeated timeout clusters.

### v1.3.3

Timeout rotation, fast-container prioritization, and worker recovery tuning.

### v1.3.4

Matroska-specific scheduling and probe-profile tuning.

### v1.3.5

Local Matroska header staging to avoid direct network ffprobe access.

### v1.3.6

Native Matroska/EBML header parser with bounded ffprobe fallback.

### v1.4.0

Unified native parsers for Matroska, MP4/MOV, AVI, ASF/WMV, MPEG-TS/M2TS, and MPEG program streams.

### v1.4.1

Poster pipeline moved ahead of technical analysis, plus poster-only repair scans.

### v1.4.2

Direct IMDb-ID poster matching through TMDB and stronger cleaned-title fallback.

### v1.4.3

Manual TMDB poster search, image upload/removal, and scan-safe manual poster locks.

### v1.4.4

Probe Failures workspace with reason classification, attempt history, remediation guidance, and targeted retries.

## Unraid releases

- `unraid-v1.0.0` — original all-in-one Unraid package
- `unraid-v1.0.1` — first numbered Unraid maintenance build
- `unraid-v1.0.2` — second Unraid maintenance build
- `unraid-v1.0.3` — icon, favicon, and packaging refinements

## Auxiliary tool

- `offline-builder-v1.0.0` — creates a self-contained offline Windows installer from an installed ReelIndex runtime.
