from __future__ import annotations

from app.services.media_utils import clean_title


def test_additional_dotted_title_variants_preserve_the_full_title():
    assert clean_title("L.A. Confidential (1997)")[:2] == ("L A Confidential", 1997)
    assert clean_title("G.I. Joe The Rise of Cobra (2009)")[:2] == (
        "G I Joe The Rise of Cobra",
        2009,
    )
    assert clean_title("WALL.E (2008).mkv")[:2] == ("WALL E", 2008)
