from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MediaProfile, Video
from app.routes.videos import to_list_item
from app.schemas import (
    MediaProfileDetailOut,
    MediaProfileOut,
    MediaProfilePlaybackStatusIn,
    MediaProfileSampleVideoOut,
)
from app.services.media_profile_service import update_manual_profile_status

router = APIRouter(prefix="/api/media-profiles", tags=["media-profiles"])


def _sample_video_out(video: Video | None) -> MediaProfileSampleVideoOut | None:
    if video is None:
        return None
    return MediaProfileSampleVideoOut(
        id=video.id,
        title=video.title,
        filename=video.filename,
        relative_path=video.relative_path,
        thumbnail_url=f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
        watch_url=f"/watch/{video.id}",
    )


def _to_profile_out(db: Session, profile: MediaProfile) -> MediaProfileOut:
    files_count = db.query(func.count(Video.id)).filter(Video.media_profile_id == profile.id).scalar() or 0
    sample_id = profile.sample_video_id
    sample_video = db.query(Video).filter(Video.id == sample_id).first() if sample_id else None
    if sample_video is None:
        sample_video = (
            db.query(Video)
            .filter(Video.media_profile_id == profile.id)
            .order_by(Video.created_at.desc())
            .first()
        )
        if sample_video is not None and profile.sample_video_id is None:
            profile.sample_video_id = sample_video.id
            db.flush()

    return MediaProfileOut(
        id=profile.id,
        profile_key=profile.profile_key,
        profile_version=profile.profile_version,
        files_count=int(files_count),
        sample_video=_sample_video_out(sample_video),
        extension=profile.extension,
        container_format=profile.container_format,
        video_codec=profile.video_codec,
        video_profile=profile.video_profile,
        video_level=profile.video_level,
        pixel_format=profile.pixel_format,
        audio_codec=profile.audio_codec,
        audio_channels=profile.audio_channels,
        audio_sample_rate=profile.audio_sample_rate,
        width_bucket=profile.width_bucket,
        height_bucket=profile.height_bucket,
        auto_compatibility_status=profile.auto_compatibility_status,
        auto_compatibility_reason=profile.auto_compatibility_reason,
        manual_playback_status=profile.manual_playback_status,
        manual_playback_note=profile.manual_playback_note,
        manual_checked_at=profile.manual_checked_at,
        effective_compatibility_status=profile.effective_compatibility_status,
        compatibility_source=profile.compatibility_source,
    )


@router.get("", response_model=list[MediaProfileOut])
def list_media_profiles(db: Session = Depends(get_db)) -> list[MediaProfileOut]:
    profiles = db.query(MediaProfile).all()

    def sort_key(profile: MediaProfile) -> tuple[int, int]:
        files_count = db.query(func.count(Video.id)).filter(Video.media_profile_id == profile.id).scalar() or 0
        no_manual = 0 if profile.manual_playback_status is None else 1
        return no_manual, -int(files_count)

    ordered = sorted(profiles, key=sort_key)
    return [_to_profile_out(db, profile) for profile in ordered]


@router.get("/{profile_id}", response_model=MediaProfileDetailOut)
def get_media_profile(profile_id: int, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)) -> MediaProfileDetailOut:
    profile = db.query(MediaProfile).filter(MediaProfile.id == profile_id).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Media profile not found")

    videos = (
        db.query(Video)
        .filter(Video.media_profile_id == profile.id)
        .order_by(Video.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    out = _to_profile_out(db, profile)
    return MediaProfileDetailOut(**out.model_dump(), videos=[to_list_item(video) for video in videos])


@router.put("/{profile_id}/playback-status", response_model=MediaProfileOut)
def set_profile_playback_status(
    profile_id: int,
    body: MediaProfilePlaybackStatusIn,
    db: Session = Depends(get_db),
) -> MediaProfileOut:
    allowed = {"playable", "not_playable", "partially_playable", "unknown"}
    if body.manual_playback_status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid manual_playback_status")

    profile = db.query(MediaProfile).filter(MediaProfile.id == profile_id).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Media profile not found")

    update_manual_profile_status(
        db,
        profile,
        manual_status=body.manual_playback_status,
        manual_note=(body.manual_playback_note or "").strip() or None,
    )
    db.commit()
    db.refresh(profile)
    return _to_profile_out(db, profile)


@router.delete("/{profile_id}/playback-status", response_model=MediaProfileOut)
def clear_profile_playback_status(profile_id: int, db: Session = Depends(get_db)) -> MediaProfileOut:
    profile = db.query(MediaProfile).filter(MediaProfile.id == profile_id).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Media profile not found")

    update_manual_profile_status(db, profile, manual_status=None, manual_note=None)
    db.commit()
    db.refresh(profile)
    return _to_profile_out(db, profile)

