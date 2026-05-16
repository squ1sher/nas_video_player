import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.media_probe import probe_video
from app.models import Video, WatchProgress
from app.scan_status import fail_scan, finish_scan, increment_progress, start_scan, update_current_file
from app.services.media_profile_service import (
    assign_profile_to_video,
    build_media_profile_fields,
    compute_auto_compatibility,
    upsert_media_profile,
)
from app.thumbnails import ensure_thumbnail
from app.utils.files import VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    scanned_files: int = 0
    detected_videos: int = 0
    probe_failed: int = 0
    ignored_non_media: int = 0
    ignored_excluded: int = 0
    thumbnails_generated: int = 0
    thumbnail_errors: int = 0
    added: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


def iter_library_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def _is_hidden_or_system(path: Path) -> bool:
    for part in path.parts:
        lower = part.lower()
        if part.startswith("."):
            return True
        if lower in {"@eaDir".lower(), "#recycle", "$recycle.bin", "system volume information"}:
            return True
    return False


def _should_probe_file(path: Path, settings: Settings) -> bool:
    extension = path.suffix.lower()
    is_known_video_extension = extension in VIDEO_EXTENSIONS
    is_unknown_extension = not is_known_video_extension

    mode = settings.media_discovery_mode
    if mode == "extension_allowlist":
        return is_known_video_extension

    if mode == "hybrid":
        if is_known_video_extension:
            return True
        if not settings.probe_unknown_extensions:
            return False

    if is_unknown_extension and path.stat().st_size < settings.min_media_file_size_bytes:
        return False

    return True


def _upsert_video_record(
    db: Session,
    existing: Video | None,
    file_path: Path,
    root: Path,
    folder_path: str,
    *,
    stat_size: int,
    stat_mtime: float,
    duration: float | None,
    width: int | None,
    height: int | None,
    video_codec: str | None,
    video_profile: str | None,
    video_level: str | None,
    pixel_format: str | None,
    audio_codec: str | None,
    audio_channels: int | None,
    audio_sample_rate: int | None,
    container_format: str | None,
    thumbnail_path: str | None,
    thumbnail_status: str,
    thumbnail_error: str | None,
    media_status: str,
    probe_status: str,
    probe_error: str | None,
    compatibility_status: str,
    compatibility_reason: str,
) -> tuple[bool, bool, Video]:
    relative_path = file_path.relative_to(root).as_posix()
    now = datetime.now(timezone.utc)

    if existing is None:
        db.add(
            Video(
                title=file_path.stem,
                filename=file_path.name,
                relative_path=relative_path,
                absolute_path=str(file_path),
                extension=file_path.suffix.lower(),
                size=stat_size,
                modified_ts=stat_mtime,
                duration=duration,
                width=width,
                height=height,
                video_codec=video_codec,
                video_profile=video_profile,
                video_level=video_level,
                pixel_format=pixel_format,
                audio_codec=audio_codec,
                audio_channels=audio_channels,
                audio_sample_rate=audio_sample_rate,
                container_format=container_format,
                thumbnail_path=thumbnail_path,
                thumbnail_status=thumbnail_status,
                thumbnail_error=thumbnail_error,
                media_status=media_status,
                probe_status=probe_status,
                probe_error=probe_error,
                folder_path=folder_path,
                compatibility_status=compatibility_status,
                compatibility_reason=compatibility_reason,
                indexed_at=now,
            )
        )
        db.flush()
        created_video = db.query(Video).filter(Video.relative_path == relative_path).first()
        return True, False, created_video

    existing.title = file_path.stem
    existing.filename = file_path.name
    existing.absolute_path = str(file_path)
    existing.extension = file_path.suffix.lower()
    existing.size = stat_size
    existing.modified_ts = stat_mtime
    existing.duration = duration
    existing.width = width
    existing.height = height
    existing.video_codec = video_codec
    existing.video_profile = video_profile
    existing.video_level = video_level
    existing.pixel_format = pixel_format
    existing.audio_codec = audio_codec
    existing.audio_channels = audio_channels
    existing.audio_sample_rate = audio_sample_rate
    existing.container_format = container_format
    existing.thumbnail_path = thumbnail_path
    existing.thumbnail_status = thumbnail_status
    existing.thumbnail_error = thumbnail_error
    existing.media_status = media_status
    existing.probe_status = probe_status
    existing.probe_error = probe_error
    existing.folder_path = folder_path
    existing.compatibility_status = compatibility_status
    existing.compatibility_reason = compatibility_reason
    existing.indexed_at = now
    return False, True, existing


def _compute_folder_path(file_path: Path, root: Path) -> str:
    """Return the folder path relative to root, using forward slashes. Empty string for root."""
    parent_relative = file_path.parent.relative_to(root)
    folder = parent_relative.as_posix()
    return "" if folder == "." else folder


