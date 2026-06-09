from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import LibraryRoot, Photo
from app.schemas import PhotoDetailOut
from app.services.photo_service import build_photo_placeholder_bytes, resolve_photo_original_path
from app.utils.files import guess_mime_type

router = APIRouter(prefix="/api/photos", tags=["photos"])


def _photo_or_404(db: Session, photo_id: int) -> Photo:
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return photo


def _photo_detail(photo: Photo, source_name: str | None) -> PhotoDetailOut:
    thumbnail_url = f"/api/photos/{photo.id}/thumbnail"
    preview_url = f"/api/photos/{photo.id}/original"
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


@router.get("/{photo_id}/thumbnail")
def get_photo_thumbnail(
    photo_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    photo = _photo_or_404(db, photo_id)
    if photo.thumbnail_path:
        thumbnail_file = settings.thumbnails_path / photo.thumbnail_path
        if thumbnail_file.exists() and thumbnail_file.is_file():
            return FileResponse(thumbnail_file)

    return Response(content=build_photo_placeholder_bytes(), media_type="image/png")


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

