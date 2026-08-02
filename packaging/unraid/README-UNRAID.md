# ReelIndex on Unraid

ReelIndex v1.4.5 uses the same backend and browser UI as the Windows edition.
The published image is `ghcr.io/bclark303/reelindex:1.4.5`; the Unraid template
tracks `ghcr.io/bclark303/reelindex:latest`.

## Install

1. Add `packaging/unraid/my-ReelIndex.xml` to your Unraid templates, or install
   it from the repository URL after the template is published.
2. Map `/data` to `/mnt/user/appdata/reelindex` with read/write access.
3. Map each movie library read-only. The primary mapping is `/media`.
4. Open the WebUI and add a filesystem source using `/media`, not the Unraid
   host path.

Additional libraries can be added as extra read-only mappings such as
`/media2`, `/media3`, and so on.

## Upgrade from Unraid v1.0.3

Keep the existing `/mnt/user/appdata/reelindex` mapping and replace only the
container image/template. ReelIndex v1.4.5 uses the same database entity schema,
so the database, encrypted source credentials, posters, and scan history are
retained. Back up appdata before any container upgrade.

The startup script repairs ownership only for top-level state and runtime
folders; it does not recursively rewrite a large poster cache on every start.

## Resource defaults

- Directory discovery: 8 workers
- Technical analysis: 4 workers
- Matroska analysis: 2 workers
- Transport stream analysis: 1 worker
- Poster processing: 6 workers
- Native initial sample: 1 MiB
- Expanded retry sample: 4 MiB

These values are intentionally bounded for SMB and HDD-backed Unraid arrays.
