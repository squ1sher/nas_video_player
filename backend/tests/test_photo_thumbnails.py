"""Tests for photo thumbnail and preview endpoints."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database import SessionLocal
from app.models import Photo
from tests.conftest import make_client, setup_test_db


def _add_photo(db, **kwargs) -> int:
    """Helper to add a photo to the database."""
    photo = Photo(**kwargs)
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo.id


def test_photo_thumbnail_endpoint_returns_placeholder(tmp_path: Path) -> None:
    """GET /api/photos/{id}/thumbnail returns placeholder when no thumbnail exists."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.config import get_settings
    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="photo.jpg",
            internal_path=str(tmp_path / "photo.jpg"),
            display_path="/volume1/photo.jpg",
            filename="photo.jpg",
            extension=".jpg",
            file_size=1000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
    finally:
        db.close()

    response = client.get(f"/api/photos/{photo_id}/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    # Placeholder is a 1x1 PNG
    assert len(response.content) > 0


def test_photo_preview_endpoint_returns_placeholder(tmp_path: Path) -> None:
    """GET /api/photos/{id}/preview returns placeholder when no preview exists."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="photo.jpg",
            internal_path=str(tmp_path / "photo.jpg"),
            display_path="/volume1/photo.jpg",
            filename="photo.jpg",
            extension=".jpg",
            file_size=1000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
    finally:
        db.close()

    response = client.get(f"/api/photos/{photo_id}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    # Placeholder is a 1x1 PNG
    assert len(response.content) > 0


def test_photo_detail_includes_preview_url(tmp_path: Path) -> None:
    """GET /api/photos/{id} returns preview_url field."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="photo.jpg",
            internal_path=str(tmp_path / "photo.jpg"),
            display_path="/volume1/photo.jpg",
            filename="photo.jpg",
            extension=".jpg",
            file_size=1000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
    finally:
        db.close()

    response = client.get(f"/api/photos/{photo_id}")
    assert response.status_code == 200
    data = response.json()
    assert "preview_url" in data
    assert data["preview_url"] == f"/api/photos/{photo_id}/preview"
    assert "thumbnail_url" in data
    assert data["thumbnail_url"] == f"/api/photos/{photo_id}/thumbnail"


def test_repair_thumbnails_endpoint_exists(tmp_path: Path) -> None:
    """POST /api/photos/repair-thumbnails endpoint exists and returns status."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    response = client.post("/api/photos/repair-thumbnails")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "repaired" in data
    assert "still_failed" in data


def test_repair_thumbnails_handles_missing_source(tmp_path: Path) -> None:
    """POST /api/photos/repair-thumbnails marks photos with missing source as failed."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        _add_photo(
            db,
            media_source_id=None,
            relative_path="missing.jpg",
            internal_path=str(tmp_path / "nonexistent.jpg"),
            display_path="/volume1/missing.jpg",
            filename="missing.jpg",
            extension=".jpg",
            file_size=1000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
    finally:
        db.close()

    response = client.post("/api/photos/repair-thumbnails")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["total_processed"] >= 1


def test_media_list_includes_photo_thumbnail_urls(tmp_path: Path) -> None:
    """GET /api/media?type=photo includes thumbnail_url for photos."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="test.jpg",
            internal_path=str(tmp_path / "test.jpg"),
            display_path="/volume1/test.jpg",
            filename="test.jpg",
            extension=".jpg",
            file_size=1000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
    finally:
        db.close()

    response = client.get("/api/media?type=photo")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) > 0
    assert data["items"][0]["type"] == "photo"
    assert data["items"][0]["thumbnail_url"] == f"/api/photos/{photo_id}/thumbnail"


def test_media_all_mode_photo_urls_correct(tmp_path: Path) -> None:
    """GET /api/media?type=all includes correct photo URLs."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="all_test.jpg",
            internal_path=str(tmp_path / "all_test.jpg"),
            display_path="/volume1/all_test.jpg",
            filename="all_test.jpg",
            extension=".jpg",
            file_size=1000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",
        )
    finally:
        db.close()

    response = client.get("/api/media?type=all")
    assert response.status_code == 200
    data = response.json()
    photos = [item for item in data["items"] if item["type"] == "photo"]
    assert len(photos) > 0
    assert photos[0]["thumbnail_url"] == f"/api/photos/{photo_id}/thumbnail"


