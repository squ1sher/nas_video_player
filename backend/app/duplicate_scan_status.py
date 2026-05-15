from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DuplicateScanState:
    status: str = "idle"
    mode: str = "strict"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    videos_checked: int = 0
    candidate_groups_found: int = 0
    duplicate_candidates_found: int = 0
    current_step: str | None = None
    errors: list[str] = field(default_factory=list)
    last_result_summary: dict[str, int | str | None] | None = None


_state = DuplicateScanState()
_lock = threading.Lock()


def get_duplicate_scan_state() -> DuplicateScanState:
    with _lock:
        return DuplicateScanState(
            status=_state.status,
            mode=_state.mode,
            started_at=_state.started_at,
            finished_at=_state.finished_at,
            videos_checked=_state.videos_checked,
            candidate_groups_found=_state.candidate_groups_found,
            duplicate_candidates_found=_state.duplicate_candidates_found,
            current_step=_state.current_step,
            errors=list(_state.errors),
            last_result_summary=dict(_state.last_result_summary) if _state.last_result_summary else None,
        )


def start_duplicate_scan(mode: str) -> bool:
    with _lock:
        if _state.status == "running":
            return False
        _state.status = "running"
        _state.mode = mode
        _state.started_at = datetime.now(timezone.utc)
        _state.finished_at = None
        _state.videos_checked = 0
        _state.candidate_groups_found = 0
        _state.duplicate_candidates_found = 0
        _state.current_step = "Loading videos"
        _state.errors = []
        _state.last_result_summary = None
        return True


def update_duplicate_scan_progress(
    *,
    current_step: str | None = None,
    videos_checked: int | None = None,
    candidate_groups_found: int | None = None,
    duplicate_candidates_found: int | None = None,
) -> None:
    with _lock:
        if current_step is not None:
            _state.current_step = current_step
        if videos_checked is not None:
            _state.videos_checked = videos_checked
        if candidate_groups_found is not None:
            _state.candidate_groups_found = candidate_groups_found
        if duplicate_candidates_found is not None:
            _state.duplicate_candidates_found = duplicate_candidates_found


def complete_duplicate_scan(summary: dict[str, int | str | None]) -> None:
    with _lock:
        _state.status = "completed"
        _state.finished_at = datetime.now(timezone.utc)
        _state.current_step = None
        _state.last_result_summary = dict(summary)
        _state.candidate_groups_found = int(summary.get("candidate_groups_found", 0) or 0)
        _state.duplicate_candidates_found = int(summary.get("duplicate_candidates_found", 0) or 0)
        _state.videos_checked = int(summary.get("videos_checked", 0) or 0)


def fail_duplicate_scan(error: str) -> None:
    with _lock:
        _state.status = "failed"
        _state.finished_at = datetime.now(timezone.utc)
        _state.current_step = None
        _state.errors.append(error)

