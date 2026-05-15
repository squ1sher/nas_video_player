"""Folder navigation endpoint."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Video
from app.schemas import FolderOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["folders"])


@router.get("/folders", response_model=list[FolderOut])
def list_folders(db: Session = Depends(get_db)) -> list[FolderOut]:
    """Return list of unique folder paths with video counts.
    Always returns relative paths. Root-level videos have folder_path="".
    """
    rows = (
        db.query(Video.folder_path, func.count(Video.id).label("video_count"))
        .group_by(Video.folder_path)
        .order_by(Video.folder_path)
        .all()
    )
    return [
        FolderOut(
            folder_path=row.folder_path if row.folder_path is not None else "",
            video_count=row.video_count,
        )
        for row in rows
    ]
