import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import asc, desc, or_
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.media_probe import probe_video
from app.models import DuplicateCandidateItem, HlsJob, LibraryRoot, MediaProfile, Video, VideoVariant, WatchProgress
from app.schemas import VideoDetail, VideoListItem
from app.services.library_root_service import resolve_video_source_path
from app.services.media_profile_service import (
    assign_profile_to_video,
    build_media_profile_fields,
    compute_auto_compatibility,
    upsert_media_profile,
)
from app.streaming import RangeError, iter_file_chunks, parse_range_header
from app.thumbnails import generate_thumbnail
from app.utils.files import guess_mime_type

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


def to_list_item(video: Video, library_root_name: str | None = None) -> VideoListItem:
    thumb_url = f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None
    file_modified_at = datetime.fromtimestamp(video.modified_ts, tz=timezone.utc) if video.modified_ts else None
    return VideoListItem(
        id=video.id,
        library_root_id=video.library_root_id,
        library_root_name=library_root_name,
        title=video.title,
        filename=video.filename,
        extension=video.extension,
        size=video.size,
        duration=video.duration,
        width=video.width,
        height=video.height,
        video_codec=video.video_codec,
        video_profile=video.video_profile,
        video_level=video.video_level,
        pixel_format=video.pixel_format,
        audio_codec=video.audio_codec,
        audio_channels=video.audio_channels,
        audio_sample_rate=video.audio_sample_rate,
        thumbnail_url=thumb_url,
        folder_path=video.folder_path,
        compatibility_status=video.compatibility_status,
        compatibility_reason=video.compatibility_reason,
        media_status=video.media_status,
        probe_status=video.probe_status,
        probe_error=video.probe_error,
        container_format=video.container_format,
        thumbnail_status=video.thumbnail_status,
        thumbnail_error=video.thumbnail_error,
        media_profile_id=video.media_profile_id,
        media_profile_key=video.media_profile_key,
        auto_compatibility_status=video.auto_compatibility_status,
        auto_compatibility_reason=video.auto_compatibility_reason,
        effective_compatibility_status=video.effective_compatibility_status,
        compatibility_source=video.compatibility_source,
        manual_playback_status=video.manual_playback_status,
        file_modified_at=file_modified_at,
        created_at=video.created_at,
        indexed_at=video.indexed_at,
    )


def to_detail(video: Video, library_root_name: str | None = None) -> VideoDetail:
    thumb_url = f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None
    file_modified_at = datetime.fromtimestamp(video.modified_ts, tz=timezone.utc) if video.modified_ts else None
    return VideoDetail(
        id=video.id,
        library_root_id=video.library_root_id,
        library_root_name=library_root_name,
        title=video.title,
        filename=video.filename,
        relative_path=video.relative_path,
        extension=video.extension,
        size=video.size,
        duration=video.duration,
        width=video.width,
        height=video.height,
        video_codec=video.video_codec,
        video_profile=video.video_profile,
        video_level=video.video_level,
        pixel_format=video.pixel_format,
        audio_codec=video.audio_codec,
        audio_channels=video.audio_channels,
        audio_sample_rate=video.audio_sample_rate,
        thumbnail_url=thumb_url,
        folder_path=video.folder_path,
        compatibility_status=video.compatibility_status,
        compatibility_reason=video.compatibility_reason,
        media_status=video.media_status,
        probe_status=video.probe_status,
        probe_error=video.probe_error,
        container_format=video.container_format,
        thumbnail_status=video.thumbnail_status,
        thumbnail_error=video.thumbnail_error,
        media_profile_id=video.media_profile_id,
        media_profile_key=video.media_profile_key,
        auto_compatibility_status=video.auto_compatibility_status,
        auto_compatibility_reason=video.auto_compatibility_reason,
        effective_compatibility_status=video.effective_compatibility_status,
        compatibility_source=video.compatibility_source,
        manual_playback_status=video.manual_playback_status,
        file_modified_at=file_modified_at,
        created_at=video.created_at,
        updated_at=video.updated_at,
        indexed_at=video.indexed_at,
    )


def get_video_or_404(db: Session, video_id: int) -> Video:
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def _library_root_name_for_video(db: Session, video: Video) -> str | None:
    if video.library_root_id is None:
        return None
    root = db.query(LibraryRoot).filter(LibraryRoot.id == video.library_root_id).first()
    return root.name if root else None


