from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.scanner import scan_video_library
from app.schemas import ScanResponse

router = APIRouter(prefix="/api", tags=["scan"])


@router.post("/scan", response_model=ScanResponse)
def scan_library(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanResponse:
    result = scan_video_library(db, settings)
    return ScanResponse(
        scanned=result.scanned,
        added=result.added,
        updated=result.updated,
        errors=result.errors,
    )

