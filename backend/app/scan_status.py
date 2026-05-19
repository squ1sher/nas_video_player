"""In-process scan status tracker.
Provides thread-safe in-memory state for the scanning task.
No external dependencies (no Redis, Celery, etc.).
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
@dataclass
class ScanState:
    status: str = "idle"  # idle | running | completed | failed | interrupted | cancelling | cancelled
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancellation_requested: bool = False
    scanned: int = 0
    scanned_files: int = 0
    detected_videos: int = 0
    existing_unchanged: int = 0
    probe_failed: int = 0
    ignored_non_media: int = 0
    ignored_excluded: int = 0
    thumbnails_generated: int = 0
    thumbnail_errors: int = 0
    added: int = 0
    updated: int = 0
    removed_missing: int = 0
    errors: list[str] = field(default_factory=list)
    current_file: str | None = None
    current_root: str | None = None
    roots_scanned: int = 0
    total_roots: int = 0
    message: str | None = None
_state = ScanState()
_lock = threading.Lock()
def get_scan_state() -> ScanState:
    """Return a snapshot copy of the current scan state."""
    with _lock:
        return ScanState(
            status=_state.status,
            started_at=_state.started_at,
            finished_at=_state.finished_at,
            cancellation_requested=_state.cancellation_requested,
            scanned=_state.scanned,
            scanned_files=_state.scanned_files,
            detected_videos=_state.detected_videos,
            existing_unchanged=_state.existing_unchanged,
            probe_failed=_state.probe_failed,
            ignored_non_media=_state.ignored_non_media,
            ignored_excluded=_state.ignored_excluded,
            thumbnails_generated=_state.thumbnails_generated,
            thumbnail_errors=_state.thumbnail_errors,
            added=_state.added,
            updated=_state.updated,
            removed_missing=_state.removed_missing,
            errors=list(_state.errors),
            current_file=_state.current_file,
            current_root=_state.current_root,
            roots_scanned=_state.roots_scanned,
            total_roots=_state.total_roots,
            message=_state.message,
        )
def start_scan() -> None:
    """Reset state and mark scan as running."""
    with _lock:
        _state.status = "running"
        _state.started_at = datetime.now(timezone.utc)
        _state.finished_at = None
        _state.cancellation_requested = False
        _state.scanned = 0
        _state.scanned_files = 0
        _state.detected_videos = 0
        _state.existing_unchanged = 0
        _state.probe_failed = 0
        _state.ignored_non_media = 0
        _state.ignored_excluded = 0
        _state.thumbnails_generated = 0
        _state.thumbnail_errors = 0
        _state.added = 0
        _state.updated = 0
        _state.removed_missing = 0
        _state.errors = []
        _state.current_file = None
        _state.current_root = None
        _state.roots_scanned = 0
        _state.total_roots = 0
        _state.message = None


def request_scan_cancellation() -> bool:
    with _lock:
        if _state.status not in {"running", "cancelling"}:
            return False
        _state.cancellation_requested = True
        _state.status = "cancelling"
        _state.message = "Library scan cancellation requested."
        return True


def is_cancellation_requested() -> bool:
    with _lock:
        return bool(_state.cancellation_requested)
def finish_scan(
    *,
    scanned_files: int,
    detected_videos: int,
    probe_failed: int,
    ignored_non_media: int,
    ignored_excluded: int,
    thumbnails_generated: int,
    thumbnail_errors: int,
    added: int,
    updated: int,
    existing_unchanged: int,
    removed_missing: int,
    errors: list[str],
    roots_scanned: int = 0,
    total_roots: int = 0,
    message: str | None = None,
) -> None:
    """Mark scan as completed with results."""
    with _lock:
        _state.status = "completed"
        _state.finished_at = datetime.now(timezone.utc)
        _state.cancellation_requested = False
        _state.scanned = scanned_files
        _state.scanned_files = scanned_files
        _state.detected_videos = detected_videos
        _state.existing_unchanged = existing_unchanged
        _state.probe_failed = probe_failed
        _state.ignored_non_media = ignored_non_media
        _state.ignored_excluded = ignored_excluded
        _state.thumbnails_generated = thumbnails_generated
        _state.thumbnail_errors = thumbnail_errors
        _state.added = added
        _state.updated = updated
        _state.removed_missing = removed_missing
        _state.errors = list(errors)
        _state.current_file = None
        _state.current_root = None
        _state.roots_scanned = roots_scanned
        _state.total_roots = total_roots
        _state.message = message


def cancel_scan(
    *,
    scanned_files: int,
    detected_videos: int,
    probe_failed: int,
    ignored_non_media: int,
    ignored_excluded: int,
    thumbnails_generated: int,
    thumbnail_errors: int,
    added: int,
    updated: int,
    existing_unchanged: int,
    removed_missing: int,
    errors: list[str],
    roots_scanned: int = 0,
    total_roots: int = 0,
    message: str = "Library scan was cancelled by user.",
) -> None:
    with _lock:
        _state.status = "cancelled"
        _state.finished_at = datetime.now(timezone.utc)
        _state.cancellation_requested = False
        _state.scanned = scanned_files
        _state.scanned_files = scanned_files
        _state.detected_videos = detected_videos
        _state.existing_unchanged = existing_unchanged
        _state.probe_failed = probe_failed
        _state.ignored_non_media = ignored_non_media
        _state.ignored_excluded = ignored_excluded
        _state.thumbnails_generated = thumbnails_generated
        _state.thumbnail_errors = thumbnail_errors
        _state.added = added
        _state.updated = updated
        _state.removed_missing = removed_missing
        _state.errors = list(errors)
        _state.current_file = None
        _state.current_root = None
        _state.roots_scanned = roots_scanned
        _state.total_roots = total_roots
        _state.message = message
def fail_scan(error: str) -> None:
    """Mark scan as failed."""
    with _lock:
        _state.status = "failed"
        _state.finished_at = datetime.now(timezone.utc)
        _state.cancellation_requested = False
        _state.errors.append(error)
        _state.current_file = None
        _state.current_root = None
        _state.message = error


def mark_scan_interrupted(message: str = "Library scan was interrupted by application restart.") -> bool:
    with _lock:
        if _state.status not in {"running", "cancelling"}:
            return False
        _state.status = "interrupted"
        _state.finished_at = datetime.now(timezone.utc)
        _state.cancellation_requested = False
        _state.current_file = None
        _state.current_root = None
        _state.message = message
        return True
def update_current_file(path: str) -> None:
    """Update the currently-being-processed file path."""
    with _lock:
        _state.current_file = path


def update_current_root(path: str | None) -> None:
    """Update the currently-being-scanned root path."""
    with _lock:
        _state.current_root = path


def update_roots_info(total_roots: int) -> None:
    """Set the total number of roots to be scanned."""
    with _lock:
        _state.total_roots = total_roots


def increment_progress(
    scanned_inc: int = 0,
    scanned_files_inc: int = 0,
    detected_videos_inc: int = 0,
    existing_unchanged_inc: int = 0,
    probe_failed_inc: int = 0,
    ignored_non_media_inc: int = 0,
    ignored_excluded_inc: int = 0,
    thumbnails_generated_inc: int = 0,
    thumbnail_errors_inc: int = 0,
    added_inc: int = 0,
    updated_inc: int = 0,
    removed_missing_inc: int = 0,
    roots_scanned_inc: int = 0,
    error: str | None = None,
) -> None:
    """Update counters in-place while scan is running for live UI updates."""
    with _lock:
        inc_scanned = scanned_inc + scanned_files_inc
        _state.scanned += inc_scanned
        _state.scanned_files += inc_scanned
        _state.detected_videos += detected_videos_inc
        _state.existing_unchanged += existing_unchanged_inc
        _state.probe_failed += probe_failed_inc
        _state.ignored_non_media += ignored_non_media_inc
        _state.ignored_excluded += ignored_excluded_inc
        _state.thumbnails_generated += thumbnails_generated_inc
        _state.thumbnail_errors += thumbnail_errors_inc
        _state.added += added_inc
        _state.updated += updated_inc
        _state.removed_missing += removed_missing_inc
        _state.roots_scanned += roots_scanned_inc
        if error:
            _state.errors.append(error)