@router.get("", response_model=list[VideoListItem])
def list_videos(
    q: str | None = None,
    folder: str | None = None,
    compatibility_status: str | None = None,
    media_status: str | None = None,
    probe_status: str | None = None,
    thumbnail_status: str | None = None,
    extension: str | None = None,
    has_probe_error: bool | None = None,
    has_thumbnail: bool | None = None,
    media_profile_id: int | None = None,
    compatibility_source: str | None = None,
    effective_compatibility_status: str | None = None,
    availability_status: str | None = None,
    show_all: bool = False,
    sort: str = "created_at",
    order: str = "desc",
    db: Session = Depends(get_db),
) -> list[VideoListItem]:
    query = db.query(Video)
    # By default exclude source_removed, source_disabled, deleted from normal library view
    if not show_all and availability_status is None:
        query = query.filter(
            or_(
                Video.availability_status.is_(None),
                Video.availability_status == "available",
                Video.availability_status == "missing",
            )
        )
    elif availability_status is not None:
        query = query.filter(Video.availability_status == availability_status)
    if q:
        query = query.filter(Video.title.ilike(f"%{q}%"))
    if folder is not None:
        # Exact match only — no path traversal possible
        query = query.filter(Video.folder_path == folder)
    if compatibility_status:
        query = query.filter(Video.compatibility_status == compatibility_status)
    if media_status:
        query = query.filter(Video.media_status == media_status)
    if probe_status:
        query = query.filter(Video.probe_status == probe_status)
    if thumbnail_status:
        query = query.filter(Video.thumbnail_status == thumbnail_status)
    if extension:
        ext = extension.strip().lower()
        normalized_ext = ext if ext.startswith(".") else f".{ext}"
        query = query.filter(Video.extension == normalized_ext)
    if has_probe_error is not None:
        if has_probe_error:
            query = query.filter(Video.probe_error.isnot(None)).filter(Video.probe_error != "")
        else:
            query = query.filter((Video.probe_error.is_(None)) | (Video.probe_error == ""))
    if has_thumbnail is not None:
        if has_thumbnail:
            query = query.filter(Video.thumbnail_path.isnot(None)).filter(Video.thumbnail_path != "")
        else:
            query = query.filter((Video.thumbnail_path.is_(None)) | (Video.thumbnail_path == ""))
    if media_profile_id is not None:
        query = query.filter(Video.media_profile_id == media_profile_id)
    if compatibility_source:
        query = query.filter(Video.compatibility_source == compatibility_source)
    if effective_compatibility_status:
        query = query.filter(Video.effective_compatibility_status == effective_compatibility_status)
    sort_field = SORT_FIELDS.get(sort, Video.created_at)
    sort_direction = desc if order.lower() == "desc" else asc
    videos = query.order_by(sort_direction(sort_field)).all()
    root_name_by_id = {
        root.id: root.name
        for root in db.query(LibraryRoot).all()
    }
    return [to_list_item(video, root_name_by_id.get(video.library_root_id)) for video in videos]


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(video_id: int, db: Session = Depends(get_db)) -> VideoDetail:
    video = get_video_or_404(db, video_id)
    return to_detail(video, _library_root_name_for_video(db, video))


