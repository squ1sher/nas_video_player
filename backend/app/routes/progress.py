"""Watch progress endpoints.

IMPORTANT: This router uses the same prefix as the videos router (/api/videos).
It must be included in main.py BEFORE the videos router so that
GET /api/videos/continue-watching is matched before GET /api/videos/{video_id}.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Video, WatchProgress
from app.routes.videos import to_list_item
from app.schemas import VideoWithProgress, WatchProgressIn, WatchProgressOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["progress"])

COMPLETED_THRESHOLD = 90.0


def _progress_to_schema(progress: WatchProgress) -> WatchProgressOut:
    return WatchProgressOut(
        video_id=progress.video_id,
        position_seconds=progress.position_seconds,
        duration_seconds=progress.duration_seconds,
        percent_watched=progress.percent_watched,
        completed=progress.completed,
        last_watched_at=progress.last_watched_at,
    )


def _default_progress(video_id: int) -> WatchProgressOut:
    return WatchProgressOut(
        video_id=video_id,
        position_seconds=0.0,
        duration_seconds=0.0,
        percent_watched=0.0,
        completed=False,
        last_watched_at=None,
    )


@router.get("/continue-watching", response_model=list[VideoWithProgress])
def get_continue_watching(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[VideoWithProgress]:
    """Return videos with active (not completed) watch progress, newest watched first."""
    rows = (
        db.query(WatchProgress, Video)
        .join(Video, WatchProgress.video_id == Video.id)
        .filter(WatchProgress.completed == False)  # noqa: E712
        .filter(WatchProgress.position_seconds > 0)
        .order_by(WatchProgress.last_watched_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for progress, video in rows:
        item = to_list_item(video)
        result.append(
            VideoWithProgress(
                **item.model_dump(),
                progress=_progress_to_schema(progress),
            )
        )
    return result


@router.get("/{video_id}/progress", response_model=WatchProgressOut)
def get_progress(video_id: int, db: Session = Depends(get_db)) -> WatchProgressOut:
    """Return watch progress for a video. Returns default empty progress if none exists."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    progress = db.query(WatchProgress).filter(WatchProgress.video_id == video_id).first()
    if progress is None:
        return _default_progress(video_id)
    return _progress_to_schema(progress)


@router.put("/{video_id}/progress", response_model=WatchProgressOut)
def update_progress(
    video_id: int,
    body: WatchProgressIn,
    db: Session = Depends(get_db),
) -> WatchProgressOut:
    """Create or update watch progress for a video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    position = max(0.0, body.position_seconds)
    duration = max(0.0, body.duration_seconds)
    percent = (position / duration * 100.0) if duration > 0 else 0.0
    completed = percent >= COMPLETED_THRESHOLD
    now = datetime.now(timezone.utc)

    # Atomic upsert avoids race conditions between parallel player updates.
    db.execute(
        sqlite_insert(WatchProgress)
        .values(
            video_id=video_id,
            position_seconds=position,
            duration_seconds=duration,
            percent_watched=percent,
            completed=completed,
            last_watched_at=now,
        )
        .on_conflict_do_update(
            index_elements=[WatchProgress.video_id],
            set_={
                "position_seconds": position,
                "duration_seconds": duration,
                "percent_watched": percent,
                "completed": completed,
                "last_watched_at": now,
            },
        )
    )
    db.commit()
    progress = db.query(WatchProgress).filter(WatchProgress.video_id == video_id).first()
    if progress is None:
        raise HTTPException(status_code=500, detail="Failed to persist watch progress")
    db.refresh(progress)
    return _progress_to_schema(progress)
