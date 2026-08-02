# Building the Windows package

The published installer in `dist/` is the recommended way to install ReelIndex.

The Windows application consists of:

- `windows/app/` — FastAPI application and static browser UI
- `windows/launcher/` — per-user launcher source
- `windows/installer/` — standard network installer source

The standard installer downloads the Python runtime, Python packages, ffprobe, and MediaInfo during installation. It installs per-user under `%LOCALAPPDATA%\Programs\ReelIndex` and stores application data separately under `%LOCALAPPDATA%\ReelIndex`.

The installer source uses Go's `embed` support and expects a generated `windows/installer/payload.zip`. The payload must contain the application, compiled launcher and uninstaller, and `install-runtime.ps1`. Generated payloads, downloaded third-party runtimes, credentials, databases, logs, and cached posters are intentionally excluded from Git.

The checked-in Windows setup binary is provided for convenient sharing and is not digitally signed. Verify its SHA-256 value against `dist/SHA256SUMS.txt` before running it.
