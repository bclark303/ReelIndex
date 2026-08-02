from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ReelIndex"
    api_prefix: str = "/api"
    data_dir: Path = Path("/data")
    database_url: str | None = None
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    demo_mode: bool = False
    log_level: str = "INFO"
    tmdb_api_token: str | None = None
    poster_width: int = 500
    max_probe_seconds: int = 45
    max_mediainfo_seconds: int = 8
    probe_workers: int = 4
    poster_workers: int = 6
    scan_commit_interval: int = 50
    scan_verbose: bool = False
    ffprobe_path: str = "ffprobe"
    mediainfo_path: str = "mediainfo"
    static_dir: Path | None = None
    windows_mode: bool = False
    allowed_extensions: str = ".mkv,.mp4,.m4v,.avi,.mov,.wmv,.ts,.m2ts,.webm,.mpg,.mpeg"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="REELINDEX_", extra="ignore")

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'reelindex.db'}"

    @property
    def cors_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.allowed_extensions.split(",") if item.strip()}


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "posters").mkdir(parents=True, exist_ok=True)
(settings.data_dir / "scan-events").mkdir(parents=True, exist_ok=True)
