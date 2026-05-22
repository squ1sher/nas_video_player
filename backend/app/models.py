from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LibraryRoot(Base):
    """Configurable media source / library root directory."""

    __tablename__ = "library_roots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False, default="video")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    recursive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scan_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("library_root_id", "relative_path", name="uq_videos_root_relative_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    library_root_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("library_roots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    absolute_path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_ts: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    video_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    video_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pixel_format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thumbnail_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_profile_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("media_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    media_profile_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    media_profile_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    media_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    probe_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    probe_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    container_format: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Folder path relative to VIDEO_LIBRARY_PATH; empty string for root
    folder_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    # Browser compatibility
    compatibility_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compatibility_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auto_compatibility_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    auto_compatibility_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    effective_compatibility_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compatibility_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manual_playback_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    # Availability status: None / "available" = normal; "missing" = source enabled but file gone;
    # "source_disabled" = root disabled; "source_removed" = root deleted; "deleted" = user deleted
    availability_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class WatchProgress(Base):
    """Global (single-user) watch progress for each video."""

    __tablename__ = "watch_progress"
    __table_args__ = (UniqueConstraint("video_id", name="uq_watch_progress_video_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    position_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    percent_watched: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_watched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("parent_id", "normalized_name", name="uq_tags_parent_normalized_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class VideoTag(Base):
    __tablename__ = "video_tags"
    __table_args__ = (UniqueConstraint("video_id", "tag_id", name="uq_video_tags_video_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DuplicateCandidateGroup(Base):
    __tablename__ = "duplicate_candidate_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_size: Mapped[int] = mapped_column(Integer, nullable=False)
    potential_saving: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DuplicateCandidateItem(Base):
    __tablename__ = "duplicate_candidate_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("duplicate_candidate_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DuplicateScanRun(Base):
    __tablename__ = "duplicate_scan_runs"
    __table_args__ = (UniqueConstraint("mode", name="uq_duplicate_scan_runs_mode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    last_scan_status: Mapped[str] = mapped_column(String(32), nullable=False)
    videos_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_groups_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_candidates_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    potential_saving: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MediaProfile(Base):
    __tablename__ = "media_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    extension: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    container_format: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown")
    video_codec: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    video_profile: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    video_level: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    pixel_format: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    audio_codec: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    audio_channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    height_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    sample_video_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    auto_compatibility_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    auto_compatibility_reason: Mapped[str] = mapped_column(String(512), nullable=False, default="unknown")
    manual_playback_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manual_playback_note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    manual_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_compatibility_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    compatibility_source: Mapped[str] = mapped_column(String(64), nullable=False, default="auto_heuristic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HlsJob(Base):
    __tablename__ = "hls_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class VideoVariant(Base):
    __tablename__ = "video_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    video_id: Mapped[int] = mapped_column(Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    quality_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    playlist_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    relative_output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stream_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class HlsBatch(Base):
    __tablename__ = "hls_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    request_type: Mapped[str] = mapped_column(String(32), nullable=False, default="library")
    qualities_csv: Mapped[str] = mapped_column(String(64), nullable=False, default="480p,720p,1080p")
    skip_existing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    only_missing_hls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HlsBatchItem(Base):
    __tablename__ = "hls_batch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("hls_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    video_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    skip_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    hls_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hls_jobs.id", ondelete="SET NULL"), nullable=True)
    current_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

