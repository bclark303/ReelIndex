from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import MediaFile, Movie, Source
from app.services.media_utils import sort_title


DEMO_MOVIES = [
    ("Arrival", 2016, "4K", "hevc", "mkv", 12_842_112_000, 6960, "A linguist works to communicate with visitors whose arrival may reshape humanity."),
    ("Blade Runner 2049", 2017, "4K", "hevc", "mkv", 28_374_928_000, 9840, "A new blade runner uncovers a secret that leads him to a former LAPD officer."),
    ("The Grand Budapest Hotel", 2014, "1080p", "h264", "mp4", 8_212_443_000, 6000, "A concierge and lobby boy become entangled in a priceless inheritance."),
    ("Mad Max: Fury Road", 2015, "4K", "hevc", "mkv", 22_503_114_000, 7200, "Survivors flee a tyrant across a ruined wasteland."),
    ("Moon", 2009, "1080p", "h264", "mkv", 7_902_000_000, 5820, "A lunar worker nears the end of a solitary three-year contract."),
    ("Spirited Away", 2001, "1080p", "h264", "mkv", 9_445_000_000, 7500, "A young girl enters a world ruled by spirits and strange creatures."),
]


def seed_demo() -> None:
    if not settings.demo_mode:
        return
    with SessionLocal() as db:
        if db.scalar(select(func.count(Movie.id))) or 0:
            return
        source = Source(name="Demo Library", type="filesystem", url_or_path="/demo", config_json=json.dumps({}), enabled=True)
        db.add(source)
        db.flush()
        for index, (title, year, resolution, codec, container, size, runtime, overview) in enumerate(DEMO_MOVIES):
            movie = Movie(
                source_id=source.id,
                source_movie_id=f"demo-{index}",
                title=title,
                sort_title=sort_title(title),
                year=year,
                runtime_seconds=runtime,
                overview=overview,
                metadata_json=json.dumps({"origin": "demo"}),
            )
            db.add(movie)
            db.flush()
            height = 2160 if resolution == "4K" else 1080
            width = 3840 if resolution == "4K" else 1920
            db.add(
                MediaFile(
                    movie_id=movie.id,
                    source_file_id=f"demo-file-{index}",
                    path=f"/demo/{title} ({year})/{title}.{container}",
                    filename=f"{title}.{container}",
                    size_bytes=size,
                    fingerprint=f"demo-{index}",
                    container=container,
                    duration_seconds=runtime,
                    video_codec=codec,
                    width=width,
                    height=height,
                    resolution_label=resolution,
                    video_bitrate=18_000_000 if resolution == "4K" else 8_000_000,
                    audio_codec="aac" if container == "mp4" else "dts",
                    audio_channels=6,
                    probe_json=json.dumps({"demo": True}),
                )
            )
        db.commit()
