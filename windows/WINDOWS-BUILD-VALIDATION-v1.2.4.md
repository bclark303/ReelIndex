# ReelIndex Windows v1.3.0 Validation

## Supplied second scan trace

- Events parsed: 16,399 JSONL records; no malformed records
- Scan mode: Quick
- Total scan time: 148.47 seconds
- Discovery: 3,170 movies / 3,183 files in 117.86 seconds (27.01 files/s)
- Indexing: 5.67 seconds
- Files queued for analysis: 3,183
- Cache hits: 0
- Analysis: 16.19 seconds (196.62 files/s)
- Poster stage: 158 jobs in 8.59 seconds (18.4 jobs/s)
- Posters found: 158 / 158

### Stage share of total time

- Discovery: 79.4%
- Analysis: 10.9%
- Poster work: 5.8%
- Database indexing: 3.8%

## Comparison with the first trace

The v1.2.3 changes removed the runaway Quick-scan fallback behavior. The first trace was cancelled after 213.47 seconds while MediaInfo and ffprobe were repeatedly timing out. The second trace completed the entire inventory, technical stage, and poster stage in 148.47 seconds.

Auxiliary-file filtering reduced the filesystem inventory from 3,488 files in the first trace to 3,183 files in the second trace, a reduction of 305 files. The second trace shows no ffprobe activity.

## Remaining bottlenecks found

1. Filesystem discovery now dominates the scan. The scanner waited 117.86 seconds while enumerating approximately 3,170 mostly independent movie folders over SMB.
2. Seven MediaInfo calls reached the eight-second timeout. The intended circuit threshold was four, but workers that finished early could start replacement attempts before all first-batch failures had been recorded.
3. Verbose logging generated one per-file fallback, success, and timing event. This is useful for diagnosis but should be disabled during normal operation.
4. Poster processing is not a bottleneck in this workload: all 158 poster jobs completed in 8.59 seconds.

## v1.3.0 changes

- Filesystem discovery uses eight bounded workers by default.
- Independent movie folders are enumerated concurrently to overlap SMB directory latency.
- Each directory is still enumerated only once.
- Media contents are not opened during discovery.
- Extras, Trailers, Samples, and Featurettes subtrees are pruned before traversal.
- Results are merged serially and sorted deterministically after worker completion.
- The worker count is configurable through `REELINDEX_DISCOVERY_WORKERS` or a filesystem source's `discovery_workers` setting.
- MediaInfo and ffprobe circuit breakers reserve attempt slots. With four analysis workers, no more than four doomed calls can start before the circuit closes.
- Discovery worker count is included in verbose scan events and Diagnostics.

## Automated validation

- Backend tests: 31 passed
- Python compilation: passed
- Existing sidecar, poster, cancellation, maintenance, and tiered-analysis tests: passed
- Concurrent-discovery result equivalence: passed
- Concurrent analyzer circuit cap: passed
- Windows installer format: PE32+ x86-64 GUI executable
- Patch preserves configured sources, credentials, database records, scan history, and poster cache

## Synthetic discovery benchmark

A 200-folder test added 30 ms latency to each directory enumeration:

- 1 worker: 6.118 seconds, 32.7 folders/s
- 4 workers: 1.543 seconds, 129.7 folders/s
- 8 workers: 0.778 seconds, 257.2 folders/s

This benchmark isolates network round-trip latency and is not a prediction of exact Unraid performance. Real results depend on SMB latency, directory caching, array disk state, antivirus, and concurrent server activity.

## Expected next scan

Because the second scan cached all 3,183 files, a normal subsequent Quick scan should spend almost no time in technical analysis. The main measurement to watch after v1.3.0 is the `Discovery complete` line. If eight workers perform well against this share, total scan time should fall substantially below 148 seconds. If the array becomes slower under parallel metadata access, lower the value to four workers.
