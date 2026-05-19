"""Maintenance API routes – Phase 2.6."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.services.maintenance_service import (
    apply_cleanup_plan,
    create_cleanup_plan,
    get_cleanup_summary,
)

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("/cleanup/summary")
def cleanup_summary(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    Return a summary of stale/orphan data:
    - orphan HLS folders
    - HLS DB records where files are missing
    - orphan thumbnails
    - stale HLS jobs
    - stale duplicate records
    - video availability breakdown
    """
    return get_cleanup_summary(db, settings)


class CleanupPlanRequest:
    pass


@router.post("/cleanup/plan")
async def cleanup_plan(
    body: dict,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    Generate a dry-run cleanup plan.

    Request body example:
    {
      "include": {
        "orphan_hls_folders": true,
        "hls_db_records_missing_files": true,
        "orphan_thumbnails": true,
        "stale_hls_jobs": true,
        "stale_duplicate_records": true,
        "source_removed_hls": false,
        "missing_video_hls": false
      }
    }
    """
    include: dict[str, bool] = body.get("include", {})
    # Safe defaults if caller provides top-level booleans
    defaults: dict[str, bool] = {
        "orphan_hls_folders": True,
        "hls_db_records_missing_files": True,
        "orphan_thumbnails": True,
        "stale_hls_jobs": True,
        "stale_duplicate_records": True,
        "source_removed_hls": False,
        "missing_video_hls": False,
    }
    merged = {**defaults, **{k: bool(v) for k, v in include.items()}}
    return create_cleanup_plan(db, settings, merged)


@router.post("/cleanup/apply")
async def cleanup_apply(
    body: dict,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    Apply selected items from a previously generated plan.

    Request body:
    {
      "plan_id": "uuid",
      "items": ["item-uuid-1", "item-uuid-2"]  // optional; omit to apply all
    }
    """
    plan_id: str = body.get("plan_id", "")
    selected_ids: list[str] | None = body.get("items")  # None means "all items"
    if not plan_id:
        return {"error": "plan_id is required"}
    return apply_cleanup_plan(db, settings, plan_id, selected_ids)

