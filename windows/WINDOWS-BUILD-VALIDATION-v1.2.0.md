# ReelIndex Windows v1.2.0 Validation

## Scope

Version 1.2.0 replaces the ffprobe-first filesystem pipeline with tiered media analysis:

1. Media-server technical metadata
2. Local sidecar metadata and artwork
3. MediaInfo CLI container-header analysis
4. ffprobe only for Deep-scan gaps or compatibility fallback

The Sources page provides separate **Quick scan** and **Deep scan** controls. Scheduled scans use Quick mode.

## Automated tests

- Backend test suite: **23 passed**
- MediaInfo JSON normalization: passed
- Quick scan avoids ffprobe after successful MediaInfo analysis: passed
- Deep scan avoids ffprobe when MediaInfo contains all core fields: passed
- Deep scan fills missing fields with ffprobe only: passed
- Quick-cache to Deep-cache upgrade behavior: passed
- Existing cancellation, local sidecar, filesystem performance, maintenance, and security tests: passed
- Python module compilation: passed
- JavaScript syntax check (`node --check`): passed

## Browser verification

A headless Chromium render with mocked production API responses verified:

- Sources page renders without JavaScript errors
- **Quick scan** control is visible
- **Deep scan** control is visible
- Footer displays **ReelIndex 1.2.0**
- Cache-busted v1.2.0 assets are referenced

Screenshot: `reelindex-v1.2.0-scan-modes.png`

## Packaging validation

- Native installer compiled as a Windows x64 GUI executable
- Embedded payload includes `mediainfo.py`, updated scanner/API/config, v1.2.0 UI, and runtime installer
- Runtime setup downloads MediaInfo CLI 26.05 and ffprobe
- In-place updater preserves `%LOCALAPPDATA%\ReelIndex`
- ZIP integrity checks passed

## Environment limitation

The Windows installer executable could not be launched in this Linux environment. Its payload, source, tests, browser UI, and PE32+ build format were validated here; installation and network-share performance require the Windows host test.
