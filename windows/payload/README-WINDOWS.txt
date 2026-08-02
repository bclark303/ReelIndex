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
3. A PowerShell progress window downloads and installs the Python runtime, application dependencies, and `ffprobe`.
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
4. Test the connection, save the source, and start a scan.

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

## Scan performance in version 1.1

- Directory discovery reuses Windows directory-entry metadata instead of reopening each folder for every movie file.
- Movie and file counts update while discovery is still running.
- The inventory is committed before technical analysis and poster enrichment finish.
- Up to four changed files are analyzed concurrently by default.
- Plex, Jellyfin, and Emby technical metadata is used directly instead of reopening mapped network files with `ffprobe`.
- Poster retrieval uses up to six concurrent workers.
- The Library and Sources pages refresh during active scans, so results appear progressively.

The first filesystem scan still has to read every directory and inspect every media file. Later scans reuse cached technical metadata whenever file size and modification time have not changed.

Version 1.1.1
- Runs ffprobe with Windows CREATE_NO_WINDOW/hidden startup flags, preventing a console window for each movie.
- Recognizes local poster, folder, cover, movie, front, and thumb artwork in JPG, JPEG, PNG, and WebP formats.
- Recognizes filename-matched artwork such as Movie-poster.jpg and Movie.poster.png.
- Reads movie.nfo and filename-matched Kodi/Jellyfin NFO sidecars for title, year, runtime, plot, edition, and unique IDs.
- Reads movie.json, metadata.json, and filename-matched JSON sidecars.
