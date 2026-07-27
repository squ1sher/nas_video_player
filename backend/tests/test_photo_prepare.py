from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client, setup_test_db


def _reset_scan_state() -> None:
    import app.scan_status as ss

    with ss._lock:
        ss._state = ss.ScanState()


def _add_photo(db, tmp_path: Path, *, filename: str = "photo.jpg", raw: bool = False, exists: bool = True) -> int:
    from app.models import Photo

    source = tmp_path / "videos" / filename
    source.parent.mkdir(parents=True, exist_ok=True)
    if exists:
        source.write_bytes(b"photo-bytes")

    photo = Photo(
        media_source_id=None,
        relative_path=filename,
        internal_path=str(source),
        display_path=f"/volume1/{filename}",
        filename=filename,
        extension=Path(filename).suffix.lower(),
        file_size=source.stat().st_size if source.exists() else 1000,
        captured_at=datetime.now(timezone.utc),
        date_source="file_modified",
        raw_format=raw,
        scan_status="indexed",
        thumbnail_status="pending",
        preview_status="pending",
        prepare_status="pending",
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo.id


def _wait_for_terminal_status(client, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get("/api/photos/prepare/status")
        assert response.status_code == 200
        last = response.json()
        if last["status"] not in {"queued", "running"}:
            return last
        time.sleep(0.05)
    assert last is not None
    return last


def test_photo_prepare_summary_returns_counts(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        _add_photo(db, tmp_path, filename="a.jpg")
        _add_photo(db, tmp_path, filename="b.arw", raw=True)
    finally:
        db.close()

    response = client.get("/api/photos/prepare/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_photos"] == 2
    assert data["missing_thumbnail"] == 2
    assert data["missing_preview"] == 2
    assert data["raw_total"] == 1


def test_prepare_selected_generates_thumbnail_and_preview(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        photo_id = _add_photo(db, tmp_path, filename="prepared.jpg")
    finally:
        db.close()

    class _Result:
        def __init__(self, path: Path | None, error: str | None = None) -> None:
            self.path = path
            self.error = error

    def _fake_thumb(_photo_path: Path, thumbnails_dir: Path, photo_id_arg: int) -> _Result:
        out = thumbnails_dir / "photos" / f"{photo_id_arg}.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"thumb")
        return _Result(out)

    def _fake_preview(_photo_path: Path, thumbnails_dir: Path, photo_id_arg: int) -> _Result:
        out = thumbnails_dir / "photos" / f"{photo_id_arg}_preview.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"preview")
        return _Result(out)

    monkeypatch.setattr("app.services.photo_prepare_service.generate_photo_thumbnail", _fake_thumb)
    monkeypatch.setattr("app.services.photo_prepare_service.generate_photo_preview", _fake_preview)

    response = client.post("/api/photos/prepare/selected", json={"photo_ids": [photo_id], "force": False})
    assert response.status_code == 202
    assert response.json()["status"] == "started"

    status = _wait_for_terminal_status(client)
    assert status["status"] == "completed"
    assert status["succeeded"] == 1

    thumb = client.get(f"/api/photos/{photo_id}/thumbnail")
    preview = client.get(f"/api/photos/{photo_id}/preview")
    assert thumb.status_code == 200
    assert preview.status_code == 200
    assert thumb.content == b"thumb"
    assert preview.content == b"preview"


def test_prepare_missing_skips_when_already_running(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import PhotoPrepareJob

    db = SessionLocal()
    try:
        db.add(PhotoPrepareJob(status="running", mode="missing", total=1))
        db.commit()
    finally:
        db.close()

    response = client.post("/api/photos/prepare/missing", json={})
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "skipped"
    assert "already running" in data["reason"]


def test_prepare_missing_skips_when_scan_running(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        _add_photo(db, tmp_path, filename="blocked.jpg")
    finally:
        db.close()

    _reset_scan_state()
    from app.scan_status import start_scan

    start_scan()
    try:
        response = client.post("/api/photos/prepare/missing", json={})
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "skipped"
        assert "library scan is running" in data["reason"].lower()
    finally:
        _reset_scan_state()


def test_prepare_cancel_stops_running_job(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import PhotoPrepareJob

    db = SessionLocal()
    try:
        db.add(PhotoPrepareJob(status="running", mode="missing", total=1))
        db.commit()
    finally:
        db.close()

    response = client.post("/api/photos/prepare/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    status = client.get("/api/photos/prepare/status").json()
    assert status["status"] == "cancelled"


def test_prepare_missing_source_is_skipped_not_crash(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        _add_photo(db, tmp_path, filename="missing.jpg", exists=False)
    finally:
        db.close()

    response = client.post("/api/photos/prepare/missing", json={})
    assert response.status_code == 202
    assert response.json()["status"] == "started"

    status = _wait_for_terminal_status(client)
    assert status["status"] == "completed"
    assert status["skipped"] == 1


def test_raw_prepare_failure_becomes_placeholder(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Photo

    db = SessionLocal()
    try:
        photo_id = _add_photo(db, tmp_path, filename="bad.arw", raw=True)
    finally:
        db.close()

    class _Result:
        path = None
        error = "raw unavailable"

    monkeypatch.setattr("app.services.photo_prepare_service.generate_raw_thumbnail", lambda *_args, **_kwargs: _Result())
    monkeypatch.setattr("app.services.photo_prepare_service.generate_raw_preview", lambda *_args, **_kwargs: _Result())

    response = client.post("/api/photos/prepare/selected", json={"photo_ids": [photo_id], "force": True})
    assert response.status_code == 202
    status = _wait_for_terminal_status(client)
    assert status["status"] == "completed"
    assert status["succeeded"] == 1

    db = SessionLocal()
    try:
        photo = db.query(Photo).filter(Photo.id == photo_id).first()
        assert photo is not None
        assert photo.thumbnail_status == "placeholder"
        assert photo.preview_status == "placeholder"
        assert photo.prepare_status == "placeholder"
    finally:
        db.close()
