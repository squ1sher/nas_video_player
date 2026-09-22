from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LibraryRoot, Photo, PhotoTag, PlaylistItem, Video, VideoTag
from app.schemas import MediaGroupItemsOut, MediaGroupOut, MediaItemOut, MediaListQueryOut
from app.services.tag_service import get_video_tags_map
from app.utils.files import IMAGE_EXTENSIONS

router = APIRouter(prefix="/api/media", tags=["media"])

GIB = 1024 * 1024 * 1024
_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _video_date(video: Video) -> tuple[datetime | None, str | None]:
    if video.modified_ts:
        return datetime.fromtimestamp(video.modified_ts, tz=timezone.utc), "file_modified"
    if video.indexed_at:
        return video.indexed_at, "indexed_at"
    if video.created_at:
        return video.created_at, "created_at"
    return None, None


def _photo_date(photo: Photo) -> datetime | None:
    return photo.captured_at or photo.file_created_at or photo.file_modified_at


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _photo_folder_path(photo: Photo) -> str:
    return "/".join(photo.relative_path.split("/")[:-1])


# -- Item builders ------------------------------------------------------------


def _video_to_item(video: Video, root_name: str | None, tags: list) -> MediaItemOut:
    video_date, date_source = _video_date(video)
    return MediaItemOut(
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
        media_source_name=root_name,
        folder_path=video.folder_path,
        tags=tags,
    )


def _photo_to_item(photo: Photo, root_name: str | None) -> MediaItemOut:
    return MediaItemOut(
        id=photo.id,
        type="photo",
        display_title=photo.filename,
        thumbnail_url=f"/api/photos/{photo.id}/thumbnail",
        date=_as_utc(_photo_date(photo)),
        date_source=photo.date_source,
        file_size=photo.file_size,
        width=photo.width,
        height=photo.height,
        extension=photo.extension,
        duration=None,
        raw_format=photo.raw_format,
        media_source_id=photo.media_source_id,
        media_source_name=root_name,
        folder_path=_photo_folder_path(photo),
        tags=[],
    )


# -- Query filters ------------------------------------------------------------


def _parse_tag_ids(raw_tag_ids: str | None) -> list[int]:
    if not raw_tag_ids:
        return []
    result: list[int] = []
    for chunk in raw_tag_ids.split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if value > 0:
            result.append(value)
    return result


def _filtered_videos_query(
    db: Session,
    *,
    search: str | None,
    media_source_id: int | None,
    folder: str | None,
    playlist_id: int | None,
    tag_ids: list[int],
    tag_mode: str,
    without_tags: bool,
):
    query = db.query(Video)
    query = query.filter(~Video.extension.in_(sorted(IMAGE_EXTENSIONS)))
    query = query.filter(
        or_(
            Video.availability_status.is_(None),
            Video.availability_status == "available",
            Video.availability_status == "missing",
        )
    )
    if media_source_id is not None:
        query = query.filter(Video.library_root_id == media_source_id)
    if search:
        query = query.filter(Video.title.ilike(f"%{search}%"))
    if folder is not None:
        query = query.filter(Video.folder_path == folder)
    if playlist_id is not None:
        query = query.join(PlaylistItem, PlaylistItem.video_id == Video.id).filter(
            PlaylistItem.playlist_id == playlist_id
        )
    if without_tags:
        query = query.outerjoin(VideoTag, VideoTag.video_id == Video.id).filter(VideoTag.id.is_(None))
    elif tag_ids:
        if tag_mode == "all":
            filtered_ids = (
                db.query(VideoTag.video_id)
                .filter(VideoTag.tag_id.in_(tag_ids))
                .group_by(VideoTag.video_id)
                .having(func.count(func.distinct(VideoTag.tag_id)) == len(tag_ids))
            )
        else:
            filtered_ids = db.query(VideoTag.video_id).filter(VideoTag.tag_id.in_(tag_ids)).distinct()
        query = query.filter(Video.id.in_(filtered_ids))
    return query


def _filtered_photos_query(
    db: Session,
    *,
    search: str | None,
    media_source_id: int | None,
    tag_ids: list[int],
    tag_mode: str,
    without_tags: bool,
):
    query = db.query(Photo)
    if media_source_id is not None:
        query = query.filter(Photo.media_source_id == media_source_id)
    if search:
        query = query.filter(Photo.filename.ilike(f"%{search}%"))
    if without_tags:
        query = query.outerjoin(PhotoTag, PhotoTag.photo_id == Photo.id).filter(PhotoTag.id.is_(None))
    elif tag_ids:
        if tag_mode == "all":
            filtered_ids = (
                db.query(PhotoTag.photo_id)
                .filter(PhotoTag.tag_id.in_(tag_ids))
                .group_by(PhotoTag.photo_id)
                .having(func.count(func.distinct(PhotoTag.tag_id)) == len(tag_ids))
            )
        else:
            filtered_ids = db.query(PhotoTag.photo_id).filter(PhotoTag.tag_id.in_(tag_ids)).distinct()
        query = query.filter(Photo.id.in_(filtered_ids))
    return query


