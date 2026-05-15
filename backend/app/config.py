from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    video_library_path: Path = Field(default=Path("/media/videos"), validation_alias="VIDEO_LIBRARY_PATH")
    database_path: Path = Field(default=Path("/app/data/app.db"), validation_alias="DATABASE_PATH")
    thumbnails_path: Path = Field(default=Path("/app/thumbnails"), validation_alias="THUMBNAILS_PATH")
    cache_path: Path = Field(default=Path("/app/cache"), validation_alias="CACHE_PATH")
    logs_path: Path = Field(default=Path("/app/logs"), validation_alias="LOGS_PATH")
    app_host: str = Field(default="0.0.0.0", validation_alias="APP_HOST")
    app_port: int = Field(default=8080, validation_alias="APP_PORT")
    chunk_size: int = Field(default=1_048_576, validation_alias="CHUNK_SIZE")

    def ensure_runtime_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.thumbnails_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

