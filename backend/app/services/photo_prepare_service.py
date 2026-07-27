from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.orm import Session

import app.database as db_module
from app.config import Settings
from app.models import Photo, PhotoPrepareJob
from app.scan_status import get_scan_state
from app.services.photo_service import (
    generate_photo_preview,
    generate_photo_thumbnail,
    generate_raw_preview,
    generate_raw_thumbnail,
    resolve_photo_original_path,
)
from app.utils.files import is_raw_photo_file

logger = logging.getLogger(__name__)

READY_STATUSES = {"ready", "generated"}
ACTIVE_STATUSES = {"queued", "running"}

_worker_lock = threading.Lock()
_cancel_event = threading.Event()
_worker_thread: threading.Thread | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_ready_status(value: str | None) -> bool:
    return (value or "").lower() in READY_STATUSES


def _path_exists(settings: Settings, relative_path: str | None) -> bool:
    if not relative_path:
        return False
    path = settings.thumbnails_path / relative_path
    return path.exists() and path.is_file()


def _thumbnail_ready(photo: Photo, settings: Settings) -> bool:
    return _is_ready_status(photo.thumbnail_status) and _path_exists(settings, photo.thumbnail_path)


def _preview_ready(photo: Photo, settings: Settings) -> bool:
    return _is_ready_status(photo.preview_status) and _path_exists(settings, photo.preview_path)


def _photo_ready(photo: Photo, settings: Settings) -> bool:
    return _thumbnail_ready(photo, settings) and _preview_ready(photo, settings)


def _running_job(db: Session) -> PhotoPrepareJob | None:
    return (
        db.query(PhotoPrepareJob)
        .filter(PhotoPrepareJob.status.in_(list(ACTIVE_STATUSES)))
        .order_by(PhotoPrepareJob.created_at.desc())
        .first()
    )


def _latest_job(db: Session) -> PhotoPrepareJob | None:
    return db.query(PhotoPrepareJob).order_by(PhotoPrepareJob.created_at.desc()).first()


