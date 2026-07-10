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


def _table_exists(engine: Engine, table_name: str) -> bool:
    insp = inspect(engine)
    return table_name in insp.get_table_names()


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


def _drop_index_if_exists(engine: Engine, index_name: str) -> None:
    if _index_exists(engine, index_name):
        logger.info("Migration: dropping legacy index %s", index_name)
        with engine.begin() as conn:
            conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))


def _table_sql(engine: Engine, table: str) -> str:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"),
            {"n": table},
        ).scalar()
    return str(result or "")


def _videos_table_requires_multi_root_rebuild(engine: Engine) -> bool:
    sql = " ".join(_table_sql(engine, "videos").lower().split())
    if not sql:
        return False
    if "uq_videos_root_relative_path" in sql or "unique (library_root_id, relative_path)" in sql:
        return False
    return "uq_videos_relative_path" in sql or "unique (relative_path)" in sql


def _rebuild_videos_table_for_multi_root(engine: Engine) -> None:
    if not _videos_table_requires_multi_root_rebuild(engine):
        return

    logger.info("Migration: rebuilding videos table for multi-root relative_path uniqueness")
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE videos__new (
                    id INTEGER PRIMARY KEY,
                    library_root_id INTEGER NULL REFERENCES library_roots(id) ON DELETE SET NULL,
                    title VARCHAR(512) NOT NULL,
                    filename VARCHAR(512) NOT NULL,
                    relative_path VARCHAR(1024) NOT NULL,
                    absolute_path VARCHAR(2048) NOT NULL,
                    extension VARCHAR(16) NOT NULL,
                    size INTEGER NOT NULL,
                    modified_ts FLOAT NOT NULL,
                    duration FLOAT NULL,
                    width INTEGER NULL,
                    height INTEGER NULL,
                    video_codec VARCHAR(64) NULL,
                    video_profile VARCHAR(64) NULL,
                    video_level VARCHAR(32) NULL,
                    pixel_format VARCHAR(64) NULL,
                    audio_codec VARCHAR(64) NULL,
                    audio_channels INTEGER NULL,
                    audio_sample_rate INTEGER NULL,
                    thumbnail_path VARCHAR(1024) NULL,
                    thumbnail_status VARCHAR(32) NULL,
                    thumbnail_error TEXT NULL,
                    media_profile_id INTEGER NULL REFERENCES media_profiles(id) ON DELETE SET NULL,
                    media_profile_key VARCHAR(128) NULL,
                    media_profile_version VARCHAR(32) NULL,
                    media_status VARCHAR(64) NULL,
                    probe_status VARCHAR(32) NULL,
                    probe_error TEXT NULL,
                    container_format VARCHAR(128) NULL,
                    folder_path VARCHAR(1024) NULL,
                    compatibility_status VARCHAR(32) NULL,
                    compatibility_reason VARCHAR(512) NULL,
                    auto_compatibility_status VARCHAR(32) NULL,
                    auto_compatibility_reason VARCHAR(512) NULL,
                    effective_compatibility_status VARCHAR(32) NULL,
                    compatibility_source VARCHAR(64) NULL,
                    manual_playback_status VARCHAR(32) NULL,
                    indexed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_videos_root_relative_path UNIQUE (library_root_id, relative_path)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO videos__new (
                    id, library_root_id, title, filename, relative_path, absolute_path, extension, size, modified_ts,
                    duration, width, height, video_codec, video_profile, video_level, pixel_format,
                    audio_codec, audio_channels, audio_sample_rate, thumbnail_path, thumbnail_status,
                    thumbnail_error, media_profile_id, media_profile_key, media_profile_version,
                    media_status, probe_status, probe_error, container_format, folder_path,
                    compatibility_status, compatibility_reason, auto_compatibility_status,
                    auto_compatibility_reason, effective_compatibility_status, compatibility_source,
                    manual_playback_status, indexed_at, created_at, updated_at
                )
                SELECT
                    id, library_root_id, title, filename, relative_path, absolute_path, extension, size, modified_ts,
                    duration, width, height, video_codec, video_profile, video_level, pixel_format,
                    audio_codec, audio_channels, audio_sample_rate, thumbnail_path, thumbnail_status,
                    thumbnail_error, media_profile_id, media_profile_key, media_profile_version,
                    media_status, probe_status, probe_error, container_format, folder_path,
                    compatibility_status, compatibility_reason, auto_compatibility_status,
                    auto_compatibility_reason, effective_compatibility_status, compatibility_source,
                    manual_playback_status, indexed_at, created_at, updated_at
                FROM videos
                """
            )
        )
        conn.execute(text("DROP TABLE videos"))
        conn.execute(text("ALTER TABLE videos__new RENAME TO videos"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _tags_table_requires_hierarchy_rebuild(engine: Engine) -> bool:
    sql = " ".join(_table_sql(engine, "tags").lower().split())
    if not sql:
        return False
    # Legacy flat-tag schema had a global UNIQUE(normalized_name) constraint.
    has_global_unique = "unique (normalized_name)" in sql or "normalized_name varchar(255) not null unique" in sql
    has_scoped_unique = "unique (parent_id, normalized_name)" in sql
    return has_global_unique and not has_scoped_unique


def _rebuild_tags_table_for_hierarchy(engine: Engine) -> None:
    if not _tags_table_requires_hierarchy_rebuild(engine):
        return

    logger.info("Migration: rebuilding tags table to remove legacy global normalized_name uniqueness")
    has_normalized = _column_exists(engine, "tags", "normalized_name")
    has_parent = _column_exists(engine, "tags", "parent_id")
    has_path = _column_exists(engine, "tags", "path")
    has_depth = _column_exists(engine, "tags", "depth")
    has_color = _column_exists(engine, "tags", "color")
    has_description = _column_exists(engine, "tags", "description")
    has_created_at = _column_exists(engine, "tags", "created_at")
    has_updated_at = _column_exists(engine, "tags", "updated_at")

    normalized_expr = "coalesce(nullif(trim(normalized_name), ''), lower(trim(name)))" if has_normalized else "lower(trim(name))"
    parent_expr = "parent_id" if has_parent else "NULL"
    path_expr = "coalesce(nullif(trim(path), ''), name)" if has_path else "name"
    depth_expr = "coalesce(depth, 0)" if has_depth else "0"
    color_expr = "color" if has_color else "NULL"
    description_expr = "description" if has_description else "NULL"
    created_at_expr = "coalesce(created_at, CURRENT_TIMESTAMP)" if has_created_at else "CURRENT_TIMESTAMP"
    updated_at_expr = "coalesce(updated_at, CURRENT_TIMESTAMP)" if has_updated_at else "CURRENT_TIMESTAMP"

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE tags__new (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    normalized_name VARCHAR(255) NOT NULL,
                    parent_id INTEGER NULL REFERENCES tags(id) ON DELETE CASCADE,
                    path VARCHAR(2048) NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    color VARCHAR(32) NULL,
                    description TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO tags__new (
                    id, name, normalized_name, parent_id, path, depth,
                    color, description, created_at, updated_at
                )
                SELECT
                    id,
                    name,
                    {normalized_expr},
                    {parent_expr},
                    {path_expr},
                    {depth_expr},
                    {color_expr},
                    {description_expr},
                    {created_at_expr},
                    {updated_at_expr}
                FROM tags
                """
            )
        )
        conn.execute(text("DROP TABLE tags"))
        conn.execute(text("ALTER TABLE tags__new RENAME TO tags"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


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
        ("availability_status", "VARCHAR(32)"),
    ]
    for col, col_def in videos_migrations:
        _add_column_if_missing(engine, "videos", col, col_def)

    # Create indexes for columns that have index=True in the model
    _create_index_if_missing(engine, "ix_videos_media_status", "videos", "media_status")
    _create_index_if_missing(engine, "ix_videos_probe_status", "videos", "probe_status")
    _create_index_if_missing(engine, "ix_videos_folder_path", "videos", "folder_path")
    _create_index_if_missing(engine, "ix_videos_media_profile_id", "videos", "media_profile_id")
    _create_index_if_missing(engine, "ix_videos_media_profile_key", "videos", "media_profile_key")
    _create_index_if_missing(engine, "ix_videos_availability_status", "videos", "availability_status")

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
                    qualities_csv VARCHAR(64) NOT NULL DEFAULT '480p',
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
        ("qualities_csv", "VARCHAR(64) NOT NULL DEFAULT '480p'"),
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

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE hls_batches
                SET qualities_csv = '480p'
                WHERE trim(coalesce(qualities_csv, '')) = ''
                   OR trim(qualities_csv) = '480p,720p'
                   OR trim(qualities_csv) = '480p,720p,1080p'
                """
            )
        )

    # ── scheduled_jobs table ─────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id INTEGER PRIMARY KEY,
                    job_type VARCHAR(64) NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 0,
                    schedule_type VARCHAR(32) NOT NULL DEFAULT 'daily',
                    time_of_day VARCHAR(5) NOT NULL DEFAULT '02:00',
                    days_of_week VARCHAR(32) NULL,
                    last_run_at DATETIME NULL,
                    next_run_at DATETIME NULL,
                    last_status VARCHAR(32) NULL,
                    last_error TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    scheduled_job_migrations = [
        ("job_type", "VARCHAR(64)"),
        ("name", "VARCHAR(255)"),
        ("enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("schedule_type", "VARCHAR(32) NOT NULL DEFAULT 'daily'"),
        ("time_of_day", "VARCHAR(5) NOT NULL DEFAULT '02:00'"),
        ("days_of_week", "VARCHAR(32) NULL"),
        ("last_run_at", "DATETIME NULL"),
        ("next_run_at", "DATETIME NULL"),
        ("last_status", "VARCHAR(32) NULL"),
        ("last_error", "TEXT NULL"),
        ("created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in scheduled_job_migrations:
        _add_column_if_missing(engine, "scheduled_jobs", col, col_def)

    _create_index_if_missing(engine, "ix_scheduled_jobs_job_type", "scheduled_jobs", "job_type")
    _create_index_if_missing(engine, "ix_scheduled_jobs_next_run_at", "scheduled_jobs", "next_run_at")

    # ── library_roots table ───────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS library_roots (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    path VARCHAR(2048) NOT NULL UNIQUE,
                    media_type VARCHAR(32) NOT NULL DEFAULT 'video',
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    recursive BOOLEAN NOT NULL DEFAULT 1,
                    scan_priority INTEGER NOT NULL DEFAULT 100,
                    last_scanned_at DATETIME NULL,
                    last_scan_status VARCHAR(32) NULL,
                    last_error TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    _create_index_if_missing(engine, "ix_library_roots_id", "library_roots", "id")

    # ── videos.library_root_id column ────────────────────────────────────────
    _add_column_if_missing(engine, "videos", "library_root_id", "INTEGER NULL REFERENCES library_roots(id)")
    _rebuild_videos_table_for_multi_root(engine)
    _create_index_if_missing(engine, "ix_videos_library_root_id", "videos", "library_root_id")
    _create_index_if_missing(engine, "ix_videos_relative_path", "videos", "relative_path")
    _create_index_if_missing(engine, "ix_videos_absolute_path", "videos", "absolute_path")

    # ── photos table ───────────────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY,
                    media_source_id INTEGER NULL REFERENCES library_roots(id) ON DELETE SET NULL,
                    relative_path VARCHAR(1024) NOT NULL,
                    internal_path VARCHAR(2048) NOT NULL,
                    display_path VARCHAR(2048) NOT NULL,
                    filename VARCHAR(512) NOT NULL,
                    extension VARCHAR(16) NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_created_at DATETIME NULL,
                    file_modified_at DATETIME NULL,
                    captured_at DATETIME NULL,
                    date_source VARCHAR(32) NULL,
                    width INTEGER NULL,
                    height INTEGER NULL,
                    orientation INTEGER NULL,
                    camera_make VARCHAR(128) NULL,
                    camera_model VARCHAR(128) NULL,
                    lens_model VARCHAR(128) NULL,
                    iso INTEGER NULL,
                    exposure_time VARCHAR(64) NULL,
                    aperture VARCHAR(32) NULL,
                    focal_length VARCHAR(32) NULL,
                    thumbnail_path VARCHAR(1024) NULL,
                    preview_path VARCHAR(1024) NULL,
                    preview_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    preview_error TEXT NULL,
                    prepare_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    prepare_error TEXT NULL,
                    prepared_at DATETIME NULL,
                    media_identity VARCHAR(255) NULL UNIQUE,
                    scan_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    thumbnail_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    thumbnail_error TEXT NULL,
                    scan_error TEXT NULL,
                    raw_format BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_photos_source_relative_path UNIQUE (media_source_id, relative_path)
                )
                """
            )
        )

    _create_index_if_missing(engine, "ix_photos_media_source_id", "photos", "media_source_id")
    _create_index_if_missing(engine, "ix_photos_relative_path", "photos", "relative_path")
    _create_index_if_missing(engine, "ix_photos_extension", "photos", "extension")
    _create_index_if_missing(engine, "ix_photos_captured_at", "photos", "captured_at")
    _create_index_if_missing(engine, "ix_photos_media_identity", "photos", "media_identity")
    _create_index_if_missing(engine, "ix_photos_scan_status", "photos", "scan_status")
    _create_index_if_missing(engine, "ix_photos_thumbnail_status", "photos", "thumbnail_status")

    photo_prepare_migrations = [
        ("preview_status", "VARCHAR(32) NOT NULL DEFAULT 'pending'"),
        ("preview_error", "TEXT NULL"),
        ("prepare_status", "VARCHAR(32) NOT NULL DEFAULT 'pending'"),
        ("prepare_error", "TEXT NULL"),
        ("prepared_at", "DATETIME NULL"),
    ]
    for col, col_def in photo_prepare_migrations:
        _add_column_if_missing(engine, "photos", col, col_def)
    _create_index_if_missing(engine, "ix_photos_preview_status", "photos", "preview_status")
    _create_index_if_missing(engine, "ix_photos_prepare_status", "photos", "prepare_status")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS photo_prepare_jobs (
                    id INTEGER PRIMARY KEY,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    mode VARCHAR(32) NOT NULL DEFAULT 'missing',
                    total INTEGER NOT NULL DEFAULT 0,
                    processed INTEGER NOT NULL DEFAULT 0,
                    succeeded INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    current_photo_id INTEGER NULL REFERENCES photos(id) ON DELETE SET NULL,
                    current_path VARCHAR(1024) NULL,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    error TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    _create_index_if_missing(engine, "ix_photo_prepare_jobs_status", "photo_prepare_jobs", "status")
    _create_index_if_missing(engine, "ix_photo_prepare_jobs_mode", "photo_prepare_jobs", "mode")
    _create_index_if_missing(engine, "ix_photo_prepare_jobs_current_photo_id", "photo_prepare_jobs", "current_photo_id")

    # ── photo_tags table ───────────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS photo_tags (
                    id INTEGER PRIMARY KEY,
                    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    if _table_exists(engine, "photo_tags"):
        _add_column_if_missing(engine, "photo_tags", "created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_photo_tags_photo_tag
                ON photo_tags (photo_id, tag_id)
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_photo_tags_photo_id ON photo_tags (photo_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_photo_tags_tag_id ON photo_tags (tag_id)"))

    # ── tags table (hierarchical) ─────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    normalized_name VARCHAR(255) NOT NULL,
                    parent_id INTEGER NULL REFERENCES tags(id) ON DELETE CASCADE,
                    path VARCHAR(2048) NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    color VARCHAR(32) NULL,
                    description TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    _rebuild_tags_table_for_hierarchy(engine)

    # Support older flat-tag table shapes if they exist.
    tag_migrations = [
        ("normalized_name", "VARCHAR(255)"),
        ("parent_id", "INTEGER NULL REFERENCES tags(id)"),
        ("path", "VARCHAR(2048)"),
        ("depth", "INTEGER NOT NULL DEFAULT 0"),
        ("color", "VARCHAR(32)"),
        ("description", "TEXT"),
        ("created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in tag_migrations:
        _add_column_if_missing(engine, "tags", col, col_def)

    _drop_index_if_exists(engine, "uq_tags_normalized_name")
    _drop_index_if_exists(engine, "ix_tags_normalized_name_unique")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE tags
                SET normalized_name = lower(trim(name))
                WHERE normalized_name IS NULL OR trim(normalized_name) = ''
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE tags
                SET path = name
                WHERE path IS NULL OR trim(path) = ''
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE tags
                SET depth = CASE
                    WHEN path IS NULL OR trim(path) = '' THEN 0
                    ELSE (length(path) - length(replace(path, '/', '')))
                END
                WHERE depth IS NULL
                """
            )
        )

    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_parent_id ON tags (parent_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_path ON tags (path)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tags_normalized_name ON tags (normalized_name)"))
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_parent_normalized_expr
                ON tags (ifnull(parent_id, -1), normalized_name)
                """
            )
        )

    # ── video_tags table ─────────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS video_tags (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    if _table_exists(engine, "video_tags"):
        _add_column_if_missing(engine, "video_tags", "created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_video_tags_video_tag
                ON video_tags (video_id, tag_id)
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_video_tags_video_id ON video_tags (video_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_video_tags_tag_id ON video_tags (tag_id)"))

    # ── playlists table ──────────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    playlist_migrations = [
        ("description", "TEXT NULL"),
        ("created_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in playlist_migrations:
        _add_column_if_missing(engine, "playlists", col, col_def)

    _create_index_if_missing(engine, "ix_playlists_name", "playlists", "name")

    # ── playlist_items table ─────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS playlist_items (
                    id INTEGER PRIMARY KEY,
                    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    playlist_item_migrations = [
        ("position", "INTEGER NOT NULL DEFAULT 1"),
        ("added_at", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]
    for col, col_def in playlist_item_migrations:
        _add_column_if_missing(engine, "playlist_items", col, col_def)

    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_playlist_items_playlist_id ON playlist_items (playlist_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_playlist_items_video_id ON playlist_items (video_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_playlist_items_position ON playlist_items (position)"))
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_playlist_items_playlist_video
                ON playlist_items (playlist_id, video_id)
                """
            )
        )
        # Best-effort cleanup for old inconsistent DB snapshots.
        conn.execute(
            text(
                """
                DELETE FROM playlist_items
                WHERE playlist_id NOT IN (SELECT id FROM playlists)
                   OR video_id NOT IN (SELECT id FROM videos)
                """
            )
        )

    logger.info("Database migrations applied successfully")

