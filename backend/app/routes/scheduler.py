from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.schemas import ScheduledJobOut, ScheduledJobRunNowOut, ScheduledJobUpdateIn
from app.services.scheduler_service import (
    initialize_default_jobs,
    list_jobs,
    run_job_now,
    update_job,
)

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=list[ScheduledJobOut])
def get_scheduler_jobs(db: Session = Depends(get_db)) -> list[ScheduledJobOut]:
    initialize_default_jobs(db)
    jobs = list_jobs(db)
    return [
        ScheduledJobOut(
            id=job.id,
            job_type=job.job_type,
            name=job.name,
            enabled=job.enabled,
            schedule_type=job.schedule_type,
            time_of_day=job.time_of_day,
            days_of_week=job.days_of_week,
            last_run_at=job.last_run_at,
            next_run_at=job.next_run_at,
            last_status=job.last_status,
            last_error=job.last_error,
        )
        for job in jobs
    ]


@router.put("/jobs/{job_id}", response_model=ScheduledJobOut)
def update_scheduler_job(
    job_id: int,
    body: ScheduledJobUpdateIn,
    db: Session = Depends(get_db),
) -> ScheduledJobOut:
    try:
        updated = update_job(
            db,
            job_id=job_id,
            enabled=body.enabled,
            schedule_type=body.schedule_type,
            time_of_day=body.time_of_day,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    return ScheduledJobOut(
        id=updated.id,
        job_type=updated.job_type,
        name=updated.name,
        enabled=updated.enabled,
        schedule_type=updated.schedule_type,
        time_of_day=updated.time_of_day,
        days_of_week=updated.days_of_week,
        last_run_at=updated.last_run_at,
        next_run_at=updated.next_run_at,
        last_status=updated.last_status,
        last_error=updated.last_error,
    )


@router.post("/jobs/{job_id}/run-now", response_model=ScheduledJobRunNowOut)
def run_scheduler_job_now(
    job_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScheduledJobRunNowOut:
    payload = run_job_now(db, settings, job_id)
    if payload.get("reason") == "Scheduled job not found.":
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    return ScheduledJobRunNowOut(**payload)

