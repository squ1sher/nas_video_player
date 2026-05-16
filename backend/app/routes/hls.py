from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Video
from app.schemas import (
    HlsGlobalStatusOut,
    HlsJobOut,
    HlsPrepareIn,
    HlsPrepareOut,
    HlsVideoStatusOut,
    PlaybackSourceOut,
)
from app.services.hls_service import (
    get_global_hls_status,
    get_hls_video_status,
    list_hls_jobs,
    resolve_hls_path,
    start_hls_prepare,
    validate_hls_quality,
    validate_segment_name,
)
from app.utils.files import safe_resolve_under_root

video_hls_router = APIRouter(prefix="/api/videos", tags=["hls"])
global_hls_router = APIRouter(prefix="/api/hls", tags=["hls"])


def _get_video_or_404(db: Session, video_id: int) -> Video:
    video = db.query(Video).filter(Video.id == video_id).first()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@video_hls_router.post("/{video_id}/hls/prepare", response_model=HlsPrepareOut, status_code=202)
def prepare_hls(
    video_id: int,
    body: HlsPrepareIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HlsPrepareOut:
    video = _get_video_or_404(db, video_id)

    try:
        source_path = safe_resolve_under_root(settings.video_library_path, video.relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Source file not found") from exc
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail="Source file not found")

    status, job_id = start_hls_prepare(
        db,
        settings,
        video=video,
        force=body.force,
        qualities=body.qualities,
    )

    if status == "already_running":
        raise HTTPException(status_code=409, detail="HLS preparation is already running for this video")
    if status == "concurrency_limit":
        raise HTTPException(status_code=409, detail="HLS preparation queue is full. Try later.")
    if status == "invalid_qualities":
        raise HTTPException(status_code=400, detail="No valid qualities for this source")
    if status == "already_completed":
        return HlsPrepareOut(status="completed", video_id=video_id, job_id=job_id)

    return HlsPrepareOut(status="started", video_id=video_id, job_id=job_id)


@video_hls_router.get("/{video_id}/hls/status", response_model=HlsVideoStatusOut)
def get_video_hls_status(
    video_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HlsVideoStatusOut:
    _get_video_or_404(db, video_id)
    return HlsVideoStatusOut(**get_hls_video_status(db, settings, video_id))


@video_hls_router.get("/{video_id}/playback-source", response_model=PlaybackSourceOut)
def get_playback_source(
    video_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlaybackSourceOut:
    video = _get_video_or_404(db, video_id)
    try:
        source_path = safe_resolve_under_root(settings.video_library_path, video.relative_path)
    except ValueError:
        return PlaybackSourceOut(
            source_type="none",
            stream_url=None,
            available_qualities=[],
            reason="Source file is missing.",
        )

    if not source_path.exists() or not source_path.is_file():
        return PlaybackSourceOut(
            source_type="none",
            stream_url=None,
            available_qualities=[],
            reason="Source file is missing.",
        )

    hls_status = get_hls_video_status(db, settings, video_id)
    if hls_status["status"] == "completed" and hls_status["master_playlist_url"]:
        qualities = ["auto"] + [q for q in hls_status["available_qualities"] if isinstance(q, str)]
        return PlaybackSourceOut(
            source_type="hls",
            stream_url=str(hls_status["master_playlist_url"]),
            available_qualities=qualities,
            reason="Using pre-generated HLS streaming variants.",
        )

    return PlaybackSourceOut(
        source_type="original",
        stream_url=f"/api/videos/{video_id}/stream",
        available_qualities=["original"],
        reason="Using original file.",
    )


@video_hls_router.get("/{video_id}/hls/master.m3u8")
def get_hls_master_playlist(
    video_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    _get_video_or_404(db, video_id)
    path = resolve_hls_path(settings, video_id, "master.m3u8")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="HLS master playlist not found")
    return FileResponse(path, media_type="application/vnd.apple.mpegurl")


@video_hls_router.get("/{video_id}/hls/{quality}/index.m3u8")
def get_hls_quality_playlist(
    video_id: int,
    quality: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    _get_video_or_404(db, video_id)
    if not validate_hls_quality(quality):
        raise HTTPException(status_code=400, detail="Invalid quality")

    path = resolve_hls_path(settings, video_id, f"{quality}/index.m3u8")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="HLS quality playlist not found")
    return FileResponse(path, media_type="application/vnd.apple.mpegurl")


@video_hls_router.get("/{video_id}/hls/{quality}/{segment_name}")
def get_hls_segment(
    video_id: int,
    quality: str,
    segment_name: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    _get_video_or_404(db, video_id)
    if not validate_hls_quality(quality):
        raise HTTPException(status_code=400, detail="Invalid quality")
    if not validate_segment_name(segment_name):
        raise HTTPException(status_code=400, detail="Invalid segment name")

    path = resolve_hls_path(settings, video_id, f"{quality}/{segment_name}")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="HLS segment not found")
    return FileResponse(path, media_type="video/mp2t")


@global_hls_router.get("/jobs", response_model=list[HlsJobOut])
def get_hls_jobs(db: Session = Depends(get_db)) -> list[HlsJobOut]:
    jobs = list_hls_jobs(db)
    return [
        HlsJobOut(
            id=job.id,
            video_id=job.video_id,
            status=job.status,
            progress_percent=job.progress_percent,
            current_quality=job.current_quality,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        for job in jobs
    ]


@global_hls_router.get("/status", response_model=HlsGlobalStatusOut)
def get_hls_status(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HlsGlobalStatusOut:
    return HlsGlobalStatusOut(**get_global_hls_status(db, settings))

