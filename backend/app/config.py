import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    video_library_path: Path = Field(default=Path("/media"), validation_alias="VIDEO_LIBRARY_PATH")
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
            ".mp3,.flac,.wav,.m4a,.aac,.ogg,.wma,.opus"
            ",.jpg,.jpeg,.png,.webp,.gif,.heic,.heif,.bmp,.tiff,.avif,.svg"
            ",.txt,.nfo,.srt,.ass,.ssa,.sub,.idx,.vtt"
            ",.db,.sqlite,.json,.xml,.log,.tmp,.part,.crdownload,.ds_store"
            ",.zip,.rar,.7z,.tar,.gz"
            ",.pdf,.doc,.docx,.xls,.xlsx,.exe,.sh"
        ),
        validation_alias="EXCLUDED_EXTENSIONS",
    )
    min_media_file_size_bytes: int = Field(default=1_048_576, validation_alias="MIN_MEDIA_FILE_SIZE_BYTES")
    probe_unknown_extensions: bool = Field(default=True, validation_alias="PROBE_UNKNOWN_EXTENSIONS")
    max_concurrent_hls_jobs: int = Field(default=1, validation_alias="MAX_CONCURRENT_HLS_JOBS")
    hls_segment_seconds: int = Field(default=4, validation_alias="HLS_SEGMENT_SECONDS")
    hls_ffmpeg_preset: str = Field(default="veryfast", validation_alias="HLS_FFMPEG_PRESET")
    hls_crf: int = Field(default=23, validation_alias="HLS_CRF")

    # ── Multi-root / library sources settings ────────────────────────────────
    # Comma-separated allowed base paths for media sources (security restriction).
    # If empty (default), any path is accepted. Set this in production for safety.
    # Example: ALLOWED_MEDIA_ROOT_BASES=/media,/media/videos
    allowed_media_root_bases: str = Field(
        default="",
        validation_alias="ALLOWED_MEDIA_ROOT_BASES",
    )
    # Comma-separated container paths to initialise as library roots on first run.
    # Example: /media/sclad/video,/media/sclad/gopro,/media/sclad/family
    media_library_roots: str = Field(default="", validation_alias="MEDIA_LIBRARY_ROOTS")
    # JSON alternative (preferred if both are set).
    # Example: [{"name":"GoPro","path":"/media/sclad/gopro"},{"name":"Family","path":"/media/sclad/family"}]
    media_library_roots_json: str = Field(default="", validation_alias="MEDIA_LIBRARY_ROOTS_JSON")

    @staticmethod
    def _ensure_writable_dir(path: Path, label: str) -> None:
        path.mkdir(parents=True, exist_ok=True)
        probe_path = path / f".write-probe-{os.getpid()}"
        try:
            probe_path.write_text("ok", encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Runtime directory is not writable for {label}: {path}") from exc
        finally:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass

    def ensure_runtime_dirs(self) -> None:
        self._ensure_writable_dir(self.database_path.parent, "database")
        self._ensure_writable_dir(self.thumbnails_path, "thumbnails")
        self._ensure_writable_dir(self.cache_path, "cache")
        self._ensure_writable_dir(self.hls_output_path, "hls")
        self._ensure_writable_dir(self.logs_path, "logs")

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

