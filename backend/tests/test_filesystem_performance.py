from pathlib import Path

from app.services.scanner import ScanManager
from app.sources.base import FileCandidate
from app.sources.filesystem import FilesystemAdapter


def test_filesystem_scan_reports_progress_and_avoids_path_resolve(tmp_path, monkeypatch):
    movie = tmp_path / "Example Movie (2024)"
    movie.mkdir()
    media = movie / "Example Movie (2024).mkv"
    media.write_bytes(b"not-real-video")
    (movie / "poster.jpg").write_bytes(b"poster")

    # A network-backed Path.resolve() was one of the original per-file SMB calls.
    monkeypatch.setattr(Path, "resolve", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("resolve called")))

    progress = []
    results = FilesystemAdapter(str(tmp_path), {}).scan(lambda movies, files, location: progress.append((movies, files, location)))

    assert len(results) == 1
    assert results[0].title == "Example Movie"
    assert results[0].year == 2024
    assert results[0].poster_ref == str(movie / "poster.jpg")
    assert results[0].files[0].size_bytes == len(b"not-real-video")
    assert progress[-1][:2] == (1, 1)


def test_server_technical_metadata_skips_ffprobe(monkeypatch):
    monkeypatch.setattr("app.services.scanner.probe_media", lambda path: (_ for _ in ()).throw(AssertionError("ffprobe called")))
    candidate = FileCandidate(
        source_file_id="1",
        path="movie.mkv",
        filename="movie.mkv",
        local_path=Path("movie.mkv"),
        technical={"video_codec": "hevc", "width": 3840, "height": 2160},
    )

    technical, error = ScanManager._analyze_file(candidate)

    assert error is None
    assert technical["video_codec"] == "hevc"


def test_filesystem_reads_common_nfo_and_local_poster_names(tmp_path):
    movie = tmp_path / "Folder Name That Should Not Win"
    movie.mkdir()
    media = movie / "Example.Movie.2022.mkv"
    media.write_bytes(b"not-real-video")
    poster = movie / "Example.Movie.2022-poster.webp"
    poster.write_bytes(b"poster")
    (movie / "movie.nfo").write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<movie>
  <title>Sidecar Movie Title</title>
  <originaltitle>Original Sidecar Title</originaltitle>
  <year>2022</year>
  <runtime>123</runtime>
  <plot>Plot loaded from a local NFO file.</plot>
  <edition>Director's Cut</edition>
  <uniqueid type=\"tmdb\">12345</uniqueid>
</movie>
""",
        encoding="utf-8",
    )

    results = FilesystemAdapter(str(tmp_path), {}).scan()

    assert len(results) == 1
    candidate = results[0]
    assert candidate.title == "Sidecar Movie Title"
    assert candidate.year == 2022
    assert candidate.runtime_seconds == 123 * 60
    assert candidate.overview == "Plot loaded from a local NFO file."
    assert candidate.poster_ref == str(poster)
    assert candidate.files[0].edition == "Director's Cut"
    assert candidate.metadata["metadata_sidecar"] == "movie.nfo"
    assert candidate.metadata["unique_ids"]["tmdb"] == "12345"


def test_flat_folder_uses_per_file_sidecars_and_not_generic_poster(tmp_path):
    # Four files force the flat-folder layout. Each movie should use its own
    # filename sidecar; generic poster.jpg must not be assigned to every title.
    (tmp_path / "poster.jpg").write_bytes(b"generic")
    for index in range(1, 5):
        stem = f"Movie {index} (2020)"
        (tmp_path / f"{stem}.mkv").write_bytes(b"video")
        (tmp_path / f"{stem}.nfo").write_text(
            f"<movie><title>Metadata Movie {index}</title><year>2020</year></movie>",
            encoding="utf-8",
        )
    specific = tmp_path / "Movie 2 (2020)-poster.jpg"
    specific.write_bytes(b"specific")

    results = FilesystemAdapter(str(tmp_path), {}).scan()

    assert [movie.title for movie in results] == [f"Metadata Movie {index}" for index in range(1, 5)]
    posters = {movie.title: movie.poster_ref for movie in results}
    assert posters["Metadata Movie 2"] == str(specific)
    assert posters["Metadata Movie 1"] is None
    assert posters["Metadata Movie 3"] is None
    assert posters["Metadata Movie 4"] is None


def test_local_poster_replaces_existing_cached_poster(tmp_path):
    source = tmp_path / "poster.png"
    source.write_bytes(b"new-local-poster")
    destination = tmp_path / "cached.jpg"
    destination.write_bytes(b"old-cached-poster" * 20)

    class Adapter:
        @staticmethod
        def fetch_poster(candidate, target):
            target.write_bytes(Path(candidate.poster_ref).read_bytes())
            return True

    from app.sources.base import MovieCandidate

    candidate = MovieCandidate(
        source_movie_id="movie",
        title="Movie",
        poster_ref=str(source),
        metadata={"origin": "filesystem"},
    )
    result = ScanManager._fetch_poster(Adapter(), candidate, destination, None)

    assert result.found is True
    assert destination.read_bytes() == b"new-local-poster"
