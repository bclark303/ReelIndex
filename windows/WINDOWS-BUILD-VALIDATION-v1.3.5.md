# ReelIndex Windows v1.3.5 Validation and Deep-Scan Analysis

## Uploaded v1.3.4 resume trace

The newest resume segment ran from 2026-08-01 21:37:07 UTC through 21:57:58 UTC.

- Wall time: 1,250.86 seconds (20m 50.86s)
- Files attempted: 590
- Successful: 430
- Timed out: 160
- Queue remaining after cancellation: 1,235
- Container mix: 589 MKV and 1 MP4
- Matroska successes: 429
- Matroska timeouts: 160
- Successful Matroska median: 0.309 seconds
- Successful Matroska 95th percentile: 1.013 seconds
- Mean timeout duration: 8.049 seconds
- Worker reductions: 30
- Worker increases: 30

The successful MKV probes consumed about 213 worker-seconds, while timed-out MKV probes consumed about 1,288 worker-seconds. Therefore 85.8% of direct Matroska probing time was spent waiting for timeouts. The scheduler was stable, but direct ffprobe access over SMB remained the limiting factor.

## v1.3.5 design

For MKV and WebM files, ReelIndex no longer points ffprobe directly at the network file during Deep Scan.

1. A killable child Python process performs one bounded, sequential read from the source.
2. First attempts stage 2 MiB; retries stage 4 MiB.
3. The temporary fragment is written under the local ReelIndex data directory.
4. ffprobe runs against the local fragment with a three-second local timeout.
5. Overall bitrate is calculated from the original file size and embedded duration, avoiding the temporary fragment's misleading size.
6. The temporary fragment is deleted immediately, including cancellation and error paths.
7. MP4, MOV, AVI, transport streams, and other containers keep their existing direct profiles.

This remains read-only against the movie library.

## Validation completed

- Backend test suite: 50 passed
- Python compilation: passed
- Real generated Matroska integration test: passed
  - H.264 video detected
  - 1280x720 dimensions detected
  - AAC audio detected
  - duration detected from the staged fragment
  - bitrate recalculated from the original file size
  - temporary fragment removed
- Cancellation cleanup test: passed
- Non-Matroska regression test: passed
- Runtime health response: version 1.3.5, status `ok`
- Patch archive integrity: passed
- Installer payload ZIP integrity: passed
- Windows setup executable format: PE32+ x86-64 GUI

## Recommended test

Install v1.3.5, leave verbose scan logging enabled, and select **Resume deep** without clearing the cache. Run for 10 to 20 minutes, cancel, and upload the JSONL log. Useful new timing lines include `Matroska staging ... + local probe ...`.
