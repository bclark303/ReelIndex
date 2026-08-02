# ReelIndex Windows v1.1.1 validation

## Changes

- Added `CREATE_NO_WINDOW` and hidden `STARTUPINFO` flags to every Windows `ffprobe` subprocess.
- Expanded local artwork detection to common generic and filename-matched JPG, JPEG, PNG, and WebP names.
- Added Kodi/Jellyfin NFO parsing for title, year, runtime, overview, edition, tagline, and unique IDs.
- Added generic and filename-matched JSON sidecar parsing.
- Avoided assigning a generic folder poster to every movie in a flat multi-movie directory.
- Local sidecar artwork replaces an older cached online poster during a rescan.

## Validation

- Backend test suite: 10 passed.
- Python bytecode compilation: passed.
- NFO metadata and filename-matched WebP poster test: passed.
- Flat-folder per-file metadata/artwork isolation test: passed.
- Windows GUI installer rebuilt with the updated embedded payload.

The installer executable was cross-compiled on Linux and could not be executed in this environment. The small PowerShell patch is the recommended upgrade path for an existing v1.1.0 installation.
