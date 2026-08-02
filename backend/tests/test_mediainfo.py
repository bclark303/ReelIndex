from pathlib import Path

from app.services.mediainfo import normalize_mediainfo


def test_normalize_mediainfo_json():
    raw = {
        "media": {
            "track": [
                {"@type": "General", "Format": "Matroska", "Duration": "7264.125"},
                {
                    "@type": "Video",
                    "Format": "HEVC",
                    "Width": "3840",
                    "Height": "2160",
                    "BitRate": "18432000",
                },
                {"@type": "Audio", "Format": "E-AC-3", "Channels": "6", "Language": "en"},
                {"@type": "Audio", "Format": "AAC", "Channels": "2", "Language": "fr"},
            ]
        }
    }

    result = normalize_mediainfo(raw, Path("Example.mkv"))

    assert result["container"] == "matroska"
    assert result["duration_seconds"] == 7264.125
    assert result["video_codec"] == "hevc"
    assert result["width"] == 3840
    assert result["height"] == 2160
    assert result["resolution_label"] == "4K"
    assert result["video_bitrate"] == 18_432_000
    assert result["audio_codec"] == "eac3"
    assert result["audio_channels"] == 6
    assert result["audio_languages"] == "en, fr"
