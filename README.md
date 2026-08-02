# ReelIndex

ReelIndex is a portable, read-only movie inventory application built for the Friendly AI Movie Inventory App Competition. It inventories complete movie libraries from mounted folders, Plex, Jellyfin, or Emby; presents poster and table views; searches and filters the collection; displays technical file data; and supports incremental manual or scheduled rescans.

## Feature coverage

- Poster grid and dense table view
- Title search plus source, resolution, codec, container, poster, edition, and error filters
- File size, path, container, resolution, bitrate, video/audio codecs, channels, languages, and runtime
- Multiple files and editions grouped under one movie
- Filesystem, Plex, Jellyfin, and Emby source adapters
- Read-only media access and no media-server mutation endpoints
- Incremental fingerprints and ffprobe result caching
- Automatic scheduled scans or user-triggered scans
- Cached local and server posters with optional TMDB fallback
- Responsive layout, keyboard-accessible table rows, visible focus states, reduced-motion support
- Setup UI, connection testing, path mapping, encrypted stored tokens, credential clearing by source removal
- Diagnostics page and downloadable diagnostic JSON
- Optional synthetic demo mode

## Fast installation

Requirements:

- Docker Desktop or Docker Engine with Docker Compose
- Network access from the Docker host to Plex/Jellyfin/Emby when using a server adapter
- A read-only API token where the media server supports scoped permissions

### 1. Configure

Copy the example environment file:

```bash
cp .env.example .env
```

Set `MEDIA_PATH` to a movie folder for direct filesystem scans. The folder is mounted inside the backend container at `/media` with Docker's read-only flag.

Windows example:

```env
MEDIA_PATH=D:/Movies
```

Linux example:

```env
MEDIA_PATH=/mnt/media/Movies
```

### 2. Start

```bash
docker compose up -d --build
```

Open `http://localhost:8080`.

### 3. Add a source

Open **Sources → Add source**.

For a filesystem source:

- Type: Filesystem
- Container media path: `/media`
- Test the connection
- Save, then select **Scan now**

For Plex:

- Enter the Plex base URL, normally `http://SERVER:32400`
- Enter a token with read access
- Test the connection and choose a movie library
- Optional: map the path Plex reports to a mounted path. Example: `D:\Movies` → `/media`

For Jellyfin or Emby:

- Enter the server base URL
- Enter an API token
- Test the connection and choose a library
- A user ID is optional; add it when server policy requires user-scoped item access

## Additional read-only mounts

Docker Compose includes one default mount. Add more under `backend.volumes` when testing several local roots:

```yaml
- type: bind
  source: /mnt/media/Movies2
  target: /media2
  read_only: true
```

Then create a filesystem source pointing to `/media2`.

## Path mapping

Plex/Jellyfin/Emby can return a media path that differs from the path visible inside the container. In the source's advanced settings, enter:

- Server path prefix: the prefix reported by the server, such as `D:\Movies`
- Mounted container prefix: the equivalent read-only Docker mount, such as `/media`

When a file is locally reachable after mapping, ReelIndex runs ffprobe. Otherwise it uses the technical metadata supplied by the media server.

## Poster sources

ReelIndex checks poster providers in this order:

1. Cached application poster
2. Poster supplied by the configured media server or local folder
3. Optional TMDB movie search and poster download
4. Generated interface placeholder

For local folders, supported filenames include `poster.jpg`, `folder.jpg`, `cover.jpg`, or an image matching the movie filename.

## Scheduling

Automatic scan intervals are configured per source in the UI. The minimum interval is one hour. Scans are coalesced and a source cannot run two scans simultaneously.

## Demo mode

To evaluate the interface without media files:

```bash
DEMO_MODE=true docker compose up -d --build
```

Demo mode seeds synthetic metadata only; it does not pretend to be a server scan.

## Development and tests

Backend:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm test
npm run dev
```

The Vite development server proxies `/api` to `localhost:8000`.

## Data and credential handling

- Media folders are mounted read-only.
- ReelIndex has no API actions for deleting, moving, renaming, replacing, or editing media.
- Source tokens are encrypted before storage using a locally generated key in the data volume.
- The local database, poster cache, key, logs, and configuration are the only writable application data.
- Tokens are masked in API responses and diagnostics exports.
- Remove temporary competition sources after testing to delete their stored credentials and cached records.

## Backup and reset

Application data is stored in the `reelindex_data` Docker volume.

Stop without deleting data:

```bash
docker compose down
```

Full reset, including cached inventory and stored source credentials:

```bash
docker compose down -v
```

## Troubleshooting

- **Filesystem path missing:** confirm `MEDIA_PATH` in `.env`, recreate containers, and use `/media` in the source UI.
- **Server connects but no movies appear:** select the correct movie library and ensure the token can read library items.
- **Technical data unavailable:** add a path mapping and read-only Docker mount, or rely on metadata returned by the server.
- **Poster lookup unavailable:** existing cached posters remain usable; missing posters display a clean placeholder.
- **Scan errors:** open Diagnostics, export JSON, and review the newest scan record.

## Project structure

```text
backend/   FastAPI API, adapters, ffprobe scan engine, SQLite cache, scheduler
frontend/  React/TypeScript interface served by nginx
docker-compose.yml
AI-DEVELOPMENT.md
KNOWN-LIMITATIONS.md
```

## Unraid installation

An all-in-one Unraid image and Docker template are included under `unraid/`. Extract the project on the Unraid server and run:

```bash
./unraid/install-reelindex.sh
```

Then open **Docker → Add Container**, select the **ReelIndex** template, confirm the read-only movie mapping, and create a filesystem source using `/media`. See `unraid/README-UNRAID.md` for additional shares, media-server path mapping, rebuilding, and reset instructions.
