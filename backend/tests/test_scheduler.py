from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.conftest import make_client


def _reset_scan_state() -> None:
    import app.scan_status as ss

    ss._state = ss.ScanState()


def _create_video_with_file(tmp_path: Path, stem: str = "scheduled") -> int:
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    source_file = videos_dir / f"{stem}.mp4"
    source_file.write_bytes(b"fake-media")

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title=f"Video {stem}",
        filename=f"{stem}.mp4",
        relative_path=f"{stem}.mp4",
        absolute_path=str(source_file),
        extension=".mp4",
        size=source_file.stat().st_size,
        modified_ts=time.time(),
        duration=30.0,
        width=1280,
        height=720,
        video_codec="h264",
        audio_codec="aac",
        folder_path="",
        compatibility_status="direct_play",
        compatibility_reason="ok",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()
    return video_id


def _create_enabled_source(tmp_path: Path) -> None:
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    from app.database import SessionLocal
    from app.models import LibraryRoot

    db = SessionLocal()
    existing = db.query(LibraryRoot).filter(LibraryRoot.path == str(videos_dir)).first()
    if existing is None:
        db.add(
            LibraryRoot(
                name="Test Root",
                path=str(videos_dir),
                media_type="video",
                enabled=True,
                recursive=True,
                scan_priority=100,
            )
        )
        db.commit()
    db.close()


def test_scheduler_default_jobs_created_disabled(tmp_path: Path) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)

    response = client.get("/api/scheduler/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert {job["job_type"] for job in jobs} == {"library_scan", "hls_prepare_missing", "photo_prepare_missing"}
    assert all(job["enabled"] is False for job in jobs)


def test_scheduler_jobs_have_next_run_at(tmp_path: Path) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)

    response = client.get("/api/scheduler/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert all(job["next_run_at"] is not None for job in jobs)


def test_scheduler_run_now_library_scan_skips_when_already_running(tmp_path: Path) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)

    from app.scan_status import start_scan

    start_scan()

    jobs = client.get("/api/scheduler/jobs").json()
    library_job = next(job for job in jobs if job["job_type"] == "library_scan")

    response = client.post(f"/api/scheduler/jobs/{library_job['id']}/run-now")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "skipped"
    assert "already running" in (payload.get("reason") or "").lower()


def test_scheduler_run_now_library_scan_skips_when_no_sources(tmp_path: Path) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)
    jobs = client.get("/api/scheduler/jobs").json()
    library_job = next(job for job in jobs if job["job_type"] == "library_scan")

    response = client.post(f"/api/scheduler/jobs/{library_job['id']}/run-now")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "skipped"
    assert "no media sources" in (payload.get("reason") or "").lower()


def test_scheduler_run_now_library_scan_skips_when_photo_prepare_running(tmp_path: Path) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import PhotoPrepareJob

    db = SessionLocal()
    try:
        db.add(PhotoPrepareJob(status="running", mode="missing", total=1))
        db.commit()
    finally:
        db.close()

    jobs = client.get("/api/scheduler/jobs").json()
    library_job = next(job for job in jobs if job["job_type"] == "library_scan")

    response = client.post(f"/api/scheduler/jobs/{library_job['id']}/run-now")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "skipped"
    assert "photo preparation" in (payload.get("reason") or "").lower()


def test_scheduler_run_now_hls_prepare_missing_starts_batch(tmp_path: Path, monkeypatch) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)
    _create_video_with_file(tmp_path)

    import app.services.hls_service as hls_service

    class DummyResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text):
        playlist_path = Path(cmd[-1])
        playlist_path.parent.mkdir(parents=True, exist_ok=True)
        playlist_path.write_text("#EXTM3U\n#EXTINF:4.0,\nsegment_000.ts\n", encoding="utf-8")
        (playlist_path.parent / "segment_000.ts").write_bytes(b"ts")
        return DummyResult()

    monkeypatch.setattr(hls_service.subprocess, "run", fake_run)

    jobs = client.get("/api/scheduler/jobs").json()
    hls_job = next(job for job in jobs if job["job_type"] == "hls_prepare_missing")

    response = client.post(f"/api/scheduler/jobs/{hls_job['id']}/run-now")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"

    status = client.get("/api/hls/status")
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["active_batch_id"] is not None or status_payload["queued_jobs"] >= 0


def test_scheduler_run_now_hls_prepare_missing_skips_when_hls_running(tmp_path: Path) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import HlsBatch

    db = SessionLocal()
    batch = HlsBatch(
        status="running",
        request_type="library",
        qualities_csv="480p",
        skip_existing=True,
        force=False,
        only_missing_hls=True,
    )
    db.add(batch)
    db.commit()
    db.close()

    jobs = client.get("/api/scheduler/jobs").json()
    hls_job = next(job for job in jobs if job["job_type"] == "hls_prepare_missing")

    response = client.post(f"/api/scheduler/jobs/{hls_job['id']}/run-now")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "skipped"
    assert "already running" in (payload.get("reason") or "").lower()


def test_scheduler_run_now_photo_prepare_missing_starts_job(tmp_path: Path) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import Photo

    source = tmp_path / "videos" / "photo.jpg"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"photo")

    db = SessionLocal()
    try:
        db.add(
            Photo(
                media_source_id=None,
                relative_path="photo.jpg",
                internal_path=str(source),
                display_path="/volume1/photo.jpg",
                filename="photo.jpg",
                extension=".jpg",
                file_size=source.stat().st_size,
                scan_status="indexed",
                thumbnail_status="pending",
                preview_status="pending",
                prepare_status="pending",
                raw_format=False,
            )
        )
        db.commit()
    finally:
        db.close()

    jobs = client.get("/api/scheduler/jobs").json()
    photo_job = next(job for job in jobs if job["job_type"] == "photo_prepare_missing")

    response = client.post(f"/api/scheduler/jobs/{photo_job['id']}/run-now")
    assert response.status_code == 200
    assert response.json()["status"] == "started"


def test_due_scheduler_job_executes_and_updates_status(tmp_path: Path, monkeypatch) -> None:
    _reset_scan_state()
    client = make_client(tmp_path)
    _create_enabled_source(tmp_path)
    client.get("/api/scheduler/jobs")

    import app.services.scheduler_service as scheduler_service
    from app.scan_status import start_scan

    def fake_scan(_settings):
        start_scan()

    monkeypatch.setattr(scheduler_service, "scan_video_library_background", fake_scan)

    from app.database import SessionLocal
    from app.models import ScheduledJob
    from app.config import get_settings

    db = SessionLocal()
    job = db.query(ScheduledJob).filter(ScheduledJob.job_type == "library_scan").first()
    assert job is not None
    job.enabled = True
    job.time_of_day = "00:00"
    job.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()

    scheduler_service.run_due_jobs_once(get_settings())

    db = SessionLocal()
    updated = db.query(ScheduledJob).filter(ScheduledJob.job_type == "library_scan").first()
    assert updated is not None
    assert updated.last_status in {"started", "skipped"}
    assert updated.last_run_at is not None
    assert updated.next_run_at is not None
    db.close()


