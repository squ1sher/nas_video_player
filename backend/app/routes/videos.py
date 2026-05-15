import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Video, WatchProgress
from app.schemas import VideoDetail, VideoListItem
from app.streaming import RangeError, iter_file_chunks, parse_range_header
from app.utils.files import guess_mime_type, safe_resolve_under_root

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"])

SORT_FIELDS = {
    "created_at": Video.created_at,
    "file_modified_at": Video.modified_ts,
    "indexed_at": Video.indexed_at,
    "title": Video.title,
    "duration": Video.duration,
    "size": Video.size,
}


def to_list_item(video: Video) -> VideoListItem:
    thumb_url = f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None
    return VideoListItem(
        id=video.id,
        title=video.title,
        filename=video.filename,
        extension=video.extension,
        size=video.size,
        duration=video.duration,
        width=video.width,
        height=video.height,
        video_codec=video.video_codec,
        audio_codec=video.audio_codec,
        thumbnail_url=thumb_url,
        folder_path=video.folder_path,
        compatibility_status=video.compatibility_status,
        compatibility_reason=video.compatibility_reason,
        created_at=video.created_at,
        indexed_at=video.indexed_at,
    )


def get_video_or_404(db: Session, video_id: int) -> Video:
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.get("", response_model=list[VideoListItem])
def list_videos(
    q: str | None = None,
    folder: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    db: Session = Depends(get_db),
) -> list[VideoListItem]:
    query = db.query(Video)
    if q:
        query = query.filter(Video.title.ilike(f"%{q}%"))
    if folder is not None:
        # Exact match only — no path traversal possible
        query = query.filter(Video.folder_path == folder)
    sort_field = SORT_FIELDS.get(sort, Video.created_at)
    sort_direction = desc if order.lower() == "desc" else asc
    videos = query.order_by(sort_direction(sort_field)).all()
    return [to_list_item(video) for video in videos]


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(video_id: int, db: Session = Depends(get_db)) -> VideoDetail:
    video = get_video_or_404(db, video_id)
    thumb_url = f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None
    return VideoDetail(
        id=video.id,
        title=video.title,
        filename=video.filename,
        relative_path=video.relative_path,
        extension=video.extension,
        size=video.size,
        duration=video.duration,
        width=video.width,
        height=video.height,
        video_codec=video.video_codec,
        audio_codec=video.audio_codec,
        thumbnail_url=thumb_url,
        folder_path=video.folder_path,
        compatibility_status=video.compatibility_status,
        compatibility_reason=video.compatibility_reason,
        created_at=video.created_at,
        updated_at=video.updated_at,
        indexed_at=video.indexed_at,
    )


@router.get("/{video_id}/thumbnail")
def get_thumbnail(
    video_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    video = get_video_or_404(db, video_id)
    if not video.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    thumb_path = settings.thumbnails_path / video.thumbnail_path
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file missing")

    return FileResponse(thumb_path)


@router.get("/{video_id}/download")
def download_video(
    video_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Download the original video file."""
    video = get_video_or_404(db, video_id)
    try:
        video_path = safe_resolve_under_root(settings.video_library_path, video.relative_path)
    except ValueError as exc:
        logger.warning("Path validation failed for download video id=%s: %s", video_id, exc)
        raise HTTPException(status_code=404, detail="Video file not found") from exc

    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    return FileResponse(video_path, media_type=guess_mime_type(Path(video_path)), filename=video.filename)


@router.delete("/{video_id}")
def delete_video(
    video_id: int,
    delete_file: bool = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    """Delete video from index and optionally delete source file from library."""
    video = get_video_or_404(db, video_id)

    if delete_file:
        try:
            video_path = safe_resolve_under_root(settings.video_library_path, video.relative_path)
        except ValueError as exc:
            logger.warning("Path validation failed for delete video id=%s: %s", video_id, exc)
            raise HTTPException(status_code=404, detail="Video file not found") from exc

        if video_path.exists() and video_path.is_file():
            try:
                video_path.unlink()
            except OSError as exc:
                logger.warning("Failed to delete source file video id=%s: %s", video_id, exc)
                raise HTTPException(
                    status_code=409,
                    detail="Failed to delete source file. Check mount mode and file permissions.",
                ) from exc

    # SQLite foreign keys may be disabled, so explicitly clean progress rows.
    db.query(WatchProgress).filter(WatchProgress.video_id == video_id).delete()
    db.delete(video)
    db.commit()
    return {"deleted": True}


@router.get("/{video_id}/stream")
def stream_video(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    video = get_video_or_404(db, video_id)
    try:
        video_path = safe_resolve_under_root(settings.video_library_path, video.relative_path)
    except ValueError as exc:
        logger.warning("Path validation failed for video id=%s: %s", video_id, exc)
        raise HTTPException(status_code=404, detail="Video file not found") from exc

    file_size = video_path.stat().st_size
    range_header = request.headers.get("range")
    mime_type = guess_mime_type(Path(video_path))

    if not range_header:
        logger.info("Streaming full file video_id=%s", video_id)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime_type,
        }
        return StreamingResponse(
            iter_file_chunks(video_path, 0, file_size - 1, settings.chunk_size),
            status_code=200,
            headers=headers,
            media_type=mime_type,
        )

    try:
        start, end = parse_range_header(range_header, file_size)
    except RangeError as exc:
        logger.warning("Invalid range request for video_id=%s range=%s", video_id, range_header)
        raise HTTPException(
            status_code=416,
            detail=str(exc),
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
        ) from exc

    content_length = end - start + 1
    logger.info("Streaming partial file video_id=%s range=%s-%s", video_id, start, end)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length),
        "Content-Type": mime_type,
    }
    return StreamingResponse(
        iter_file_chunks(video_path, start, end, settings.chunk_size),
        status_code=206,
        headers=headers,
        media_type=mime_type,
    )
