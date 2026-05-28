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
        duration=20.0,
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


def _create_playlist(client, name: str = "Kids cartoons") -> int:
    response = client.post("/api/playlists", json={"name": name, "description": "Cartoons for children"})
    assert response.status_code == 201
    return response.json()["id"]


def test_create_list_update_playlist(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    playlist_id = _create_playlist(client)

    listed = client.get("/api/playlists")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == playlist_id
    assert listed.json()[0]["item_count"] == 0

    updated = client.put(
        f"/api/playlists/{playlist_id}",
        json={"name": "Kids evening", "description": "Updated description"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Kids evening"
    assert updated.json()["description"] == "Updated description"


def test_delete_playlist_does_not_delete_videos(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    video_id = _create_video(tmp_path, "Cartoon", "Kids/cartoon.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [video_id]}).status_code == 200

    deleted = client.delete(f"/api/playlists/{playlist_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}

    video_still_exists = client.get(f"/api/videos/{video_id}")
    assert video_still_exists.status_code == 200


def test_add_videos_to_playlist_skips_duplicates_and_invalid(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "A", "Family/a.mp4")
    second = _create_video(tmp_path, "B", "Family/b.mp4")
    playlist_id = _create_playlist(client)

    added = client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second, first, 999999]})
    assert added.status_code == 200
    payload = added.json()
    assert payload["added"] == [first, second]
    assert payload["skipped_existing"] == []
    assert payload["invalid"] == [999999]
    assert payload["item_count"] == 2

    second_add = client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [second]})
    assert second_add.status_code == 200
    assert second_add.json()["added"] == []
    assert second_add.json()["skipped_existing"] == [second]


def test_get_playlist_returns_ordered_items(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "First", "P/1.mp4")
    second = _create_video(tmp_path, "Second", "P/2.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second]}).status_code == 200

    detail = client.get(f"/api/playlists/{playlist_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["item_count"] == 2
    assert [item["position"] for item in payload["items"]] == [1, 2]
    assert [item["id"] for item in payload["items"]] == [first, second]
    assert payload["items"][0]["video"]["display_title"] == "First"


def test_remove_video_from_playlist_normalizes_positions(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "First", "Q/1.mp4")
    second = _create_video(tmp_path, "Second", "Q/2.mp4")
    third = _create_video(tmp_path, "Third", "Q/3.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second, third]}).status_code == 200

    removed = client.delete(f"/api/playlists/{playlist_id}/items/{second}")
    assert removed.status_code == 200

    detail = client.get(f"/api/playlists/{playlist_id}")
    assert detail.status_code == 200
    assert [item["id"] for item in detail.json()["items"]] == [first, third]
    assert [item["position"] for item in detail.json()["items"]] == [1, 2]


def test_reorder_playlist_by_video_ids(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "First", "R/1.mp4")
    second = _create_video(tmp_path, "Second", "R/2.mp4")
    third = _create_video(tmp_path, "Third", "R/3.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second, third]}).status_code == 200

    reordered = client.post(f"/api/playlists/{playlist_id}/items/reorder", json={"video_ids": [third, first, second]})
    assert reordered.status_code == 200
    payload = reordered.json()
    assert [item["id"] for item in payload["items"]] == [third, first, second]
    assert [item["position"] for item in payload["items"]] == [1, 2, 3]


def test_reorder_playlist_by_items_array(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "First", "S/1.mp4")
    second = _create_video(tmp_path, "Second", "S/2.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second]}).status_code == 200

    reordered = client.post(
        f"/api/playlists/{playlist_id}/items/reorder",
        json={"items": [{"video_id": second, "position": 1}, {"video_id": first, "position": 2}]},
    )
    assert reordered.status_code == 200
    assert [item["id"] for item in reordered.json()["items"]] == [second, first]


def test_reorder_rejects_partial_payload(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "First", "T/1.mp4")
    second = _create_video(tmp_path, "Second", "T/2.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second]}).status_code == 200

    invalid = client.post(f"/api/playlists/{playlist_id}/items/reorder", json={"video_ids": [first]})
    assert invalid.status_code == 409


def test_bulk_remove_playlist_items(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "First", "BR/1.mp4")
    second = _create_video(tmp_path, "Second", "BR/2.mp4")
    third = _create_video(tmp_path, "Third", "BR/3.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second, third]}).status_code == 200

    removed = client.post(
        f"/api/playlists/{playlist_id}/items/remove-bulk",
        json={"video_ids": [second, 999999, first]},
    )
    assert removed.status_code == 200
    payload = removed.json()
    assert payload["removed"] == [second, first]
    assert payload["not_found"] == [999999]
    assert payload["item_count"] == 1

    detail = client.get(f"/api/playlists/{playlist_id}")
    assert detail.status_code == 200
    assert [item["id"] for item in detail.json()["items"]] == [third]
    assert [item["position"] for item in detail.json()["items"]] == [1]


def test_deleting_video_removes_playlist_item(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    first = _create_video(tmp_path, "First", "U/1.mp4")
    second = _create_video(tmp_path, "Second", "U/2.mp4")
    playlist_id = _create_playlist(client)
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [first, second]}).status_code == 200

    deleted = client.delete(f"/api/videos/{first}")
    assert deleted.status_code == 200

    detail = client.get(f"/api/playlists/{playlist_id}")
    assert detail.status_code == 200
    assert [item["id"] for item in detail.json()["items"]] == [second]
    assert [item["position"] for item in detail.json()["items"]] == [1]


def test_playlist_items_include_tags(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    video_id = _create_video(tmp_path, "Tagged", "V/1.mp4")
    playlist_id = _create_playlist(client)

    tag_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    assert client.post(f"/api/videos/{video_id}/tags", json={"tag_ids": [tag_id]}).status_code == 200
    assert client.post(f"/api/playlists/{playlist_id}/items", json={"video_ids": [video_id]}).status_code == 200

    detail = client.get(f"/api/playlists/{playlist_id}")
    assert detail.status_code == 200
    tags = detail.json()["items"][0]["video"]["tags"]
    assert tags == [{"id": tag_id, "name": "Family", "path": "Family", "color": None}]

