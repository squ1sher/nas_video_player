from fastapi import APIRouter, BackgroundTasks, Depends

from app.config import Settings, get_settings
from app.scan_status import get_scan_state
from app.scanner import scan_video_library_background
from app.schemas import ScanStartedResponse, ScanStatusOut

router = APIRouter(prefix="/api", tags=["scan"])


@router.post("/scan", response_model=ScanStartedResponse, status_code=202)
def scan_library(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> ScanStartedResponse:
    """Start a library scan in the background and return immediately."""
    state = get_scan_state()
    if state.status == "running":
        return ScanStartedResponse(status="running", message="Scan is already running")
    background_tasks.add_task(scan_video_library_background, settings)
    return ScanStartedResponse(status="started", message="Scan started in background")


@router.get("/scan/status", response_model=ScanStatusOut)
def get_scan_status() -> ScanStatusOut:
    """Return the current scan status."""
    state = get_scan_state()
    return ScanStatusOut(
        status=state.status,
        started_at=state.started_at,
        finished_at=state.finished_at,
        scanned_files=state.scanned_files,
        detected_videos=state.detected_videos,
        probe_failed=state.probe_failed,
        ignored_non_media=state.ignored_non_media,
        ignored_excluded=state.ignored_excluded,
        thumbnails_generated=state.thumbnails_generated,
        thumbnail_errors=state.thumbnail_errors,
        scanned=state.scanned,
        added=state.added,
        updated=state.updated,
        errors=state.errors,
        current_file=state.current_file,
    )


@router.get("/scan/last-result", response_model=ScanStatusOut)
def get_last_scan_result() -> ScanStatusOut:
    """Return the last scan result (same as status, kept for frontend convenience)."""
    state = get_scan_state()
    return ScanStatusOut(
        status=state.status,
        started_at=state.started_at,
        finished_at=state.finished_at,
        scanned_files=state.scanned_files,
        detected_videos=state.detected_videos,
        probe_failed=state.probe_failed,
        ignored_non_media=state.ignored_non_media,
        ignored_excluded=state.ignored_excluded,
        thumbnails_generated=state.thumbnails_generated,
        thumbnail_errors=state.thumbnail_errors,
        scanned=state.scanned,
        added=state.added,
        updated=state.updated,
        errors=state.errors,
        current_file=state.current_file,
    )
