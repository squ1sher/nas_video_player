from __future__ import annotations

import math
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
import app.database as db_module
from app.models import HlsBatch, HlsBatchItem, HlsJob, Video, VideoVariant
from app.services.library_root_service import resolve_video_source_path
from app.services.hls_reconciliation_service import (
    collect_hls_diagnostics,
    has_valid_hls,
    inspect_video_hls,
    reconcile_all_hls,
    reconcile_video_hls,
)

ALLOWED_QUALITIES = ("480p", "720p", "1080p")
# Keep legacy quality labels valid for playback, but only generate 480p for new jobs.
GENERATION_QUALITIES = ("480p",)
DEFAULT_GENERATION_QUALITIES = GENERATION_QUALITIES
QUALITY_PROFILES: dict[str, dict[str, int]] = {
    "480p": {"height": 480, "video_bitrate": 1_200_000, "audio_bitrate": 96_000},
    "720p": {"height": 720, "video_bitrate": 2_500_000, "audio_bitrate": 128_000},
    "1080p": {"height": 1080, "video_bitrate": 5_000_000, "audio_bitrate": 160_000},
}
SEGMENT_RE = re.compile(r"^segment_\d{3,6}\.ts$")

_settings = get_settings()
_hls_semaphore = threading.BoundedSemaphore(max(1, _settings.max_concurrent_hls_jobs))
_batch_worker_lock = threading.Lock()
_batch_worker_started = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_output_root(settings: Settings) -> Path:
    root = settings.hls_output_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _video_output_dir(settings: Settings, video_id: int) -> Path:
    root = _resolve_output_root(settings)
    out = (root / str(video_id)).resolve()
    out.relative_to(root)
    return out


def _playlist_stream_url(video_id: int, quality: str) -> str:
    return f"/api/videos/{video_id}/hls/{quality}/index.m3u8"


def _master_stream_url(video_id: int) -> str:
    return f"/api/videos/{video_id}/hls/master.m3u8"


def _normalize_qualities(requested: list[str] | None, source_height: int | None) -> list[str]:
    raw = requested if requested else list(DEFAULT_GENERATION_QUALITIES)
    deduped = [q for q in GENERATION_QUALITIES if q in raw]
    if source_height and source_height > 0:
        deduped = [q for q in deduped if QUALITY_PROFILES[q]["height"] <= source_height]
    return deduped


def _upsert_variant(
    db: Session,
    *,
    video_id: int,
    variant_type: str,
    status: str,
    quality_label: str | None = None,
) -> VideoVariant:
    variant = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video_id)
        .filter(VideoVariant.variant_type == variant_type)
        .first()
    )
    if variant is None:
        variant = VideoVariant(
            video_id=video_id,
            variant_type=variant_type,
            status=status,
            quality_label=quality_label,
        )
        db.add(variant)
        db.flush()
        return variant

    variant.status = status
    variant.quality_label = quality_label
    return variant


def _variant_type_for_quality(quality: str) -> str:
    return f"hls_{quality}"


def _compute_output_resolution(source_width: int | None, source_height: int | None, target_height: int) -> tuple[int, int]:
    if not source_width or not source_height or source_height <= 0 or source_width <= 0:
        # Conservative default that still keeps even width.
        if target_height == 480:
            return 854, 480
        if target_height == 720:
            return 1280, 720
        return 1920, 1080

    raw_width = source_width * (target_height / source_height)
    even_width = max(2, int(math.floor(raw_width / 2) * 2))
    return even_width, target_height


def _run_ffmpeg_quality(
    *,
    input_path: Path,
    quality: str,
    quality_dir: Path,
    settings: Settings,
) -> tuple[bool, str | None]:
    profile = QUALITY_PROFILES[quality]
    quality_dir.mkdir(parents=True, exist_ok=True)
    output_playlist = quality_dir / "index.m3u8"
    segment_pattern = quality_dir / "segment_%03d.ts"

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        settings.hls_ffmpeg_preset,
        "-crf",
        str(settings.hls_crf),
        "-vf",
        f"scale=-2:{profile['height']}",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        f"{int(profile['audio_bitrate'] / 1000)}k",
        "-maxrate",
        f"{int(profile['video_bitrate'] / 1000)}k",
        "-bufsize",
        f"{int(profile['video_bitrate'] / 500)}k",
        "-hls_time",
        str(settings.hls_segment_seconds),
        "-hls_playlist_type",
        "vod",
        "-hls_segment_filename",
        str(segment_pattern),
        str(output_playlist),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "ffmpeg failed").strip()[:4000]
    return True, None


