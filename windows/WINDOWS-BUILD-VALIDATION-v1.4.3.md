# ReelIndex Windows v1.4.3 Validation

## Scope

v1.4.3 improves poster recovery after the v1.4.2 IMDb-ID pass and adds manual poster management to each movie detail drawer.

The supplied poster scan contained 77 unresolved titles. Pattern analysis found:

- 59 titles where ReelIndex can now generate at least one materially cleaner automatic search variant.
- 36 titles containing common release/source tags such as DVDRip, BRRip, XviD, HDRip, R5, or READNFO.
- 11 titles containing encoded dimensions such as `1280x544`.
- 7 titles containing disc markers such as `cd1` or `cd2`.
- 2 titles using a trailing article such as `Quest, The`.
- 18 titles that remained inherently ambiguous, collection-like, episodic, concert-oriented, misspelled, or based on working titles and therefore benefit from manual selection.

Counts overlap because a title may contain more than one kind of noise.

## Automatic matching changes

- Added release-name cleanup for disc markers, dimensions, resolution tags, rip/source tags, codecs, subtitle tags, release groups, websites, and `aka` suffixes.
- Added trailing-article normalization.
- Added safe franchise-order variants for numbered Star Trek and Harry Potter folders.
- Automatic TMDB matching now tries an ordered set of cleaned variants rather than only the raw folder title.
- Manual search ranks TMDB movie and TV results and supports IMDb IDs.

## Manual poster management

The movie detail drawer now includes **Manage poster**. It supports:

- TMDB movie and TV search by title, alternate phrase, year, or IMDb ID.
- A result grid with poster previews, title, year, media type, original title, and overview.
- Applying a selected TMDB poster to ReelIndex's local cache.
- Uploading JPEG, PNG, or WebP artwork up to 10 MB.
- Removing a cached poster without modifying media or sidecar files.
- Manual poster locking so later quick, deep, or poster scans do not overwrite the chosen image.
- Cache-busted poster URLs so changes appear immediately.

## Verification

- Backend test suite: 75 passed.
- Python bytecode compilation passed.
- JavaScript syntax validation passed.
- Runtime health endpoint returned ReelIndex `1.4.3`.
- Direct API upload test accepted a PNG, stored it under the poster cache, returned a cache-busted URL, and reduced missing-poster coverage from one to zero.
- Browser DOM validation rendered the detail drawer, opened the poster manager, submitted a mocked TMDB search, displayed a selectable poster result, and reported no JavaScript errors.
- Manual TMDB selection, manual upload, and scan-lock persistence have dedicated backend tests.

## Safety

- No endpoint modifies movie files or sidecar artwork.
- Uploaded and selected posters are written only under ReelIndex's application data directory.
- Uploads are restricted to JPEG, PNG, or WebP signatures and a maximum of 10 MB.
- TMDB credentials remain server-side and are never exposed to the browser.