def test_unprepared_existing_jpg_returns_visible_placeholder(tmp_path: Path) -> None:
    """Photo endpoints do not prepare synchronously; they return placeholders until the prepare service runs."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    photo_dir = tmp_path / "videos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    real_jpg = photo_dir / "real.jpg"
    real_jpg.write_bytes(b"jpg-bytes")

    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="real.jpg",
            internal_path=str(real_jpg),
            display_path="/volume1/real.jpg",
            filename="real.jpg",
            extension=".jpg",
            file_size=real_jpg.stat().st_size,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=False,
            scan_status="indexed",
            thumbnail_status="pending",  # no thumbnail yet
        )
    finally:
        db.close()

    response = client.get(f"/api/photos/{photo_id}/thumbnail")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 0

    preview = client.get(f"/api/photos/{photo_id}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert len(preview.content) > 0


def test_raw_format_photo_has_correct_thumbnail_url(tmp_path: Path) -> None:
    """Photos marked as raw_format=True still have correct thumbnail_url."""
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal as get_db_session

    db = get_db_session()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="raw.arw",
            internal_path=str(tmp_path / "raw.arw"),
            display_path="/volume1/raw.arw",
            filename="raw.arw",
            extension=".arw",
            file_size=50_000_000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=True,
            scan_status="indexed",
            thumbnail_status="pending",
        )
    finally:
        db.close()

    response = client.get(f"/api/photos/{photo_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["raw_format"] is True
    assert data["thumbnail_url"] == f"/api/photos/{photo_id}/thumbnail"
    assert data["preview_url"] == f"/api/photos/{photo_id}/preview"


def test_raw_photo_preview_endpoint_can_generate_on_demand(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Photo

    source = tmp_path / "raw-preview.arw"
    source.write_bytes(b"raw-bytes")

    db = SessionLocal()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="raw-preview.arw",
            internal_path=str(source),
            display_path="/volume1/raw-preview.arw",
            filename="raw-preview.arw",
            extension=".arw",
            file_size=50_000_000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=True,
            scan_status="indexed",
            thumbnail_status="pending",
            preview_status="pending",
        )
    finally:
        db.close()

    class _Result:
        def __init__(self, path: Path | None, error: str | None = None) -> None:
            self.path = path
            self.error = error

    def _fake_preview(_photo_path: Path, thumbnails_dir: Path, photo_id_arg: int) -> _Result:
        out = thumbnails_dir / "photos" / f"{photo_id_arg}_preview.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"raw-preview")
        return _Result(out)

    monkeypatch.setattr("app.routes.photos.generate_raw_preview", _fake_preview)

    response = client.get(f"/api/photos/{photo_id}/preview")
    assert response.status_code == 200
    assert response.content == b"raw-preview"

    db = SessionLocal()
    try:
        photo = db.query(Photo).filter(Photo.id == photo_id).first()
        assert photo is not None
        assert photo.preview_status == "ready"
        assert photo.preview_path == f"photos/{photo_id}_preview.jpg"
    finally:
        db.close()


def test_raw_photo_thumbnail_endpoint_can_generate_on_demand(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Photo

    source = tmp_path / "raw-thumb.arw"
    source.write_bytes(b"raw-bytes")

    db = SessionLocal()
    try:
        photo_id = _add_photo(
            db,
            media_source_id=None,
            relative_path="raw-thumb.arw",
            internal_path=str(source),
            display_path="/volume1/raw-thumb.arw",
            filename="raw-thumb.arw",
            extension=".arw",
            file_size=50_000_000,
            captured_at=datetime.now(timezone.utc),
            date_source="file_modified",
            raw_format=True,
            scan_status="indexed",
            thumbnail_status="pending",
            preview_status="pending",
        )
    finally:
        db.close()

    class _Result:
        def __init__(self, path: Path | None, error: str | None = None) -> None:
            self.path = path
            self.error = error

    def _fake_thumb(_photo_path: Path, thumbnails_dir: Path, photo_id_arg: int) -> _Result:
        out = thumbnails_dir / "photos" / f"{photo_id_arg}.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"raw-thumb")
        return _Result(out)

    monkeypatch.setattr("app.routes.photos.generate_raw_thumbnail", _fake_thumb)

    response = client.get(f"/api/photos/{photo_id}/thumbnail")
    assert response.status_code == 200
    assert response.content == b"raw-thumb"

    db = SessionLocal()
    try:
        photo = db.query(Photo).filter(Photo.id == photo_id).first()
        assert photo is not None
        assert photo.thumbnail_status == "ready"
        assert photo.thumbnail_path == f"photos/{photo_id}.jpg"
    finally:
        db.close()