# -- Lightweight projection for grouping --------------------------------------


@dataclass
class _MediaRow:
    type: str
    id: int
    date: datetime | None
    file_size: int
    duration: float | None


def _collect_media_rows(
    db: Session,
    *,
    type: str,
    search: str | None,
    media_source_id: int | None,
    folder: str | None,
    playlist_id: int | None,
    tag_ids: list[int],
    tag_mode: str,
    without_tags: bool,
) -> list[_MediaRow]:
    rows: list[_MediaRow] = []

    if type in {"video", "all"}:
        videos = _filtered_videos_query(
            db,
            search=search,
            media_source_id=media_source_id,
            folder=folder,
            playlist_id=playlist_id,
            tag_ids=tag_ids,
            tag_mode=tag_mode,
            without_tags=without_tags,
        ).all()
        for video in videos:
            video_date, _ = _video_date(video)
            rows.append(
                _MediaRow(type="video", id=video.id, date=_as_utc(video_date), file_size=video.size, duration=video.duration)
            )

    # Playlists only contain videos; skip photos entirely when scoping to a playlist.
    if type in {"photo", "all"} and playlist_id is None:
        photos = _filtered_photos_query(
            db,
            search=search,
            media_source_id=media_source_id,
            tag_ids=tag_ids,
            tag_mode=tag_mode,
            without_tags=without_tags,
        ).all()
        for photo in photos:
            if folder is not None and _photo_folder_path(photo) != folder:
                continue
            rows.append(
                _MediaRow(type="photo", id=photo.id, date=_as_utc(_photo_date(photo)), file_size=photo.file_size, duration=None)
            )

    return rows


def _sort_rows(rows: list[_MediaRow], sort: str, order: str) -> list[_MediaRow]:
    reverse = order == "desc"
    if sort == "file_size":
        rows.sort(key=lambda r: (r.file_size, r.type, r.id), reverse=reverse)
    elif sort == "duration":
        rows.sort(key=lambda r: (r.duration or 0.0, r.type, r.id), reverse=reverse)
    else:
        rows.sort(key=lambda r: (r.date or _EPOCH, r.type, r.id), reverse=reverse)
    return rows


# -- Bucket helpers (size / duration) -----------------------------------------

_SIZE_BUCKETS = [
    ("under1gib", "Under 1 GB"),
    ("1to20gib", "1-20 GB"),
    ("20to100gib", "20-100 GB"),
    ("over100gib", "Over 100 GB"),
    ("unknown", "Unknown size"),
]

_DURATION_BUCKETS = [
    ("under3", "Under 3 minutes"),
    ("3to20", "3-20 minutes"),
    ("over20", "Over 20 minutes"),
    ("unknown", "Unknown duration"),
]


def _size_bucket(size: int | None) -> str:
    if not size or size <= 0:
        return "unknown"
    if size < GIB:
        return "under1gib"
    if size <= 20 * GIB:
        return "1to20gib"
    if size <= 100 * GIB:
        return "20to100gib"
    return "over100gib"


def _duration_bucket(duration: float | None) -> str:
    if not duration or duration <= 0:
        return "unknown"
    if duration < 3 * 60:
        return "under3"
    if duration <= 20 * 60:
        return "3to20"
    return "over20"


_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# -- Endpoints ----------------------------------------------------------------


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
        videos = _filtered_videos_query(
            db, search=search, media_source_id=media_source_id, folder=None,
            playlist_id=None, tag_ids=[], tag_mode="any", without_tags=False,
        ).all()
        tags_by_video = get_video_tags_map(db, [video.id for video in videos])
        for video in videos:
            items.append(_video_to_item(video, root_name_by_id.get(video.library_root_id), tags_by_video.get(video.id, [])))

    if type in {"photo", "all"}:
        photos = _filtered_photos_query(
            db, search=search, media_source_id=media_source_id,
            tag_ids=[], tag_mode="any", without_tags=False,
        ).all()
        for photo in photos:
            items.append(_photo_to_item(photo, root_name_by_id.get(photo.media_source_id)))

    if sort == "file_size":
        items.sort(key=lambda item: (item.file_size, item.type, item.id), reverse=order == "desc")
    else:
        items.sort(key=lambda item: (item.date or _EPOCH, item.type, item.id), reverse=order == "desc")

    return MediaListQueryOut(items=items, total=len(items))


