from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class ScanResponse(BaseModel):
    scanned_files: int
    detected_videos: int
    probe_failed: int
    ignored_non_media: int
    ignored_excluded: int
    thumbnails_generated: int
    thumbnail_errors: int
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
    scanned_files: int
    detected_videos: int
    probe_failed: int
    ignored_non_media: int
    ignored_excluded: int
    thumbnails_generated: int
    thumbnail_errors: int
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
    media_status: str | None
    probe_status: str | None
    probe_error: str | None
    container_format: str | None
    thumbnail_status: str | None
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
    media_status: str | None
    probe_status: str | None
    probe_error: str | None
    container_format: str | None
    thumbnail_status: str | None
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


class DuplicateScanStartResponse(BaseModel):
    status: str
    mode: str


class DuplicateScanStatusOut(BaseModel):
    status: str
    mode: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    videos_checked: int
    candidate_groups_found: int
    duplicate_candidates_found: int
    current_step: Optional[str]
    errors: list[str]
    last_result_summary: dict[str, int | str | None] | None = None


class DuplicateFingerprintOut(BaseModel):
    mode: str
    version: str
    file_size: int
    duration_seconds: int | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    extension: str | None
    normalized_title: str | None


class DuplicateGroupVideoOut(BaseModel):
    id: int
    title: str
    filename: str
    relative_path: str
    size: int
    duration: float | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    extension: str
    thumbnail_url: str | None
    watch_url: str


class DuplicateGroupOut(BaseModel):
    group_id: str
    confidence: str
    reason: str
    candidate_count: int
    total_size: int
    potential_saving: int
    fingerprint: DuplicateFingerprintOut
    videos: list[DuplicateGroupVideoOut]


class DuplicateSummaryOut(BaseModel):
    last_scan_status: str
    candidate_groups_found: int
    duplicate_candidates_found: int
    potential_saving: int
    last_scan_at: str | None
    mode: str


