import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.media_probe import probe_video
from app.models import LibraryRoot, Video, WatchProgress
from app.scan_status import (
    cancel_scan,
    fail_scan,
    finish_scan,
    increment_progress,
    is_cancellation_requested,
    mark_scan_interrupted,
    start_scan,
    update_current_file,
    update_current_root,
    update_roots_info,
)
from app.services.library_root_service import bootstrap_library_roots, get_enabled_library_roots
from app.services.media_profile_service import (
    assign_profile_to_video,
    build_media_profile_fields,
    compute_auto_compatibility,
    upsert_media_profile,
)
from app.services.hls_service import reconcile_hls_variants_for_video
from app.thumbnails import ensure_thumbnail
from app.utils.files import VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    scanned_files: int = 0
    detected_videos: int = 0
    probe_failed: int = 0
    existing_unchanged: int = 0
    ignored_non_media: int = 0
    ignored_excluded: int = 0
    thumbnails_generated: int = 0
    thumbnail_errors: int = 0
    added: int = 0
    updated: int = 0
    removed_missing: int = 0
    roots_scanned: int = 0
    total_roots: int = 0
    cancelled: bool = False
    message: str | None = None
    errors: list[str] = field(default_factory=list)


def iter_library_files(root: Path, recursive: bool = True) -> list[Path]:
    if recursive:
        return [path for path in root.rglob("*") if path.is_file()]
    return [path for path in root.iterdir() if path.is_file()]


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
    library_root_id: int | None = None,
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
                library_root_id=library_root_id,
                indexed_at=now,
            )
        )
        db.flush()
        created_video = db.query(Video).filter(Video.absolute_path == str(file_path)).first()
        return True, False, created_video

    existing.title = file_path.stem
    existing.filename = file_path.name
    existing.relative_path = relative_path
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
    existing.library_root_id = library_root_id
    existing.indexed_at = now
    return False, True, existing


def _compute_folder_path(file_path: Path, root: Path) -> str:
    """Return the folder path relative to root, using forward slashes. Empty string for root."""
    parent_relative = file_path.parent.relative_to(root)
    folder = parent_relative.as_posix()
    return "" if folder == "." else folder


def initialize_library_roots(db: Session, settings: Settings) -> None:
    """Ensure library_roots has at least one entry. Called at application startup."""
    if db.query(LibraryRoot).count() > 0:
        return
    logger.info("No library roots found at startup – initialising defaults from environment.")
    bootstrap_library_roots(db, settings)


def _create_roots_from_config(db: Session, settings: Settings) -> list[LibraryRoot]:
    """Backward-compatible wrapper around the shared library root bootstrap logic."""
    return bootstrap_library_roots(db, settings)


# ── Per-root file scan ─────────────────────────────────────────────────────


def _scan_root_files(
    db: Session,
    settings: Settings,
    root: Path,
    library_root_id: int | None,
    result: ScanResult,
    recursive: bool = True,
) -> bool:
    """
    Scan all files under ``root`` and update ``result`` in place.
    Returns True if the scan was cancelled during this root.
    """
    files = iter_library_files(root, recursive=recursive)
    logger.info("Root %s: found %d candidate files", root, len(files))

    for file_path in files:
        if is_cancellation_requested():
            result.cancelled = True
            result.message = "Library scan was cancelled by user."
            db.commit()
            return True

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

            # Prefer absolute_path for direct matches, then fall back to
            # per-root relative key to align with uq_videos_root_relative_path.
            existing = db.query(Video).filter(Video.absolute_path == str(file_path)).first()
            if existing is None and library_root_id is not None:
                existing = (
                    db.query(Video)
                    .filter(
                        Video.library_root_id == library_root_id,
                        Video.relative_path == relative_path,
                    )
                    .first()
                )
            unchanged = (
                existing is not None
                and existing.size == stat.st_size
                and abs(existing.modified_ts - stat.st_mtime) < 1e-6
            )
            if unchanged:
                # Update library_root_id for files migrating from single-root
                if existing.library_root_id != library_root_id:
                    existing.library_root_id = library_root_id
                if is_cancellation_requested():
                    result.cancelled = True
                    result.message = "Library scan was cancelled by user."
                    db.commit()
                    return True
                if existing is not None and existing.media_status == "detected_video":
                    if reconcile_hls_variants_for_video(db, settings, existing.id):
                        logger.warning(
                            "Reset stale HLS DB state for video_id=%s relative_path=%s",
                            existing.id,
                            existing.relative_path,
                        )
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
                else:
                    result.existing_unchanged += 1
                    increment_progress(existing_unchanged_inc=1)
                continue

            logger.info("Indexing file: %s", relative_path)
            probe = probe_video(file_path)
            if is_cancellation_requested():
                result.cancelled = True
                result.message = "Library scan was cancelled by user."
                db.commit()
                return True
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
                        library_root_id=library_root_id,
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
            if is_cancellation_requested():
                result.cancelled = True
                result.message = "Library scan was cancelled by user."
                db.commit()
                return True
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
                library_root_id=library_root_id,
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
                if saved_video.media_status == "detected_video":
                    if reconcile_hls_variants_for_video(db, settings, saved_video.id):
                        logger.warning(
                            "Reset stale HLS DB state for video_id=%s relative_path=%s",
                            saved_video.id,
                            saved_video.relative_path,
                        )
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
        finally:
            db.commit()

    return False  # Not cancelled


# ── Missing-file cleanup ───────────────────────────────────────────────────


