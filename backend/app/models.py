from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("relative_path", name="uq_videos_relative_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    absolute_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_ts: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Folder path relative to VIDEO_LIBRARY_PATH; empty string for root
    folder_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    # Browser compatibility
    compatibility_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compatibility_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


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