def _write_master_playlist(video_id: int, out_dir: Path, variants: list[VideoVariant]) -> Path:
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for variant in variants:
        if not variant.quality_label or variant.status != "completed":
            continue
        profile = QUALITY_PROFILES[variant.quality_label]
        width = variant.width or 1280
        height = variant.height or profile["height"]
        bandwidth = profile["video_bitrate"] + profile["audio_bitrate"]
        lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={width}x{height}")
        lines.append(f"{variant.quality_label}/index.m3u8")

    master_path = out_dir / "master.m3u8"
    master_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return master_path


def _job_status_for_video(db: Session, video_id: int) -> HlsJob | None:
    return (
        db.query(HlsJob)
        .filter(HlsJob.video_id == video_id)
        .order_by(HlsJob.created_at.desc())
        .first()
    )


def has_completed_hls(db: Session, video_id: int) -> bool:
    master = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video_id)
        .filter(VideoVariant.variant_type == "hls_master")
        .filter(VideoVariant.status == "completed")
        .first()
    )
    return master is not None


def _completed_quality_labels(db: Session, video_id: int) -> list[str]:
    labels = [
        row[0]
        for row in (
            db.query(VideoVariant.quality_label)
            .filter(VideoVariant.video_id == video_id)
            .filter(VideoVariant.status == "completed")
            .filter(VideoVariant.quality_label.in_(list(ALLOWED_QUALITIES)))
            .all()
        )
        if row[0] in ALLOWED_QUALITIES
    ]
    return sorted(set(labels), key=lambda label: ALLOWED_QUALITIES.index(label))


def _has_hls_files_for_video(settings: Settings, video_id: int, completed_qualities: list[str]) -> bool:
    if not completed_qualities:
        return False
    out_dir = _video_output_dir(settings, video_id)
    if not (out_dir / "master.m3u8").is_file():
        return False
    return all((out_dir / quality / "index.m3u8").is_file() for quality in completed_qualities)


def has_completed_hls_consistent(db: Session, settings: Settings, video_id: int) -> bool:
    return has_valid_hls(settings, video_id)


def reconcile_hls_variants_for_video(db: Session, settings: Settings, video_id: int) -> bool:
    video = db.query(Video).filter(Video.id == video_id).first()
    if video is None:
        return False
    result = reconcile_video_hls(db, settings, video)
    return bool(result.get("stale_completed_invalidated", 0) or result.get("db_repaired_to_completed", 0))


def get_hls_video_status(db: Session, settings: Settings, video_id: int) -> dict[str, object]:
    job = _job_status_for_video(db, video_id)
    variants = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video_id)
        .all()
    )
    available = sorted(
        {
            variant.quality_label
            for variant in variants
            if variant.quality_label in ALLOWED_QUALITIES and variant.status == "completed"
        },
        key=lambda label: ALLOWED_QUALITIES.index(label),
    )

    inspected = inspect_video_hls(settings, video_id)
    valid = bool(inspected["has_valid_hls"])
    if valid and not available:
        available = [q for q in inspected.get("valid_qualities", []) if q in ALLOWED_QUALITIES]
    master_url = _master_stream_url(video_id) if valid and available else None

    status = "idle"
    progress = None
    current_quality = None
    error_message = None
    if job is not None and job.status in {"pending", "running"}:
        status = job.status
        progress = job.progress_percent
        current_quality = job.current_quality
        error_message = job.error_message
    elif valid and available:
        status = "completed"

    return {
        "video_id": video_id,
        "status": status,
        "progress_percent": progress,
        "current_quality": current_quality,
        "available_qualities": available,
        "master_playlist_url": master_url,
        "error_message": error_message,
    }


