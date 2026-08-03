# ReelIndex

ReelIndex is a local, read-only movie inventory application for **Windows,
Docker, and Unraid**. It indexes movie libraries from local folders, mapped
or mounted paths, UNC/SMB shares, Plex, Jellyfin, or Emby and presents
searchable poster and table views with technical media details.

The Windows and Docker/Unraid editions use the same v1.4.10 FastAPI backend and
browser interface.

![ReelIndex library](docs/images/library.png)

## Download for Windows

Download the fully offline Windows package from
[`dist/ReelIndex-Windows-Setup-v1.4.10.0.exe`](dist/ReelIndex-Windows-Setup-v1.4.10.0.exe).
Its Microsoft Defender release-gate record is published beside it at
[`dist/ReelIndex-Windows-Setup-v1.4.10.0.defender.json`](dist/ReelIndex-Windows-Setup-v1.4.10.0.defender.json).

Windows Setup package 1.4.10.0 contains ReelIndex application version 1.4.10. The
installer bundles the Python runtime and Python dependencies, performs no
network access or PowerShell execution on the user device, and verifies an
embedded SHA-256 manifest before installing files.

The package remains unsigned until an Authenticode certificate is available,
so SmartScreen can still display an unknown-publisher warning. An
unknown-publisher warning is different from an antivirus malware detection;
never bypass an antivirus detection.

Requirements:

- Windows 10 or Windows 11, 64-bit
- A movie folder, mapped drive, UNC share, Plex server, Jellyfin server, or Emby server
- A read-only server token when using a media-server source

The installer does not require administrator rights and installs for the
current Windows user.

## Docker and Unraid

The published image is:

```text
ghcr.io/bclark303/reelindex:1.4.10
```

Start it with the included Compose file:

```bash
cp .env.example .env
mkdir -p data media
docker compose up -d
```

Open `http://localhost:8080` and configure a filesystem source using `/media`.
The Compose and Unraid configurations mount movie libraries read-only.

Unraid users can use [`packaging/unraid/my-ReelIndex.xml`](packaging/unraid/my-ReelIndex.xml).
See [`docs/DOCKER-UNRAID.md`](docs/DOCKER-UNRAID.md) for installation, additional
library mappings, PUID/PGID handling, and v1.0.3 upgrade guidance.

## Highlights

- Read-only media inventory; no rename, move, delete, or media-server mutation actions
- Poster grid and dense list views
- Search and filters for source, resolution, codec, container, edition, poster status, and probe status
- Native bounded parsers for MKV/WebM, MP4/M4V/MOV, AVI, ASF/WMV, MPEG-TS/M2TS/MTS, and MPEG-PS/MPG
- `ffprobe` compatibility fallback for unusual or malformed files
- Resumable Deep Scan queue with bounded concurrency
- Local sidecar, media-server, embedded, and optional TMDB posters
- Direct IMDb-ID poster matching and manual poster search/upload
- Probe Failures workspace with diagnosis and targeted native, extended, or ffprobe retries
- Encrypted stored source credentials
- Scheduled scans, live progress, structured logs, and diagnostics
- Global canonical movie/file identities across filesystem, Plex, Jellyfin, and Emby scans
- Post-scan duplicate reconciliation and repaired parsing for punctuation-bearing movie titles
- Safe per-movie inventory record deletion for rebuilding legacy bad groupings without touching media files or sidecars

## Repairing an incorrectly grouped record

Open the movie details, find **Inventory repair**, and choose **Delete inventory
record**. ReelIndex removes the selected generated database record, its media
inventory rows, and its source associations. It does not modify movie files,
sidecars, source definitions, Plex, Jellyfin, or Emby.

After deletion, run a Quick Scan for each source that contributed to the old
record. The underlying movies are rediscovered using the current matching
rules. Record deletion is blocked while any scan is active.

## Competition baseline and historical releases

The original competition submission is preserved as the
**[v1.0.0 Competition Baseline](https://github.com/bclark303/ReelIndex/releases/tag/v1.0.0)**,
including its Windows installer and exact source snapshot. Historical Windows
installers used the retired downloader packaging path and should not be run.
See [`docs/RELEASE-HISTORY.md`](docs/RELEASE-HISTORY.md).

## First run

1. Install or start ReelIndex.
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
/media
/media2
```

Optional TMDB poster matching requires your own TMDB API read token. Tokens and
application data are not included in this repository.

## Persistent data

Windows application data:

```text
%LOCALAPPDATA%\ReelIndex
```

Docker/Unraid application data:

```text
/data
```

These locations contain the SQLite database, encrypted credentials, scan logs,
resumable queues, and cached posters. Do not publish them.

## Source layout

```text
backend/             Canonical FastAPI backend and automated tests
web/                 Canonical browser interface used by every edition
windows/app/         Generated self-contained Windows payload copy
windows/launcher/    Windows launcher source
windows/installer/   Offline Windows installer source
packaging/docker/    nginx and container entrypoint
packaging/unraid/    Unraid template, icon, and instructions
docs/                Build, deployment, history, and validation notes
dist/                Published release assets
scripts/             Package synchronization and validation helpers
```

Run `python scripts/sync-packages.py` after changing `backend/app` or `web`.
CI runs `python scripts/sync-packages.py --check` to prevent Windows and Docker
from drifting again.

## Development

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest -q
```

The v1.4.10 validation gate includes 102 backend tests, an amd64 Docker smoke
test with live DELETE-route validation, the bundled Windows runtime smoke test,
and a Microsoft Defender scan of both the unpacked payload and final setup
executable.

## Privacy and safety

- Movie files and sidecars are opened read-only.
- ReelIndex writes only to its application-data directory.
- Per-movie record deletion removes only generated inventory state and ReelIndex-managed poster cache files.
- Source tokens are encrypted before storage.
- API responses and diagnostics mask stored credentials.
- Do not upload database files, `.secret_key`, logs, cached posters, or `.env` files.
- Do not bypass antivirus detections for Windows installers.

## License

No open-source license has been selected yet. Unless a license is added,
copyright and reuse rights remain with the project owner.
