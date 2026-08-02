# ReelIndex Windows v1.1.4 Validation

## Fix

Version 1.1.4 corrects scan cancellation that could remain indefinitely in the `cancelling` state.

The previous implementation set the cancellation flag correctly, but the scan thread then called `ThreadPoolExecutor.shutdown(wait=True)`. A running poster HTTP request, slow media-server request, or blocked SMB discovery call could therefore keep the scan row active until the operating system or network timeout completed.

## Changes

- Blocking source discovery now runs in a daemon helper thread while the scan manager polls cancellation every 100 ms.
- Probe and poster worker pools use cancellation-aware polling instead of blocking in `as_completed`.
- Pending futures are cancelled immediately.
- Worker-pool shutdown no longer waits for blocked jobs after cancellation.
- Poster workers write to unique temporary files and atomically publish only when the scan is still active.
- Late poster responses after cancellation are discarded.
- Runtime aggregation checks the cancellation signal during large-library processing.
- Application and health version updated to 1.1.4.

## Tests

Executed from `backend` with `PYTHONPATH=.`:

```text
15 passed in 0.88s
```

Coverage includes:

- Immediate cancellation of a blocking discovery operation.
- Cancellation and termination of an active subprocess.
- Rejection of probe work after cancellation.
- Preservation of an existing cached poster when a late poster worker finishes after cancellation.
- Cleanup of temporary poster files.
- Existing filesystem metadata, poster-sidecar, security, and media parsing tests.

## Upgrade behavior

The in-place updater stops the current ReelIndex process before replacing files. Any scan that was stuck in `running` or `cancelling` is marked `interrupted` at the next startup. The database, configured sources, technical metadata, scan history, and poster cache are preserved.