def get_global_hls_status(db: Session, settings: Settings) -> dict[str, int]:
    running = db.query(HlsJob).filter(HlsJob.status == "running").count()
    queued = db.query(HlsJob).filter(HlsJob.status == "pending").count()
    recent_failed = db.query(HlsJob).filter(HlsJob.status == "failed").count()
    recent_completed = db.query(HlsJob).filter(HlsJob.status == "completed").count()
    active_batch = _active_batch(db)
    return {
        "running": int(running),
        "max_concurrent": int(max(1, settings.max_concurrent_hls_jobs)),
        "queued_jobs": int(queued),
        "active_batch_id": active_batch.id if active_batch else None,
        "active_batch_status": active_batch.status if active_batch else None,
        "active_batch_progress_percent": float(active_batch.progress_percent) if active_batch else None,
        "recent_failed": int(recent_failed),
        "recent_completed": int(recent_completed),
    }


def list_hls_jobs(db: Session, limit: int = 50) -> list[HlsJob]:
    return db.query(HlsJob).order_by(HlsJob.created_at.desc()).limit(limit).all()


def _csv_qualities(qualities: list[str]) -> str:
    return ",".join(qualities)


def _parse_qualities_csv(value: str) -> list[str]:
    parsed = [q.strip() for q in value.split(",") if q.strip()]
    normalized = [q for q in GENERATION_QUALITIES if q in parsed]
    return normalized if normalized else list(DEFAULT_GENERATION_QUALITIES)


def _is_video_queued_or_running(db: Session, video_id: int) -> bool:
    queued_item = (
        db.query(HlsBatchItem)
        .join(HlsBatch, HlsBatch.id == HlsBatchItem.batch_id)
        .filter(HlsBatchItem.video_id == video_id)
        .filter(HlsBatchItem.status.in_(["queued", "running"]))
        .filter(HlsBatch.status.in_(["queued", "running"]))
        .first()
    )
    if queued_item is not None:
        return True
    running_job = (
        db.query(HlsJob)
        .filter(HlsJob.video_id == video_id)
        .filter(HlsJob.status.in_(["pending", "running"]))
        .first()
    )
    return running_job is not None


def _is_video_eligible(video: Video) -> bool:
    if video.media_status in {"ignored_non_media", "ignored_excluded"}:
        return False
    return True


def _refresh_batch_counts(db: Session, batch: HlsBatch) -> None:
    total = db.query(HlsBatchItem).filter(HlsBatchItem.batch_id == batch.id).count()
    queued = db.query(HlsBatchItem).filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "queued").count()
    running = db.query(HlsBatchItem).filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "running").count()
    completed = db.query(HlsBatchItem).filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "completed").count()
    failed = db.query(HlsBatchItem).filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "failed").count()
    skipped = db.query(HlsBatchItem).filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "skipped").count()

    batch.total_count = int(total)
    batch.queued_count = int(queued)
    batch.running_count = int(running)
    batch.completed_count = int(completed)
    batch.failed_count = int(failed)
    batch.skipped_count = int(skipped)
    done = completed + failed + skipped
    batch.progress_percent = float((done / total) * 100.0) if total > 0 else 0.0


def _finalize_batch_status(db: Session, batch: HlsBatch) -> None:
    _refresh_batch_counts(db, batch)
    if batch.queued_count > 0 or batch.running_count > 0:
        return
    if batch.status == "cancelled":
        if batch.finished_at is None:
            batch.finished_at = _utcnow()
        return
    if batch.failed_count > 0:
        batch.status = "completed_with_errors"
    else:
        batch.status = "completed"
    batch.finished_at = _utcnow()


