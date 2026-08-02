# ReelIndex Windows v1.2.1 Validation

## Scope

This release adds persistent live scan output to the Sources page.

Events include:

- queue and scan start
- filesystem/media-server discovery progress
- per-movie indexing
- cache hits
- media-server metadata reuse
- MediaInfo header reads
- ffprobe fallback decisions
- completed analyses and warnings
- poster enrichment
- cancellation, failure, and completion

The UI provides recent-run selection, automatic scrolling, copy-to-clipboard,
and a local Clear view action. Credentials are not included in event messages.

## Automated backend validation

- Python bytecode compilation: passed
- Pytest: **25 passed**
- Scan-event JSONL cursor test: passed
- Scan-event tail retrieval test: passed
- Scan-event cleanup test: passed
- Existing cancellation, maintenance, MediaInfo, tiered analysis, security,
  filesystem, and media utility tests: passed

## Live API validation

A deep scan was run against three generated MP4 files through the real FastAPI
application. The event API returned queue, discovery, indexing, MediaInfo,
ffprobe fallback, successful analysis, and completion events. Byte-offset cursor
and status fields were present.

## Browser validation

Chromium rendered the Sources page at 1500 × 1100 with mocked live API data.
Validated:

- Scan Output card rendered
- six mixed-level events rendered
- paths and stages rendered safely
- ffprobe fallback warning rendered
- recent-run selector rendered
- Auto-scroll, Copy, and Clear view controls rendered
- footer showed ReelIndex 1.2.1
- no JavaScript console or page errors

Screenshot: `reelindex-v1.2.1-live-scan-output.png`

## Packaging validation

- Update patch contains all modified backend and frontend files
- Installer payload contains `scan_events.py` and v1.2.1 web assets
- Installer is a Windows x64 GUI PE executable
- Python cache files were removed from the payload
- Existing `%LOCALAPPDATA%\ReelIndex` data is not included in or replaced by the update

## Limitation

The generated setup executable could not be executed on Windows in this Linux
build environment. The payload, source, tests, browser UI, and PE format were
validated here; installation must still be exercised on the target Windows PC.