@router.get("/groups", response_model=list[MediaGroupOut])
def list_media_groups(
    type: Literal["video", "photo", "all"] = "all",
    group_by: Literal["date", "file_size", "duration"] = "date",
    order: Literal["asc", "desc"] = "desc",
    search: str | None = None,
    tag_ids: str | None = None,
    tag_mode: Literal["any", "all"] = "any",
    without_tags: bool = False,
    media_source_id: int | None = None,
    folder: str | None = None,
    playlist_id: int | None = None,
    year: int | None = None,
    db: Session = Depends(get_db),
) -> list[MediaGroupOut]:
    parsed_tag_ids = _parse_tag_ids(tag_ids)
    rows = _collect_media_rows(
        db,
        type=type,
        search=search,
        media_source_id=media_source_id,
        folder=folder,
        playlist_id=playlist_id,
        tag_ids=parsed_tag_ids,
        tag_mode=tag_mode,
        without_tags=without_tags,
    )

    if group_by == "date":
        if year is None:
            counts: dict[str, int] = {}
            for row in rows:
                key = str(row.date.year) if row.date else "unknown"
                counts[key] = counts.get(key, 0) + 1
            known = sorted((k for k in counts if k != "unknown"), key=lambda k: int(k), reverse=order == "desc")
            ordered_keys = known + (["unknown"] if "unknown" in counts else [])
            return [
                MediaGroupOut(
                    group_key=f"date:year:{key}",
                    group_type="year",
                    label="Unknown date" if key == "unknown" else key,
                    count=counts[key],
                    children_loaded=False,
                )
                for key in ordered_keys
            ]
        counts_m: dict[int, int] = {}
        for row in rows:
            if row.date and row.date.year == year:
                counts_m[row.date.month] = counts_m.get(row.date.month, 0) + 1
        months = sorted(counts_m.keys(), reverse=order == "desc")
        return [
            MediaGroupOut(
                group_key=f"date:month:{year}-{month:02d}",
                group_type="month",
                label=f"{_MONTH_NAMES[month - 1]} {year}",
                count=counts_m[month],
                items_loaded=False,
            )
            for month in months
        ]

    bucket_defs = _SIZE_BUCKETS if group_by == "file_size" else _DURATION_BUCKETS
    counts_b: dict[str, int] = {}
    for row in rows:
        key = _size_bucket(row.file_size) if group_by == "file_size" else _duration_bucket(row.duration)
        counts_b[key] = counts_b.get(key, 0) + 1
    result: list[MediaGroupOut] = []
    for key, label in bucket_defs:
        if key not in counts_b:
            continue
        result.append(
            MediaGroupOut(
                group_key=f"{group_by}:{key}",
                group_type="bucket",
                label=label,
                count=counts_b[key],
                items_loaded=False,
            )
        )
    if order == "desc":
        result.reverse()
    return result


@router.get("/group-items", response_model=MediaGroupItemsOut)
def list_media_group_items(
    type: Literal["video", "photo", "all"] = "all",
    group_by: Literal["date", "file_size", "duration"] = "date",
    sort: Literal["date", "file_size", "duration"] = "date",
    order: Literal["asc", "desc"] = "desc",
    year: int | None = None,
    month: int | None = None,
    bucket: str | None = None,
    unknown: bool = False,
    offset: int = 0,
    limit: int = 100,
    search: str | None = None,
    tag_ids: str | None = None,
    tag_mode: Literal["any", "all"] = "any",
    without_tags: bool = False,
    media_source_id: int | None = None,
    folder: str | None = None,
    playlist_id: int | None = None,
    db: Session = Depends(get_db),
) -> MediaGroupItemsOut:
    parsed_tag_ids = _parse_tag_ids(tag_ids)
    rows = _collect_media_rows(
        db,
        type=type,
        search=search,
        media_source_id=media_source_id,
        folder=folder,
        playlist_id=playlist_id,
        tag_ids=parsed_tag_ids,
        tag_mode=tag_mode,
        without_tags=without_tags,
    )

    if group_by == "date":
        def in_group(row: _MediaRow) -> bool:
            if unknown:
                return row.date is None
            if row.date is None:
                return year is None and month is None
            if year is not None and row.date.year != year:
                return False
            if month is not None and row.date.month != month:
                return False
            return True

        rows = [row for row in rows if in_group(row)]
    else:
        target = bucket
        rows = [
            row
            for row in rows
            if (_size_bucket(row.file_size) if group_by == "file_size" else _duration_bucket(row.duration)) == target
        ]

    _sort_rows(rows, sort, order)
    total = len(rows)
    page = rows[offset : offset + limit]

    video_ids = [row.id for row in page if row.type == "video"]
    photo_ids = [row.id for row in page if row.type == "photo"]

    root_name_by_id = {root.id: root.name for root in db.query(LibraryRoot).all()}

    videos_by_id: dict[int, Video] = {}
    if video_ids:
        for video in db.query(Video).filter(Video.id.in_(video_ids)).all():
            videos_by_id[video.id] = video
    tags_by_video = get_video_tags_map(db, video_ids) if video_ids else {}

    photos_by_id: dict[int, Photo] = {}
    if photo_ids:
        for photo in db.query(Photo).filter(Photo.id.in_(photo_ids)).all():
            photos_by_id[photo.id] = photo

    items: list[MediaItemOut] = []
    for row in page:
        if row.type == "video":
            video = videos_by_id.get(row.id)
            if video is not None:
                items.append(
                    _video_to_item(video, root_name_by_id.get(video.library_root_id), tags_by_video.get(video.id, []))
                )
        else:
            photo = photos_by_id.get(row.id)
            if photo is not None:
                items.append(_photo_to_item(photo, root_name_by_id.get(photo.media_source_id)))

    return MediaGroupItemsOut(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )
