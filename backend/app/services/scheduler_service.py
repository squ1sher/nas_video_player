from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import app.database as db_module
from app.config import Settings
from app.models import LibraryRoot, ScheduledJob
from app.scan_status import get_scan_state
from app.scanner import scan_video_library_background
from app.services.hls_service import DEFAULT_GENERATION_QUALITIES, create_library_batch, get_global_hls_status
from app.services.photo_prepare_service import get_prepare_status, start_prepare_missing

JOB_TYPE_LIBRARY_SCAN = "library_scan"
JOB_TYPE_HLS_PREPARE_MISSING = "hls_prepare_missing"
JOB_TYPE_PHOTO_PREPARE_MISSING = "photo_prepare_missing"
ALLOWED_JOB_TYPES = {JOB_TYPE_LIBRARY_SCAN, JOB_TYPE_HLS_PREPARE_MISSING, JOB_TYPE_PHOTO_PREPARE_MISSING}
ALLOWED_SCHEDULE_TYPES = {"daily"}
SCHEDULER_POLL_SECONDS = 60

_DEFAULT_JOBS: tuple[tuple[str, str, str], ...] = (
    (JOB_TYPE_LIBRARY_SCAN, "Library scan", "02:00"),
    (JOB_TYPE_HLS_PREPARE_MISSING, "Prepare HLS for all missing", "03:00"),
    (JOB_TYPE_PHOTO_PREPARE_MISSING, "Prepare photo thumbnails/previews", "04:00"),
)

_scheduler_lock = threading.Lock()
_scheduler_started = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _is_valid_time_of_day(value: str) -> bool:
    try:
        hour_raw, minute_raw = value.split(":", 1)
        hour = int(hour_raw)
        minute = int(minute_raw)
    except (ValueError, AttributeError):
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _compute_next_run_at(time_of_day: str, *, now_local: datetime | None = None) -> datetime:
    if not _is_valid_time_of_day(time_of_day):
        raise ValueError("time_of_day must use HH:MM (24-hour) format")

    local_now = now_local or _now_local()
    hour, minute = [int(token) for token in time_of_day.split(":", 1)]
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def initialize_default_jobs(db: Session) -> None:
    existing = {
        job.job_type: job
        for job in db.query(ScheduledJob)
        .filter(ScheduledJob.job_type.in_(list(ALLOWED_JOB_TYPES)))
        .all()
    }

    changed = False
    for job_type, name, default_time in _DEFAULT_JOBS:
        job = existing.get(job_type)
        if job is None:
            job = ScheduledJob(
                job_type=job_type,
                name=name,
                enabled=False,
                schedule_type="daily",
                time_of_day=default_time,
                days_of_week=None,
                next_run_at=_compute_next_run_at(default_time),
            )
            db.add(job)
            changed = True
            continue

        if not _is_valid_time_of_day(job.time_of_day):
            job.time_of_day = default_time
            changed = True
        if job.schedule_type not in ALLOWED_SCHEDULE_TYPES:
            job.schedule_type = "daily"
            changed = True
        if not job.name:
            job.name = name
            changed = True
        if job.next_run_at is None:
            job.next_run_at = _compute_next_run_at(job.time_of_day)
            changed = True

    if changed:
        db.commit()


def recalculate_next_runs(db: Session) -> None:
    jobs = db.query(ScheduledJob).filter(ScheduledJob.job_type.in_(list(ALLOWED_JOB_TYPES))).all()
    if not jobs:
        return
    for job in jobs:
        if not _is_valid_time_of_day(job.time_of_day):
            continue
        job.next_run_at = _compute_next_run_at(job.time_of_day)
    db.commit()


def list_jobs(db: Session) -> list[ScheduledJob]:
    return (
        db.query(ScheduledJob)
        .filter(ScheduledJob.job_type.in_(list(ALLOWED_JOB_TYPES)))
        .order_by(ScheduledJob.id.asc())
        .all()
    )


def update_job(
    db: Session,
    *,
    job_id: int,
    enabled: bool,
    schedule_type: str,
    time_of_day: str,
) -> ScheduledJob | None:
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if job is None:
        return None
    if job.job_type not in ALLOWED_JOB_TYPES:
        return None
    if schedule_type not in ALLOWED_SCHEDULE_TYPES:
        raise ValueError("Unsupported schedule_type")
    if not _is_valid_time_of_day(time_of_day):
        raise ValueError("Invalid time_of_day")

    job.enabled = bool(enabled)
    job.schedule_type = schedule_type
    job.time_of_day = time_of_day
    job.next_run_at = _compute_next_run_at(time_of_day)
    db.commit()
    db.refresh(job)
    return job