def cancel_hls_batch(db: Session, batch_id: int) -> bool:
    batch = db.query(HlsBatch).filter(HlsBatch.id == batch_id).first()
    if batch is None:
        return False

    if batch.status not in {"queued", "running"}:
        return True

    now = _utcnow()
    batch.status = "cancelled"
    batch.error_message = "Cancelled by user"
    batch.finished_at = now

    queued_items = (
        db.query(HlsBatchItem)
        .filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "queued")
        .all()
    )
    for item in queued_items:
        item.status = "skipped"
        item.skip_reason = "cancelled_by_user"
        item.finished_at = now

    _refresh_batch_counts(db, batch)
    db.commit()
    return True


def create_library_batch(
    db: Session,
    settings: Settings,
    *,
    qualities: list[str] | None,
    skip_existing: bool,
    force: bool,
    only_missing_hls: bool,
) -> dict[str, object]:
    normalized_qualities = _normalize_qualities(qualities, None)
    if not normalized_qualities:
        normalized_qualities = list(DEFAULT_GENERATION_QUALITIES)

    all_videos = db.query(Video).order_by(Video.id.asc()).all()
    total_library_videos = len(all_videos)

    queued_videos: list[Video] = []
    repaired_stale_hls = 0
    skipped_existing_hls = 0
    skipped_already_queued = 0
    skipped_missing_source = 0
    skipped_invalid = 0
    skipped_items: list[tuple[int | None, str]] = []

    for video in all_videos:
        if not _is_video_eligible(video):
            skipped_invalid += 1
            skipped_items.append((video.id, "not_video"))
            continue

        if reconcile_hls_variants_for_video(db, settings, video.id):
            repaired_stale_hls += 1

        resolved = resolve_video_source_path(video, settings)

        if not resolved.exists() or not resolved.is_file():
            skipped_missing_source += 1
            skipped_items.append((video.id, "source_file_missing"))
            continue

        if (skip_existing or only_missing_hls) and not force and has_completed_hls_consistent(db, settings, video.id):
            skipped_existing_hls += 1
            skipped_items.append((video.id, "hls_already_exists"))
            continue

        if _is_video_queued_or_running(db, video.id):
            skipped_already_queued += 1
            skipped_items.append((video.id, "already_queued"))
            continue

        if not _normalize_qualities(normalized_qualities, video.height if video.height and video.height > 0 else None):
            skipped_invalid += 1
            skipped_items.append((video.id, "invalid_metadata"))
            continue

        queued_videos.append(video)

    if not queued_videos:
        if repaired_stale_hls > 0:
            db.commit()
        reasons: list[str] = []
        if skipped_existing_hls > 0:
            reasons.append(f"existing_hls={skipped_existing_hls}")
        if skipped_already_queued > 0:
            reasons.append(f"already_queued={skipped_already_queued}")
        if skipped_missing_source > 0:
            reasons.append(f"missing_source={skipped_missing_source}")
        if skipped_invalid > 0:
            reasons.append(f"invalid={skipped_invalid}")
        if not reasons:
            reasons.append("no_eligible_videos")

        return {
            "batch_id": None,
            "status": "nothing_to_do",
            "total_library_videos": total_library_videos,
            "queued_count": 0,
            "skipped_existing_hls": skipped_existing_hls,
            "skipped_already_queued": skipped_already_queued,
            "skipped_missing_source": skipped_missing_source,
            "skipped_invalid": skipped_invalid,
            "message": (
                f"No videos queued for HLS ({', '.join(reasons)}). "
                f"Auto-repaired stale HLS flags: {repaired_stale_hls}."
            ),
        }

    batch = HlsBatch(
        status="queued",
        request_type="library",
        qualities_csv=_csv_qualities(normalized_qualities),
        skip_existing=skip_existing,
        force=force,
        only_missing_hls=only_missing_hls,
        total_count=0,
        queued_count=0,
        running_count=0,
        completed_count=0,
        failed_count=0,
        skipped_count=0,
        progress_percent=0.0,
    )
    db.add(batch)
    db.flush()

    for video in queued_videos:
        db.add(HlsBatchItem(batch_id=batch.id, video_id=video.id, status="queued"))
    for video_id, reason in skipped_items:
        db.add(HlsBatchItem(batch_id=batch.id, video_id=video_id, status="skipped", skip_reason=reason))

    _refresh_batch_counts(db, batch)
    db.commit()

    ensure_batch_worker_started()

    return {
        "batch_id": batch.id,
        "status": "queued",
        "total_library_videos": total_library_videos,
        "queued_count": len(queued_videos),
        "skipped_existing_hls": skipped_existing_hls,
        "skipped_already_queued": skipped_already_queued,
        "skipped_missing_source": skipped_missing_source,
        "skipped_invalid": skipped_invalid,
        "message": f"Library HLS preparation batch queued. Auto-repaired stale HLS flags: {repaired_stale_hls}.",
    }


