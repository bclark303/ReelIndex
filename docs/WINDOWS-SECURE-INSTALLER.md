# Secure Windows installer

The ReelIndex Windows installer is built as a fully offline package.

Release requirements:

- No PowerShell execution on the user device.
- No network access during installation.
- No downloaded scripts or runtime dependency installation.
- The Python runtime and all Python packages are bundled into the installer.
- A SHA-256 manifest is embedded with the payload and verified before files are installed.
- The complete payload and final setup executable are scanned with Microsoft Defender Antivirus on a Windows GitHub Actions runner.
- Publication occurs only after the Defender scan succeeds.

The installer remains unsigned until an Authenticode certificate is available, so Windows SmartScreen can still display an unknown-publisher warning. An unknown-publisher warning is different from an antivirus malware detection; users must never bypass an antivirus detection.
