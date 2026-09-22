"""Tests for moving video/photo source files to a new folder."""
from __future__ import annotations

import time
from pathlib import Path

from tests.conftest import make_client


def _make_library_root(tmp_path: Path, *, name: str, subdir: str) -> tuple[int, Path]:
    from app.database import SessionLocal
    from app.models import LibraryRoot

    root_dir = tmp_path / subdir
    root_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    root = LibraryRoot(name=name, path=str(root_dir), media_type="mixed")
    db.add(root)
    db.commit()
    db.refresh(root)
    root_id = root.id
    db.close()
    return root_id, root_dir


def _make_video(root_dir: Path, root_id: int, *, name: str = "sample") -> int:
    from app.database import SessionLocal
    from app.models import Video

    source_file = root_dir / f"{name}.mp4"
    source_file.write_bytes(b"fake-media-content")

    db = SessionLocal()
    video = Video(
        library_root_id=root_id,
        title=f"Test {name}",
        filename=f"{name}.mp4",
        relative_path=f"{name}.mp4",
        absolute_path=str(source_file),
        extension=".mp4",
        size=source_file.stat().st_size,
        modified_ts=time.time(),
        duration=60.0,
        folder_path="",
        thumbnail_path="sample.mp4.jpg",
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()
    return video_id


def _make_photo(root_dir: Path, root_id: int, *, name: str = "photo") -> int:
    from app.database import SessionLocal
    from app.models import Photo

    source_file = root_dir / f"{name}.jpg"
    source_file.write_bytes(b"fake-photo-content")

    db = SessionLocal()
    photo = Photo(
        media_source_id=root_id,
        relative_path=f"{name}.jpg",
        internal_path=str(source_file),
        display_path=f"/volume1/{name}.jpg",
        filename=f"{name}.jpg",
        extension=".jpg",
        file_size=source_file.stat().st_size,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    photo_id = photo.id
    db.close()
    return photo_id


def test_move_video_updates_paths_and_moves_thumbnail(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    root_id, root_dir = _make_library_root(tmp_path, name="Movies", subdir="videos/movies")
    video_id = _make_video(root_dir, root_id)

    # Matching on-disk thumbnail using the relative-path naming convention.
    thumbs_dir = tmp_path / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    (thumbs_dir / "sample.mp4.jpg").write_bytes(b"thumb")

    dest_dir = root_dir / "subfolder"
    dest_dir.mkdir(parents=True, exist_ok=True)

    response = client.post(f"/api/videos/{video_id}/move", json={"target_directory": str(dest_dir)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["relative_path"] == "subfolder/sample.mp4"
    assert data["folder_path"] == "subfolder"

    assert (dest_dir / "sample.mp4").exists()
    assert not (root_dir / "sample.mp4").exists()
    assert (thumbs_dir / "subfolder__sample.mp4.jpg").exists()
    assert not (thumbs_dir / "sample.mp4.jpg").exists()


def test_move_video_rejects_existing_destination_file(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    root_id, root_dir = _make_library_root(tmp_path, name="Movies", subdir="videos/movies")
    video_id = _make_video(root_dir, root_id)

    dest_dir = root_dir / "subfolder"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "sample.mp4").write_bytes(b"already-here")

    response = client.post(f"/api/videos/{video_id}/move", json={"target_directory": str(dest_dir)})
    assert response.status_code == 409


def test_move_video_rejects_destination_outside_any_root(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    root_id, root_dir = _make_library_root(tmp_path, name="Movies", subdir="videos/movies")
    video_id = _make_video(root_dir, root_id)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)

    response = client.post(f"/api/videos/{video_id}/move", json={"target_directory": str(outside_dir)})
    assert response.status_code == 400


def test_move_photo_updates_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    root_id, root_dir = _make_library_root(tmp_path, name="Photos", subdir="videos/photos")
    photo_id = _make_photo(root_dir, root_id)

    dest_dir = root_dir / "2024"
    dest_dir.mkdir(parents=True, exist_ok=True)

    response = client.post(f"/api/photos/{photo_id}/move", json={"target_directory": str(dest_dir)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["relative_path"] == "2024/photo.jpg"

    assert (dest_dir / "photo.jpg").exists()
    assert not (root_dir / "photo.jpg").exists()
