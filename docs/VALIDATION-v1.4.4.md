# ReelIndex Windows v1.4.4 Validation

## Scope

v1.4.4 adds a persistent Probe failures workspace so current technical-analysis failures are visible and actionable without parsing JSONL scan logs or rescanning an entire source.

## Failure visibility

The new page lists every active media file with a current `probe_error` and shows:

- Movie, year, filename, full indexed path, source, container, size, and last attempt time.
- The original analyzer error without truncating it into a generic warning.
- Attempt and Deep Scan attempt counts.
- A normalized cause and plain-language explanation.
- Cause-specific remediation guidance.
- Search plus source, cause, and container filters.

Current cause classes include timeout, unavailable path, permission failure, missing analyzer, malformed or unusual container, incomplete metadata, network/storage I/O, interrupted work, and unclassified failures.

## Targeted remediation

Each retryable record supports three one-file actions:

1. **Retry native** — rerun the normal bounded native-first strategy.
2. **Extended retry** — use larger bounded samples and the extended profile.
3. **ffprobe retry** — bypass native parsing and use the compatibility analyzer directly.

The same controls appear inside the movie detail page. Successful retries update the technical fields and clear the current failure. Failed retries retain the new error and append a bounded failure-history record. Retries are blocked while the same source has an active scan.

Non-retryable diagnoses provide corrective guidance instead, such as repairing a path mapping, checking share/NTFS permissions, or repairing the ReelIndex installation when ffprobe is unavailable.

## Verification

- Backend test suite: **80 passed**.
- New tests cover classification, failure listing, successful targeted retry, unavailable paths, retained attempt history, and active-scan protection.
- Python bytecode compilation passed.
- JavaScript syntax validation passed.
- Runtime health endpoint returned ReelIndex `1.4.4`.
- `/api/probe-failures` returned a valid paginated response.
- Static application delivery included the new Probe failures navigation and v1.4.4 cache-busted assets.
- Browser automation could not be used because the environment's Chromium policy blocks localhost navigation; direct runtime/API/static validation was used instead.

## Safety

- Probe remedies only read media files.
- Movie files, sidecars, directory names, and server metadata are never modified.
- Only one selected file is analyzed per manual retry.
- Existing source credentials, inventory, posters, Deep Scan queues, and scan history are preserved by the in-place patch.
