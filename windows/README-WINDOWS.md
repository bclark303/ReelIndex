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


## Version 1.3.0 scan optimization

Version 1.3.0 uses MediaInfo's fastest parse mode, reduces the Quick-scan MediaInfo timeout to eight seconds, never launches ffprobe during a Quick scan, and stops launching an analyzer for the remainder of a scan after a full worker batch times out. Quick-scan analyzer failures are cached as filesystem-only metadata so unchanged files do not stall every later scan. Trailer, sample, and extras clips are excluded when a primary movie file is present.

## Version 1.3.0 network discovery optimization

Version 1.3.0 enumerates independent movie folders concurrently instead of waiting for one SMB directory round trip at a time. The default is eight bounded discovery workers and can be changed before launching ReelIndex with `REELINDEX_DISCOVERY_WORKERS`. MediaInfo and ffprobe circuit breakers also reserve attempt slots so a failed worker batch cannot immediately launch extra doomed probes.

## Version 1.3.0 resumable deep analysis

Version 1.3.0 separates deep analysis from ordinary inventory work. Deep scans create a persistent queue under the ReelIndex data directory, can be cancelled and resumed after a browser refresh or application restart, and support targeted scopes for incomplete/changed files, prior failures, missing fields, 4K/HDR candidates, or every active file.

Deep analysis now bypasses MediaInfo on filesystem files and starts with a bounded minimal ffprobe query. A timeout is marked deferred and is not followed by a longer retry. An extended probe runs only when the standard probe succeeds but leaves core fields missing. Live output reports completed and remaining files, average processing time, and an estimated time remaining.
## Version 1.3.1 deep-scan backpressure and recovery

Version 1.3.1 submits only a bounded worker window instead of creating one future for every queued file. When a timeout circuit opens, untouched records remain in the persistent queue without being rewritten or logged one by one. Timed-out files also stay resumable.

After a full worker batch times out, ReelIndex waits briefly and runs one serial recovery probe. A successful recovery continues the queue at reduced concurrency; a second timeout pauses the queue cleanly with a single summary event.


## Version 1.3.2 adaptive deep-scan continuation

Version 1.3.2 keeps a deep queue moving through isolated SMB/ffprobe timeout clusters. A timeout batch reduces concurrency and enters up to three serial recovery checks. Any responsive recovery file resumes the queue at a lower worker count; only repeated consecutive serial timeouts pause untouched work. Standard deep probes now use an eight-second limit, extended probes use twenty seconds, and technical-only deep scans reuse healthy cached local posters instead of copying them again.

## Version 1.3.4 timeout rotation and fast-container priority

Version 1.3.4 removes per-timeout recovery sleeps and serial canary probes. Timed-out files are rotated behind untouched work, concurrency drops only after a full timeout cluster, and healthy runs cautiously restore parallelism. The queue prioritizes MP4/M4V/MOV/AVI before Matroska and transport-stream files, first attempts use a four-second timeout, retried files retain the eight-second timeout, and the queue pauses only after six consecutive serial timeouts.

## Version 1.3.4 Matroska deep-scan tuning

Version 1.3.4 separates Quick-scan history from actual Deep-probe attempts, so untouched files receive the intended four-second first-attempt timeout. Deep analysis now processes Matroska/WebM with a two-worker cap and a smaller header-read window, transport streams with one worker, and fast containers with the full global worker pool. Concurrency recovery uses a rolling health window rather than requiring a long uninterrupted success streak. Verbose logs include per-container checkpoints and a final checkpoint when the scan is cancelled.



## Version 1.3.5 local Matroska header staging

Version 1.3.5 stops running ffprobe directly against MKV/WebM files on network shares. ReelIndex copies a bounded 2 MB header window (4 MB on retries) to local application storage in a killable child process, probes the temporary local fragment, calculates overall bitrate from the original file size and embedded duration, and deletes the fragment immediately. This avoids repeated SMB seeks while remaining read-only against the movie library.
## Version 1.3.6 native Matroska analysis

Version 1.3.6 parses Matroska/WebM EBML headers directly after copying a one-megabyte sequential header window to local storage. It extracts duration, video and audio codecs, resolution, channels, languages, frame rate, stream counts, and basic HDR signalling without launching ffprobe for normal MKV files. The parser expands to four megabytes only when the first header is incomplete, and ffprobe remains a bounded fallback for unusual or malformed containers. This removes truncated-fragment ffprobe stalls while keeping source media read-only.

