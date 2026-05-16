from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    video_library_path: Path = Field(default=Path("/media/videos"), validation_alias="VIDEO_LIBRARY_PATH")
    database_path: Path = Field(default=Path("/app/data/app.db"), validation_alias="DATABASE_PATH")
    thumbnails_path: Path = Field(default=Path("/app/thumbnails"), validation_alias="THUMBNAILS_PATH")
    cache_path: Path = Field(default=Path("/app/cache"), validation_alias="CACHE_PATH")
    hls_output_path: Path = Field(default=Path("/app/cache/hls"), validation_alias="HLS_OUTPUT_PATH")
    logs_path: Path = Field(default=Path("/app/logs"), validation_alias="LOGS_PATH")
    app_host: str = Field(default="0.0.0.0", validation_alias="APP_HOST")
    app_port: int = Field(default=8080, validation_alias="APP_PORT")
    chunk_size: int = Field(default=1_048_576, validation_alias="CHUNK_SIZE")
    media_discovery_mode: Literal["extension_allowlist", "probe", "hybrid"] = Field(
        default="probe",
        validation_alias="MEDIA_DISCOVERY_MODE",
    )
    excluded_extensions: str = Field(
        default=(
            ".txt,.nfo,.srt,.ass,.ssa,.jpg,.jpeg,.png,.webp,.gif,.db,.sqlite,.json,.xml,.log,.tmp,.part,.crdownload,.ds_store"
        ),
        validation_alias="EXCLUDED_EXTENSIONS",
    )
    min_media_file_size_bytes: int = Field(default=1_048_576, validation_alias="MIN_MEDIA_FILE_SIZE_BYTES")
    probe_unknown_extensions: bool = Field(default=True, validation_alias="PROBE_UNKNOWN_EXTENSIONS")
    max_concurrent_hls_jobs: int = Field(default=1, validation_alias="MAX_CONCURRENT_HLS_JOBS")
    hls_segment_seconds: int = Field(default=4, validation_alias="HLS_SEGMENT_SECONDS")
    hls_ffmpeg_preset: str = Field(default="veryfast", validation_alias="HLS_FFMPEG_PRESET")
    hls_crf: int = Field(default=23, validation_alias="HLS_CRF")

    def ensure_runtime_dirs(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.thumbnails_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.hls_output_path.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)

    @property
    def excluded_extensions_set(self) -> set[str]:
        return {
            ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
            for ext in self.excluded_extensions.split(",")
            if ext.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()

