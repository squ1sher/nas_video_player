from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.duplicate_scan_status import (
    complete_duplicate_scan,
    fail_duplicate_scan,
    get_duplicate_scan_state,
    start_duplicate_scan,
)
from app.schemas import (
    DuplicateGroupOut,
    DuplicateScanStartResponse,
    DuplicateScanStatusOut,
    DuplicateSummaryOut,
)
from app.services.duplicate_service import load_duplicate_groups, load_duplicate_summary, run_duplicate_scan, save_duplicate_summary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/duplicates", tags=["duplicates"])


def _run_duplicate_scan_background(mode: str) -> None:
    from app.database import SessionLocal
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        summary = run_duplicate_scan(db, mode=mode)
        complete_duplicate_scan(summary)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Duplicate scan failed: %s", exc)
        save_duplicate_summary(
            db,
            mode,
            {
                "status": "failed",
                "videos_checked": 0,
                "candidate_groups_found": 0,
                "duplicate_candidates_found": 0,
                "potential_saving": 0,
                "last_scan_at": datetime.now(timezone.utc).isoformat(),
            },
            errors=[str(exc)],
        )
        fail_duplicate_scan(str(exc))
    finally:
        db.close()


@router.post("/scan", response_model=DuplicateScanStartResponse, status_code=202)
def start_duplicates_scan(
    background_tasks: BackgroundTasks,
) -> DuplicateScanStartResponse:
    mode = "strict"

    started = start_duplicate_scan(mode)
    if not started:
        raise HTTPException(status_code=409, detail="Duplicate scan is already running")

    background_tasks.add_task(_run_duplicate_scan_background, mode)
    return DuplicateScanStartResponse(status="started", mode=mode)


@router.get("/status", response_model=DuplicateScanStatusOut)
def get_duplicates_status() -> DuplicateScanStatusOut:
    state = get_duplicate_scan_state()
    return DuplicateScanStatusOut(
        status=state.status,
        mode=state.mode,
        started_at=state.started_at,
        finished_at=state.finished_at,
        videos_checked=state.videos_checked,
        candidate_groups_found=state.candidate_groups_found,
        duplicate_candidates_found=state.duplicate_candidates_found,
        current_step=state.current_step,
        errors=state.errors,
        last_result_summary=state.last_result_summary,
    )


@router.get("/groups", response_model=list[DuplicateGroupOut])
def get_duplicate_groups(db: Session = Depends(get_db)) -> list[DuplicateGroupOut]:
    mode = "strict"
    groups = load_duplicate_groups(db, mode=mode)
    return [DuplicateGroupOut(**group) for group in groups]


@router.get("/summary", response_model=DuplicateSummaryOut)
def get_duplicate_summary(db: Session = Depends(get_db)) -> DuplicateSummaryOut:
    mode = "strict"
    summary = load_duplicate_summary(db, mode=mode)
    return DuplicateSummaryOut(**summary)



