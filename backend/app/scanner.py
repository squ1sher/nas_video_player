import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.compatibility import get_compatibility
from app.config import Settings
from app.media_probe import probe_video
from app.models import Video
from app.scan_status import fail_scan, finish_scan, start_scan, update_current_file
from app.thumbnails import ensure_thumbnail
from app.utils.files import VIDEO_EXTENSIONS, is_video_file

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


def iter_video_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file() and is_video_file(path)]


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

    files = iter_video_files(root)
    logger.info("Found %d candidate files", len(files))

    for file_path in files:
        result.scanned += 1
        update_current_file(str(file_path))
        try:
            relative_path = file_path.relative_to(root).as_posix()
            folder_path = _compute_folder_path(file_path, root)
            stat = file_path.stat()
            existing = db.query(Video).filter(Video.relative_path == relative_path).first()
            unchanged = (
                existing is not None
                and existing.size == stat.st_size
                and abs(existing.modified_ts - stat.st_mtime) < 1e-6
            )
            if unchanged:
                continue

            logger.info("Indexing file: %s", relative_path)
            probe = probe_video(file_path)
            compat = get_compatibility(file_path.suffix.lower(), probe.video_codec, probe.audio_codec)
            thumb_path = ensure_thumbnail(file_path, settings.thumbnails_path, relative_path)
            thumb_relative = thumb_path.name if thumb_path else None

            if existing is None:
                video = Video(
                    title=file_path.stem,
                    filename=file_path.name,
                    relative_path=relative_path,
                    absolute_path=str(file_path),
                    extension=file_path.suffix.lower(),
                    size=stat.st_size,
                    modified_ts=stat.st_mtime,
                    duration=probe.duration,
                    width=probe.width,
                    height=probe.height,
                    video_codec=probe.video_codec,
                    audio_codec=probe.audio_codec,
                    thumbnail_path=thumb_relative,
                    folder_path=folder_path,
                    compatibility_status=compat["status"],
                    compatibility_reason=compat["reason"],
                    indexed_at=datetime.now(timezone.utc),
                )
                db.add(video)
                result.added += 1
            else:
                existing.title = file_path.stem
                existing.filename = file_path.name
                existing.absolute_path = str(file_path)
                existing.extension = file_path.suffix.lower()
                existing.size = stat.st_size
                existing.modified_ts = stat.st_mtime
                existing.duration = probe.duration
                existing.width = probe.width
                existing.height = probe.height
                existing.video_codec = probe.video_codec
                existing.audio_codec = probe.audio_codec
                existing.thumbnail_path = thumb_relative
                existing.folder_path = folder_path
                existing.compatibility_status = compat["status"]
                existing.compatibility_reason = compat["reason"]
                existing.indexed_at = datetime.now(timezone.utc)
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            error_msg = f"Failed to index {file_path}: {exc}"
            logger.exception(error_msg)
            result.errors.append(error_msg)

    db.commit()
    logger.info(
        "Scan completed scanned=%d added=%d updated=%d errors=%d",
        result.scanned,
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
        finish_scan(result.scanned, result.added, result.updated, result.errors)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background scan failed: %s", exc)
        fail_scan(str(exc))
    finally:
        db.close()


def is_supported_extension(extension: str) -> bool:
    return extension.lower() in VIDEO_EXTENSIONS