@router.post("/{video_id}/reprobe", response_model=VideoDetail)
def reprobe_video(
    video_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VideoDetail:
    video = get_video_or_404(db, video_id)
    video_path = resolve_video_source_path(video, settings)

    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    probe = probe_video(video_path)
    profile: MediaProfile | None = None
    if not probe.success:
        video.duration = None
        video.width = None
        video.height = None
        video.video_codec = None
        video.video_profile = None
        video.video_level = None
        video.pixel_format = None
        video.audio_codec = None
        video.audio_channels = None
        video.audio_sample_rate = None
        video.container_format = None
        video.media_status = "probe_failed_possible_video"
        video.probe_status = "failed"
        video.probe_error = probe.error
        auto_status, auto_reason = compute_auto_compatibility(video.extension, None, None)
        profile_fields = build_media_profile_fields(
            extension=video.extension,
            container_format=None,
            video_codec=None,
            video_profile=None,
            video_level=None,
            pixel_format=None,
            audio_codec=None,
            audio_channels=None,
            audio_sample_rate=None,
            width=None,
            height=None,
        )
        profile = upsert_media_profile(db, profile_fields, auto_status=auto_status, auto_reason=auto_reason)
        assign_profile_to_video(video, profile)
    elif not probe.has_video_stream:
        video.duration = probe.duration
        video.width = None
        video.height = None
        video.video_codec = None
        video.video_profile = None
        video.video_level = None
        video.pixel_format = None
        video.audio_codec = probe.audio_codec
        video.audio_channels = probe.audio_channels
        video.audio_sample_rate = probe.audio_sample_rate
        video.container_format = probe.container_format
        video.media_status = "ignored_non_media"
        video.probe_status = "success"
        video.probe_error = "No video stream detected"
        auto_status, auto_reason = compute_auto_compatibility(video.extension, None, probe.audio_codec)
        profile_fields = build_media_profile_fields(
            extension=video.extension,
            container_format=probe.container_format,
            video_codec=None,
            video_profile=None,
            video_level=None,
            pixel_format=None,
            audio_codec=probe.audio_codec,
            audio_channels=probe.audio_channels,
            audio_sample_rate=probe.audio_sample_rate,
            width=None,
            height=None,
        )
        profile = upsert_media_profile(db, profile_fields, auto_status=auto_status, auto_reason=auto_reason)
        assign_profile_to_video(video, profile)
    else:
        video.duration = probe.duration
        video.width = probe.width
        video.height = probe.height
        video.video_codec = probe.video_codec
        video.video_profile = probe.video_profile
        video.video_level = probe.video_level
        video.pixel_format = probe.pixel_format
        video.audio_codec = probe.audio_codec
        video.audio_channels = probe.audio_channels
        video.audio_sample_rate = probe.audio_sample_rate
        video.container_format = probe.container_format
        video.media_status = "detected_video"
        video.probe_status = "success"
        video.probe_error = None
        auto_status, auto_reason = compute_auto_compatibility(video.extension, probe.video_codec, probe.audio_codec)
        profile_fields = build_media_profile_fields(
            extension=video.extension,
            container_format=probe.container_format,
            video_codec=probe.video_codec,
            video_profile=probe.video_profile,
            video_level=probe.video_level,
            pixel_format=probe.pixel_format,
            audio_codec=probe.audio_codec,
            audio_channels=probe.audio_channels,
            audio_sample_rate=probe.audio_sample_rate,
            width=probe.width,
            height=probe.height,
        )
        profile = upsert_media_profile(db, profile_fields, auto_status=auto_status, auto_reason=auto_reason)
        assign_profile_to_video(video, profile)

    if profile is not None and profile.sample_video_id is None:
        profile.sample_video_id = video.id

    db.commit()
    db.refresh(video)
    return to_detail(video, _library_root_name_for_video(db, video))


@router.post("/{video_id}/thumbnail/regenerate", response_model=VideoDetail)
def regenerate_video_thumbnail(
    video_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VideoDetail:
    video = get_video_or_404(db, video_id)
    video_path = resolve_video_source_path(video, settings)

    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    result = generate_thumbnail(video_path, settings.thumbnails_path, video.relative_path, force=True)
    if result.path is not None:
        video.thumbnail_path = result.path.name
        video.thumbnail_status = "generated"
        video.thumbnail_error = None
    else:
        video.thumbnail_status = "failed"
        video.thumbnail_error = result.error or "Thumbnail generation failed"

    db.commit()
    db.refresh(video)
    return to_detail(video, _library_root_name_for_video(db, video))


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
    video_path = resolve_video_source_path(video, settings)

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
    """Delete video from index and remove source file, HLS cache, thumbnail, and related records."""
    video = get_video_or_404(db, video_id)

    if delete_file:
        video_path = resolve_video_source_path(video, settings)

        if video_path.exists() and video_path.is_file():
            try:
                video_path.unlink()
            except OSError as exc:
                logger.warning("Failed to delete source file video id=%s: %s", video_id, exc)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Failed to delete source file. "
                        "Check Docker volume mode and Synology permissions."
                    ),
                ) from exc

    # Delete HLS cache folder (best-effort; log warning on failure)
    hls_dir = settings.hls_output_path.resolve() / str(video_id)
    if hls_dir.exists() and hls_dir.is_dir():
        try:
            shutil.rmtree(hls_dir)
            logger.info("Deleted HLS cache for video_id=%s", video_id)
        except OSError as exc:
            logger.warning("Failed to delete HLS cache for video_id=%s: %s", video_id, exc)

    # Delete thumbnail file (best-effort)
    if video.thumbnail_path:
        thumb_path = settings.thumbnails_path / video.thumbnail_path
        if thumb_path.exists():
            try:
                thumb_path.unlink()
                logger.info("Deleted thumbnail for video_id=%s", video_id)
            except OSError as exc:
                logger.warning("Failed to delete thumbnail for video_id=%s: %s", video_id, exc)

    # Mark active HLS jobs as failed so background workers stop gracefully
    now = datetime.now(timezone.utc)
    active_jobs = db.query(HlsJob).filter(
        HlsJob.video_id == video_id,
        HlsJob.status.in_(["pending", "running"]),
    ).all()
    for job in active_jobs:
        job.status = "failed"
        job.error_message = "Video deleted by user."
        job.finished_at = now

    # Explicitly delete related records (SQLite FK enforcement may be disabled)
    db.query(WatchProgress).filter(WatchProgress.video_id == video_id).delete()
    db.query(VideoVariant).filter(VideoVariant.video_id == video_id).delete()
    db.query(DuplicateCandidateItem).filter(DuplicateCandidateItem.video_id == video_id).delete()

    db.flush()
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
    video_path = resolve_video_source_path(video, settings)

    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

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
