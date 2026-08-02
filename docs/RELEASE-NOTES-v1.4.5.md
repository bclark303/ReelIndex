# ReelIndex v1.4.5

v1.4.5 synchronizes the Windows, Docker, and Unraid editions on one canonical
backend and browser interface.

## Docker and Unraid

- Complete v1.4.4 Windows feature set is now available in the container.
- Added bounded native parsing for MKV/WebM, MP4/MOV, AVI, ASF/WMV, MPEG-TS,
  M2TS/MTS, and MPEG program streams.
- Added resumable Deep Scan queues, cancellation, structured scan output,
  manual poster management, IMDb poster matching, Probe Failures diagnosis,
  and targeted retry strategies.
- Added MediaInfo and ffprobe to the all-in-one image.
- Removed the legacy React/Node build; Docker now ships the same static UI as
  Windows.
- Added versioned GHCR publishing for amd64 and arm64.
- Added a current Unraid template with read-only media mappings and bounded
  worker controls.
- Reduced routine disk work by disabling nginx access logs and avoiding
  recursive poster-cache ownership changes during startup.

## Windows

- New v1.4.5 standard installer and in-place update package.
- Windows and Docker now consume the same canonical backend and web source.
- Added central release identity and platform-aware edition labels.
- Updated probe-failure guidance so it is accurate on Windows and containers.

## Upgrade compatibility

The v1.0.3 Unraid and v1.4.5 database entity definitions are identical. Existing
appdata, sources, encrypted credentials, posters, and scan history are retained.
Back up appdata before changing images.

## Validation

- 82 backend tests passed.
- v1.0.3 appdata opened successfully with retained records.
- Windows setup, launcher, uninstaller, and updater were built.
- Static UI, Python, Bash, nginx, XML, and workflow configuration checks passed.
- The GitHub Docker workflow performs the actual image build and container smoke
  test before publishing to GHCR.
