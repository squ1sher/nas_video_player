"""Application settings routes – Phase 2.5: configurable Media Sources."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import LibraryRoot, Video
from app.scan_status import get_scan_state
from app.schemas import (
    LibraryRootIn,
    LibraryRootOut,
    LibraryRootUpdate,
    PathValidationRequest,
    PathValidationResult,
    ScanStartedResponse,
)
from app.services.library_root_service import bootstrap_library_roots, validate_media_source_path

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── Media Sources CRUD ─────────────────────────────────────────────────────


@router.get("/media-sources", response_model=list[LibraryRootOut])
def list_media_sources(
    db: Session = Depends(get_db),
) -> list[LibraryRootOut]:
    """Return all configured media sources."""
    if db.query(LibraryRoot).count() == 0:
        bootstrap_library_roots(db, get_settings())
    roots = (
        db.query(LibraryRoot)
        .order_by(LibraryRoot.scan_priority.asc(), LibraryRoot.name.asc())
        .all()
    )
    result = []
    for root in roots:
        video_count = db.query(Video).filter(Video.library_root_id == root.id).count()
        result.append(
            LibraryRootOut(
                id=root.id,
                name=root.name,
                path=root.path,
                media_type=root.media_type,
                enabled=root.enabled,
                recursive=root.recursive,
                scan_priority=root.scan_priority,
                last_scanned_at=root.last_scanned_at,
                last_scan_status=root.last_scan_status,
                last_error=root.last_error,
                created_at=root.created_at,
                updated_at=root.updated_at,
                video_count=video_count,
            )
        )
    return result


@router.post("/media-sources/validate", response_model=PathValidationResult)
def validate_path(
    body: PathValidationRequest,
    settings: Settings = Depends(get_settings),
) -> PathValidationResult:
    """Validate that a container path can be used as a media source."""
    return validate_media_source_path(body.path, settings)


@router.post("/media-sources", response_model=LibraryRootOut, status_code=201)
def create_media_source(
    body: LibraryRootIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryRootOut:
    """Add a new media source."""
    # Validate path
    validation = validate_media_source_path(body.path, settings)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail={"code": validation.code, "message": validation.message},
        )
    normalized_path = validation.path or body.path

    # Check for duplicate path
    existing = db.query(LibraryRoot).filter(LibraryRoot.path == normalized_path).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_path", "message": f"A media source with path '{normalized_path}' already exists."},
        )

    root = LibraryRoot(
        name=body.name,
        path=normalized_path,
        media_type=body.media_type,
        enabled=body.enabled,
        recursive=body.recursive,
        scan_priority=body.scan_priority,
    )
    db.add(root)
    db.commit()
    db.refresh(root)

    return LibraryRootOut(
        id=root.id,
        name=root.name,
        path=root.path,
        media_type=root.media_type,
        enabled=root.enabled,
        recursive=root.recursive,
        scan_priority=root.scan_priority,
        last_scanned_at=root.last_scanned_at,
        last_scan_status=root.last_scan_status,
        last_error=root.last_error,
        created_at=root.created_at,
        updated_at=root.updated_at,
        video_count=0,
    )


@router.get("/media-sources/{source_id}", response_model=LibraryRootOut)
def get_media_source(source_id: int, db: Session = Depends(get_db)) -> LibraryRootOut:
    """Get a single media source by ID."""
    root = db.query(LibraryRoot).filter(LibraryRoot.id == source_id).first()
    if not root:
        raise HTTPException(status_code=404, detail="Media source not found.")
    video_count = db.query(Video).filter(Video.library_root_id == root.id).count()
    return LibraryRootOut(
        id=root.id,
        name=root.name,
        path=root.path,
        media_type=root.media_type,
        enabled=root.enabled,
        recursive=root.recursive,
        scan_priority=root.scan_priority,
        last_scanned_at=root.last_scanned_at,
        last_scan_status=root.last_scan_status,
        last_error=root.last_error,
        created_at=root.created_at,
        updated_at=root.updated_at,
        video_count=video_count,
    )


@router.put("/media-sources/{source_id}", response_model=LibraryRootOut)
def update_media_source(
    source_id: int,
    body: LibraryRootUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryRootOut:
    """Update a media source."""
    root = db.query(LibraryRoot).filter(LibraryRoot.id == source_id).first()
    if not root:
        raise HTTPException(status_code=404, detail="Media source not found.")

    # Validate new path if provided and different
    if body.path is not None and body.path != root.path:
        validation = validate_media_source_path(body.path, settings)
        if not validation.valid:
            raise HTTPException(
                status_code=422,
                detail={"code": validation.code, "message": validation.message},
            )
        normalized_path = validation.path or body.path
        # Check duplicate path
        conflict = db.query(LibraryRoot).filter(
            LibraryRoot.path == normalized_path,
            LibraryRoot.id != source_id,
        ).first()
        if conflict:
            raise HTTPException(
                status_code=409,
                detail={"code": "duplicate_path", "message": f"Another media source already uses path '{normalized_path}'."},
            )
        root.path = normalized_path

    if body.name is not None:
        root.name = body.name
    if body.media_type is not None:
        root.media_type = body.media_type
    if body.enabled is not None:
        root.enabled = body.enabled
    if body.recursive is not None:
        root.recursive = body.recursive
    if body.scan_priority is not None:
        root.scan_priority = body.scan_priority

    db.commit()
    db.refresh(root)
    video_count = db.query(Video).filter(Video.library_root_id == root.id).count()
    return LibraryRootOut(
        id=root.id,
        name=root.name,
        path=root.path,
        media_type=root.media_type,
        enabled=root.enabled,
        recursive=root.recursive,
        scan_priority=root.scan_priority,
        last_scanned_at=root.last_scanned_at,
        last_scan_status=root.last_scan_status,
        last_error=root.last_error,
        created_at=root.created_at,
        updated_at=root.updated_at,
        video_count=video_count,
    )


@router.delete("/media-sources/{source_id}")
def delete_media_source(source_id: int, db: Session = Depends(get_db)) -> dict:
    """
    Remove a media source configuration.
    Original media files are NOT deleted.
    HLS cache is NOT deleted (use Maintenance page to clean up later).
    Videos from this source are marked source_removed and hidden from the normal library.
    """
    root = db.query(LibraryRoot).filter(LibraryRoot.id == source_id).first()
    if not root:
        raise HTTPException(status_code=404, detail="Media source not found.")

    video_count = db.query(Video).filter(Video.library_root_id == root.id).count()

    # Mark videos as source_removed and detach from root
    # They are hidden from normal library but HLS/files are preserved
    db.query(Video).filter(Video.library_root_id == root.id).update(
        {"library_root_id": None, "availability_status": "source_removed"},
        synchronize_session=False,
    )
    db.delete(root)
    db.commit()

    return {
        "deleted": True,
        "message": (
            f"Media source '{root.name}' removed. "
            f"{video_count} video(s) marked as source_removed and hidden from the library. "
            f"Original files and HLS cache are preserved. "
            f"Use Settings → Maintenance to clean up generated cache."
        ),
    }


@router.post("/media-sources/{source_id}/scan", response_model=ScanStartedResponse, status_code=202)
def scan_single_source(
    source_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ScanStartedResponse:
    """
    Start a full library scan (including this source).
    Scans all enabled sources – per-source isolation is planned for a future release.
    """
    root = db.query(LibraryRoot).filter(LibraryRoot.id == source_id).first()
    if not root:
        raise HTTPException(status_code=404, detail="Media source not found.")

    if not root.enabled:
        raise HTTPException(status_code=422, detail="Media source is disabled. Enable it first.")

    state = get_scan_state()
    if state.status in {"running", "cancelling"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "already_running", "message": "Library scan is already running."},
        )

    from app.scanner import scan_video_library_background

    background_tasks.add_task(scan_video_library_background, settings)
    return ScanStartedResponse(
        status="started",
        message=f"Scan started for all enabled sources (including '{root.name}').",
    )