def _job_to_status(job: PhotoPrepareJob | None) -> dict[str, object]:
    if job is None:
        return {
            "status": "idle",
            "mode": None,
            "total": 0,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "current_photo_id": None,
            "current_path": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
    return {
        "status": job.status,
        "mode": job.mode,
        "total": job.total,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "skipped": job.skipped,
        "current_photo_id": job.current_photo_id,
        "current_path": job.current_path,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
    }


def get_prepare_status(db: Session) -> dict[str, object]:
    running = _running_job(db)
    if running is not None:
        return _job_to_status(running)
    return _job_to_status(_latest_job(db))


def get_prepare_summary(db: Session, settings: Settings) -> dict[str, int]:
    photos = db.query(Photo).all()
    total = len(photos)
    ready = 0
    missing_thumbnail = 0
    missing_preview = 0
    failed = 0
    raw_total = 0
    raw_ready = 0
    raw_placeholder = 0

    for photo in photos:
        thumb_ready = _thumbnail_ready(photo, settings)
        preview_ready = _preview_ready(photo, settings)
        if thumb_ready and preview_ready:
            ready += 1
        if not thumb_ready:
            missing_thumbnail += 1
        if not preview_ready:
            missing_preview += 1
        if photo.prepare_status == "failed" or photo.thumbnail_status == "failed" or photo.preview_status == "failed":
            failed += 1
        if photo.raw_format:
            raw_total += 1
            if thumb_ready and preview_ready:
                raw_ready += 1
            if photo.thumbnail_status == "placeholder" or photo.preview_status == "placeholder":
                raw_placeholder += 1

    return {
        "total_photos": total,
        "ready": ready,
        "missing_thumbnail": missing_thumbnail,
        "missing_preview": missing_preview,
        "failed": failed,
        "raw_total": raw_total,
        "raw_ready": raw_ready,
        "raw_placeholder": raw_placeholder,
    }


def _needs_preparation(
    photo: Photo,
    settings: Settings,
    *,
    include_failed: bool,
    include_raw_placeholders: bool,
) -> bool:
    if not _thumbnail_ready(photo, settings) or not _preview_ready(photo, settings):
        return True
    if include_failed and (
        photo.prepare_status == "failed" or photo.thumbnail_status == "failed" or photo.preview_status == "failed"
    ):
        return True
    if include_raw_placeholders and photo.raw_format and (
        photo.thumbnail_status == "placeholder" or photo.preview_status == "placeholder"
    ):
        return True
    return False


def _candidate_missing_photo_ids(
    db: Session,
    settings: Settings,
    *,
    include_failed: bool,
    include_raw_placeholders: bool,
) -> list[int]:
    candidates = db.query(Photo).order_by(Photo.id.asc()).all()
    return [
        int(photo.id)
        for photo in candidates
        if _needs_preparation(
            photo,
            settings,
            include_failed=include_failed,
            include_raw_placeholders=include_raw_placeholders,
        )
    ]


def _mark_skipped(photo: Photo, reason: str) -> None:
    photo.prepare_status = "skipped"
    photo.prepare_error = reason


def _prepare_one_photo(db: Session, settings: Settings, photo: Photo, *, force: bool = False) -> str:
    if not force and _photo_ready(photo, settings):
        _mark_skipped(photo, "Already prepared")
        return "skipped"

    photo.prepare_status = "processing"
    photo.prepare_error = None
    db.commit()

    try:
        original_path = resolve_photo_original_path(photo)
    except Exception as exc:  # noqa: BLE001
        _mark_skipped(photo, f"Original path is invalid: {exc}")
        return "skipped"

    if not original_path.exists() or not original_path.is_file():
        _mark_skipped(photo, "Source file not found")
        return "skipped"

    is_raw = bool(photo.raw_format) or is_raw_photo_file(original_path)
    if is_raw:
        thumbnail_result = generate_raw_thumbnail(original_path, settings.thumbnails_path, photo.id)
        preview_result = generate_raw_preview(original_path, settings.thumbnails_path, photo.id)
    else:
        thumbnail_result = generate_photo_thumbnail(original_path, settings.thumbnails_path, photo.id)
        preview_result = generate_photo_preview(original_path, settings.thumbnails_path, photo.id)

    thumbnail_ok = thumbnail_result.path is not None
    preview_ok = preview_result.path is not None

    if thumbnail_ok:
        photo.thumbnail_path = str(thumbnail_result.path.relative_to(settings.thumbnails_path).as_posix())
        photo.thumbnail_status = "ready"
        photo.thumbnail_error = None
    else:
        photo.thumbnail_status = "placeholder" if is_raw else "failed"
        photo.thumbnail_error = thumbnail_result.error or "Thumbnail generation failed"

    if preview_ok:
        photo.preview_path = str(preview_result.path.relative_to(settings.thumbnails_path).as_posix())
        photo.preview_status = "ready"
        photo.preview_error = None
    else:
        photo.preview_status = "placeholder" if is_raw else "failed"
        photo.preview_error = preview_result.error or "Preview generation failed"

    if thumbnail_ok and preview_ok:
        photo.prepare_status = "ready"
        photo.prepare_error = None
        photo.prepared_at = _utcnow()
        return "succeeded"

    message = "; ".join(
        part
        for part in [
            None if thumbnail_ok else photo.thumbnail_error,
            None if preview_ok else photo.preview_error,
        ]
        if part
    )
    if is_raw:
        photo.prepare_status = "placeholder"
        photo.prepare_error = message or "RAW preview unavailable; using placeholder"
        photo.prepared_at = _utcnow()
        return "succeeded"

    photo.prepare_status = "failed"
    photo.prepare_error = message or "Photo preparation failed"
    return "failed"


def _update_job_progress(db: Session, job: PhotoPrepareJob, outcome: str) -> None:
    job.processed += 1
    if outcome == "succeeded":
        job.succeeded += 1
    elif outcome == "skipped":
        job.skipped += 1
    else:
        job.failed += 1
    job.updated_at = _utcnow()
    if job.total > 0:
        # Keep the same shape as HLS progress without adding a schema field.
        pass


def _run_prepare_job(job_id: int, settings: Settings, photo_ids: list[int], *, force: bool) -> None:
    db = db_module.SessionLocal()
    try:
        job = db.query(PhotoPrepareJob).filter(PhotoPrepareJob.id == job_id).first()
        if job is None:
            return
        job.status = "running"
        job.started_at = _utcnow()
        job.updated_at = job.started_at
        db.commit()

        for photo_id in photo_ids:
            db.expire_all()
            job = db.query(PhotoPrepareJob).filter(PhotoPrepareJob.id == job_id).first()
            if job is None:
                return
            if _cancel_event.is_set() or job.status == "cancelled":
                job.status = "cancelled"
                job.finished_at = _utcnow()
                job.current_photo_id = None
                job.current_path = None
                db.commit()
                return

            photo = db.query(Photo).filter(Photo.id == photo_id).first()
            if photo is None:
                _update_job_progress(db, job, "skipped")
                db.commit()
                continue

            job.current_photo_id = photo.id
            job.current_path = photo.relative_path
            job.updated_at = _utcnow()
            db.commit()

            try:
                outcome = _prepare_one_photo(db, settings, photo, force=force)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Photo preparation failed for photo %s", photo_id)
                photo.prepare_status = "failed"
                photo.prepare_error = str(exc)
                photo.thumbnail_status = photo.thumbnail_status or "failed"
                photo.preview_status = photo.preview_status or "failed"
                outcome = "failed"

            _update_job_progress(db, job, outcome)
            db.commit()

        job.status = "completed" if job.failed == 0 else "failed"
        job.finished_at = _utcnow()
        job.current_photo_id = None
        job.current_path = None
        job.updated_at = job.finished_at
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Photo preparation batch crashed")
        try:
            job = db.query(PhotoPrepareJob).filter(PhotoPrepareJob.id == job_id).first()
            if job is not None:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = _utcnow()
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
        with _worker_lock:
            global _worker_thread
            _worker_thread = None
            _cancel_event.clear()


def _start_job(db: Session, settings: Settings, *, mode: str, photo_ids: list[int], force: bool) -> dict[str, object]:
    global _worker_thread
    with _worker_lock:
        scan_state = get_scan_state()
        if scan_state.status in {"running", "cancelling"}:
            return {"status": "skipped", "job_id": None, "reason": "Library scan is running."}

        running = _running_job(db)
        if running is not None:
            return {"status": "skipped", "job_id": running.id, "reason": "Photo preparation is already running."}

        job = PhotoPrepareJob(
            status="queued",
            mode=mode,
            total=len(photo_ids),
            processed=0,
            succeeded=0,
            failed=0,
            skipped=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        _cancel_event.clear()
        _worker_thread = threading.Thread(
            target=_run_prepare_job,
            args=(job.id, settings, photo_ids),
            kwargs={"force": force},
            daemon=True,
        )
        _worker_thread.start()
        return {"status": "started", "job_id": job.id, "reason": None}


def start_prepare_missing(
    db: Session,
    settings: Settings,
    *,
    include_failed: bool = False,
    include_raw_placeholders: bool = True,
) -> dict[str, object]:
    running = _running_job(db)
    if running is not None:
        return {"status": "skipped", "job_id": running.id, "reason": "Photo preparation is already running."}

    photo_ids = _candidate_missing_photo_ids(
        db,
        settings,
        include_failed=include_failed,
        include_raw_placeholders=include_raw_placeholders,
    )
    if not photo_ids:
        return {"status": "skipped", "job_id": None, "reason": "No photos need preparation."}
    return _start_job(db, settings, mode="missing", photo_ids=photo_ids, force=False)


def start_prepare_selected(db: Session, settings: Settings, *, photo_ids: Iterable[int], force: bool = False) -> dict[str, object]:
    wanted_ids = sorted({int(photo_id) for photo_id in photo_ids if int(photo_id) > 0})
    if not wanted_ids:
        return {"status": "skipped", "job_id": None, "reason": "No photo IDs were provided."}
    existing_ids = [row[0] for row in db.query(Photo.id).filter(Photo.id.in_(wanted_ids)).order_by(Photo.id.asc()).all()]
    if not existing_ids:
        return {"status": "skipped", "job_id": None, "reason": "No matching photos found."}
    return _start_job(db, settings, mode="selected", photo_ids=existing_ids, force=force)


def cancel_prepare_job(db: Session) -> dict[str, object]:
    job = _running_job(db)
    if job is None:
        return {"status": "skipped", "reason": "Photo preparation is not running."}
    _cancel_event.set()
    job.status = "cancelled"
    job.error = "Cancellation requested."
    job.finished_at = _utcnow()
    job.updated_at = job.finished_at
    db.commit()
    return {"status": "cancelled", "job_id": job.id, "reason": None}


def recover_photo_prepare_runtime_state(db: Session) -> None:
    stale_jobs = db.query(PhotoPrepareJob).filter(PhotoPrepareJob.status.in_(list(ACTIVE_STATUSES))).all()
    if not stale_jobs:
        return
    now = _utcnow()
    for job in stale_jobs:
        job.status = "cancelled"
        job.error = "Application restarted before photo preparation completed."
        job.finished_at = now
        job.updated_at = now
    db.commit()
