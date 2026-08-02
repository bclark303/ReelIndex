# Windows Build Validation

Build date: July 30, 2026

## Completed checks

- Compiled the setup program as a native Windows x86-64 GUI executable.
- Compiled the launcher and uninstaller as native Windows x86-64 GUI executables.
- Verified the embedded installer payload ZIP and every archived file.
- Compiled all Python backend modules.
- Ran the backend automated tests: 5 passed.
- Validated the production JavaScript syntax with Node.js.
- Started the packaged production UI against the FastAPI backend.
- Verified `/`, static assets, `/api/health`, movie statistics, sources, and diagnostics.
- Ran a headless Chromium interaction check across Library, Sources, Add Source, and Diagnostics.
- Confirmed no browser console errors or framework error overlays.
- Confirmed current Windows-compatible dependency releases and Python 3.12 support from their official package records.

## Environment limitation

The setup executable could not be executed end-to-end on Windows in the Linux build environment. The next validation step is to run the installer on a Windows 10 or Windows 11 x64 computer and confirm the runtime downloads, Start Menu registration, launch, scan, and uninstall process.

The setup executable is unsigned, so Windows may display an unknown-publisher warning.
