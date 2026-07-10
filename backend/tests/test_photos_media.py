from datetime import datetime, timezone
from pathlib import Path

from app.media_probe import ProbeResult
from app.scanner import scan_video_library
from tests.conftest import make_client, setup_test_db


def _add_root(db, path: Path, *, media_type: str) -> int:
    from app.models import LibraryRoot

    root = LibraryRoot(
        name=f"{media_type}-root",
        path=str(path),
        media_type=media_type,
        enabled=True,
        recursive=True,
        scan_priority=100,
    )
    db.add(root)
    db.commit()
    db.refresh(root)
    return root.id


def test_photo_source_scans_jpg_and_marks_preparation_pending(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos" / "photos"
    root.mkdir(parents=True)
    image_path = root / "a.jpg"
    image_path.write_bytes(b"dummy-jpg")

    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import Photo
    from app.services.photo_service import PhotoMetadata

    monkeypatch.setattr(
        "app.scanner.extract_photo_metadata",
        lambda *_args, **_kwargs: PhotoMetadata(
            width=24,
            height=24,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
        ),
    )

    db = SessionLocal()
    try:
        _add_root(db, root, media_type="photo")
        result = scan_video_library(db, get_settings())
        photos = db.query(Photo).all()
    finally:
        db.close()

    assert result.added == 1
    assert len(photos) == 1
    assert photos[0].extension == ".jpg"
    assert photos[0].thumbnail_status == "pending"
    assert photos[0].preview_status == "pending"
    assert photos[0].prepare_status == "pending"


def test_mixed_source_scans_video_and_photo(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos" / "mixed"
    root.mkdir(parents=True)
    video_path = root / "clip.mp4"
    video_path.write_bytes(b"0" * 2_000_000)
    image_path = root / "b.jpg"
    image_path.write_bytes(b"dummy-jpg")

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(
            success=True,
            has_video_stream=True,
            duration=10.0,
            width=1280,
            height=720,
            video_codec="h264",
            audio_codec="aac",
            container_format="mp4",
        ),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *a, **k: None)
    from app.services.photo_service import PhotoMetadata

    monkeypatch.setattr(
        "app.scanner.extract_photo_metadata",
        lambda *_a, **_k: PhotoMetadata(
            width=32,
            height=24,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
        ),
    )
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import Photo, Video

    db = SessionLocal()
    try:
        _add_root(db, root, media_type="mixed")
        scan_video_library(db, get_settings())
        video_count = db.query(Video).count()
        photo_count = db.query(Photo).count()
    finally:
        db.close()

    assert video_count == 1
    assert photo_count == 1


def test_raw_file_indexed_without_thumbnail_crash(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos" / "raws"
    root.mkdir(parents=True)
    raw_file = root / "raw.arw"
    raw_file.write_bytes(b"raw-bytes")

    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import Photo

    db = SessionLocal()
    try:
        _add_root(db, root, media_type="photo")
        scan_video_library(db, get_settings())
        photo = db.query(Photo).first()
    finally:
        db.close()

    assert photo is not None
    assert photo.raw_format is True
    # Scan indexes RAW quickly; preparation is handled by the separate photo preparation service.
    assert photo.thumbnail_status == "pending"
    assert photo.preview_status == "pending"
    assert photo.prepare_status == "pending"


def test_media_api_returns_photo_video_and_all(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Photo, Video

    db = SessionLocal()
    try:
        video = Video(
            title="v1",
            filename="v1.mp4",
            relative_path="v1.mp4",
            absolute_path=str(tmp_path / "videos" / "v1.mp4"),
            extension=".mp4",
            size=123,
            modified_ts=datetime.now(timezone.utc).timestamp(),
            folder_path="",
            media_status="detected_video",
            probe_status="success",
            compatibility_status="direct_play",
            compatibility_reason="ok",
            indexed_at=datetime.now(timezone.utc),
        )
        photo = Photo(
            media_source_id=None,
            relative_path="p1.jpg",
            internal_path=str(tmp_path / "videos" / "p1.jpg"),
            display_path="/volume1/p1.jpg",
            filename="p1.jpg",
            extension=".jpg",
            file_size=456,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
        db.add(video)
        db.add(photo)
        db.commit()
    finally:
        db.close()

    photo_resp = client.get("/api/media?type=photo")
    video_resp = client.get("/api/media?type=video")
    all_resp = client.get("/api/media?type=all")

    assert photo_resp.status_code == 200
    assert video_resp.status_code == 200
    assert all_resp.status_code == 200

    assert all(item["type"] == "photo" for item in photo_resp.json()["items"])
    assert all(item["type"] == "video" for item in video_resp.json()["items"])
    types = {item["type"] for item in all_resp.json()["items"]}
    assert types == {"photo", "video"}


def test_media_api_all_includes_tagged_videos(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Photo, Tag, Video, VideoTag

    db = SessionLocal()
    try:
        video = Video(
            title="tagged",
            filename="tagged.mp4",
            relative_path="tagged.mp4",
            absolute_path=str(tmp_path / "videos" / "tagged.mp4"),
            extension=".mp4",
            size=321,
            modified_ts=datetime.now(timezone.utc).timestamp(),
            folder_path="",
            media_status="detected_video",
            probe_status="success",
            compatibility_status="direct_play",
            compatibility_reason="ok",
            indexed_at=datetime.now(timezone.utc),
        )
        photo = Photo(
            media_source_id=None,
            relative_path="p2.jpg",
            internal_path=str(tmp_path / "videos" / "p2.jpg"),
            display_path="/volume1/p2.jpg",
            filename="p2.jpg",
            extension=".jpg",
            file_size=654,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
        tag = Tag(name="Travel", normalized_name="travel", path="Travel", depth=0, color=None)

        db.add_all([video, photo, tag])
        db.flush()
        db.add(VideoTag(video_id=video.id, tag_id=tag.id))
        db.commit()
        tag_id = tag.id
    finally:
        db.close()

    response = client.get("/api/media?type=all")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 2
    video_items = [item for item in payload["items"] if item["type"] == "video"]
    assert len(video_items) == 1
    assert video_items[0]["tags"] == [
        {
            "id": tag_id,
            "name": "Travel",
            "path": "Travel",
            "color": None,
        }
    ]


def test_raw_photo_extensions_are_hidden_from_video_endpoints(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    try:
        raw_video = Video(
            title="raw photo",
            filename="photo.arw",
            relative_path="photo.arw",
            absolute_path=str(tmp_path / "videos" / "photo.arw"),
            extension=".arw",
            size=1024,
            modified_ts=datetime.now(timezone.utc).timestamp(),
            folder_path="",
            media_status="detected_video",
            probe_status="success",
            compatibility_status="may_not_play",
            compatibility_reason="should not be visible as video",
            indexed_at=datetime.now(timezone.utc),
        )
        db.add(raw_video)
        db.commit()
        raw_id = raw_video.id
    finally:
        db.close()

    list_resp = client.get("/api/videos")
    media_resp = client.get("/api/media?type=video")
    detail_resp = client.get(f"/api/videos/{raw_id}")

    assert list_resp.status_code == 200
    assert media_resp.status_code == 200
    assert detail_resp.status_code == 404
    assert all(item["extension"] != ".arw" for item in list_resp.json())
    assert all(item["extension"] != ".arw" for item in media_resp.json()["items"])

