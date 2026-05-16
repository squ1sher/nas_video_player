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
    video_profile: str | None
    video_level: str | None
    pixel_format: str | None
    audio_codec: str | None
    audio_channels: int | None
    audio_sample_rate: int | None
    thumbnail_url: str | None
    folder_path: str | None
    compatibility_status: str | None
    compatibility_reason: str | None
    media_status: str | None
    probe_status: str | None
    probe_error: str | None
    container_format: str | None
    thumbnail_status: str | None
    thumbnail_error: str | None
    media_profile_id: int | None
    media_profile_key: str | None
    auto_compatibility_status: str | None
    auto_compatibility_reason: str | None
    effective_compatibility_status: str | None
    compatibility_source: str | None
    manual_playback_status: str | None
    file_modified_at: datetime | None
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
    video_profile: str | None
    video_level: str | None
    pixel_format: str | None
    audio_codec: str | None
    audio_channels: int | None
    audio_sample_rate: int | None
    thumbnail_url: str | None
    folder_path: str | None
    compatibility_status: str | None
    compatibility_reason: str | None
    media_status: str | None
    probe_status: str | None
    probe_error: str | None
    container_format: str | None
    thumbnail_status: str | None
    thumbnail_error: str | None
    media_profile_id: int | None
    media_profile_key: str | None
    auto_compatibility_status: str | None
    auto_compatibility_reason: str | None
    effective_compatibility_status: str | None
    compatibility_source: str | None
    manual_playback_status: str | None
    file_modified_at: datetime | None
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


class LastLibraryScanSummary(BaseModel):
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    scanned_files: int
    detected_videos: int
    probe_failed: int
    ignored_non_media: int
    ignored_excluded: int
    thumbnail_errors: int


class LastDuplicateScanSummary(BaseModel):
    status: str
    candidate_groups_found: int
    potential_saving: int
    finished_at: Optional[datetime]


class LibrarySummaryOut(BaseModel):
    total_indexed: int
    detected_videos: int
    probe_failed_possible_video: int
    direct_play: int
    may_play: int
    may_not_play: int
    needs_conversion: int
    unknown_compatibility: int
    thumbnail_generated: int
    thumbnail_failed: int
    thumbnail_missing: int
    total_size: int
    media_profiles_total: int
    media_profiles_manual_checked: int
    media_profiles_pending_manual_check: int
    media_profiles_playable: int
    media_profiles_not_playable: int
    media_profiles_partially_playable: int
    media_profiles_unknown: int
    last_library_scan: LastLibraryScanSummary
    last_duplicate_scan: LastDuplicateScanSummary


class MediaProfileSampleVideoOut(BaseModel):
    id: int
    title: str
    filename: str
    relative_path: str
    thumbnail_url: str | None
    watch_url: str


class MediaProfileOut(BaseModel):
    id: int
    profile_key: str
    profile_version: str
    files_count: int
    sample_video: MediaProfileSampleVideoOut | None
    extension: str
    container_format: str
    video_codec: str
    video_profile: str
    video_level: str
    pixel_format: str
    audio_codec: str
    audio_channels: int | None
    audio_sample_rate: int | None
    width_bucket: str
    height_bucket: str
    auto_compatibility_status: str
    auto_compatibility_reason: str
    manual_playback_status: str | None
    manual_playback_note: str | None
    manual_checked_at: datetime | None
    effective_compatibility_status: str
    compatibility_source: str


class MediaProfileDetailOut(MediaProfileOut):
    videos: list[VideoListItem]


class MediaProfilePlaybackStatusIn(BaseModel):
    manual_playback_status: str
    manual_playback_note: str | None = None


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


class HlsPrepareIn(BaseModel):
    force: bool = False
    qualities: list[str] | None = None


class HlsPrepareOut(BaseModel):
    status: str
    video_id: int
    job_id: int | None = None


class HlsVideoStatusOut(BaseModel):
    video_id: int
    status: str
    progress_percent: float | None = None
    current_quality: str | None = None
    available_qualities: list[str] = []
    master_playlist_url: str | None = None
    error_message: str | None = None


class HlsJobOut(BaseModel):
    id: int
    video_id: int
    status: str
    progress_percent: float | None = None
    current_quality: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class HlsGlobalStatusOut(BaseModel):
    running: int
    max_concurrent: int
    recent_failed: int
    recent_completed: int


class PlaybackSourceOut(BaseModel):
    source_type: str
    stream_url: str | None
    available_qualities: list[str]
    reason: str


