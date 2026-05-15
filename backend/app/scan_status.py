"""In-process scan status tracker.
Provides thread-safe in-memory state for the scanning task.
No external dependencies (no Redis, Celery, etc.).
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
@dataclass
class ScanState:
    status: str = "idle"  # idle | running | completed | failed
    started_at: datetime | None = None
    finished_at: datetime | None = None
    scanned: int = 0
    added: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)
    current_file: str | None = None
_state = ScanState()
_lock = threading.Lock()
def get_scan_state() -> ScanState:
    """Return a snapshot copy of the current scan state."""
    with _lock:
        return ScanState(
            status=_state.status,
            started_at=_state.started_at,
            finished_at=_state.finished_at,
            scanned=_state.scanned,
            added=_state.added,
            updated=_state.updated,
            errors=list(_state.errors),
            current_file=_state.current_file,
        )
def start_scan() -> None:
    """Reset state and mark scan as running."""
    with _lock:
        _state.status = "running"
        _state.started_at = datetime.now(timezone.utc)
        _state.finished_at = None
        _state.scanned = 0
        _state.added = 0
        _state.updated = 0
        _state.errors = []
        _state.current_file = None
def finish_scan(scanned: int, added: int, updated: int, errors: list[str]) -> None:
    """Mark scan as completed with results."""
    with _lock:
        _state.status = "completed"
        _state.finished_at = datetime.now(timezone.utc)
        _state.scanned = scanned
        _state.added = added
        _state.updated = updated
        _state.errors = list(errors)
        _state.current_file = None
def fail_scan(error: str) -> None:
    """Mark scan as failed."""
    with _lock:
        _state.status = "failed"
        _state.finished_at = datetime.now(timezone.utc)
        _state.errors.append(error)
        _state.current_file = None
def update_current_file(path: str) -> None:
    """Update the currently-being-processed file path."""
    with _lock:
        _state.current_file = path


def increment_progress(
    scanned_inc: int = 0,
    added_inc: int = 0,
    updated_inc: int = 0,
    error: str | None = None,
) -> None:
    """Update counters in-place while scan is running for live UI updates."""
    with _lock:
        _state.scanned += scanned_inc
        _state.added += added_inc
        _state.updated += updated_inc
        if error:
            _state.errors.append(error)

