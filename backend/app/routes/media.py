from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LibraryRoot, Photo, Video
from app.schemas import MediaItemOut, MediaListQueryOut
from app.services.tag_service import get_video_tags_map
from app.utils.files import IMAGE_EXTENSIONS

router = APIRouter(prefix="/api/media", tags=["media"])


def _video_date(video: Video) -> tuple[datetime | None, str | None]:
    if video.modified_ts:
        return datetime.fromtimestamp(video.modified_ts, tz=timezone.utc), "file_modified"
    if video.indexed_at:
        return video.indexed_at, "indexed_at"
    if video.created_at:
        return video.created_at, "created_at"
    return None, None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("", response_model=MediaListQueryOut)
def list_media(
    type: Literal["video", "photo", "all"] = "all",
    search: str | None = None,
    sort: Literal["date", "file_size"] = "date",
    order: Literal["asc", "desc"] = "desc",
    media_source_id: int | None = None,
    db: Session = Depends(get_db),
) -> MediaListQueryOut:
    root_name_by_id = {root.id: root.name for root in db.query(LibraryRoot).all()}

    items: list[MediaItemOut] = []

    if type in {"video", "all"}:
        video_query = db.query(Video)
        video_query = video_query.filter(~Video.extension.in_(sorted(IMAGE_EXTENSIONS)))
        video_query = video_query.filter(
            or_(
                Video.availability_status.is_(None),
                Video.availability_status == "available",
                Video.availability_status == "missing",
            )
        )
        if media_source_id is not None:
            video_query = video_query.filter(Video.library_root_id == media_source_id)
        if search:
            video_query = video_query.filter(Video.title.ilike(f"%{search}%"))

        videos = video_query.all()
        tags_by_video = get_video_tags_map(db, [video.id for video in videos])
        for video in videos:
            video_date, date_source = _video_date(video)
            items.append(
                MediaItemOut(
                    id=video.id,
                    type="video",
                    display_title=video.title,
                    thumbnail_url=f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
                    date=_as_utc(video_date),
                    date_source=date_source,
                    file_size=video.size,
                    width=video.width,
                    height=video.height,
                    extension=video.extension,
                    duration=video.duration,
                    raw_format=False,
                    media_source_id=video.library_root_id,
                    media_source_name=root_name_by_id.get(video.library_root_id),
                    folder_path=video.folder_path,
                    tags=tags_by_video.get(video.id, []),
                )
            )

    if type in {"photo", "all"}:
        photo_query = db.query(Photo)
        if media_source_id is not None:
            photo_query = photo_query.filter(Photo.media_source_id == media_source_id)
        if search:
            photo_query = photo_query.filter(Photo.filename.ilike(f"%{search}%"))

        photos = photo_query.all()
        for photo in photos:
            items.append(
                MediaItemOut(
                    id=photo.id,
                    type="photo",
                    display_title=photo.filename,
                    thumbnail_url=f"/api/photos/{photo.id}/thumbnail",
                    date=_as_utc(photo.captured_at or photo.file_created_at or photo.file_modified_at),
                    date_source=photo.date_source,
                    file_size=photo.file_size,
                    width=photo.width,
                    height=photo.height,
                    extension=photo.extension,
                    duration=None,
                    raw_format=photo.raw_format,
                    media_source_id=photo.media_source_id,
                    media_source_name=root_name_by_id.get(photo.media_source_id),
                    folder_path="/".join(photo.relative_path.split("/")[:-1]),
                    tags=[],
                )
            )

    if sort == "file_size":
        items.sort(key=lambda item: (item.file_size, item.type, item.id), reverse=order == "desc")
    else:
        items.sort(
            key=lambda item: (
                item.date or datetime.fromtimestamp(0, tz=timezone.utc),
                item.type,
                item.id,
            ),
            reverse=order == "desc",
        )

    return MediaListQueryOut(items=items, total=len(items))

