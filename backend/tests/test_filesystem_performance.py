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
