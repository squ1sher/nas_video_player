from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ScanResponse(BaseModel):
    scanned: int
    added: int
    updated: int
    errors: list[str]


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
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime

