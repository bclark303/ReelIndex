# ReelIndex Offline Installer Builder 1.0.0 — Validation

## Deliverable

`Build-ReelIndex-Offline-Installer.exe` is a Windows x64 console application.
It creates a Windows x64 GUI setup executable by appending a ZIP payload to a
precompiled installer stub.

## Payload integrity format

The generated setup executable contains:

1. Windows GUI installer stub
2. ZIP payload
3. 72-byte footer:
   - 32-byte format magic
   - 8-byte little-endian payload length
   - 32-byte SHA-256 payload digest

The installer verifies the footer and SHA-256 digest before extracting any
files. Extraction rejects absolute paths, volume-qualified paths, and parent
traversal.

## Data boundaries

The builder reads only the program directory, normally:

`%LOCALAPPDATA%\Programs\ReelIndex`

It does not read the user-data directory:

`%LOCALAPPDATA%\ReelIndex`

Therefore databases, credentials, encryption keys, posters, and scan logs are
not added to the offline setup payload.

## Upgrade behavior

The generated installer:

- Stops the existing ReelIndex background process.
- Renames the previous program directory to a temporary backup.
- Extracts the complete offline payload.
- Validates required Python imports and bundled media-analysis tools.
- Recreates Start Menu, desktop, and uninstall entries.
- Restores the previous program directory if extraction or validation fails.
- Leaves the separate ReelIndex user-data directory untouched.

## Checks performed in the build environment

- Go source formatted successfully.
- Windows x64 installer stub cross-compiled successfully.
- Windows x64 builder cross-compiled successfully.
- `go vet` passed for both Windows targets.
- PE inspection identified the builder as Windows x64 console executable.
- PE inspection identified the generated installer stub as Windows x64 GUI executable.
- Embedded installer stub and PowerShell configuration script were confirmed in the builder.
- A mock payload was appended to the real installer stub.
- Footer parsing, payload-size parsing, SHA-256 validation, and ZIP extraction passed.
- Output-path protection prevents writing the generated setup inside the source installation tree.

## Windows-only checks remaining

The builder and generated setup executable must still be run on Windows to
validate the complete native flow, including WScript shortcut creation,
registry writes, Python import execution, ffprobe execution, MediaInfo
execution, service launch, and SmartScreen behavior.