def scan_video_library(db: Session, settings: Settings) -> ScanResult:
    result = ScanResult()
    root = settings.video_library_path
    logger.info("Scan started for %s", root)

    if not root.exists() or not root.is_dir():
        msg = f"Video library path does not exist: {root}"
        logger.error(msg)
        result.errors.append(msg)
        return result

    # ── Step 1: remove DB records whose source file no longer exists ─────────
    all_db_videos = db.query(Video).all()
    removed = 0
    for db_video in all_db_videos:
        try:
            disk_path = root / db_video.relative_path
            if not disk_path.exists() or not disk_path.is_file():
                logger.info("Source file missing, removing from index: %s", db_video.relative_path)
                db.query(WatchProgress).filter(WatchProgress.video_id == db_video.id).delete()
                db.delete(db_video)
                removed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error checking file for removal %s: %s", db_video.relative_path, exc)
    if removed:
        db.commit()
        logger.info("Removed %d stale DB records", removed)

    # ── Step 2: index new / changed files ───────────────────────────────────
    files = iter_library_files(root)
    logger.info("Found %d candidate files", len(files))

    for file_path in files:
        result.scanned_files += 1
        increment_progress(scanned_files_inc=1)
        update_current_file(str(file_path))
        try:
            if _is_hidden_or_system(file_path):
                continue

            relative_path = file_path.relative_to(root).as_posix()
            folder_path = _compute_folder_path(file_path, root)
            stat = file_path.stat()
            extension = file_path.suffix.lower()

            if extension in settings.excluded_extensions_set:
                result.ignored_excluded += 1
                increment_progress(ignored_excluded_inc=1)
                continue

            if not _should_probe_file(file_path, settings):
                result.ignored_non_media += 1
                increment_progress(ignored_non_media_inc=1)
                continue

            existing = db.query(Video).filter(Video.relative_path == relative_path).first()
            unchanged = (
                existing is not None
                and existing.size == stat.st_size
                and abs(existing.modified_ts - stat.st_mtime) < 1e-6
            )
            if unchanged:
                if existing and existing.media_profile_id is None:
                    auto_status, auto_reason = compute_auto_compatibility(
                        existing.extension,
                        existing.video_codec,
                        existing.audio_codec,
                    )
                    profile_fields = build_media_profile_fields(
                        extension=existing.extension,
                        container_format=existing.container_format,
                        video_codec=existing.video_codec,
                        video_profile=existing.video_profile,
                        video_level=existing.video_level,
                        pixel_format=existing.pixel_format,
                        audio_codec=existing.audio_codec,
                        audio_channels=existing.audio_channels,
                        audio_sample_rate=existing.audio_sample_rate,
                        width=existing.width,
                        height=existing.height,
                    )
                    profile = upsert_media_profile(db, profile_fields, auto_status=auto_status, auto_reason=auto_reason)
                    assign_profile_to_video(existing, profile)
                    if profile.sample_video_id is None:
                        profile.sample_video_id = existing.id
                    result.updated += 1
                    increment_progress(updated_inc=1)
                continue

            logger.info("Indexing file: %s", relative_path)
            probe = probe_video(file_path)
            if not probe.success:
                result.probe_failed += 1
                increment_progress(probe_failed_inc=1)

                if settings.probe_unknown_extensions and extension not in settings.excluded_extensions_set:
                    auto_status, auto_reason = compute_auto_compatibility(extension, None, None)
                    profile_fields = build_media_profile_fields(
                        extension=extension,
                        container_format=None,
                        video_codec=None,
                        video_profile=None,
                        video_level=None,
                        pixel_format=None,
                        audio_codec=None,
                        audio_channels=None,
                        audio_sample_rate=None,
                        width=None,
                        height=None,
                    )
                    profile = upsert_media_profile(db, profile_fields, auto_status=auto_status, auto_reason=auto_reason)
                    added, updated, saved_video = _upsert_video_record(
                        db,
                        existing,
                        file_path,
                        root,
                        folder_path,
                        stat_size=stat.st_size,
                        stat_mtime=stat.st_mtime,
                        duration=None,
                        width=None,
                        height=None,
                        video_codec=None,
                        video_profile=None,
                        video_level=None,
                        pixel_format=None,
                        audio_codec=None,
                        audio_channels=None,
                        audio_sample_rate=None,
                        container_format=None,
                        thumbnail_path=None,
                        thumbnail_status="failed",
                        thumbnail_error="Thumbnail skipped because metadata probe failed",
                        media_status="probe_failed_possible_video",
                        probe_status="failed",
                        probe_error=probe.error,
                        compatibility_status=auto_status,
                        compatibility_reason=auto_reason,
                    )
                    if saved_video is not None:
                        assign_profile_to_video(saved_video, profile)
                        if profile.sample_video_id is None:
                            profile.sample_video_id = saved_video.id
                    if added:
                        result.added += 1
                        increment_progress(added_inc=1)
                    if updated:
                        result.updated += 1
                        increment_progress(updated_inc=1)
                continue

            if not probe.has_video_stream:
                result.ignored_non_media += 1
                increment_progress(ignored_non_media_inc=1)
                if existing is not None:
                    db.query(WatchProgress).filter(WatchProgress.video_id == existing.id).delete()
                    db.delete(existing)
                continue

            auto_status, auto_reason = compute_auto_compatibility(extension, probe.video_codec, probe.audio_codec)
            profile_fields = build_media_profile_fields(
                extension=extension,
                container_format=probe.container_format,
                video_codec=probe.video_codec,
                video_profile=probe.video_profile,
                video_level=probe.video_level,
                pixel_format=probe.pixel_format,
                audio_codec=probe.audio_codec,
                audio_channels=probe.audio_channels,
                audio_sample_rate=probe.audio_sample_rate,
                width=probe.width,
                height=probe.height,
            )
            profile = upsert_media_profile(db, profile_fields, auto_status=auto_status, auto_reason=auto_reason)
            thumb_relative: str | None = None
            thumbnail_status = "pending"
            thumbnail_error: str | None = None
            try:
                thumb_path = ensure_thumbnail(file_path, settings.thumbnails_path, relative_path)
                thumb_relative = thumb_path.name if thumb_path else None
                if thumb_relative:
                    result.thumbnails_generated += 1
                    increment_progress(thumbnails_generated_inc=1)
                    thumbnail_status = "generated"
                else:
                    thumbnail_status = "skipped"
                    thumbnail_error = "Thumbnail generation was skipped"
            except Exception as thumb_exc:  # noqa: BLE001
                logger.warning("Thumbnail generation failed for %s: %s", relative_path, thumb_exc)
                result.thumbnail_errors += 1
                increment_progress(thumbnail_errors_inc=1)
                thumbnail_status = "failed"
                thumbnail_error = str(thumb_exc)

            added, updated, saved_video = _upsert_video_record(
                db,
                existing,
                file_path,
                root,
                folder_path,
                stat_size=stat.st_size,
                stat_mtime=stat.st_mtime,
                duration=probe.duration,
                width=probe.width,
                height=probe.height,
                video_codec=probe.video_codec,
                video_profile=probe.video_profile,
                video_level=probe.video_level,
                pixel_format=probe.pixel_format,
                audio_codec=probe.audio_codec,
                audio_channels=probe.audio_channels,
                audio_sample_rate=probe.audio_sample_rate,
                container_format=probe.container_format,
                thumbnail_path=thumb_relative,
                thumbnail_status=thumbnail_status,
                thumbnail_error=thumbnail_error,
                media_status="detected_video",
                probe_status="success",
                probe_error=None,
                compatibility_status=auto_status,
                compatibility_reason=auto_reason,
            )
            if saved_video is not None:
                assign_profile_to_video(saved_video, profile)
                if profile.sample_video_id is None:
                    profile.sample_video_id = saved_video.id
            if added:
                result.added += 1
                increment_progress(added_inc=1)
            if updated:
                result.updated += 1
                increment_progress(updated_inc=1)
            result.detected_videos += 1
            increment_progress(detected_videos_inc=1)
        except Exception as exc:  # noqa: BLE001
            error_msg = f"Failed to index {file_path}: {exc}"
            logger.exception(error_msg)
            result.errors.append(error_msg)
            increment_progress(error=error_msg)

    db.commit()
    logger.info(
        "Scan completed scanned_files=%d detected_videos=%d added=%d updated=%d errors=%d",
        result.scanned_files,
        result.detected_videos,
        result.added,
        result.updated,
        len(result.errors),
    )
    return result


def scan_video_library_background(settings: Settings) -> None:
    """Run scan in a background task with its own database session."""
    from app.database import SessionLocal

    start_scan()
    db = SessionLocal()
    try:
        result = scan_video_library(db, settings)
        finish_scan(
            scanned_files=result.scanned_files,
            detected_videos=result.detected_videos,
            probe_failed=result.probe_failed,
            ignored_non_media=result.ignored_non_media,
            ignored_excluded=result.ignored_excluded,
            thumbnails_generated=result.thumbnails_generated,
            thumbnail_errors=result.thumbnail_errors,
            added=result.added,
            updated=result.updated,
            errors=result.errors,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background scan failed: %s", exc)
        fail_scan(str(exc))
    finally:
        db.close()


def is_supported_extension(extension: str) -> bool:
    return extension.lower() in VIDEO_EXTENSIONS
