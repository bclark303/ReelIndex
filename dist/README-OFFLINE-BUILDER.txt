ReelIndex Offline Installer Builder 1.0.0
========================================

Purpose
-------
This tool creates a fully self-contained ReelIndex Windows installer from an
existing working ReelIndex installation. The generated setup EXE does not
access the internet during installation.

It bundles:
- ReelIndex application files and launchers
- The installed Python runtime and standard library
- All installed Python packages
- ffprobe
- MediaInfo CLI, when present in the existing installation
- Third-party license and metadata files already present in the installation

It never bundles:
- The ReelIndex SQLite database
- Configured source details or access tokens
- Encryption keys
- Posters or thumbnails
- Scan logs or verbose traces
- Any movie files

Requirements
------------
Run the builder on a 64-bit Windows computer where ReelIndex is already
installed and working. If the current installation was created by the older
network installer, it already contains the dependencies needed by the builder.

Usage
-----
1. Double-click Build-ReelIndex-Offline-Installer.exe.
2. Approve the confirmation prompt.
3. Wait while the installed runtime is compressed.
4. The builder writes this file to the Windows desktop:

   ReelIndex-Windows-Offline-Setup-v<installed-version>.exe

5. It also writes a matching .sha256.txt checksum file.
6. Copy the generated setup EXE to another Windows x64 computer and run it.
   No internet connection is required.

The generated installer preserves existing ReelIndex user data under:

   %LOCALAPPDATA%\ReelIndex

It replaces only the program installation under:

   %LOCALAPPDATA%\Programs\ReelIndex

Command-line usage
------------------
The default source is %LOCALAPPDATA%\Programs\ReelIndex and the default output
is the current user's desktop.

Custom source and output:

  Build-ReelIndex-Offline-Installer.exe "C:\Path\To\ReelIndex" "D:\ReelIndex-Offline-Setup.exe"

Validation and rollback
-----------------------
The generated installer validates Python imports, ffprobe, and MediaInfo when
present. Before replacing an existing installation, it creates a temporary
program-file backup. If extraction or validation fails, the previous program
files are restored. ReelIndex user data is not deleted.

Expected size
-------------
The generated setup file will usually be much larger than the network
bootstrapper because it contains Python, site-packages, ffprobe, and MediaInfo.
The exact size depends on the installed dependency versions.

Windows SmartScreen
-------------------
The builder and generated installer are not digitally signed. Windows may show
an Unknown publisher or SmartScreen warning.
