from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client


def _create_video(tmp_path: Path, relative_path: str) -> int:
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title=relative_path.split("/")[-1],
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=".mp4",
        size=1024,
        modified_ts=datetime.now(timezone.utc).timestamp(),
        duration=12.0,
        width=1280,
        height=720,
        video_codec="h264",
        audio_codec="aac",
        folder_path="Bulk",
        compatibility_status="direct_play",
        compatibility_reason="test",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()
    return video_id


def test_bulk_assign_tags_adds_links_without_duplicates(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_a = _create_video(tmp_path, "Bulk/a.mp4")
    video_b = _create_video(tmp_path, "Bulk/b.mp4")

    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    mallorca_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": travel_id}).json()["id"]

    first = client.post("/api/tags/bulk-assign", json={"video_ids": [video_a, video_b], "tag_ids": [mallorca_id]})
    assert first.status_code == 200
    assert first.json()["assignments_created"] == 2

    second = client.post("/api/tags/bulk-assign", json={"video_ids": [video_a, video_b], "tag_ids": [mallorca_id]})
    assert second.status_code == 200
    assert second.json()["assignments_created"] == 0


def test_bulk_delete_returns_item_level_results_and_cleans_video_tags(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_a = _create_video(tmp_path, "Bulk/delete-a.mp4")
    video_b = _create_video(tmp_path, "Bulk/delete-b.mp4")

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    son_id = client.post("/api/tags", json={"name": "Son", "parent_id": family_id}).json()["id"]

    assign = client.post(f"/api/videos/{video_a}/tags", json={"tag_ids": [son_id]})
    assert assign.status_code == 200

    response = client.post("/api/videos/bulk-delete", json={"video_ids": [video_a, 999999]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == [video_a]
    assert payload["failed"] == [{"video_id": 999999, "error": "Video not found."}]

    videos = client.get("/api/videos")
    assert videos.status_code == 200
    remaining_ids = {item["id"] for item in videos.json()}
    assert video_a not in remaining_ids
    assert video_b in remaining_ids

    from app.database import SessionLocal
    from app.models import VideoTag

    db = SessionLocal()
    links = db.query(VideoTag).filter(VideoTag.video_id == video_a).count()
    db.close()
    assert links == 0