def _active_batch(db: Session) -> HlsBatch | None:
    return (
        db.query(HlsBatch)
        .filter(HlsBatch.status.in_(["queued", "running"]))
        .order_by(HlsBatch.id.asc())
        .first()
    )


def get_hls_batch_detail(
    db: Session,
    batch_id: int,
    *,
    include_items: bool,
    item_status: str | None,
    limit: int,
    offset: int,
) -> dict[str, object] | None:
    batch = db.query(HlsBatch).filter(HlsBatch.id == batch_id).first()
    if batch is None:
        return None

    _refresh_batch_counts(db, batch)
    db.flush()

    running_item = (
        db.query(HlsBatchItem)
        .filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "running")
        .order_by(HlsBatchItem.id.asc())
        .first()
    )
    current_video = None
    if running_item and running_item.video_id is not None:
        video = db.query(Video).filter(Video.id == running_item.video_id).first()
        if video is not None:
            current_video = {
                "id": video.id,
                "title": video.title,
                "relative_path": video.relative_path,
            }

    response: dict[str, object] = {
        "id": batch.id,
        "status": batch.status,
        "total_count": batch.total_count,
        "queued_count": batch.queued_count,
        "running_count": batch.running_count,
        "completed_count": batch.completed_count,
        "failed_count": batch.failed_count,
        "skipped_count": batch.skipped_count,
        "progress_percent": batch.progress_percent,
        "estimated_remaining_count": int(batch.queued_count + batch.running_count),
        "current_video": current_video,
        "started_at": batch.started_at,
        "finished_at": batch.finished_at,
        "items": [],
    }

    if include_items:
        query = db.query(HlsBatchItem).filter(HlsBatchItem.batch_id == batch.id)
        if item_status:
            query = query.filter(HlsBatchItem.status == item_status)
        items = query.order_by(HlsBatchItem.id.asc()).offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
        response["items"] = [
            {
                "id": item.id,
                "batch_id": item.batch_id,
                "video_id": item.video_id,
                "status": item.status,
                "skip_reason": item.skip_reason,
                "error_message": item.error_message,
                "hls_job_id": item.hls_job_id,
                "current_quality": item.current_quality,
                "progress_percent": item.progress_percent,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
            }
            for item in items
        ]
    return response


def recover_hls_runtime_state() -> None:
    db = db_module.SessionLocal()
    try:
        for job in db.query(HlsJob).filter(HlsJob.status.in_(["pending", "running"])).all():
            job.status = "failed"
            job.error_message = "Interrupted by application restart."
            job.finished_at = _utcnow()

        for item in db.query(HlsBatchItem).filter(HlsBatchItem.status.in_(["queued", "running"])).all():
            item.status = "failed"
            item.error_message = "Interrupted by application restart."
            item.finished_at = _utcnow()

        for batch in db.query(HlsBatch).filter(HlsBatch.status.in_(["queued", "running"])).all():
            batch.status = "completed_with_errors"
            batch.error_message = "Interrupted by application restart."
            batch.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)

        db.commit()
    finally:
        db.close()


def _poll_job_until_finished(item_id: int, job_id: int) -> tuple[str, str | None]:
    while True:
        db = db_module.SessionLocal()
        try:
            item = db.query(HlsBatchItem).filter(HlsBatchItem.id == item_id).first()
            job = db.query(HlsJob).filter(HlsJob.id == job_id).first()
            if item is None or job is None:
                return "failed", "Batch item or HLS job not found"

            item.progress_percent = job.progress_percent
            item.current_quality = job.current_quality
            db.commit()

            if job.status in {"completed", "failed", "cancelled"}:
                if job.status == "completed":
                    return "completed", None
                return "failed", job.error_message or "HLS job failed"
        finally:
            db.close()
        time.sleep(0.4)


