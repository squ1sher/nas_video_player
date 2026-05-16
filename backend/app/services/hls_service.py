from __future__ import annotations

import math
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
import app.database as db_module
from app.models import HlsJob, Video, VideoVariant
from app.utils.files import safe_resolve_under_root

ALLOWED_QUALITIES = ("480p", "720p", "1080p")
QUALITY_PROFILES: dict[str, dict[str, int]] = {
    "480p": {"height": 480, "video_bitrate": 1_200_000, "audio_bitrate": 96_000},
    "720p": {"height": 720, "video_bitrate": 2_500_000, "audio_bitrate": 128_000},
    "1080p": {"height": 1080, "video_bitrate": 5_000_000, "audio_bitrate": 160_000},
}
SEGMENT_RE = re.compile(r"^segment_\d{3,6}\.ts$")

_settings = get_settings()
_hls_semaphore = threading.BoundedSemaphore(max(1, _settings.max_concurrent_hls_jobs))


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
    raw = requested if requested else list(ALLOWED_QUALITIES)
    deduped = [q for q in ALLOWED_QUALITIES if q in raw]
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


def get_hls_video_status(db: Session, settings: Settings, video_id: int) -> dict[str, object]:
    job = _job_status_for_video(db, video_id)
    variants = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video_id)
        .all()
    )
    available = sorted(
        [
            variant.quality_label
            for variant in variants
            if variant.quality_label in ALLOWED_QUALITIES and variant.status == "completed"
        ],
        key=lambda label: ALLOWED_QUALITIES.index(label),
    )

    master_path = _video_output_dir(settings, video_id) / "master.m3u8"
    master_url = _master_stream_url(video_id) if master_path.exists() and available else None

    status = "idle"
    progress = None
    current_quality = None
    error_message = None
    if job is not None:
        status = job.status
        progress = job.progress_percent
        current_quality = job.current_quality
        error_message = job.error_message
    elif available:
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
    recent_failed = db.query(HlsJob).filter(HlsJob.status == "failed").count()
    recent_completed = db.query(HlsJob).filter(HlsJob.status == "completed").count()
    return {
        "running": int(running),
        "max_concurrent": int(max(1, settings.max_concurrent_hls_jobs)),
        "recent_failed": int(recent_failed),
        "recent_completed": int(recent_completed),
    }


def list_hls_jobs(db: Session, limit: int = 50) -> list[HlsJob]:
    return db.query(HlsJob).order_by(HlsJob.created_at.desc()).limit(limit).all()


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

        try:
            input_path = safe_resolve_under_root(settings.video_library_path, video.relative_path)
        except ValueError:
            _update_job(
                db,
                job,
                status="failed",
                error_message="Source file path is invalid",
                finished=True,
            )
            db.commit()
            return

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
        job = db.query(HlsJob).filter(HlsJob.id == job_id).first()
        if job is not None:
            _update_job(db, job, status="failed", error_message=str(exc)[:4000], finished=True)
            db.commit()
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

    if not force and has_completed_hls(db, video.id):
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


