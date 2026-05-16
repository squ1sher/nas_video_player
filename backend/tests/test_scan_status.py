"""Tests for in-process scan status tracker."""
import threading
from pathlib import Path

import app.scan_status as ss
from tests.conftest import make_client


def _reset_state():
    ss._state = ss.ScanState()
    ss._lock = threading.Lock()


def test_initial_status_is_idle() -> None:
    _reset_state()
    from app.scan_status import get_scan_state
    state = get_scan_state()
    assert state.status == "idle"
    assert state.scanned == 0
    assert state.errors == []


def test_start_scan_sets_running() -> None:
    _reset_state()
    from app.scan_status import get_scan_state, start_scan
    start_scan()
    state = get_scan_state()
    assert state.status == "running"
    assert state.started_at is not None
    assert state.finished_at is None


def test_finish_scan_sets_completed() -> None:
    _reset_state()
    from app.scan_status import finish_scan, get_scan_state, start_scan
    start_scan()
    finish_scan(
        scanned_files=10,
        detected_videos=6,
        probe_failed=2,
        ignored_non_media=1,
        ignored_excluded=1,
        thumbnails_generated=5,
        thumbnail_errors=1,
        added=5,
        updated=3,
        errors=["oops"],
    )
    state = get_scan_state()
    assert state.status == "completed"
    assert state.scanned == 10
    assert state.scanned_files == 10
    assert state.detected_videos == 6
    assert state.added == 5
    assert state.updated == 3
    assert state.errors == ["oops"]
    assert state.finished_at is not None


def test_fail_scan_sets_failed() -> None:
    _reset_state()
    from app.scan_status import fail_scan, get_scan_state, start_scan
    start_scan()
    fail_scan("something went wrong")
    state = get_scan_state()
    assert state.status == "failed"
    assert "something went wrong" in state.errors


def test_update_current_file() -> None:
    _reset_state()
    from app.scan_status import get_scan_state, start_scan, update_current_file
    start_scan()
    update_current_file("/media/videos/movie.mp4")
    state = get_scan_state()
    assert state.current_file == "/media/videos/movie.mp4"


def test_scan_status_api_returns_idle(tmp_path: Path) -> None:
    _reset_state()
    client = make_client(tmp_path)
    response = client.get("/api/scan/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"
