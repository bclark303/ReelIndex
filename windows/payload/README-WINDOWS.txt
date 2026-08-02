# ReelIndex for Windows

`ReelIndex-Windows-Setup.exe` installs the complete ReelIndex movie inventory application for the current Windows user.

## System requirements

- Windows 10 or Windows 11, 64-bit
- Internet access during the first installation
- A local movie folder, mapped drive, UNC share, Plex server, Jellyfin server, or Emby server
- Enough free space for the application runtime, package cache, database, and downloaded posters

Administrator rights are not required. The program is installed per-user.

## Install

1. Download `ReelIndex-Windows-Setup.exe`.
2. Double-click it and approve the installation prompt.
3. A PowerShell progress window downloads and installs the Python runtime, application dependencies, MediaInfo CLI, and `ffprobe`.
4. When setup completes, ReelIndex opens in the default browser.

The installer is not digitally signed. Windows SmartScreen may identify it as an unknown publisher. Review the checksum supplied with the download before running it.

## First use

1. Open **Sources**.
2. Select **Add source**.
3. Choose one of:
   - **Filesystem** — local folder, mapped drive, or UNC path
   - **Plex** — server URL and read-only token
   - **Jellyfin** — server URL and API key
   - **Emby** — server URL and API key
4. Test the connection and save the source.
5. Start with **Quick scan**. Use **Deep scan** only when you need to fill technical fields that MediaInfo could not obtain.

Filesystem examples:

```text
D:\Movies
M:\Media\Movies
\\NAS\Media\Movies
```

ReelIndex reads media files and server metadata. It does not rename, move, delete, or modify the movie collection.

## Installed locations

Program files:

```text
%LOCALAPPDATA%\Programs\ReelIndex
```

Database, settings, poster cache, and logs:

```text
%LOCALAPPDATA%\ReelIndex
```

The local web service listens only on `127.0.0.1`, using the first available port from 8765 through 8784.

## Start Menu shortcuts

- **ReelIndex** — starts the local service and opens the interface
- **Stop ReelIndex** — stops the local service
- **View ReelIndex Logs** — opens the log directory
- **Uninstall ReelIndex** — removes the application

The installer also creates a desktop shortcut.

## Upgrade and reinstall

Run a newer setup executable. Program files are replaced, while the database, cached posters, settings, and scan history under `%LOCALAPPDATA%\ReelIndex` are retained.

## Uninstall

Use **Settings → Apps → Installed apps → ReelIndex Movie Inventory**, or use the Start Menu uninstall shortcut.

The uninstaller asks whether application data should also be deleted. Keeping the data preserves the database and cached artwork for a later reinstall.

## Troubleshooting

Installation log:

```text
%TEMP%\ReelIndex-install.log
```

Application log:

```text
%LOCALAPPDATA%\ReelIndex\logs\reelindex.log
```

For a mapped network drive, ReelIndex must be launched under the same Windows account that owns the drive mapping. A UNC path is usually more dependable for network shares.

## Tiered media analysis in version 1.2

ReelIndex no longer launches `ffprobe` for every changed filesystem movie. The analyzer now uses this order:

1. Reuse Plex, Jellyfin, or Emby technical metadata when available.
2. Read local `.nfo`/JSON sidecars and local poster artwork during directory discovery.
3. Run MediaInfo CLI for a lightweight container-header analysis.
4. Run `ffprobe` only when a **Deep scan** still has important missing fields, or when MediaInfo is unavailable and a compatibility fallback is required.

**Quick scan** is the recommended default for local and network folders. It stops after the MediaInfo pass and makes the inventory usable as quickly as possible. **Deep scan** upgrades Quick-scan cache entries only when needed; files already analyzed deeply are reused while unchanged. Scheduled scans use Quick mode.

Directory counts update during discovery, the inventory is committed before enrichment completes, and changed files are analyzed concurrently. Later scans reuse cached results whenever file size and modification time have not changed.

## Scan cancellation

Active scans can be cancelled from the progress banner or the Sources page. ReelIndex stops discovery, pending MediaInfo/ffprobe work, and pending poster work, then records the run as cancelled. Movies indexed before cancellation remain available; media files are never modified.

## UI update reliability

ReelIndex cache-busts browser assets and displays the installed version in the footer. If scan state cannot be loaded, the interface displays the API error rather than silently hiding scan controls.

## Clear cached data or start over

Open **Diagnostics → Maintenance**.

- **Clear inventory cache** removes indexed movies, technical metadata, scan history, and downloaded posters while retaining source connections and credentials.
- **Factory reset ReelIndex** removes all database content, including sources and stored credentials, then returns the app to first-run state.

Both actions require a typed confirmation and are disabled while a scan is active. Neither action changes media files or sidecar artwork/metadata.

ReelIndex 1.2.2 adds optional verbose performance logging. Enable it under
Diagnostics, reproduce a partial scan, then use Sources > Scan output >
Download log. The JSONL export excludes credentials but may include movie
names and filesystem paths.
