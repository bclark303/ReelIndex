from app.services.media_utils import clean_title, normalized_movie_key, resolution_label, sort_title


def test_clean_title_with_year_and_quality():
    title, year, edition = clean_title("Blade.Runner.2049.2017.2160p.UHD.BluRay.x265.mkv")
    assert title == "Blade Runner 2049"
    assert year == 2017
    assert edition is None


def test_clean_title_detects_edition():
    title, year, edition = clean_title("Alien (1979) Directors Cut 1080p.mkv")
    assert title == "Alien"
    assert year == 1979
    assert edition == "Director's Cut"


def test_resolution_labels():
    assert resolution_label(3840, 2160) == "4K"
    assert resolution_label(1920, 1080) == "1080p"
    assert resolution_label(1280, 720) == "720p"


def test_sort_title_and_key():
    assert sort_title("The Matrix") == "matrix, the"
    assert normalized_movie_key("The Matrix", 1999) == "thematrix:1999"
