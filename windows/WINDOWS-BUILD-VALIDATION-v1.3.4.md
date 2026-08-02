# ReelIndex Windows v1.3.4 Validation and Scan Analysis

## Input trace

Analyzed `reelindex-scan-2bdb89d1-586a-4d80-b06e-207ad769a78e (2).jsonl`, focusing on the v1.3.3 resume segment from 2026-08-01 21:03:00 UTC through 21:23:54 UTC.

## v1.3.3 measured results

- Resume queue at start: 2,794 files
- Runtime before user cancellation: 20 minutes 54.6 seconds
- Probe attempts started: 1,240
- Completed attempts with timing: 1,239
- Successful analyses: 1,129
- Timed-out analyses: 110
- One active probe was cancelled
- Approximate queue remaining after the segment: 1,665 files
- Recovery sleeps and canary probes: none

### Container results

| Container | Attempted | Successful | Timed out | Success rate | Successful median | Successful p95 |
|---|---:|---:|---:|---:|---:|---:|
| MP4 | 754 | 754 | 0 | 100% | 1.211 s | 2.017 s |
| AVI | 35 | 35 | 0 | 100% | 1.310 s | 2.317 s |
| MOV | 14 | 14 | 0 | 100% | 0.659 s | 1.813 s |
| MKV | 437 | 326 | 110 | 74.6% | 0.311 s | 1.112 s |

All observed timeouts were Matroska files. The 803 MP4/AVI/MOV files completed in about 4 minutes 22 seconds at roughly 3.06 files per second. The subsequent MKV section processed about 0.44 files per second because timed-out files consumed the full eight-second limit and the scheduler spent most of the period at one worker.

## Defects identified

1. The four-second first-attempt timeout did not activate for untouched files. The generic analysis attempt counter had already been incremented by Quick scans, so every Deep probe appeared to be a retry and received eight seconds.
2. Matroska used the same 12 MB probe-size and six-second analysis-duration limits as other non-transport containers, despite its track metadata normally being near the beginning of the file.
3. Four global workers were initially used when the queue entered the MKV section, producing an immediate timeout cluster on the SMB-backed source.
4. Concurrency recovery required a long consecutive-success streak. With a roughly 75% MKV success rate, isolated timeouts repeatedly reset the streak and kept the scheduler at one worker.
5. Cancellation logs lacked a final structured per-container checkpoint.

## v1.3.4 changes

- Added a dedicated `deep_attempt_count` marker.
- Migrates older records safely: Quick-only records count as zero Deep attempts; records whose latest mode is Deep count as previously attempted.
- Untouched Deep files now receive the intended four-second initial timeout.
- Retried Deep files retain the eight-second timeout.
- Matroska/WebM standard probes use a 4 MB probe window and two-second analysis duration.
- MP4/M4V/MOV/AVI/WMV standard probes use an 8 MB/four-second header window.
- Matroska/WebM is capped at two concurrent workers.
- Transport-stream formats are capped at one concurrent worker.
- Fast containers retain the full configured worker pool.
- Container groups are processed separately rather than mixed at a queue boundary.
- Reduced concurrency recovers using a rolling health window: at least eight responsive results with no more than one-third timeouts in the recent window.
- Verbose logs emit per-container checkpoints every 100 attempts.
- Cancellation writes a final checkpoint containing attempted, succeeded, failed, timed-out, remaining, active-worker, group, and per-container statistics.

## Automated validation

- Backend tests: 47 passed
- Python compilation: passed for backend, Windows app, and Windows payload
- Windows static JavaScript syntax: passed
- Runtime import and health response: version 1.3.4, status `ok`
- Patch ZIP integrity: passed
- Installer payload ZIP integrity: passed
- Setup executable format: Windows x64 PE32+ GUI executable
- Setup SHA-256: `45655f4068d0c61c24cd0a3d3023bd5bf4793e3893b1c9679b96399b5b290fac`

## Test recommendation

Install v1.3.4 and use **Resume deep** without clearing the cache. Leave verbose scan logging enabled and run for 10 to 20 minutes. The next trace should demonstrate:

- `Deep probe profile switched to matroska · up to 2 workers`
- Four-second probes for untouched MKV records
- Eight-second probes only for previously timed-out records
- Per-container checkpoint events
- More frequent recovery from one worker back to two
- A final structured checkpoint after cancellation
