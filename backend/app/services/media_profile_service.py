from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.compatibility import get_compatibility
from app.models import MediaProfile, Video

PROFILE_VERSION = "v1"

_CODEC_ALIASES = {
    "h265": "hevc",
    "x265": "hevc",
    "h264": "h264",
    "avc1": "h264",
    "aac": "aac",
    "ac-3": "ac3",
    "e-ac-3": "eac3",
}

_MANUAL_TO_EFFECTIVE = {
    "playable": "direct_play",
    "not_playable": "needs_conversion",
    "partially_playable": "may_play",
    "unknown": "unknown",
}


def _norm_text(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return normalized if normalized else "unknown"


def _norm_extension(value: str | None) -> str:
    extension = _norm_text(value)
    if extension == "unknown":
        return extension
    return extension if extension.startswith(".") else f".{extension}"


def _norm_codec(value: str | None) -> str:
    codec = _norm_text(value)
    return _CODEC_ALIASES.get(codec, codec)


def _norm_container(value: str | None) -> str:
    container = _norm_text(value)
    if container == "unknown":
        return container
    parts = sorted({part.strip().lower() for part in container.split(",") if part.strip()})
    return ",".join(parts) if parts else "unknown"


def _bucket_dimension(value: int | None) -> str:
    return str(value) if value and value > 0 else "unknown"


def build_media_profile_fields(
    *,
    extension: str | None,
    container_format: str | None,
    video_codec: str | None,
    video_profile: str | None,
    video_level: str | None,
    pixel_format: str | None,
    audio_codec: str | None,
    audio_channels: int | None,
    audio_sample_rate: int | None,
    width: int | None,
    height: int | None,
) -> dict[str, str | int | None]:
    fields: dict[str, str | int | None] = {
        "extension": _norm_extension(extension),
        "container_format": _norm_container(container_format),
        "video_codec": _norm_codec(video_codec),
        "video_profile": _norm_text(video_profile),
        "video_level": _norm_text(video_level),
        "pixel_format": _norm_text(pixel_format),
        "audio_codec": _norm_codec(audio_codec),
        "audio_channels": audio_channels,
        "audio_sample_rate": audio_sample_rate,
        "width_bucket": _bucket_dimension(width),
        "height_bucket": _bucket_dimension(height),
    }
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    fields["profile_version"] = PROFILE_VERSION
    fields["profile_key"] = f"profile-{PROFILE_VERSION}-{digest}"
    return fields


def map_effective_status(
    auto_status: str,
    auto_reason: str,
    manual_status: str | None,
    manual_note: str | None,
) -> tuple[str, str, str]:
    if manual_status:
        effective = _MANUAL_TO_EFFECTIVE.get(manual_status, "unknown")
        reason = (manual_note or "Manual profile playback calibration").strip() or "Manual profile playback calibration"
        return effective, reason, "manual_profile_override"
    return auto_status, auto_reason, "auto_heuristic"


def upsert_media_profile(
    db: Session,
    profile_fields: dict[str, str | int | None],
    *,
    auto_status: str,
    auto_reason: str,
) -> MediaProfile:
    profile = db.query(MediaProfile).filter(MediaProfile.profile_key == profile_fields["profile_key"]).first()
    effective_status, _reason, source = map_effective_status(
        auto_status,
        auto_reason,
        profile.manual_playback_status if profile else None,
        profile.manual_playback_note if profile else None,
    )

    if profile is None:
        profile = MediaProfile(
            profile_key=str(profile_fields["profile_key"]),
            profile_version=str(profile_fields["profile_version"]),
            extension=str(profile_fields["extension"]),
            container_format=str(profile_fields["container_format"]),
            video_codec=str(profile_fields["video_codec"]),
            video_profile=str(profile_fields["video_profile"]),
            video_level=str(profile_fields["video_level"]),
            pixel_format=str(profile_fields["pixel_format"]),
            audio_codec=str(profile_fields["audio_codec"]),
            audio_channels=profile_fields.get("audio_channels"),
            audio_sample_rate=profile_fields.get("audio_sample_rate"),
            width_bucket=str(profile_fields["width_bucket"]),
            height_bucket=str(profile_fields["height_bucket"]),
            auto_compatibility_status=auto_status,
            auto_compatibility_reason=auto_reason,
            effective_compatibility_status=effective_status,
            compatibility_source=source,
        )
        db.add(profile)
        db.flush()
        return profile

    profile.extension = str(profile_fields["extension"])
    profile.container_format = str(profile_fields["container_format"])
    profile.video_codec = str(profile_fields["video_codec"])
    profile.video_profile = str(profile_fields["video_profile"])
    profile.video_level = str(profile_fields["video_level"])
    profile.pixel_format = str(profile_fields["pixel_format"])
    profile.audio_codec = str(profile_fields["audio_codec"])
    profile.audio_channels = profile_fields.get("audio_channels")
    profile.audio_sample_rate = profile_fields.get("audio_sample_rate")
    profile.width_bucket = str(profile_fields["width_bucket"])
    profile.height_bucket = str(profile_fields["height_bucket"])
    profile.auto_compatibility_status = auto_status
    profile.auto_compatibility_reason = auto_reason
    profile.effective_compatibility_status = effective_status
    profile.compatibility_source = source
    db.flush()
    return profile


def assign_profile_to_video(video: Video, profile: MediaProfile) -> None:
    _, reason, source = map_effective_status(
        profile.auto_compatibility_status,
        profile.auto_compatibility_reason,
        profile.manual_playback_status,
        profile.manual_playback_note,
    )
    video.media_profile_id = profile.id
    video.media_profile_key = profile.profile_key
    video.media_profile_version = profile.profile_version
    video.auto_compatibility_status = profile.auto_compatibility_status
    video.auto_compatibility_reason = profile.auto_compatibility_reason
    video.effective_compatibility_status = profile.effective_compatibility_status
    video.compatibility_source = source
    video.manual_playback_status = profile.manual_playback_status
    video.compatibility_status = profile.effective_compatibility_status
    video.compatibility_reason = reason


def apply_profile_to_all_videos(db: Session, profile: MediaProfile) -> int:
    videos = db.query(Video).filter(Video.media_profile_id == profile.id).all()
    for video in videos:
        assign_profile_to_video(video, profile)
    return len(videos)


def update_manual_profile_status(
    db: Session,
    profile: MediaProfile,
    *,
    manual_status: str | None,
    manual_note: str | None,
) -> MediaProfile:
    profile.manual_playback_status = manual_status
    profile.manual_playback_note = manual_note
    profile.manual_checked_at = datetime.now(timezone.utc) if manual_status else None

    effective_status, _reason, source = map_effective_status(
        profile.auto_compatibility_status,
        profile.auto_compatibility_reason,
        profile.manual_playback_status,
        profile.manual_playback_note,
    )
    profile.effective_compatibility_status = effective_status
    profile.compatibility_source = source
    db.flush()
    apply_profile_to_all_videos(db, profile)
    return profile


def compute_auto_compatibility(extension: str | None, video_codec: str | None, audio_codec: str | None) -> tuple[str, str]:
    compat = get_compatibility(extension or "unknown", video_codec, audio_codec)
    return compat["status"], compat["reason"]


def media_profile_stats(db: Session) -> dict[str, int]:
    total = db.query(func.count(MediaProfile.id)).scalar() or 0
    manual_checked = db.query(func.count(MediaProfile.id)).filter(MediaProfile.manual_playback_status.isnot(None)).scalar() or 0
    playable = db.query(func.count(MediaProfile.id)).filter(MediaProfile.manual_playback_status == "playable").scalar() or 0
    not_playable = db.query(func.count(MediaProfile.id)).filter(MediaProfile.manual_playback_status == "not_playable").scalar() or 0
    partially_playable = (
        db.query(func.count(MediaProfile.id)).filter(MediaProfile.manual_playback_status == "partially_playable").scalar() or 0
    )
    unknown = db.query(func.count(MediaProfile.id)).filter(MediaProfile.effective_compatibility_status == "unknown").scalar() or 0
    return {
        "media_profiles_total": int(total),
        "media_profiles_manual_checked": int(manual_checked),
        "media_profiles_pending_manual_check": int(max(0, total - manual_checked)),
        "media_profiles_playable": int(playable),
        "media_profiles_not_playable": int(not_playable),
        "media_profiles_partially_playable": int(partially_playable),
        "media_profiles_unknown": int(unknown),
    }

