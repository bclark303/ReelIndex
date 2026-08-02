# Competition Demonstration Script

## 1. Initial configuration

1. Open ReelIndex in the browser.
2. Open **Sources**.
3. Show the read-only notice.
4. Add or edit the demonstration server.
5. Point out that the URL/path, library ID, token, schedule, and path mapping are configuration—not source-code changes.
6. Select **Test connection** and choose the movie library.

## 2. Inventory creation

1. Select **Scan now**.
2. Show the live progress banner: discovered, analyzed, cached, and error counts.
3. Explain that ffprobe runs only for new or changed locally reachable files.
4. On a subsequent scan, point out the cached count and faster completion.

## 3. Library views and search

1. Show the poster grid.
2. Search for a known title.
3. Switch to table view.
4. Demonstrate resolution, codec, container, missing-poster, multiple-version, and probe-error filters.
5. Show pagination if the collection exceeds one page.

## 4. Technical information

1. Open a movie.
2. Show all grouped files/editions.
3. Show file size, resolution, video codec and bitrate, container, file path, audio codec and channels, language, and runtime.
4. Point out clean handling for missing posters or unavailable probe data.

## 5. Updating

1. Run a second scan and show cached reuse.
2. If practical, add, rename, replace, or remove a test file and scan again.
3. Confirm that the application inventory updates without altering the media library.

## 6. Portability test

1. Add the other competitor's server as a new source.
2. Test the connection and choose its movie library.
3. Add a path mapping only when exact ffprobe access is desired.
4. Start the scan without changing application code.

## 7. AI and code disclosure

1. Open `AI-DEVELOPMENT.md`.
2. State that GPT-5.6 Thinking helped design and implement the application.
3. Identify the manually reviewed and server-specific testing work.
4. Show the source layout and tests if a coding tie-break occurs.
