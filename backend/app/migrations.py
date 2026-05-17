"""Simple in-process SQLite migration helpers.

Because the project does not use Alembic, schema changes that extend existing
tables (ADD COLUMN) are applied here at startup via raw SQL.  Every migration
is idempotent: it checks whether the column already exists before trying to add
it, so it is safe to run on every startup.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _column_exists(engine: Engine, table: str, column: str) -> bool:
    insp = inspect(engine)
    return any(c["name"] == column for c in insp.get_columns(table))


def _add_column_if_missing(
    engine: Engine,
    table: str,
    column: str,
    col_def: str,
) -> None:
    if not _column_exists(engine, table, column):
        logger.info("Migration: adding column %s.%s", table, column)
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


def _index_exists(engine: Engine, index_name: str) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": index_name},
        )
        return result.first() is not None


def _create_index_if_missing(
    engine: Engine,
    index_name: str,
    table: str,
    column: str,
) -> None:
    if not _index_exists(engine, index_name):
        logger.info("Migration: creating index %s on %s.%s", index_name, table, column)
        with engine.begin() as conn:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"))


def run_migrations(engine: Engine) -> None:
    """Apply all pending schema migrations.

    Safe to call on every startup – each step is a no-op if already applied.
    """
    # ── videos table – columns added in Stage 2 ─────────────────────────────
    videos_migrations = [
        # (column_name, sqlite_type_definition)
        ("thumbnail_status", "VARCHAR(32)"),
        ("media_status", "VARCHAR(64)"),
        ("probe_status", "VARCHAR(32)"),
        ("probe_error", "TEXT"),
        ("container_format", "VARCHAR(128)"),
        ("folder_path", "VARCHAR(1024)"),
        ("compatibility_status", "VARCHAR(32)"),
        ("compatibility_reason", "VARCHAR(512)"),
        ("pixel_format", "VARCHAR(64)"),
        ("thumbnail_error", "TEXT"),
        ("video_profile", "VARCHAR(64)"),
        ("video_level", "VARCHAR(32)"),
        ("audio_channels", "INTEGER"),
        ("audio_sample_rate", "INTEGER"),
        ("media_profile_id", "INTEGER"),
        ("media_profile_key", "VARCHAR(128)"),
        ("media_profile_version", "VARCHAR(32)"),
        ("auto_compatibility_status", "VARCHAR(32)"),
        ("auto_compatibility_reason", "VARCHAR(512)"),
        ("effective_compatibility_status", "VARCHAR(32)"),
        ("compatibility_source", "VARCHAR(64)"),
        ("manual_playback_status", "VARCHAR(32)"),
    ]
    for col, col_def in videos_migrations:
        _add_column_if_missing(engine, "videos", col, col_def)

    # Create indexes for columns that have index=True in the model
    _create_index_if_missing(engine, "ix_videos_media_status", "videos", "media_status")
    _create_index_if_missing(engine, "ix_videos_probe_status", "videos", "probe_status")
    _create_index_if_missing(engine, "ix_videos_folder_path", "videos", "folder_path")
    _create_index_if_missing(engine, "ix_videos_media_profile_id", "videos", "media_profile_id")
    _create_index_if_missing(engine, "ix_videos_media_profile_key", "videos", "media_profile_key")

    # ── media_profiles table ─────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS media_profiles (
                    id INTEGER PRIMARY KEY,
                    profile_key VARCHAR(128) NOT NULL UNIQUE,
                    profile_version VARCHAR(32) NOT NULL DEFAULT 'v1',
                    extension VARCHAR(16) NOT NULL DEFAULT 'unknown',
                    container_format VARCHAR(128) NOT NULL DEFAULT 'unknown',
                    video_codec VARCHAR(64) NOT NULL DEFAULT 'unknown',
                    video_profile VARCHAR(64) NOT NULL DEFAULT 'unknown',
                    video_level VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    pixel_format VARCHAR(64) NOT NULL DEFAULT 'unknown',
                    audio_codec VARCHAR(64) NOT NULL DEFAULT 'unknown',
                    audio_channels INTEGER NULL,
                    audio_sample_rate INTEGER NULL,
                    width_bucket VARCHAR(16) NOT NULL DEFAULT 'unknown',
                    height_bucket VARCHAR(16) NOT NULL DEFAULT 'unknown',
                    sample_video_id INTEGER NULL,
                    auto_compatibility_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    auto_compatibility_reason VARCHAR(512) NOT NULL DEFAULT 'unknown',
                    manual_playback_status VARCHAR(32) NULL,
                    manual_playback_note VARCHAR(1024) NULL,
                    manual_checked_at DATETIME NULL,
                    effective_compatibility_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    compatibility_source VARCHAR(64) NOT NULL DEFAULT 'auto_heuristic',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    _create_index_if_missing(engine, "ix_media_profiles_profile_key", "media_profiles", "profile_key")

    # ── media_profiles table – columns that may be missing in older deployments ─
    media_profile_migrations = [
        ("profile_version", "VARCHAR(32) NOT NULL DEFAULT 'v1'"),
        ("extension", "VARCHAR(16) NOT NULL DEFAULT 'unknown'"),
        ("container_format", "VARCHAR(128) NOT NULL DEFAULT 'unknown'"),
        ("video_codec", "VARCHAR(64) NOT NULL DEFAULT 'unknown'"),
        ("video_profile", "VARCHAR(64) NOT NULL DEFAULT 'unknown'"),
        ("video_level", "VARCHAR(32) NOT NULL DEFAULT 'unknown'"),
        ("pixel_format", "VARCHAR(64) NOT NULL DEFAULT 'unknown'"),
        ("audio_codec", "VARCHAR(64) NOT NULL DEFAULT 'unknown'"),
        ("audio_channels", "INTEGER NULL"),
        ("audio_sample_rate", "INTEGER NULL"),
        ("width_bucket", "VARCHAR(16) NOT NULL DEFAULT 'unknown'"),
        ("height_bucket", "VARCHAR(16) NOT NULL DEFAULT 'unknown'"),
        ("sample_video_id", "INTEGER NULL"),
        ("auto_compatibility_status", "VARCHAR(32) NOT NULL DEFAULT 'unknown'"),
        ("auto_compatibility_reason", "VARCHAR(512) NOT NULL DEFAULT 'unknown'"),
        ("manual_playback_status", "VARCHAR(32) NULL"),
        ("manual_playback_note", "VARCHAR(1024) NULL"),
        ("manual_checked_at", "DATETIME NULL"),
        ("effective_compatibility_status", "VARCHAR(32) NOT NULL DEFAULT 'unknown'"),
        ("compatibility_source", "VARCHAR(64) NOT NULL DEFAULT 'auto_heuristic'"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in media_profile_migrations:
        _add_column_if_missing(engine, "media_profiles", col, col_def)

    # ── hls_jobs table ────────────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS hls_jobs (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    progress_percent FLOAT NULL,
                    current_quality VARCHAR(32) NULL,
                    error_message TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    _create_index_if_missing(engine, "ix_hls_jobs_video_id", "hls_jobs", "video_id")
    _create_index_if_missing(engine, "ix_hls_jobs_status", "hls_jobs", "status")

    hls_job_migrations = [
        ("started_at", "DATETIME NULL"),
        ("finished_at", "DATETIME NULL"),
        ("progress_percent", "FLOAT NULL"),
        ("current_quality", "VARCHAR(32) NULL"),
        ("error_message", "TEXT NULL"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in hls_job_migrations:
        _add_column_if_missing(engine, "hls_jobs", col, col_def)

    # ── video_variants table ──────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS video_variants (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL,
                    variant_type VARCHAR(32) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    quality_label VARCHAR(32) NULL,
                    playlist_path VARCHAR(1024) NULL,
                    relative_output_path VARCHAR(1024) NULL,
                    stream_url VARCHAR(1024) NULL,
                    width INTEGER NULL,
                    height INTEGER NULL,
                    bitrate INTEGER NULL,
                    file_size INTEGER NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME NULL,
                    error_message TEXT NULL
                )
                """
            )
        )

    _create_index_if_missing(engine, "ix_video_variants_video_id", "video_variants", "video_id")
    _create_index_if_missing(engine, "ix_video_variants_variant_type", "video_variants", "variant_type")
    _create_index_if_missing(engine, "ix_video_variants_status", "video_variants", "status")

    video_variant_migrations = [
        ("quality_label", "VARCHAR(32) NULL"),
        ("playlist_path", "VARCHAR(1024) NULL"),
        ("relative_output_path", "VARCHAR(1024) NULL"),
        ("stream_url", "VARCHAR(1024) NULL"),
        ("width", "INTEGER NULL"),
        ("height", "INTEGER NULL"),
        ("bitrate", "INTEGER NULL"),
        ("file_size", "INTEGER NULL"),
        ("completed_at", "DATETIME NULL"),
        ("error_message", "TEXT NULL"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in video_variant_migrations:
        _add_column_if_missing(engine, "video_variants", col, col_def)

    # ── hls_batches table ─────────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS hls_batches (
                    id INTEGER PRIMARY KEY,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    request_type VARCHAR(32) NOT NULL DEFAULT 'library',
                    qualities_csv VARCHAR(64) NOT NULL DEFAULT '480p,720p,1080p',
                    skip_existing BOOLEAN NOT NULL DEFAULT 1,
                    force BOOLEAN NOT NULL DEFAULT 0,
                    only_missing_hls BOOLEAN NOT NULL DEFAULT 1,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    queued_count INTEGER NOT NULL DEFAULT 0,
                    running_count INTEGER NOT NULL DEFAULT 0,
                    completed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    progress_percent FLOAT NOT NULL DEFAULT 0,
                    error_message TEXT NULL,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    _create_index_if_missing(engine, "ix_hls_batches_status", "hls_batches", "status")

    hls_batch_migrations = [
        ("request_type", "VARCHAR(32) NOT NULL DEFAULT 'library'"),
        ("qualities_csv", "VARCHAR(64) NOT NULL DEFAULT '480p,720p,1080p'"),
        ("skip_existing", "BOOLEAN NOT NULL DEFAULT 1"),
        ("force", "BOOLEAN NOT NULL DEFAULT 0"),
        ("only_missing_hls", "BOOLEAN NOT NULL DEFAULT 1"),
        ("queued_count", "INTEGER NOT NULL DEFAULT 0"),
        ("running_count", "INTEGER NOT NULL DEFAULT 0"),
        ("completed_count", "INTEGER NOT NULL DEFAULT 0"),
        ("failed_count", "INTEGER NOT NULL DEFAULT 0"),
        ("skipped_count", "INTEGER NOT NULL DEFAULT 0"),
        ("progress_percent", "FLOAT NOT NULL DEFAULT 0"),
        ("error_message", "TEXT NULL"),
        ("started_at", "DATETIME NULL"),
        ("finished_at", "DATETIME NULL"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in hls_batch_migrations:
        _add_column_if_missing(engine, "hls_batches", col, col_def)

    # ── hls_batch_items table ────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS hls_batch_items (
                    id INTEGER PRIMARY KEY,
                    batch_id INTEGER NOT NULL,
                    video_id INTEGER NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    skip_reason VARCHAR(64) NULL,
                    error_message TEXT NULL,
                    hls_job_id INTEGER NULL,
                    current_quality VARCHAR(32) NULL,
                    progress_percent FLOAT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL
                )
                """
            )
        )

    _create_index_if_missing(engine, "ix_hls_batch_items_batch_id", "hls_batch_items", "batch_id")
    _create_index_if_missing(engine, "ix_hls_batch_items_video_id", "hls_batch_items", "video_id")
    _create_index_if_missing(engine, "ix_hls_batch_items_status", "hls_batch_items", "status")

    hls_batch_item_migrations = [
        ("skip_reason", "VARCHAR(64) NULL"),
        ("error_message", "TEXT NULL"),
        ("hls_job_id", "INTEGER NULL"),
        ("current_quality", "VARCHAR(32) NULL"),
        ("progress_percent", "FLOAT NULL"),
        ("started_at", "DATETIME NULL"),
        ("finished_at", "DATETIME NULL"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in hls_batch_item_migrations:
        _add_column_if_missing(engine, "hls_batch_items", col, col_def)

    logger.info("Database migrations applied successfully")

