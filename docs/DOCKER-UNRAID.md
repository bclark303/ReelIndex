# Docker and Unraid deployment

## Published image

```text
ghcr.io/bclark303/reelindex:1.4.5
```

Aliases published from the default branch are `latest` and `unraid`.

## Docker Compose

```bash
cp .env.example .env
mkdir -p data media
docker compose up -d
```

Open `http://localhost:8080`. Configure a filesystem source using `/media`.
The Compose file mounts the media directory read-only.

## Build locally

```bash
docker build -t reelindex:1.4.5 .
docker run --rm -p 8080:8080 \
  -e PUID=1000 -e PGID=1000 -e TZ=America/Toronto \
  -v "$PWD/data:/data" \
  -v "/path/to/movies:/media:ro" \
  reelindex:1.4.5
```

## Persistent data

The `/data` mapping contains:

- `reelindex.db` and SQLite journal files
- `.secret_key` used to encrypt stored source credentials
- `posters/`
- `scan-events/`
- `deep-queues/`
- runtime settings

Never publish or replace this directory with files from another installation.

## Upgrade from the old Unraid image

1. Stop the old container.
2. Back up its `/data`/appdata directory.
3. Keep the same appdata mapping and read-only media mappings.
4. Change the image to `ghcr.io/bclark303/reelindex:1.4.5`.
5. Start the container and check `/api/health` and **Diagnostics**.
6. Run a Quick Scan before starting a full Deep Scan.

The v1.0.3 and v1.4.5 model definitions are byte-for-byte identical; no schema
migration is required. Deep Scan queues and scan-event directories are created
on demand when upgrading.

## Container security and efficiency

- Media paths are never written by ReelIndex and should always be mounted `ro`.
- The service runs as the configured numeric PUID/PGID.
- Only bounded header/tail samples are read for native technical analysis.
- `ffprobe` is a compatibility fallback rather than the primary analyzer.
- nginx access logging is disabled to reduce routine disk writes.
- Startup avoids recursive ownership changes across the poster cache.