def _process_batch_item(batch_id: int, item_id: int) -> None:
    settings = get_settings()
    db = db_module.SessionLocal()
    try:
        batch = db.query(HlsBatch).filter(HlsBatch.id == batch_id).first()
        item = db.query(HlsBatchItem).filter(HlsBatchItem.id == item_id).first()
        if batch is None or item is None:
            return
        if batch.status == "cancelled":
            if item.status == "queued":
                item.status = "skipped"
                item.skip_reason = "cancelled_by_user"
                item.finished_at = _utcnow()
                _refresh_batch_counts(db, batch)
                _finalize_batch_status(db, batch)
                db.commit()
            return
        if item.video_id is None:
            item.status = "skipped"
            item.skip_reason = "invalid_video_id"
            item.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)
            _finalize_batch_status(db, batch)
            db.commit()
            return

        video = db.query(Video).filter(Video.id == item.video_id).first()
        if video is None:
            item.status = "skipped"
            item.skip_reason = "invalid_video_id"
            item.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)
            _finalize_batch_status(db, batch)
            db.commit()
            return

        item.status = "running"
        item.started_at = _utcnow()
        db.refresh(batch)
        if batch.status == "cancelled":
            item.status = "skipped"
            item.skip_reason = "cancelled_by_user"
            item.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)
            _finalize_batch_status(db, batch)
            db.commit()
            return

        if batch.status == "queued":
            started_at = batch.started_at or _utcnow()
            transitioned = (
                db.query(HlsBatch)
                .filter(HlsBatch.id == batch.id)
                .filter(HlsBatch.status == "queued")
                .update({"status": "running", "started_at": started_at}, synchronize_session=False)
            )
            db.flush()
            if transitioned == 0:
                db.refresh(batch)
                if batch.status == "cancelled":
                    item.status = "skipped"
                    item.skip_reason = "cancelled_by_user"
                    item.finished_at = _utcnow()
                    _refresh_batch_counts(db, batch)
                    _finalize_batch_status(db, batch)
                    db.commit()
                    return
        elif batch.status not in {"running", "queued"}:
            item.status = "skipped"
            item.skip_reason = "already_running"
            item.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)
            _finalize_batch_status(db, batch)
            db.commit()
            return

        _refresh_batch_counts(db, batch)
        db.commit()

        status, job_id = start_hls_prepare(
            db,
            settings,
            video=video,
            force=batch.force,
            qualities=_parse_qualities_csv(batch.qualities_csv),
        )

        if status == "already_completed":
            item.status = "skipped"
            item.skip_reason = "hls_already_exists"
            item.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)
            _finalize_batch_status(db, batch)
            db.commit()
            return
        if status in {"already_running", "concurrency_limit"}:
            item.status = "skipped"
            item.skip_reason = "already_running"
            item.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)
            _finalize_batch_status(db, batch)
            db.commit()
            return
        if status == "invalid_qualities" or job_id is None:
            item.status = "skipped"
            item.skip_reason = "invalid_metadata"
            item.finished_at = _utcnow()
            _refresh_batch_counts(db, batch)
            _finalize_batch_status(db, batch)
            db.commit()
            return

        item.hls_job_id = job_id
        db.commit()
    finally:
        db.close()

    result, error = _poll_job_until_finished(item_id, job_id)

    db = db_module.SessionLocal()
    try:
        batch = db.query(HlsBatch).filter(HlsBatch.id == batch_id).first()
        item = db.query(HlsBatchItem).filter(HlsBatchItem.id == item_id).first()
        if batch is None or item is None:
            return

        item.status = result
        item.error_message = error
        item.finished_at = _utcnow()
        _refresh_batch_counts(db, batch)
        _finalize_batch_status(db, batch)
        db.commit()
    finally:
        db.close()


