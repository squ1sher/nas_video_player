"""Tests for watch progress endpoints."""
from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client, setup_test_db


def _create_video(tmp_path):
    from app.database import SessionLocal
    from app.models import Video
    db = SessionLocal()
    video = Video(
        title="Test Video",
        filename="test.mp4",
        relative_path="test.mp4",
        absolute_path=str(tmp_path / "videos" / "test.mp4"),
        extension=".mp4",
        size=1000,
        modified_ts=1000.0,
        folder_path="",
        compatibility_status="direct_play",
        compatibility_reason="test",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    vid_id = video.id
    db.close()
    return vid_id


def test_get_progress_no_existing_returns_default(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    vid_id = _create_video(tmp_path)
    response = client.get(f"/api/videos/{vid_id}/progress")
    assert response.status_code == 200
    data = response.json()
    assert data["video_id"] == vid_id
    assert data["position_seconds"] == 0.0
    assert data["percent_watched"] == 0.0
    assert data["completed"] is False
    assert data["last_watched_at"] is None


def test_put_progress_creates_record(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    vid_id = _create_video(tmp_path)
    response = client.put(
        f"/api/videos/{vid_id}/progress",
        json={"position_seconds": 60.0, "duration_seconds": 3600.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["video_id"] == vid_id
    assert data["position_seconds"] == 60.0
    assert round(data["percent_watched"], 3) == round(60.0 / 3600.0 * 100, 3)
    assert data["completed"] is False
    assert data["last_watched_at"] is not None


def test_put_progress_updates_existing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    vid_id = _create_video(tmp_path)
    client.put(f"/api/videos/{vid_id}/progress", json={"position_seconds": 60.0, "duration_seconds": 600.0})
    response = client.put(
        f"/api/videos/{vid_id}/progress",
        json={"position_seconds": 120.0, "duration_seconds": 600.0},
    )
    assert response.status_code == 200
    assert response.json()["position_seconds"] == 120.0


def test_completed_flag_at_ninety_percent(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    vid_id = _create_video(tmp_path)
    response = client.put(
        f"/api/videos/{vid_id}/progress",
        json={"position_seconds": 90.0, "duration_seconds": 100.0},
    )
    assert response.status_code == 200
    assert response.json()["completed"] is True


def test_completed_flag_below_ninety_percent(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    vid_id = _create_video(tmp_path)
    response = client.put(
        f"/api/videos/{vid_id}/progress",
        json={"position_seconds": 89.0, "duration_seconds": 100.0},
    )
    assert response.status_code == 200
    assert response.json()["completed"] is False


def test_get_progress_for_missing_video_returns_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/api/videos/99999/progress")
    assert response.status_code == 404


def test_continue_watching_returns_in_progress_videos(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    vid_id = _create_video(tmp_path)
    client.put(
        f"/api/videos/{vid_id}/progress",
        json={"position_seconds": 30.0, "duration_seconds": 600.0},
    )
    response = client.get("/api/videos/continue-watching")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == vid_id
    assert "progress" in data[0]
