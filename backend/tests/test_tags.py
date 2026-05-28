from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import make_client
from tests.conftest import setup_test_db


def _create_video(tmp_path: Path, relative_path: str = "Family/test.mp4") -> int:
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title="Tagged Video",
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=".mp4",
        size=1024,
        modified_ts=datetime.now(timezone.utc).timestamp(),
        duration=10.0,
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
        folder_path="Family",
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


def test_create_hierarchical_tags_and_duplicate_rules(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    family = client.post("/api/tags", json={"name": "Family"})
    assert family.status_code == 201
    family_id = family.json()["id"]

    alex = client.post("/api/tags", json={"name": "Alex", "parent_id": family_id})
    assert alex.status_code == 201

    duplicate_same_parent = client.post("/api/tags", json={"name": " alex ", "parent_id": family_id})
    assert duplicate_same_parent.status_code == 409

    work = client.post("/api/tags", json={"name": "Work"})
    assert work.status_code == 201
    work_id = work.json()["id"]

    alex_in_work = client.post("/api/tags", json={"name": "Alex", "parent_id": work_id})
    assert alex_in_work.status_code == 201


def test_rename_and_move_updates_paths_and_blocks_invalid_parent(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    spain_id = client.post("/api/tags", json={"name": "Spain", "parent_id": travel_id}).json()["id"]
    mallorca_resp = client.post("/api/tags", json={"name": "Mallorca", "parent_id": spain_id})
    mallorca_id = mallorca_resp.json()["id"]

    renamed = client.put(f"/api/tags/{spain_id}", json={"name": "Spain 2025", "parent_id": travel_id})
    assert renamed.status_code == 200

    tree = client.get("/api/tags/tree")
    assert tree.status_code == 200
    mallorca = tree.json()[0]["children"][0]["children"][0]
    assert mallorca["path"] == "Travel/Spain 2025/Mallorca"
    assert mallorca["depth"] == 2

    invalid_move = client.put(f"/api/tags/{travel_id}", json={"name": "Travel", "parent_id": mallorca_id})
    assert invalid_move.status_code == 409


def test_delete_tag_requires_leaf_unless_force(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    parent_id = client.post("/api/tags", json={"name": "GoPro"}).json()["id"]
    child_id = client.post("/api/tags", json={"name": "Bike", "parent_id": parent_id}).json()["id"]

    blocked = client.delete(f"/api/tags/{parent_id}")
    assert blocked.status_code == 409

    deleted_leaf = client.delete(f"/api/tags/{child_id}")
    assert deleted_leaf.status_code == 200

    force_deleted = client.delete(f"/api/tags/{parent_id}?force=true")
    assert force_deleted.status_code == 200


def test_assign_replace_remove_video_tags_and_return_full_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video(tmp_path)

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    alex_id = client.post("/api/tags", json={"name": "Alex", "parent_id": family_id}).json()["id"]
    running_id = client.post("/api/tags", json={"name": "Running"}).json()["id"]

    assigned = client.post(f"/api/videos/{video_id}/tags", json={"tag_ids": [alex_id, alex_id]})
    assert assigned.status_code == 200
    assert [item["path"] for item in assigned.json()] == ["Family/Alex"]

    replaced = client.put(f"/api/videos/{video_id}/tags", json={"tag_ids": [alex_id, running_id]})
    assert replaced.status_code == 200
    assert {item["path"] for item in replaced.json()} == {"Family/Alex", "Running"}

    removed = client.delete(f"/api/videos/{video_id}/tags/{running_id}")
    assert removed.status_code == 200

    tags_after_remove = client.get(f"/api/videos/{video_id}/tags")
    assert tags_after_remove.status_code == 200
    assert [item["path"] for item in tags_after_remove.json()] == ["Family/Alex"]


def test_video_list_includes_tags_and_video_delete_cleans_links(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video(tmp_path, relative_path="Travel/clip.mp4")

    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    mallorca_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": travel_id}).json()["id"]
    assign = client.post(f"/api/videos/{video_id}/tags", json={"tag_ids": [mallorca_id]})
    assert assign.status_code == 200

    videos = client.get("/api/videos")
    assert videos.status_code == 200
    tagged_video = next(item for item in videos.json() if item["id"] == video_id)
    assert tagged_video["tags"] == [
        {
            "id": mallorca_id,
            "name": "Mallorca",
            "path": "Travel/Mallorca",
            "color": None,
        }
    ]

    delete_response = client.delete(f"/api/videos/{video_id}")
    assert delete_response.status_code == 200

    from app.database import SessionLocal
    from app.models import VideoTag

    db = SessionLocal()
    dangling_links = db.query(VideoTag).filter(VideoTag.video_id == video_id).count()
    db.close()
    assert dangling_links == 0


def test_get_tag_tree_nested_structure(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    son_id = client.post("/api/tags", json={"name": "Son", "parent_id": family_id}).json()["id"]
    client.post("/api/tags", json={"name": "Birthday", "parent_id": son_id})

    response = client.get("/api/tags/tree")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["path"] == "Family"
    assert payload[0]["children"][0]["path"] == "Family/Son"
    assert payload[0]["children"][0]["children"][0]["path"] == "Family/Son/Birthday"


def test_legacy_global_unique_tag_schema_is_repaired(tmp_path: Path) -> None:
    engine = setup_test_db(tmp_path)

    # Emulate an old flat-tag schema that enforced UNIQUE(normalized_name).
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("DROP TABLE IF EXISTS video_tags"))
        conn.execute(text("DROP TABLE IF EXISTS tags"))
        conn.execute(
            text(
                """
                CREATE TABLE tags (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    normalized_name VARCHAR(255) NOT NULL UNIQUE,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE video_tags (
                    id INTEGER PRIMARY KEY,
                    video_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(text("PRAGMA foreign_keys=ON"))

    from app.migrations import run_migrations
    from app.services.tag_service import create_tag

    run_migrations(engine)

    with Session(engine) as db:
        family = create_tag(db, name="Family", parent_id=None, color=None, description=None)
        work = create_tag(db, name="Work", parent_id=None, color=None, description=None)
        create_tag(db, name="Alex", parent_id=family.id, color=None, description=None)
        second_alex = create_tag(db, name="Alex", parent_id=work.id, color=None, description=None)

        assert second_alex.parent_id == work.id


def test_patch_tag_tree_moves_to_new_parent_and_root(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    spain_id = client.post("/api/tags", json={"name": "Spain", "parent_id": travel_id}).json()["id"]
    mallorca_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": spain_id}).json()["id"]

    move_under_family = client.patch("/api/tags/tree", json={"moves": [{"tag_id": spain_id, "new_parent_id": family_id}]})
    assert move_under_family.status_code == 200
    payload = move_under_family.json()
    assert payload["status"] == "updated"
    assert payload["updated_tags"] >= 2
    moved_spain = next(node for node in payload["tree"][0]["children"] if node["id"] == spain_id)
    assert moved_spain["path"] == "Family/Spain"
    assert moved_spain["children"][0]["path"] == "Family/Spain/Mallorca"

    move_to_root = client.patch("/api/tags/tree", json={"moves": [{"tag_id": mallorca_id, "new_parent_id": None}]})
    assert move_to_root.status_code == 200
    roots = [node["path"] for node in move_to_root.json()["tree"]]
    assert "Mallorca" in roots


def test_patch_tag_tree_rejects_self_and_descendant_moves(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    spain_id = client.post("/api/tags", json={"name": "Spain", "parent_id": travel_id}).json()["id"]
    mallorca_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": spain_id}).json()["id"]

    self_move = client.patch("/api/tags/tree", json={"moves": [{"tag_id": spain_id, "new_parent_id": spain_id}]})
    assert self_move.status_code == 409

    descendant_move = client.patch("/api/tags/tree", json={"moves": [{"tag_id": travel_id, "new_parent_id": mallorca_id}]})
    assert descendant_move.status_code == 409


def test_patch_tag_tree_rejects_duplicate_name_under_same_parent_and_is_atomic(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]
    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    alex_family_id = client.post("/api/tags", json={"name": "Alex", "parent_id": family_id}).json()["id"]
    alex_travel_id = client.post("/api/tags", json={"name": "Alex", "parent_id": travel_id}).json()["id"]
    spain_id = client.post("/api/tags", json={"name": "Spain", "parent_id": travel_id}).json()["id"]

    # First move is valid, second introduces duplicate sibling name under Family.
    response = client.patch(
        "/api/tags/tree",
        json={
            "moves": [
                {"tag_id": spain_id, "new_parent_id": family_id},
                {"tag_id": alex_travel_id, "new_parent_id": family_id},
            ]
        },
    )
    assert response.status_code == 409

    tree_after = client.get("/api/tags/tree")
    assert tree_after.status_code == 200
    travel_node = next(node for node in tree_after.json() if node["id"] == travel_id)
    assert any(child["id"] == spain_id for child in travel_node["children"])
    family_node = next(node for node in tree_after.json() if node["id"] == family_id)
    assert any(child["id"] == alex_family_id for child in family_node["children"])
    assert not any(child["id"] == alex_travel_id for child in family_node["children"])


def test_patch_tag_tree_keeps_video_links_and_updates_video_tag_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video(tmp_path, relative_path="Travel/clip2.mp4")

    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    spain_id = client.post("/api/tags", json={"name": "Spain", "parent_id": travel_id}).json()["id"]
    mallorca_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": spain_id}).json()["id"]
    family_id = client.post("/api/tags", json={"name": "Family"}).json()["id"]

    assign = client.post(f"/api/videos/{video_id}/tags", json={"tag_ids": [mallorca_id]})
    assert assign.status_code == 200
    assert assign.json()[0]["path"] == "Travel/Spain/Mallorca"

    move = client.patch("/api/tags/tree", json={"moves": [{"tag_id": spain_id, "new_parent_id": family_id}]})
    assert move.status_code == 200

    tags_after_move = client.get(f"/api/videos/{video_id}/tags")
    assert tags_after_move.status_code == 200
    assert tags_after_move.json()[0]["id"] == mallorca_id
    assert tags_after_move.json()[0]["path"] == "Family/Spain/Mallorca"


def test_patch_tag_tree_renames_tag_and_updates_descendants_and_video_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video(tmp_path, relative_path="Travel/clip3.mp4")

    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    spain_id = client.post("/api/tags", json={"name": "Spain", "parent_id": travel_id}).json()["id"]
    mallorca_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": spain_id}).json()["id"]

    assign = client.post(f"/api/videos/{video_id}/tags", json={"tag_ids": [mallorca_id]})
    assert assign.status_code == 200

    rename = client.patch("/api/tags/tree", json={"moves": [{"tag_id": spain_id, "new_parent_id": travel_id, "new_name": "Spain 2025"}]})
    assert rename.status_code == 200
    payload = rename.json()
    renamed_spain = payload["tree"][0]["children"][0]
    assert renamed_spain["name"] == "Spain 2025"
    assert renamed_spain["path"] == "Travel/Spain 2025"
    assert renamed_spain["children"][0]["path"] == "Travel/Spain 2025/Mallorca"

    tags_after_rename = client.get(f"/api/videos/{video_id}/tags")
    assert tags_after_rename.status_code == 200
    assert tags_after_rename.json()[0]["id"] == mallorca_id
    assert tags_after_rename.json()[0]["path"] == "Travel/Spain 2025/Mallorca"


def test_patch_tag_tree_rejects_duplicate_rename_under_same_parent(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    travel_id = client.post("/api/tags", json={"name": "Travel"}).json()["id"]
    first_id = client.post("/api/tags", json={"name": "Spain", "parent_id": travel_id}).json()["id"]
    second_id = client.post("/api/tags", json={"name": "Mallorca", "parent_id": travel_id}).json()["id"]

    rename = client.patch("/api/tags/tree", json={"moves": [{"tag_id": second_id, "new_parent_id": travel_id, "new_name": "Spain"}]})
    assert rename.status_code == 409

    tree_after = client.get("/api/tags/tree")
    assert tree_after.status_code == 200
    travel_children = tree_after.json()[0]["children"]
    assert any(child["id"] == first_id and child["name"] == "Spain" for child in travel_children)
    assert any(child["id"] == second_id and child["name"] == "Mallorca" for child in travel_children)


