from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services.scanner import ScanManager
from app.services.tmdb import TmdbClient, clean_tmdb_search_title, extract_imdb_id
from app.sources.base import FileCandidate, MovieCandidate


class _Response:
    def __init__(self, payload=None, content: bytes = b""):
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_extracts_imdb_ids_from_release_names_and_nfo_metadata():
    assert extract_imdb_id("Alien 1979 (tt0078748)") == "tt0078748"
    assert extract_imdb_id("Release.cp(tt1911658)") == "tt1911658"
    assert extract_imdb_id({"unique_ids": {"imdb": "tt0050083"}}) == "tt0050083"


def test_cleans_imdb_suffix_for_title_search():
    assert clean_tmdb_search_title("12 Angry Men tt0050083") == "12 Angry Men"
    assert clean_tmdb_search_title("Prometheus cp(tt1446714)") == "Prometheus"
    assert clean_tmdb_search_title("Alien [IMDb tt0078748]") == "Alien"


def test_tmdb_uses_find_endpoint_before_title_search(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        if "/find/" in url:
            return _Response({"movie_results": [{"id": 348, "poster_path": "/alien.jpg"}]})
        raise AssertionError("title search should not be called when IMDb lookup succeeds")

    monkeypatch.setattr("app.services.tmdb.httpx.get", fake_get)
    result = TmdbClient("token").find_movie("Alien tt0078748", 1979)

    assert result["id"] == 348
    assert result["_reelindex_match"] == "imdb"
    assert result["_reelindex_imdb_id"] == "tt0078748"
    assert calls[0][0].endswith("/find/tt0078748")
    assert calls[0][1]["external_source"] == "imdb_id"


def test_tmdb_falls_back_to_clean_title_when_external_id_is_unknown(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        if "/find/" in url:
            return _Response({"movie_results": []})
        return _Response({"results": [{"id": 1, "poster_path": "/poster.jpg"}]})

    monkeypatch.setattr("app.services.tmdb.httpx.get", fake_get)
    result = TmdbClient("token").find_movie("A Beautiful Mind cp(tt0268978)", 2001)

    assert result["id"] == 1
    assert result["_reelindex_match"] == "title-year"
    search = calls[-1]
    assert search[1]["query"] == "A Beautiful Mind"
    assert search[1]["year"] == "2001"


def test_poster_fetch_extracts_imdb_id_from_filename(monkeypatch, tmp_path: Path):
    captured = {}

    class _Tmdb:
        def __init__(self, token):
            assert token == "token"

        def find_movie(self, title, year, imdb_id=None):
            captured.update(title=title, year=year, imdb_id=imdb_id)
            return {
                "id": 348,
                "poster_path": "/alien.jpg",
                "overview": "Space horror",
                "_reelindex_match": "imdb",
                "_reelindex_imdb_id": imdb_id,
            }

        def download_poster(self, poster_path, destination):
            destination.write_bytes(b"poster-data")
            return True

    class _Adapter:
        @staticmethod
        def fetch_poster(candidate, destination):
            return False

    monkeypatch.setattr("app.services.scanner.TmdbClient", _Tmdb)
    candidate = MovieCandidate(
        source_movie_id="movie",
        title="Alien tt0078748",
        year=1979,
        metadata={"origin": "filesystem"},
        files=[
            FileCandidate(
                source_file_id="file",
                path=r"M:\\Movies\\Alien 1979 (tt0078748)\\Alien.mkv",
                filename="Alien 1979 (tt0078748).mkv",
            )
        ],
    )
    destination = tmp_path / "poster.jpg"

    result = ScanManager._fetch_poster(_Adapter(), candidate, destination, "token")

    assert result.found is True
    assert result.imdb_id == "tt0078748"
    assert result.match_method == "imdb"
    assert captured["imdb_id"] == "tt0078748"
    assert destination.read_bytes() == b"poster-data"
