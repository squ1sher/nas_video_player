from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    runtime_dirs: dict[str, str]


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
    current_status: dict[str, object] | None = None


class ScanStatusOut(BaseModel):
    status: str  # idle | running | completed | failed | interrupted | cancelling | cancelled
    cancellation_requested: bool = False
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    scanned_files: int
    detected_videos: int
    existing_unchanged: int = 0
    probe_failed: int
    ignored_non_media: int
    ignored_excluded: int
    thumbnails_generated: int
    thumbnail_errors: int
    thumbnail_failed: int = 0
    scanned: int
    added: int
    updated: int
    removed_missing: int = 0
    errors: list[str]
    current_file: Optional[str]
    current_root: Optional[str] = None
    roots_scanned: int = 0
    total_roots: int = 0
    message: str | None = None


class VideoListItem(BaseModel):
    id: int
    library_root_id: int | None = None
    library_root_name: str | None = None
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
    tags: list["VideoTagLiteOut"] = Field(default_factory=list)


class VideoDetail(BaseModel):
    id: int
    library_root_id: int | None = None
    library_root_name: str | None = None
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
    tags: list["VideoTagLiteOut"] = Field(default_factory=list)


class VideoTagLiteOut(BaseModel):
    id: int
    name: str
    path: str
    color: str | None = None


class VideoTagOut(BaseModel):
    id: int
    name: str
    path: str
    parent_id: int | None = None
    color: str | None = None


class VideoTagAssignIn(BaseModel):
    tag_ids: list[int]


class TagCreateIn(BaseModel):
    name: str
    parent_id: int | None = None
    color: str | None = None
    description: str | None = None


class TagUpdateIn(BaseModel):
    name: str
    parent_id: int | None = None
    color: str | None = None
    description: str | None = None


class TagOut(BaseModel):
    id: int
    name: str
    normalized_name: str
    parent_id: int | None = None
    path: str
    depth: int
    color: str | None = None
    description: str | None = None
    video_count: int
    created_at: datetime
    updated_at: datetime


class TagTreeOut(TagOut):
    children: list["TagTreeOut"] = Field(default_factory=list)


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
    library_root_id: int | None = None
    library_root_name: str | None = None
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
    is_outdated: bool = False


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
    queued_jobs: int = 0
    active_batch_id: int | None = None
    active_batch_status: str | None = None
    active_batch_progress_percent: float | None = None
    recent_failed: int
    recent_completed: int


class HlsLibraryBatchIn(BaseModel):
    qualities: list[str] | None = None
    skip_existing: bool = True
    force: bool = False
    only_missing_hls: bool = True


class HlsLibraryBatchOut(BaseModel):
    batch_id: int | None
    status: str
    total_library_videos: int
    queued_count: int
    skipped_existing_hls: int = 0
    skipped_already_queued: int = 0
    skipped_missing_source: int = 0
    skipped_invalid: int = 0
    message: str


class HlsBatchCurrentVideoOut(BaseModel):
    id: int
    title: str
    relative_path: str


class HlsBatchItemOut(BaseModel):
    id: int
    batch_id: int
    video_id: int | None
    status: str
    skip_reason: str | None = None
    error_message: str | None = None
    hls_job_id: int | None = None
    current_quality: str | None = None
    progress_percent: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class HlsBatchDetailOut(BaseModel):
    id: int
    status: str
    total_count: int
    queued_count: int
    running_count: int
    completed_count: int
    failed_count: int
    skipped_count: int
    progress_percent: float
    estimated_remaining_count: int
    current_video: HlsBatchCurrentVideoOut | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    items: list[HlsBatchItemOut] = []


class HlsDiagnosticsItemOut(BaseModel):
    video_id: int | None
    title: str
    relative_path: str
    reason: str


class HlsDiagnosticsOut(BaseModel):
    total_videos: int
    valid_hls: int
    missing_hls: int
    db_completed_but_files_missing: int
    files_exist_but_db_missing: int
    stale_queued: int
    stale_running: int
    active_queued: int
    active_running: int
    invalid_source_missing: int
    details: dict[str, list[HlsDiagnosticsItemOut]] | None = None


class HlsRepairOut(BaseModel):
    checked: int
    valid_hls: int
    missing_hls: int
    db_repaired_to_completed: int
    stale_completed_invalidated: int
    stale_queued_reset: int
    stale_running_reset: int
    errors: list[str]


class PlaybackSourceOut(BaseModel):
    source_type: str
    stream_url: str | None
    available_qualities: list[str]
    reason: str


# ── Library Root / Media Source schemas ──────────────────────────────────────

class LibraryRootIn(BaseModel):
    name: str
    path: str
    media_type: str = "video"
    enabled: bool = True
    recursive: bool = True
    scan_priority: int = 100


class LibraryRootUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    media_type: Optional[str] = None
    enabled: Optional[bool] = None
    recursive: Optional[bool] = None
    scan_priority: Optional[int] = None


class LibraryRootOut(BaseModel):
    id: int
    name: str
    path: str
    relative_path: str = ""    # relative to media root, e.g. "sclad/Movies"
    display_path: str = ""     # host-side display path, e.g. "/volume1/sclad/Movies"
    media_type: str
    enabled: bool
    recursive: bool
    scan_priority: int
    last_scanned_at: Optional[datetime]
    last_scan_status: Optional[str]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime
    video_count: int = 0

    model_config = {"from_attributes": True}


class PathValidationRequest(BaseModel):
    path: str


class PathValidationResult(BaseModel):
    valid: bool
    path: Optional[str] = None
    code: Optional[str] = None
    message: str


class MediaSourceBrowseItem(BaseModel):
    name: str
    relative_path: str    # e.g. "sclad/Movies"
    internal_path: str    # e.g. "/media/sclad/Movies"
    display_path: str     # e.g. "/volume1/sclad/Movies"
    is_directory: bool
    already_added: bool
    blocked: bool


class PathValidationResult(BaseModel):
    valid: bool
    path: Optional[str] = None
    code: Optional[str] = None
    message: str

