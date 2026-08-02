from app.sources.filesystem import FilesystemAdapter
from app.sources.jellyfin import JellyfinAdapter
from app.sources.plex import PlexAdapter


def create_adapter(source_type: str, url_or_path: str, library_id: str | None, config: dict):
    if source_type == "filesystem":
        return FilesystemAdapter(url_or_path, config)
    if source_type == "plex":
        return PlexAdapter(url_or_path, library_id, config)
    if source_type in {"jellyfin", "emby"}:
        return JellyfinAdapter(url_or_path, library_id, config, server_type=source_type)
    raise ValueError(f"Unsupported source type: {source_type}")
