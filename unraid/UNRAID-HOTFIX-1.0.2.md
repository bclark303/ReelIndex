# ReelIndex Unraid hotfix 1.0.2

This update fixes nginx startup failure when ReelIndex runs as the configured Unraid PUID/PGID.

## Symptom

`open() "/dev/stderr" failed (13: Permission denied)`

## Change

nginx access and error logs now write to `/data/logs`, which maps to the persistent ReelIndex appdata directory. The startup script creates and assigns ownership of that directory before nginx starts.

## Rebuild

From the ReelIndex project directory on Unraid:

```bash
cd /mnt/user/Ben/reelindex/unraid
./install-reelindex.sh
```

Then recreate or start the ReelIndex container from the Unraid Docker page.
