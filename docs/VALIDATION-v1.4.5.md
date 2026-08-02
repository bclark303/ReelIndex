# ReelIndex v1.4.5 validation

## Scope

v1.4.5 synchronizes the Windows and Docker/Unraid editions on one canonical
backend and browser UI. It adds current all-in-one container packaging, Unraid
template updates, and GHCR publishing without changing the inventory database
entity schema.

## Completed validation

- `python scripts/sync-packages.py --check`
- Python bytecode compilation for backend, Windows payload, and package scripts
- JavaScript syntax validation with `node --check web/app.js`
- Bash syntax validation for the container entrypoint
- XML parsing of the Unraid template
- YAML parsing of both GitHub Actions workflows
- 82 backend tests passed
- v1.0.3 appdata opened with the v1.4.5 backend
- Existing source and movie records remained queryable
- `/data/posters`, `/data/scan-events`, and `/data/deep-queues` were created
- Health response reported version `1.4.5` and the Docker/Unraid edition
- Windows launcher, uninstaller, setup executable, and in-place update package built
- Release artifacts checked with SHA-256

## Container validation delegated to CI

A Docker daemon is not available in the artifact build environment. The checked
in `Docker image` GitHub Actions workflow performs the remaining runtime checks:

- Build the amd64 image
- Start a container with persistent appdata and read-only media mappings
- Verify `/api/health`, version, edition, and browser UI
- Verify ffprobe and MediaInfo availability
- Verify database and encryption-key creation
- Publish amd64 and arm64 images only after smoke validation succeeds

## Upgrade compatibility

The v1.0.3 and v1.4.5 SQLAlchemy entity definitions are identical. The upgrade
uses the existing SQLite database and `.secret_key`; no destructive migration is
performed. Operators should still back up appdata before changing container
images.
