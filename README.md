# ReelIndex

ReelIndex is a local, read-only movie inventory application for Windows. It indexes movie libraries from local folders, mapped drives, UNC shares, Plex, Jellyfin, or Emby and presents searchable poster and table views with technical media details.

![ReelIndex library](docs/images/library.png)

## Download for Windows

Download the current installer from [`dist/ReelIndex-Windows-Setup-v1.4.4.exe`](dist/ReelIndex-Windows-Setup-v1.4.4.exe).

The installer is not digitally signed, so Windows SmartScreen may show an unknown-publisher warning. Verify the file against [`dist/SHA256SUMS.txt`](dist/SHA256SUMS.txt) before running it.

### Requirements

- Windows 10 or Windows 11, 64-bit
- Internet access during installation
- A movie folder, mapped drive, UNC share, Plex server, Jellyfin server, or Emby server
- A read-only server token when using a media-server source

The installer does not require administrator rights. ReelIndex installs for the current Windows user.

## Highlights

- Read-only media inventory; no rename, move, delete, or media-server mutation actions
- Poster grid and dense list views
- Search and filters for source, resolution, codec, container, edition, poster status, and probe status
- Native bounded parsers for MKV/WebM, MP4/M4V/MOV, AVI, ASF/WMV, MPEG-TS/M2TS/MTS, and MPEG-PS/MPG
- `ffprobe` compatibility fallback for unusual or malformed files
- Resumable Deep Scan queue with bounded concurrency
- Local sidecar, media-server, embedded, and optional TMDB posters
- Direct IMDb-ID poster matching and manual poster search/upload
- Probe Failures workspace with diagnosis and targeted retries
- Encrypted stored source credentials
- Scheduled scans, live progress, structured logs, and diagnostics


## Competition baseline and historical releases

The original competition submission is preserved as the **[v1.0.0 Competition Baseline](https://github.com/bclark303/ReelIndex/releases/tag/v1.0.0)**, including its Windows installer and exact source snapshot. Every subsequent Windows revision is also available under [Releases](https://github.com/bclark303/ReelIndex/releases). See [`docs/RELEASE-HISTORY.md`](docs/RELEASE-HISTORY.md) for the version-by-version summary.

## First run

1. Install and open ReelIndex.
2. Open **Sources** and select **Add source**.
3. Choose **Filesystem**, **Plex**, **Jellyfin**, or **Emby**.
4. Test and save the connection.
5. Run a **Quick scan** for normal inventory maintenance.
6. Use **Deep scan** when technical metadata needs to be refreshed or completed.

Filesystem examples:

```text
D:\Movies
M:\Media\Movies
\\NAS\Media\Movies
```

Optional TMDB poster matching requires your own TMDB API read token, entered in the source settings. Tokens and application data are not included in this repository.

## Data locations

Program files:

```text
%LOCALAPPDATA%\Programs\ReelIndex
```

Database, configuration, encrypted credentials, scan logs, and cached posters:

```text
%LOCALAPPDATA%\ReelIndex
```

Reinstalling or upgrading preserves the data directory. Do not publish that directory.

## Updating an existing installation

The current in-place update package is available at [`dist/reelindex-windows-v1.4.4-update.zip`](dist/reelindex-windows-v1.4.4-update.zip). Extract it and run `apply-update.ps1`. The update preserves the inventory database, sources, credentials, posters, scan history, and resumable Deep Scan queue.

## Source layout

```text
backend/            FastAPI backend and automated tests
windows/app/        Windows application payload
windows/launcher/   Windows launcher source
windows/installer/  Windows installer source
windows/web/        Static browser interface source
docs/               Build and validation notes
dist/               Published Windows installer and update package
```

## Development

Run the backend tests with Python 3.12:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest -q
```

The v1.4.4 validation run passed 80 backend tests. See [`docs/VALIDATION-v1.4.4.md`](docs/VALIDATION-v1.4.4.md).

## Privacy and safety

- Movie files and sidecars are opened read-only.
- ReelIndex writes only to its local application-data directory.
- Source tokens are encrypted before storage.
- API responses and diagnostics mask stored credentials.
- Do not upload database files, `.secret_key`, logs, cached posters, or `.env` files.

## License

No open-source license has been selected yet. Unless a license is added, copyright and reuse rights remain with the project owner.
