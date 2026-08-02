# ReelIndex Windows v1.2.2 Validation

## Scope

This release adds optional verbose scan-performance logging and downloadable
scan logs for active, cancelled, failed, and completed runs.

Verbose events include:

- discovery elapsed time and files per second
- indexing elapsed time, changed files, and cache activity
- MediaInfo elapsed time per file
- ffprobe fallback elapsed time per file
- total analysis time per file
- worker-pool elapsed time and throughput
- poster-job elapsed time and throughput
- total scan elapsed time

The setting is persisted in `%LOCALAPPDATA%\ReelIndex\runtime-settings.json`
and can be changed without restarting ReelIndex.

## Automated validation

- Python bytecode compilation: passed
- Existing backend test suite: **25 passed**
- Runtime logging setting GET/PUT API: passed
- Diagnostics response includes logging state: passed
- Verbose MediaInfo and total-analysis timing events: passed
- Active-run JSONL export endpoint: passed
- Real two-file filesystem scan produced 28 events: passed
- Exported log included discovery, indexing, MediaInfo, ffprobe, job, and total timings: passed
- API tokens and source credentials are not emitted by the event logger
- JavaScript syntax check with Node: passed

## Live API sample

A two-file scan through the real FastAPI application produced:

- discovery: 102 ms
- indexing: 19 ms
- MediaInfo: 4–5 ms per test file
- ffprobe fallback: 302–304 ms per test file
- total scan: 451 ms

The files were intentionally invalid placeholders, so analysis warnings were
expected. The test confirms instrumentation and export behavior rather than
media accuracy.

## Packaging validation

- Update patch contains all modified backend, launcher, and frontend files
- Installer payload contains `runtime_settings.py`
- Installer payload contains v1.2.2 cache-busted web assets
- Setup executable is a Windows x64 GUI PE file
- Existing `%LOCALAPPDATA%\ReelIndex` data is not included or replaced

## Privacy

Authentication tokens and passwords are not logged. Scan logs may contain
movie titles, filenames, source names, and local or UNC filesystem paths. Users
should review the JSONL file before sharing it outside a trusted troubleshooting
conversation.

## Limitation

The Windows setup executable was built and its payload validated on Linux, but
it could not be executed inside an actual Windows session in this environment.
