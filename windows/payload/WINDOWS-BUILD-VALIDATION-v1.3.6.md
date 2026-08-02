# ReelIndex Windows v1.3.6 Validation and Deep-Scan Analysis

## Uploaded v1.3.5 trace

The latest resume segment ran from 22:06:54 to 22:20:52 UTC.

- Queue at start: 1,235 MKV files
- Attempted: 695
- Successful: 534
- Timed out: 161
- Remaining: 701
- Elapsed: 838.60 seconds (13m 58.6s)
- Attempt throughput: 0.829 files/second
- Success throughput: 0.637 files/second

Compared with the preceding v1.3.4 segment, v1.3.5 increased attempted-file throughput from 0.472 to 0.829 files/second, approximately 1.76x.

For successful staged files:

- Median 4 MiB SMB staging time: 0.612 seconds
- Mean staging time: 0.793 seconds
- 95th percentile staging time: 1.514 seconds
- Median local ffprobe time: 0.110 seconds

For timed-out staged files:

- Mean total attempt time: 3.844 seconds
- Median total attempt time: 3.643 seconds

Successful attempts consumed 482.49 worker-seconds. Timed-out attempts consumed 618.91 worker-seconds, so 56.2% of measured worker time was still spent waiting for ffprobe against truncated local MKV fragments.

## v1.3.6 design

v1.3.6 adds a dependency-free Matroska/EBML header parser. After one bounded sequential copy from the source share, ReelIndex reads the staged header directly in Python instead of launching ffprobe for normal MKV/WebM files.

The native reader extracts:

- Matroska duration and timecode scale
- Video and audio codec identifiers
- Pixel/display resolution
- Audio channel count and languages
- Frame rate from DefaultDuration or FrameRate
- Video/audio/subtitle stream counts
- Basic HDR transfer and colour-primary signalling
- Overall bitrate calculated from original source size and embedded duration

The initial staged window is reduced from 2 MiB to 1 MiB. It expands to 4 MiB only when the native header is valid but incomplete. A bounded local ffprobe remains only as a compatibility fallback for unusual or malformed files. Fallback ffprobe uses zero packet-analysis duration and a one-packet read interval to avoid waiting for data beyond a truncated fragment.

The existing persistent Deep Scan queue remains compatible and is not reset by the patch.

## Validation

- Backend tests: 52 passed
- Python compilation: passed
- JavaScript syntax check: passed
- Native parser unit test: passed
- Native staged-probe bypass test: passed; ffprobe was not invoked
- Real MKV integration test: passed
  - Staged header: 135,327 bytes from a one-megabyte limit
  - Native parse time: 0.0003 seconds
  - Extracted H.264, 1920x1080, AAC, one channel, 3.021-second duration
  - Temporary staged file removed after analysis
- Existing cancellation and queue persistence tests: passed

## Expected next trace

Resume the existing queue without clearing the cache. Useful v1.3.6 verbose lines include:

- `Native Matroska header scan (1 MB initial)`
- `Native Matroska analysis ...`
- `Matroska staging ... + native parse ... + fallback probe ...`

The primary success criterion is that normal MKV files show a zero-second fallback probe and no longer create three-second local ffprobe timeouts.
