from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ScanResponse(BaseModel):
    scanned: int
    added: int
    updated: int
    errors: list[str]


class ScanStartedResponse(BaseModel):
    status: str
    message: str


class ScanStatusOut(BaseModel):
    status: str  # idle | running | completed | failed
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    scanned: int
    added: int
    updated: int
    errors: list[str]
    current_file: Optional[str]


class VideoListItem(BaseModel):
    id: int
    title: str
    filename: str
    extension: str
    size: int
    duration: float | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    thumbnail_url: str | None
    folder_path: str | None
    compatibility_status: str | None
    compatibility_reason: str | None
    created_at: datetime
    indexed_at: datetime


class VideoDetail(BaseModel):
    id: int
    title: str
    filename: str
    relative_path: str
    extension: str
    size: int
    duration: float | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    thumbnail_url: str | None
    folder_path: str | None
    compatibility_status: str | None
    compatibility_reason: str | None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime


class WatchProgressIn(BaseModel):
    position_seconds: float
    duration_seconds: float


class WatchProgressOut(BaseModel):
    video_id: int
    position_seconds: float
    duration_seconds: float
    percent_watched: float
    completed: bool
    last_watched_at: Optional[datetime]


class VideoWithProgress(VideoListItem):
    """VideoListItem with embedded watch progress for continue-watching."""

    progress: WatchProgressOut


class FolderOut(BaseModel):
    folder_path: str  # relative path, empty string for root
    video_count: int
