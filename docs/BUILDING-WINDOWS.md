# Building the Windows package

The Windows and Docker editions share the canonical `backend/app/` and `web/`
trees. The Windows installer requires a self-contained payload under
`windows/app/`, so synchronize it before building:

```bash
python scripts/sync-packages.py
python scripts/sync-packages.py --check
```

The Windows application consists of:

- `backend/app/` — canonical FastAPI application
- `web/` — canonical static browser UI
- `windows/app/` — synchronized Windows payload plus launcher script
- `windows/launcher/` — per-user launcher source
- `windows/installer/` — standard network installer source

The standard installer downloads the Python runtime, Python packages, ffprobe,
and MediaInfo during installation. It installs per-user under
`%LOCALAPPDATA%\Programs\ReelIndex` and stores application data separately under
`%LOCALAPPDATA%\ReelIndex`.

The installer uses Go's `embed` support and expects a generated
`windows/installer/payload.zip`. The payload contains:

- `app/`
- compiled `ReelIndex.exe`
- compiled `Uninstall ReelIndex.exe`
- `install-runtime.ps1`

Generated payloads, third-party runtimes, credentials, databases, logs, and
cached posters are excluded from Git.

Cross-compile the launcher, uninstaller, and setup program from Linux with:

```bash
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath \
  -ldflags "-s -w -H=windowsgui" -o ReelIndex.exe windows/launcher/main.go
```

The checked-in setup binary is not digitally signed. Verify its SHA-256 value
against `dist/SHA256SUMS.txt` before running it.