def _batch_worker_loop() -> None:
    while True:
        try:
            db = db_module.SessionLocal()
            try:
                batch = _active_batch(db)
                if batch is None:
                    db.close()
                    time.sleep(1.0)
                    continue

                item = (
                    db.query(HlsBatchItem)
                    .filter(HlsBatchItem.batch_id == batch.id, HlsBatchItem.status == "queued")
                    .order_by(HlsBatchItem.id.asc())
                    .first()
                )

                if item is None:
                    _finalize_batch_status(db, batch)
                    db.commit()
                    db.close()
                    time.sleep(0.5)
                    continue

                running_jobs = db.query(HlsJob).filter(HlsJob.status == "running").count()
                if running_jobs >= max(1, get_settings().max_concurrent_hls_jobs):
                    db.close()
                    time.sleep(0.5)
                    continue

                batch_id = batch.id
                item_id = item.id
            finally:
                db.close()

            _process_batch_item(batch_id, item_id)
        except Exception:
            time.sleep(1.0)


def ensure_batch_worker_started() -> None:
    global _batch_worker_started
    with _batch_worker_lock:
        if _batch_worker_started:
            return
        worker = threading.Thread(target=_batch_worker_loop, daemon=True)
        worker.start()
        _batch_worker_started = True


def _update_job(
    db: Session,
    job: HlsJob,
    *,
    status: str | None = None,
    progress: float | None = None,
    current_quality: str | None = None,
    error_message: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress_percent = progress
    if current_quality is not None:
        job.current_quality = current_quality
    if error_message is not None:
        job.error_message = error_message
    if started:
        job.started_at = _utcnow()
    if finished:
        job.finished_at = _utcnow()
    db.flush()


def _set_variant_failed(db: Session, variant: VideoVariant, error: str) -> None:
    variant.status = "failed"
    variant.error_message = error[:4000]
    db.flush()


def _prepare_hls_worker(video_id: int, job_id: int, qualities: list[str], force: bool) -> None:
    settings = get_settings()
    acquired = _hls_semaphore.acquire(timeout=0)
    if not acquired:
        db = db_module.SessionLocal()
        try:
            job = db.query(HlsJob).filter(HlsJob.id == job_id).first()
            if job:
                _update_job(db, job, status="failed", error_message="HLS concurrency limit reached", finished=True)
                db.commit()
        finally:
            db.close()
        return

    db = db_module.SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        job = db.query(HlsJob).filter(HlsJob.id == job_id).first()
        if video is None or job is None:
            return

        _update_job(db, job, status="running", started=True, progress=0.0)
        db.commit()

        input_path = resolve_video_source_path(video, settings)

        if not input_path.exists() or not input_path.is_file():
            _update_job(db, job, status="failed", error_message="Source file not found", finished=True)
            db.commit()
            return

        out_dir = _video_output_dir(settings, video_id)
        if force and out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        source_height = video.height if video.height and video.height > 0 else None
        source_width = video.width if video.width and video.width > 0 else None
        filtered = _normalize_qualities(qualities, source_height)
        if not filtered:
            _update_job(db, job, status="failed", error_message="No valid qualities for source resolution", finished=True)
            db.commit()
            return

        if force:
            db.query(VideoVariant).filter(VideoVariant.video_id == video_id).delete()
            db.flush()

        completed_variants: list[VideoVariant] = []
        for index, quality in enumerate(filtered):
            variant = _upsert_variant(
                db,
                video_id=video_id,
                variant_type=_variant_type_for_quality(quality),
                quality_label=quality,
                status="running",
            )
            _update_job(
                db,
                job,
                current_quality=quality,
                progress=(index / max(1, len(filtered))) * 100.0,
            )
            db.commit()

            quality_dir = out_dir / quality
            ok, ffmpeg_error = _run_ffmpeg_quality(
                input_path=input_path,
                quality=quality,
                quality_dir=quality_dir,
                settings=settings,
            )
            if not ok:
                _set_variant_failed(db, variant, ffmpeg_error or "ffmpeg failed")
                _update_job(db, job, status="failed", error_message=ffmpeg_error or "ffmpeg failed", finished=True)
                db.commit()
                return

            playlist_path = quality_dir / "index.m3u8"
            width, height = _compute_output_resolution(source_width, source_height, QUALITY_PROFILES[quality]["height"])
            total_size = sum(path.stat().st_size for path in quality_dir.glob("*") if path.is_file())

            variant.status = "completed"
            variant.playlist_path = str(playlist_path)
            variant.relative_output_path = f"{video_id}/{quality}"
            variant.stream_url = _playlist_stream_url(video_id, quality)
            variant.width = width
            variant.height = height
            variant.bitrate = QUALITY_PROFILES[quality]["video_bitrate"]
            variant.file_size = int(total_size)
            variant.completed_at = _utcnow()
            variant.error_message = None
            db.flush()
            completed_variants.append(variant)
            _update_job(db, job, progress=((index + 1) / len(filtered)) * 100.0)
            db.commit()

        master_path = _write_master_playlist(video_id, out_dir, completed_variants)
        master_variant = _upsert_variant(
            db,
            video_id=video_id,
            variant_type="hls_master",
            status="completed",
            quality_label="master",
        )
        master_variant.playlist_path = str(master_path)
        master_variant.relative_output_path = f"{video_id}"
        master_variant.stream_url = _master_stream_url(video_id)
        master_variant.completed_at = _utcnow()
        master_variant.error_message = None

        _update_job(db, job, status="completed", progress=100.0, current_quality="done", finished=True)
        db.commit()
    except Exception as exc:  # pragma: no cover - defensive for background execution
        try:
            job = db.query(HlsJob).filter(HlsJob.id == job_id).first()
            if job is not None:
                _update_job(db, job, status="failed", error_message=str(exc)[:4000], finished=True)
                db.commit()
        except Exception:
            # If DB is unavailable (for example during test teardown), just exit safely.
            pass
    finally:
        db.close()
        _hls_semaphore.release()


def start_hls_prepare(
    db: Session,
    settings: Settings,
    *,
    video: Video,
    force: bool,
    qualities: list[str] | None,
) -> tuple[str, int | None]:
    running_for_video = (
        db.query(HlsJob)
        .filter(HlsJob.video_id == video.id)
        .filter(HlsJob.status == "running")
        .first()
    )
    if running_for_video is not None:
        return "already_running", running_for_video.id

    running_total = db.query(HlsJob).filter(HlsJob.status == "running").count()
    if running_total >= max(1, settings.max_concurrent_hls_jobs):
        return "concurrency_limit", None

    normalized = _normalize_qualities(qualities, video.height if video.height and video.height > 0 else None)
    if not normalized:
        return "invalid_qualities", None

    if not force and has_completed_hls_consistent(db, settings, video.id):
        job = _job_status_for_video(db, video.id)
        return "already_completed", job.id if job else None

    job = HlsJob(
        video_id=video.id,
        status="pending",
        progress_percent=0.0,
        current_quality=None,
    )
    db.add(job)
    db.flush()
    job_id = job.id
    db.commit()

    worker = threading.Thread(
        target=_prepare_hls_worker,
        args=(video.id, job_id, normalized, force),
        daemon=True,
    )
    worker.start()
    return "started", job_id


def validate_hls_quality(quality: str) -> bool:
    return quality in ALLOWED_QUALITIES


def validate_segment_name(segment_name: str) -> bool:
    return bool(SEGMENT_RE.fullmatch(segment_name))


def resolve_hls_path(settings: Settings, video_id: int, relative_path: str) -> Path:
    base = _video_output_dir(settings, video_id)
    target = (base / relative_path).resolve()
    target.relative_to(base)
    return target


def get_hls_library_diagnostics(
    db: Session,
    settings: Settings,
    *,
    limit: int,
    offset: int,
    details: bool,
) -> dict[str, object]:
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    return collect_hls_diagnostics(db, settings, details=details, limit=safe_limit, offset=safe_offset)


def repair_stale_hls_for_library(db: Session, settings: Settings) -> dict[str, object]:
    return reconcile_all_hls(db, settings)