def _enabled_sources_count(db: Session) -> int:
    return int(db.query(LibraryRoot).filter(LibraryRoot.enabled.is_(True)).count())


def _try_start_library_scan(db: Session, settings: Settings) -> tuple[str, str | None]:
    state = get_scan_state()
    if state.status in {"running", "cancelling"}:
        return "skipped", "Library scan is already running."

    photo_prepare_status = get_prepare_status(db)
    if photo_prepare_status.get("status") in {"queued", "running"}:
        return "skipped", "Photo preparation is already running."

    if _enabled_sources_count(db) == 0:
        return "skipped", "No media sources configured."

    worker = threading.Thread(target=scan_video_library_background, args=(settings,), daemon=True)
    worker.start()
    return "started", None


def _try_start_hls_prepare_missing(db: Session, settings: Settings) -> tuple[str, str | None]:
    global_status = get_global_hls_status(db, settings)
    if global_status["running"] > 0 or global_status["queued_jobs"] > 0 or global_status["active_batch_id"] is not None:
        return "skipped", "HLS preparation is already running."

    payload = create_library_batch(
        db,
        settings,
        qualities=list(DEFAULT_GENERATION_QUALITIES),
        skip_existing=True,
        force=False,
        only_missing_hls=True,
    )

    if payload["status"] == "queued":
        return "started", None
    return "skipped", str(payload.get("message") or "No videos queued for HLS.")


def _try_start_photo_prepare_missing(db: Session, settings: Settings) -> tuple[str, str | None]:
    scan_state = get_scan_state()
    if scan_state.status in {"running", "cancelling"}:
        return "skipped", "Library scan is running."

    status = get_prepare_status(db)
    if status.get("status") in {"queued", "running"}:
        return "skipped", "Photo preparation is already running."

    payload = start_prepare_missing(db, settings, include_failed=False, include_raw_placeholders=True)
    if payload["status"] == "started":
        return "started", None
    return "skipped", str(payload.get("reason") or "No photos need preparation.")


def _execute_job(
    db: Session,
    settings: Settings,
    job: ScheduledJob,
    *,
    require_enabled: bool,
) -> tuple[str, str | None]:
    if require_enabled and not job.enabled:
        return "skipped", "Job is disabled."

    if job.job_type == JOB_TYPE_LIBRARY_SCAN:
        return _try_start_library_scan(db, settings)
    if job.job_type == JOB_TYPE_HLS_PREPARE_MISSING:
        return _try_start_hls_prepare_missing(db, settings)
    if job.job_type == JOB_TYPE_PHOTO_PREPARE_MISSING:
        return _try_start_photo_prepare_missing(db, settings)
    return "skipped", "Unsupported job type."


def _record_job_result(db: Session, job: ScheduledJob, status: str, message: str | None) -> None:
    job.last_run_at = _utcnow()
    job.last_status = status
    job.last_error = message
    if _is_valid_time_of_day(job.time_of_day):
        job.next_run_at = _compute_next_run_at(job.time_of_day)
    db.commit()


def run_job_now(db: Session, settings: Settings, job_id: int) -> dict[str, str]:
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if job is None or job.job_type not in ALLOWED_JOB_TYPES:
        return {"status": "skipped", "reason": "Scheduled job not found."}

    status, reason = _execute_job(db, settings, job, require_enabled=False)
    _record_job_result(db, job, status, reason)

    response: dict[str, str] = {"status": status, "job_type": job.job_type}
    if reason:
        response["reason"] = reason
    return response


def run_due_jobs_once(settings: Settings) -> None:
    db = db_module.SessionLocal()
    try:
        initialize_default_jobs(db)
        now = _utcnow()
        due_jobs = (
            db.query(ScheduledJob)
            .filter(ScheduledJob.enabled.is_(True))
            .filter(ScheduledJob.job_type.in_(list(ALLOWED_JOB_TYPES)))
            .filter(ScheduledJob.next_run_at.is_not(None))
            .filter(ScheduledJob.next_run_at <= now)
            .order_by(ScheduledJob.next_run_at.asc(), ScheduledJob.id.asc())
            .all()
        )
        for job in due_jobs:
            status, reason = _execute_job(db, settings, job, require_enabled=True)
            _record_job_result(db, job, status, reason)
    finally:
        db.close()


def _scheduler_loop(settings: Settings) -> None:
    while True:
        try:
            run_due_jobs_once(settings)
        except Exception:
            # Defensive: scheduler must never crash the API process.
            pass
        time.sleep(SCHEDULER_POLL_SECONDS)


def start_scheduler(settings: Settings) -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        worker = threading.Thread(target=_scheduler_loop, args=(settings,), daemon=True)
        worker.start()
        _scheduler_started = True

