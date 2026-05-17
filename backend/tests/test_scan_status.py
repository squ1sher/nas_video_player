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
    assert state.cancellation_requested is False


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
        existing_unchanged=2,
        removed_missing=1,
        errors=["oops"],
        message="done",
    )
    state = get_scan_state()
    assert state.status == "completed"
    assert state.scanned == 10
    assert state.scanned_files == 10
    assert state.detected_videos == 6
    assert state.added == 5
    assert state.updated == 3
    assert state.existing_unchanged == 2
    assert state.removed_missing == 1
    assert state.errors == ["oops"]
    assert state.finished_at is not None
    assert state.message == "done"


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


def test_cancel_endpoint_returns_not_running(tmp_path: Path) -> None:
    _reset_state()
    client = make_client(tmp_path)
    response = client.post("/api/scan/cancel")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_running"


def test_cancel_endpoint_sets_cancelling_when_running(tmp_path: Path) -> None:
    _reset_state()
    from app.scan_status import start_scan

    start_scan()
    client = make_client(tmp_path)
    response = client.post("/api/scan/cancel")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "cancelling"

    status = client.get("/api/scan/status")
    assert status.status_code == 200
    assert status.json()["status"] == "cancelling"
    assert status.json()["cancellation_requested"] is True


def test_start_scan_while_running_returns_409(tmp_path: Path) -> None:
    _reset_state()
    from app.scan_status import start_scan

    start_scan()
    client = make_client(tmp_path)
    response = client.post("/api/scan")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["status"] == "already_running"


def test_mark_scan_interrupted_on_restart() -> None:
    _reset_state()
    from app.scan_status import get_scan_state, mark_scan_interrupted, start_scan

    start_scan()
    ok = mark_scan_interrupted()
    assert ok is True
    state = get_scan_state()
    assert state.status == "interrupted"
    assert state.cancellation_requested is False


def test_mark_cancelling_scan_interrupted_on_restart() -> None:
    _reset_state()
    from app.scan_status import get_scan_state, mark_scan_interrupted, request_scan_cancellation, start_scan

    start_scan()
    request_scan_cancellation()
    ok = mark_scan_interrupted()
    assert ok is True
    state = get_scan_state()
    assert state.status == "interrupted"
    assert state.cancellation_requested is False


def test_scan_status_payload_includes_live_counters(tmp_path: Path) -> None:
    _reset_state()
    from app.scan_status import increment_progress, start_scan, update_current_file

    start_scan()
    update_current_file("/tmp/videos/new_file.mp4")
    increment_progress(
        scanned_files_inc=3,
        added_inc=2,
        updated_inc=1,
        existing_unchanged_inc=4,
        probe_failed_inc=1,
        thumbnails_generated_inc=2,
        thumbnail_errors_inc=1,
    )

    client = make_client(tmp_path)
    response = client.get("/api/scan/status")
    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "running"
    assert payload["current_file"] == "/tmp/videos/new_file.mp4"
    assert payload["scanned_files"] == 3
    assert payload["added"] == 2
    assert payload["updated"] == 1
    assert payload["existing_unchanged"] == 4
    assert payload["probe_failed"] == 1
    assert payload["thumbnails_generated"] == 2
    assert payload["thumbnail_failed"] == 1
    assert payload["started_at"] is not None
    assert payload["finished_at"] is None


