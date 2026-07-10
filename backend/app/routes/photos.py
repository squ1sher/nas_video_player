from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import LibraryRoot, Photo
from app.schemas import (
    PhotoDetailOut,
    PhotoPrepareMissingIn,
    PhotoPrepareSelectedIn,
    PhotoPrepareStartOut,
    PhotoPrepareStatusOut,
    PhotoPrepareSummaryOut,
)
from app.services.photo_prepare_service import (
    cancel_prepare_job,
    get_prepare_status,
    get_prepare_summary,
    start_prepare_missing,
    start_prepare_selected,
)
from app.services.photo_service import (
    build_photo_placeholder_bytes,
    generate_photo_preview,
    generate_photo_thumbnail,
    generate_raw_preview,
    generate_raw_thumbnail,
    resolve_photo_original_path,
)
from app.utils.files import guess_mime_type, is_raw_photo_file

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.get("/prepare/status", response_model=PhotoPrepareStatusOut)
def get_photo_prepare_status(db: Session = Depends(get_db)) -> PhotoPrepareStatusOut:
    return PhotoPrepareStatusOut(**get_prepare_status(db))


@router.get("/prepare/summary", response_model=PhotoPrepareSummaryOut)
def get_photo_prepare_summary(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PhotoPrepareSummaryOut:
    return PhotoPrepareSummaryOut(**get_prepare_summary(db, settings))


@router.post("/prepare/missing", response_model=PhotoPrepareStartOut, status_code=202)
def prepare_missing_photos(
    body: PhotoPrepareMissingIn | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PhotoPrepareStartOut:
    body = body or PhotoPrepareMissingIn()
    return PhotoPrepareStartOut(
        **start_prepare_missing(
            db,
            settings,
            include_failed=body.include_failed,
            include_raw_placeholders=body.include_raw_placeholders,
        )
    )


@router.post("/prepare/selected", response_model=PhotoPrepareStartOut, status_code=202)
def prepare_selected_photos(
    body: PhotoPrepareSelectedIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PhotoPrepareStartOut:
    return PhotoPrepareStartOut(**start_prepare_selected(db, settings, photo_ids=body.photo_ids, force=body.force))


@router.post("/prepare/cancel", response_model=PhotoPrepareStartOut)
def cancel_photo_prepare(db: Session = Depends(get_db)) -> PhotoPrepareStartOut:
    return PhotoPrepareStartOut(**cancel_prepare_job(db))


def _photo_or_404(db: Session, photo_id: int) -> Photo:
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


def _photo_detail(photo: Photo, source_name: str | None) -> PhotoDetailOut:
    thumbnail_url = f"/api/photos/{photo.id}/thumbnail"
    preview_url = f"/api/photos/{photo.id}/preview"
    return PhotoDetailOut(
        id=photo.id,
        media_source_id=photo.media_source_id,
        media_source_name=source_name,
        relative_path=photo.relative_path,
        internal_path=photo.internal_path,
        display_path=photo.display_path,
        filename=photo.filename,
        extension=photo.extension,
        file_size=photo.file_size,
        file_created_at=photo.file_created_at,
        file_modified_at=photo.file_modified_at,
        captured_at=photo.captured_at,
        date_source=photo.date_source,
        width=photo.width,
        height=photo.height,
        orientation=photo.orientation,
        camera_make=photo.camera_make,
        camera_model=photo.camera_model,
        lens_model=photo.lens_model,
        iso=photo.iso,
        exposure_time=photo.exposure_time,
        aperture=photo.aperture,
        focal_length=photo.focal_length,
        thumbnail_url=thumbnail_url,
        preview_url=preview_url,
        media_identity=photo.media_identity,
        raw_format=photo.raw_format,
        scan_status=photo.scan_status,
        thumbnail_status=photo.thumbnail_status,
        thumbnail_error=photo.thumbnail_error,
        preview_status=photo.preview_status,
        preview_error=photo.preview_error,
        prepare_status=photo.prepare_status,
        prepare_error=photo.prepare_error,
        prepared_at=photo.prepared_at,
        scan_error=photo.scan_error,
        created_at=photo.created_at,
        updated_at=photo.updated_at,
    )


@router.get("/{photo_id}", response_model=PhotoDetailOut)
def get_photo(photo_id: int, db: Session = Depends(get_db)) -> PhotoDetailOut:
    photo = _photo_or_404(db, photo_id)
    source_name: str | None = None
    if photo.media_source_id is not None:
        root = db.query(LibraryRoot).filter(LibraryRoot.id == photo.media_source_id).first()
        source_name = root.name if root else None
    return _photo_detail(photo, source_name)


def _prepared_thumbnail_file(photo: Photo, settings: Settings) -> Path | None:
    """Return a valid prepared thumbnail file path if it exists."""
    if photo.thumbnail_path:
        thumbnail_file = settings.thumbnails_path / photo.thumbnail_path
        if thumbnail_file.exists() and thumbnail_file.is_file():
            return thumbnail_file
    return None


def _prepared_preview_file(photo: Photo, settings: Settings) -> Path | None:
    """Return a valid prepared preview file path if it exists."""
    if photo.preview_path:
        preview_file = settings.thumbnails_path / photo.preview_path
        if preview_file.exists() and preview_file.is_file():
            return preview_file
    return _prepared_thumbnail_file(photo, settings)


def _ensure_raw_photo_derivatives(
    db: Session,
    photo: Photo,
    settings: Settings,
    *,
    need_thumbnail: bool = False,
    need_preview: bool = False,
) -> None:
    if not (photo.raw_format or is_raw_photo_file(Path(photo.internal_path))):
        return

    photo_path = resolve_photo_original_path(photo)
    if not photo_path.exists() or not photo_path.is_file():
        return

    updated = False

    if need_thumbnail and not _prepared_thumbnail_file(photo, settings):
        thumb_result = generate_raw_thumbnail(photo_path, settings.thumbnails_path, photo.id)
        if thumb_result.path is not None:
            photo.thumbnail_path = str(thumb_result.path.relative_to(settings.thumbnails_path).as_posix())
            photo.thumbnail_status = "ready"
            photo.thumbnail_error = None
            updated = True

    if need_preview and not _prepared_preview_file(photo, settings):
        preview_result = generate_raw_preview(photo_path, settings.thumbnails_path, photo.id)
        if preview_result.path is not None:
            photo.preview_path = str(preview_result.path.relative_to(settings.thumbnails_path).as_posix())
            photo.preview_status = "ready"
            photo.preview_error = None
            updated = True

    if updated:
        if _prepared_thumbnail_file(photo, settings) and _prepared_preview_file(photo, settings):
            photo.prepare_status = "ready"
            photo.prepare_error = None
            photo.prepared_at = datetime.now(timezone.utc)
        else:
            photo.prepare_status = "placeholder"
            photo.prepare_error = None
        db.commit()


@router.get("/{photo_id}/thumbnail")
def get_photo_thumbnail(
    photo_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    photo = _photo_or_404(db, photo_id)
    thumbnail_file = _prepared_thumbnail_file(photo, settings)
    if thumbnail_file is None and photo.raw_format:
        _ensure_raw_photo_derivatives(db, photo, settings, need_thumbnail=True)
        thumbnail_file = _prepared_thumbnail_file(photo, settings)
    if thumbnail_file is not None:
        return FileResponse(thumbnail_file)

    return Response(
        content=build_photo_placeholder_bytes(raw=bool(photo.raw_format)),
        media_type="image/png",
    )


@router.get("/{photo_id}/preview")
def get_photo_preview(
    photo_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Return photo preview image.
    For browser-supported formats (JPG, PNG, WebP), returns generated preview.
    For RAW formats (ARW, CR2, NEF), returns embedded preview or converted JPEG.
    Falls back to a visible placeholder when preparation has not run yet or failed.
    """
    photo = _photo_or_404(db, photo_id)
    preview_file = _prepared_preview_file(photo, settings)
    if preview_file is None and photo.raw_format:
        _ensure_raw_photo_derivatives(db, photo, settings, need_preview=True)
        preview_file = _prepared_preview_file(photo, settings)
    if preview_file is not None:
        return FileResponse(preview_file)

    return Response(
        content=build_photo_placeholder_bytes(raw=bool(photo.raw_format)),
        media_type="image/png",
    )


@router.get("/{photo_id}/original")
def get_photo_original(
    photo_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    photo = _photo_or_404(db, photo_id)
    photo_path = resolve_photo_original_path(photo)

    if not photo_path.exists() or not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Photo file not found")

    return FileResponse(
        photo_path,
        media_type=guess_mime_type(Path(photo_path)),
        filename=photo.filename,
    )


@router.post("/repair-thumbnails")
def repair_photo_thumbnails(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Repair/regenerate missing or failed photo thumbnails.
    Attempts to generate thumbnails for photos that lack them or have failed status.
    Supports both regular photos and RAW formats.

    Returns summary of repair work performed.
    """
    import json

    photos_to_repair = db.query(Photo).filter(
        (Photo.thumbnail_status.in_(["failed", "skipped", "pending"])) | (Photo.thumbnail_path.is_(None))
    ).all()

    repaired = 0
    still_failed = 0
    errors: list[str] = []

    for photo in photos_to_repair:
        try:
            photo_path = resolve_photo_original_path(photo)
            if not photo_path.exists():
                photo.thumbnail_status = "failed"
                photo.thumbnail_error = "Source file not found"
                still_failed += 1
                continue

            # Try RAW first if it's a raw format
            if photo.raw_format or is_raw_photo_file(photo_path):
                result = generate_raw_thumbnail(photo_path, settings.thumbnails_path, photo.id)
                preview_result = generate_raw_preview(photo_path, settings.thumbnails_path, photo.id)
            else:
                result = generate_photo_thumbnail(photo_path, settings.thumbnails_path, photo.id)
                preview_result = generate_photo_preview(photo_path, settings.thumbnails_path, photo.id)

            if preview_result.path is not None:
                photo.preview_path = str(preview_result.path.relative_to(settings.thumbnails_path).as_posix())

            if result.path is not None:
                photo.thumbnail_path = str(result.path.relative_to(settings.thumbnails_path).as_posix())
                photo.thumbnail_status = "generated"
                photo.thumbnail_error = None
                repaired += 1
            else:
                photo.thumbnail_status = "failed"
                photo.thumbnail_error = result.error or "Thumbnail generation failed"
                still_failed += 1
                errors.append(f"Photo {photo.id}: {result.error}")
        except Exception as exc:  # noqa: BLE001
            photo.thumbnail_status = "failed"
            photo.thumbnail_error = str(exc)
            still_failed += 1
            errors.append(f"Photo {photo.id}: {exc}")

    db.commit()

    result_data = {
        "repaired": repaired,
        "still_failed": still_failed,
        "total_processed": len(photos_to_repair),
        "status": "completed",
        "errors": errors,
    }
    return Response(content=json.dumps(result_data), media_type="application/json")
