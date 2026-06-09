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


def test_photo_source_scans_jpg_and_generates_thumbnail(tmp_path: Path, monkeypatch) -> None:
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

    class _ThumbResult:
        def __init__(self, path: Path | None, error: str | None = None) -> None:
            self.path = path
            self.error = error

    def _fake_thumb(_photo_path: Path, thumbnails_dir: Path, photo_id: int) -> _ThumbResult:
        target = thumbnails_dir / "photos"
        target.mkdir(parents=True, exist_ok=True)
        out = target / f"{photo_id}.jpg"
        out.write_bytes(b"thumb")
        return _ThumbResult(path=out)

    monkeypatch.setattr("app.scanner.generate_photo_thumbnail", _fake_thumb)

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
    assert photos[0].thumbnail_status == "generated"


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
    monkeypatch.setattr(
        "app.scanner.generate_photo_thumbnail",
        lambda *_a, **_k: type("_R", (), {"path": None, "error": "skip"})(),
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
    assert photo.thumbnail_status == "skipped"


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

