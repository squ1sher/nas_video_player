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
    ]
    for col, col_def in videos_migrations:
        _add_column_if_missing(engine, "videos", col, col_def)

    # Create indexes for columns that have index=True in the model
    _create_index_if_missing(engine, "ix_videos_media_status", "videos", "media_status")
    _create_index_if_missing(engine, "ix_videos_probe_status", "videos", "probe_status")
    _create_index_if_missing(engine, "ix_videos_folder_path", "videos", "folder_path")

    logger.info("Database migrations applied successfully")

