from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.config import Settings, get_settings
from app.database import get_db
from app.models import LibraryRoot
from app.scan_status import get_scan_state, request_scan_cancellation
from app.scanner import scan_video_library_background
from app.schemas import ScanStartedResponse, ScanStatusOut
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api", tags=["scan"])


def _scan_state_payload(state) -> dict[str, object]:
    payload = {
        "status": state.status,
        "cancellation_requested": state.cancellation_requested,
        "started_at": state.started_at,
        "finished_at": state.finished_at,
        "scanned_files": state.scanned_files,
        "detected_videos": state.detected_videos,
        "existing_unchanged": state.existing_unchanged,
        "probe_failed": state.probe_failed,
        "ignored_non_media": state.ignored_non_media,
        "ignored_excluded": state.ignored_excluded,
        "thumbnails_generated": state.thumbnails_generated,
        "thumbnail_errors": state.thumbnail_errors,
        "thumbnail_failed": state.thumbnail_errors,
        "scanned": state.scanned,
        "added": state.added,
        "updated": state.updated,
        "removed_missing": state.removed_missing,
        "errors": state.errors,
        "current_file": state.current_file,
        "current_root": state.current_root,
        "roots_scanned": state.roots_scanned,
        "total_roots": state.total_roots,
        "message": state.message,
    }
    return ScanStatusOut(**payload).model_dump(mode="json")


@router.post("/scan", response_model=ScanStartedResponse, status_code=202)
def scan_library(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ScanStartedResponse:
    """Start a library scan in the background and return immediately."""
    state = get_scan_state()
    if state.status in {"running", "cancelling"}:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_running",
                "message": "Library scan is already running.",
                "current_status": _scan_state_payload(state),
            },
        )

    # Check for no-sources before launching a background thread
    enabled_count = (
        db.query(LibraryRoot).filter(LibraryRoot.enabled.is_(True)).count()
    )
    if enabled_count == 0:
        return ScanStartedResponse(
            status="no_sources",
            message=(
                "No media sources configured. "
                "Add folders in Settings → Media Sources."
            ),
        )

    background_tasks.add_task(scan_video_library_background, settings)
    return ScanStartedResponse(status="started", message="Scan started in background")


@router.post("/scan/cancel", response_model=ScanStartedResponse)
def cancel_scan() -> ScanStartedResponse:
    state = get_scan_state()
    if state.status not in {"running", "cancelling"}:
        return ScanStartedResponse(status="not_running", message="No library scan is currently running.")

    request_scan_cancellation()
    return ScanStartedResponse(status="cancelling", message="Library scan cancellation requested.")


@router.get("/scan/status", response_model=ScanStatusOut)
def get_scan_status() -> ScanStatusOut:
    """Return the current scan status."""
    state = get_scan_state()
    return ScanStatusOut(
        status=state.status,
        cancellation_requested=state.cancellation_requested,
        started_at=state.started_at,
        finished_at=state.finished_at,
        scanned_files=state.scanned_files,
        detected_videos=state.detected_videos,
        existing_unchanged=state.existing_unchanged,
        probe_failed=state.probe_failed,
        ignored_non_media=state.ignored_non_media,
        ignored_excluded=state.ignored_excluded,
        thumbnails_generated=state.thumbnails_generated,
        thumbnail_errors=state.thumbnail_errors,
        thumbnail_failed=state.thumbnail_errors,
        scanned=state.scanned,
        added=state.added,
        updated=state.updated,
        removed_missing=state.removed_missing,
        errors=state.errors,
        current_file=state.current_file,
        current_root=state.current_root,
        roots_scanned=state.roots_scanned,
        total_roots=state.total_roots,
        message=state.message,
    )


@router.get("/scan/last-result", response_model=ScanStatusOut)
def get_last_scan_result() -> ScanStatusOut:
    """Return the last scan result (same as status, kept for frontend convenience)."""
    state = get_scan_state()
    return ScanStatusOut(
        status=state.status,
        cancellation_requested=state.cancellation_requested,
        started_at=state.started_at,
        finished_at=state.finished_at,
        scanned_files=state.scanned_files,
        detected_videos=state.detected_videos,
        existing_unchanged=state.existing_unchanged,
        probe_failed=state.probe_failed,
        ignored_non_media=state.ignored_non_media,
        ignored_excluded=state.ignored_excluded,
        thumbnails_generated=state.thumbnails_generated,
        thumbnail_errors=state.thumbnail_errors,
        thumbnail_failed=state.thumbnail_errors,
        scanned=state.scanned,
        added=state.added,
        updated=state.updated,
        removed_missing=state.removed_missing,
        errors=state.errors,
        current_file=state.current_file,
        current_root=state.current_root,
        roots_scanned=state.roots_scanned,
        total_roots=state.total_roots,
        message=state.message,
    )
