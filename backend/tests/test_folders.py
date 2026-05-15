"""Tests for folder navigation endpoint."""
from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client


def _insert_video(tmp_path, title, relative_path, folder_path):
    from app.database import SessionLocal
    from app.models import Video
    db = SessionLocal()
    video = Video(
        title=title,
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=".mp4",
        size=1000,
        modified_ts=1000.0,
        folder_path=folder_path,
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


def test_list_folders_empty(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    response = client.get("/api/folders")
    assert response.status_code == 200
    assert response.json() == []


def test_list_folders_with_videos(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _insert_video(tmp_path, "Film 1", "Movies/film1.mp4", "Movies")
    _insert_video(tmp_path, "Film 2", "Movies/film2.mp4", "Movies")
    _insert_video(tmp_path, "Show 1", "Shows/show1.mp4", "Shows")
    _insert_video(tmp_path, "Root Video", "root.mp4", "")

    response = client.get("/api/folders")
    assert response.status_code == 200
    data = response.json()
    folders = {item["folder_path"]: item["video_count"] for item in data}
    assert folders["Movies"] == 2
    assert folders["Shows"] == 1
    assert folders[""] == 1


def test_filter_videos_by_folder(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _insert_video(tmp_path, "Film 1", "Movies/film1.mp4", "Movies")
    _insert_video(tmp_path, "Film 2", "Movies/film2.mp4", "Movies")
    _insert_video(tmp_path, "Show 1", "Shows/show1.mp4", "Shows")

    response = client.get("/api/videos?folder=Movies")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    titles = {v["title"] for v in data}
    assert titles == {"Film 1", "Film 2"}


def test_filter_videos_by_folder_shows(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    _insert_video(tmp_path, "Film 1", "Movies/film1.mp4", "Movies")
    _insert_video(tmp_path, "Show 1", "Shows/show1.mp4", "Shows")

    response = client.get("/api/videos?folder=Shows")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Show 1"