def _cleanup_missing_videos(
    db: Session,
    settings: Settings,
    scanned_root_ids: set[int],
    root_map: dict[int, Path],
) -> int:
    """
    Remove Video records whose source files no longer exist on disk.
    Only handles videos from roots that were actually scanned in this run.
    """
    removed = 0
    all_videos = db.query(Video).all()

    for video in all_videos:
        if is_cancellation_requested():
            break
        try:
            if video.library_root_id is not None:
                if video.library_root_id not in scanned_root_ids:
                    # From a disabled/unscanned root – leave it untouched
                    continue
                root_path = root_map[video.library_root_id]
                disk_path = root_path / video.relative_path
            else:
                # Legacy video without a root – check against VIDEO_LIBRARY_PATH
                disk_path = settings.video_library_path / video.relative_path

            if not disk_path.exists() or not disk_path.is_file():
                logger.info("Source file missing, removing from index: %s", video.relative_path)
                db.query(WatchProgress).filter(WatchProgress.video_id == video.id).delete()
                db.delete(video)
                removed += 1
                increment_progress(removed_missing_inc=1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error checking file for removal %s: %s", video.relative_path, exc)

    if removed:
        db.commit()
    return removed


# ── Main scan orchestrator ─────────────────────────────────────────────────


def scan_video_library(db: Session, settings: Settings) -> ScanResult:
    """Scan all enabled library roots and return aggregated results."""
    result = ScanResult()

    enabled_roots = get_enabled_library_roots(db, settings)
    result.total_roots = len(enabled_roots)

    if not enabled_roots:
        logger.info("No enabled library roots found. Nothing to scan.")
        result.message = "No enabled library roots configured."
        return result

    logger.info("Scan started for %d enabled root(s)", len(enabled_roots))
    update_roots_info(len(enabled_roots))

    if is_cancellation_requested():
        result.cancelled = True
        result.message = "Library scan was cancelled by user."
        return result

    scanned_root_ids: set[int] = set()
    root_map: dict[int, Path] = {}

    for root_record in enabled_roots:
        if is_cancellation_requested():
            result.cancelled = True
            result.message = "Library scan was cancelled by user."
            db.commit()
            return result

        root_path = Path(root_record.path)
        update_current_root(root_record.path)

        if not root_path.exists() or not root_path.is_dir():
            msg = f"Library root does not exist or is not a directory: {root_path}"
            logger.error(msg)
            result.errors.append(msg)
            root_record.last_scan_status = "error"
            root_record.last_error = msg
            db.commit()
            continue

        logger.info("Scanning root: %s (id=%s, recursive=%s)", root_path, root_record.id, root_record.recursive)
        cancelled = _scan_root_files(
            db, settings, root_path, root_record.id, result, recursive=root_record.recursive
        )

        if cancelled:
            root_record.last_scan_status = "cancelled"
            db.commit()
            return result

        root_record.last_scanned_at = datetime.now(timezone.utc)
        root_record.last_scan_status = "completed"
        root_record.last_error = None
        db.commit()

        result.roots_scanned += 1
        increment_progress(roots_scanned_inc=1)
        scanned_root_ids.add(root_record.id)
        root_map[root_record.id] = root_path

    if is_cancellation_requested():
        result.cancelled = True
        result.message = "Library scan was cancelled by user."
        db.commit()
        return result

    update_current_root(None)

    # Remove DB records whose source files no longer exist
    removed = _cleanup_missing_videos(db, settings, scanned_root_ids, root_map)
    result.removed_missing = removed

    db.commit()
    logger.info(
        "Scan completed roots=%d scanned=%d detected=%d unchanged=%d"
        " added=%d updated=%d removed=%d errors=%d",
        result.roots_scanned,
        result.scanned_files,
        result.detected_videos,
        result.existing_unchanged,
        result.added,
        result.updated,
        result.removed_missing,
        len(result.errors),
    )
    return result


def scan_video_library_background(settings: Settings) -> None:
    """Run scan in a background task with its own database session."""
    from app.database import SessionLocal
    from app.services.duplicate_service import mark_duplicates_outdated

    start_scan()
    db = SessionLocal()
    try:
        result = scan_video_library(db, settings)
        if result.cancelled:
            cancel_scan(
                scanned_files=result.scanned_files,
                detected_videos=result.detected_videos,
                probe_failed=result.probe_failed,
                ignored_non_media=result.ignored_non_media,
                ignored_excluded=result.ignored_excluded,
                thumbnails_generated=result.thumbnails_generated,
                thumbnail_errors=result.thumbnail_errors,
                added=result.added,
                updated=result.updated,
                existing_unchanged=result.existing_unchanged,
                removed_missing=result.removed_missing,
                errors=result.errors,
                roots_scanned=result.roots_scanned,
                total_roots=result.total_roots,
                message=result.message or "Library scan was cancelled by user.",
            )
        else:
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
                existing_unchanged=result.existing_unchanged,
                removed_missing=result.removed_missing,
                errors=result.errors,
                roots_scanned=result.roots_scanned,
                total_roots=result.total_roots,
                message=result.message,
            )
            try:
                mark_duplicates_outdated(db)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to mark duplicates as outdated after scan: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background scan failed: %s", exc)
        fail_scan(str(exc))
    finally:
        db.close()


def recover_scan_runtime_state() -> None:
    mark_scan_interrupted("Library scan was interrupted by application restart.")


def is_supported_extension(extension: str) -> bool:
    return extension.lower() in VIDEO_EXTENSIONS
