ReelIndex Windows v1.4.1

Unified native-container analysis release.

Native-first deep analysis supports:
- Matroska and WebM
- MP4, M4V, and MOV
- AVI
- ASF and WMV
- MPEG transport streams: TS, M2TS, and MTS
- MPEG program streams: MPG and MPEG

ffprobe remains installed as a bounded fallback for malformed, unusual, or
incomplete files. Existing databases, source credentials, poster caches, scan
history, and resumable deep queues are stored separately under
%LOCALAPPDATA%\ReelIndex and are preserved during an upgrade.

v1.4.1 poster pipeline:
Posters are resolved immediately after indexing. Use Sources > Posters to
repair missing artwork without re-running technical analysis.
