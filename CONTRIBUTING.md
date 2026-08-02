# Contributing

Contributions and bug reports are welcome.

Before opening an issue, include:

- ReelIndex version and Windows version
- Source type: filesystem, Plex, Jellyfin, or Emby
- Container type involved, if relevant
- The exact error with credentials and personal paths removed
- Whether the issue reproduces with a Quick scan, Deep scan, or manual retry

For code changes, run the backend test suite from `backend/`:

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```
