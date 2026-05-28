from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client


def _create_video(tmp_path: Path, title: str, relative_path: str) -> int:
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title=title,
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=".mp4",
        size=1024,
        modified_ts=datetime.now(timezone.utc).timestamp(),
        duration=15.0,
        width=1280,
        height=720,
        video_codec="h264",
        audio_codec="aac",
        folder_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
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


def test_video_filter_by_single_tag(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    video_a = _create_video(tmp_path, "Family clip", "Family/a.mp4")
    _create_video(tmp_path, "Travel clip", "Travel/b.mp4")

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    assign = client.post(f"/api/videos/{video_a}/tags", json={"tag_ids": [family_id]})
    assert assign.status_code == 200

    response = client.get(f"/api/videos?tag_ids={family_id}")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {video_a}


def test_video_filter_any_mode_with_multiple_tags(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    video_family = _create_video(tmp_path, "Family clip", "Family/a.mp4")
    video_travel = _create_video(tmp_path, "Travel clip", "Travel/b.mp4")
    _create_video(tmp_path, "No tags", "Misc/c.mp4")

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]

    assert client.post(f"/api/videos/{video_family}/tags", json={"tag_ids": [family_id]}).status_code == 200
    assert client.post(f"/api/videos/{video_travel}/tags", json={"tag_ids": [travel_id]}).status_code == 200

    response = client.get(f"/api/videos?tag_ids={family_id},{travel_id}&tag_mode=any")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {video_family, video_travel}


def test_video_filter_all_mode_with_multiple_tags(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    only_family = _create_video(tmp_path, "Family only", "Family/a.mp4")
    both = _create_video(tmp_path, "Family and Travel", "Family/b.mp4")

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]

    assert client.post(f"/api/videos/{only_family}/tags", json={"tag_ids": [family_id]}).status_code == 200
    assert client.post(f"/api/videos/{both}/tags", json={"tag_ids": [family_id, travel_id]}).status_code == 200

    response = client.get(f"/api/videos?tag_ids={family_id},{travel_id}&tag_mode=all")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {both}


def test_video_filter_without_tags(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    tagged = _create_video(tmp_path, "Tagged", "Family/a.mp4")
    untagged = _create_video(tmp_path, "Untagged", "Family/b.mp4")

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    assert client.post(f"/api/videos/{tagged}/tags", json={"tag_ids": [family_id]}).status_code == 200

    response = client.get("/api/videos?without_tags=true")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {untagged}


def test_video_filter_composes_with_search(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    birthday = _create_video(tmp_path, "Birthday Alex", "Family/alex.mp4")
    _create_video(tmp_path, "Birthday Kids", "Family/kids.mp4")

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    assert client.post(f"/api/videos/{birthday}/tags", json={"tag_ids": [family_id]}).status_code == 200

    response = client.get(f"/api/videos?q=Alex&tag_ids={family_id}")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == birthday


def test_video_filter_response_still_includes_tags(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    video_id = _create_video(tmp_path, "Trip", "Travel/clip.mp4")
    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    mallorca_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": travel_id}).json()["id"]
    assert client.post(f"/api/videos/{video_id}/tags", json={"tag_ids": [mallorca_id]}).status_code == 200

    response = client.get(f"/api/videos?tag_ids={mallorca_id}")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == video_id
    assert payload[0]["tags"] == [
        {
            "id": mallorca_id,
            "name": "Mallorca",
            "path": "Travel/Mallorca",
            "color": None,
        }
    ]

