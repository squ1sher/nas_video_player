from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict, cast

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import HlsBatch, HlsBatchItem, HlsJob, Video, VideoVariant
from ..utils.files import safe_resolve_under_root

ALLOWED_QUALITIES = ("480p", "720p", "1080p")


class HlsInspectResult(TypedDict):
    has_valid_hls: bool
    valid_qualities: list[str]
    reason: str
    any_segment_present: bool
    all_segments_present: bool


class HlsReconcileResult(TypedDict):
    video_id: int
    has_valid_hls: bool
    valid_qualities: list[str]
    db_was_stale: bool
    db_repaired_to_completed: int
    stale_completed_invalidated: int
    stale_queued_reset: int
    stale_running_reset: int
    reason: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _video_root(settings: Settings, video_id: int) -> Path:
    return settings.hls_output_path.resolve() / str(video_id)


def _read_non_empty(path: Path) -> list[str]:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def _playlist_entries(lines: list[str]) -> list[str]:
    return [line for line in lines if not line.startswith("#")]


def inspect_video_hls(settings: Settings, video_id: int) -> HlsInspectResult:
    root = _video_root(settings, video_id)
    master = root / "master.m3u8"
    master_lines = _read_non_empty(master)
    if not master_lines:
        return {
            "has_valid_hls": False,
            "valid_qualities": [],
            "reason": "master_playlist_missing_or_empty",
            "any_segment_present": False,
            "all_segments_present": False,
        }

    quality_paths: dict[str, Path] = {
        quality: root / quality / "index.m3u8" for quality in ALLOWED_QUALITIES
    }

    entries = _playlist_entries(master_lines)
    for entry in entries:
        if not entry.endswith(".m3u8"):
            continue
        if "/" not in entry:
            continue
        quality = entry.split("/", 1)[0].strip()
        if quality in ALLOWED_QUALITIES:
            quality_paths[quality] = root / entry

    valid_qualities: list[str] = []
    any_segment_present = False
    all_referenced_segments_present = True

    for quality in ALLOWED_QUALITIES:
        index_path = quality_paths[quality]
        lines = _read_non_empty(index_path)
        if not lines:
            continue

        segment_refs = [entry for entry in _playlist_entries(lines) if not entry.endswith(".m3u8")]
        if not segment_refs:
            continue

        segment_states: list[bool] = []
        for ref in segment_refs:
            segment_path = (index_path.parent / ref).resolve()
            exists_and_non_empty = segment_path.exists() and segment_path.is_file() and segment_path.stat().st_size > 0
            segment_states.append(bool(exists_and_non_empty))

        if any(segment_states):
            any_segment_present = True
            valid_qualities.append(quality)
        if not all(segment_states):
            all_referenced_segments_present = False

    if not valid_qualities:
        return {
            "has_valid_hls": False,
            "valid_qualities": [],
            "reason": "no_valid_quality_playlist_with_segments",
            "any_segment_present": False,
            "all_segments_present": False,
        }

    return {
        "has_valid_hls": True,
        "valid_qualities": valid_qualities,
        "reason": "ok" if all_referenced_segments_present else "some_segments_missing",
        "any_segment_present": any_segment_present,
        "all_segments_present": all_referenced_segments_present,
    }


def has_valid_hls(settings: Settings, video_id: int) -> bool:
    return bool(inspect_video_hls(settings, video_id)["has_valid_hls"])


def _variant_type_for_quality(quality: str) -> str:
    return f"hls_{quality}"


def _set_hls_variants_failed(db: Session, video_id: int, reason: str) -> int:
    touched = 0
    variants = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video_id)
        .filter(
            VideoVariant.variant_type.in_([
                "hls_master",
                _variant_type_for_quality("480p"),
                _variant_type_for_quality("720p"),
                _variant_type_for_quality("1080p"),
            ])
        )
        .all()
    )
    for variant in variants:
        if variant.status == "completed":
            touched += 1
        variant.status = "failed"
        variant.error_message = reason[:4000]
    return touched


def _upsert_completed_variants(db: Session, settings: Settings, video_id: int, qualities: list[str]) -> int:
    repaired = 0
    for quality in qualities:
        variant_type = _variant_type_for_quality(quality)
        variant = (
            db.query(VideoVariant)
            .filter(VideoVariant.video_id == video_id)
            .filter(VideoVariant.variant_type == variant_type)
            .first()
        )
        if variant is None:
            variant = VideoVariant(video_id=video_id, variant_type=variant_type)
            db.add(variant)
            repaired += 1
        if variant.status != "completed":
            repaired += 1
        variant.status = "completed"
        variant.quality_label = quality
        variant.playlist_path = str(_video_root(settings, video_id) / quality / "index.m3u8")
        variant.relative_output_path = f"{video_id}/{quality}"
        variant.stream_url = f"/api/videos/{video_id}/hls/{quality}/index.m3u8"
        variant.error_message = None
        if variant.completed_at is None:
            variant.completed_at = _utcnow()

    master = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video_id)
        .filter(VideoVariant.variant_type == "hls_master")
        .first()
    )
    if master is None:
        master = VideoVariant(video_id=video_id, variant_type="hls_master")
        db.add(master)
        repaired += 1
    if master.status != "completed":
        repaired += 1
    master.status = "completed"
    master.quality_label = "master"
    master.playlist_path = str(_video_root(settings, video_id) / "master.m3u8")
    master.relative_output_path = f"{video_id}"
    master.stream_url = f"/api/videos/{video_id}/hls/master.m3u8"
    master.error_message = None
    if master.completed_at is None:
        master.completed_at = _utcnow()
    return repaired


def reconcile_video_hls(db: Session, settings: Settings, video: Video) -> HlsReconcileResult:
    inspected = inspect_video_hls(settings, video.id)
    fs_valid = bool(inspected["has_valid_hls"])
    valid_qualities = [q for q in inspected["valid_qualities"] if q in ALLOWED_QUALITIES]

    db_completed = (
        db.query(VideoVariant)
        .filter(VideoVariant.video_id == video.id)
        .filter(VideoVariant.variant_type == "hls_master")
        .filter(VideoVariant.status == "completed")
        .first()
        is not None
    )

    db_repaired_to_completed = 0
    stale_completed_invalidated = 0

    if fs_valid:
        db_repaired_to_completed = _upsert_completed_variants(db, settings, video.id, valid_qualities)
    elif db_completed:
        stale_completed_invalidated = _set_hls_variants_failed(
            db,
            video.id,
            f"HLS files are missing or invalid: {inspected.get('reason', 'unknown')}",
        )

    return {
        "video_id": video.id,
        "has_valid_hls": fs_valid,
        "valid_qualities": valid_qualities,
        "db_was_stale": stale_completed_invalidated > 0,
        "db_repaired_to_completed": db_repaired_to_completed,
        "stale_completed_invalidated": stale_completed_invalidated,
        "stale_queued_reset": 0,
        "stale_running_reset": 0,
        "reason": inspected["reason"],
    }


def _source_exists(video: Video, settings: Settings) -> bool:
    try:
        source = safe_resolve_under_root(settings.video_library_path, video.relative_path)
    except ValueError:
        return False
    return source.exists() and source.is_file()


def collect_hls_diagnostics(
    db: Session,
    settings: Settings,
    *,
    details: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    videos = [cast(Video, row) for row in db.query(Video).order_by(Video.id.asc()).all()]
    total_videos = len(videos)
    valid_hls = 0
    missing_hls = 0
    db_completed_but_files_missing = 0
    files_exist_but_db_missing = 0
    invalid_source_missing = 0

    detail_buckets: dict[str, list[dict[str, object]]] = {
        "db_completed_but_files_missing": [],
        "files_exist_but_db_missing": [],
        "stale_queued": [],
        "stale_running": [],
        "source_missing": [],
        "missing_hls_sample": [],
    }

    for raw_video in videos:
        video = cast(Video, raw_video)
        fs_valid = has_valid_hls(settings, video.id)
        db_completed = (
            db.query(VideoVariant)
            .filter(VideoVariant.video_id == video.id)
            .filter(VideoVariant.variant_type == "hls_master")
            .filter(VideoVariant.status == "completed")
            .first()
            is not None
        )

        if fs_valid:
            valid_hls += 1
        else:
            missing_hls += 1
            if details and len(detail_buckets["missing_hls_sample"]) < limit:
                detail_buckets["missing_hls_sample"].append(
                    {"video_id": video.id, "title": video.title, "relative_path": video.relative_path, "reason": "missing_or_invalid_hls"}
                )

        if db_completed and not fs_valid:
            db_completed_but_files_missing += 1
            if details and len(detail_buckets["db_completed_but_files_missing"]) < limit:
                detail_buckets["db_completed_but_files_missing"].append(
                    {"video_id": video.id, "title": video.title, "relative_path": video.relative_path, "reason": "db_completed_but_files_missing"}
                )
        if fs_valid and not db_completed:
            files_exist_but_db_missing += 1
            if details and len(detail_buckets["files_exist_but_db_missing"]) < limit:
                detail_buckets["files_exist_but_db_missing"].append(
                    {"video_id": video.id, "title": video.title, "relative_path": video.relative_path, "reason": "files_exist_but_db_missing"}
                )

        if not _source_exists(video, settings):
            invalid_source_missing += 1
            if details and len(detail_buckets["source_missing"]) < limit:
                detail_buckets["source_missing"].append(
                    {"video_id": video.id, "title": video.title, "relative_path": video.relative_path, "reason": "source_missing"}
                )

    active_batch_statuses = ["queued", "running"]
    active_queued = (
        db.query(HlsBatchItem)
        .join(HlsBatch, HlsBatch.id == HlsBatchItem.batch_id)
        .filter(HlsBatchItem.status == "queued")
        .filter(HlsBatch.status.in_(active_batch_statuses))
        .count()
    )
    active_running = (
        db.query(HlsBatchItem)
        .join(HlsBatch, HlsBatch.id == HlsBatchItem.batch_id)
        .filter(HlsBatchItem.status == "running")
        .filter(HlsBatch.status.in_(active_batch_statuses))
        .count()
    )

    stale_queued_rows = (
        db.query(HlsBatchItem)
        .join(HlsBatch, HlsBatch.id == HlsBatchItem.batch_id)
        .filter(HlsBatchItem.status == "queued")
        .filter(~HlsBatch.status.in_(active_batch_statuses))
        .all()
    )
    stale_running_rows = (
        db.query(HlsBatchItem)
        .join(HlsBatch, HlsBatch.id == HlsBatchItem.batch_id)
        .filter(HlsBatchItem.status == "running")
        .filter(~HlsBatch.status.in_(active_batch_statuses))
        .all()
    )

    stale_queued = len(stale_queued_rows)
    stale_running = len(stale_running_rows)

    if details:
        for item in stale_queued_rows[offset : offset + limit]:
            detail_buckets["stale_queued"].append(
                {"video_id": item.video_id, "title": "", "relative_path": "", "reason": "stale_queued_item"}
            )
        for item in stale_running_rows[offset : offset + limit]:
            detail_buckets["stale_running"].append(
                {"video_id": item.video_id, "title": "", "relative_path": "", "reason": "stale_running_item"}
            )

    return {
        "total_videos": total_videos,
        "valid_hls": valid_hls,
        "missing_hls": missing_hls,
        "db_completed_but_files_missing": db_completed_but_files_missing,
        "files_exist_but_db_missing": files_exist_but_db_missing,
        "stale_queued": stale_queued,
        "stale_running": stale_running,
        "active_queued": int(active_queued),
        "active_running": int(active_running),
        "invalid_source_missing": invalid_source_missing,
        "details": detail_buckets if details else None,
    }


def reconcile_all_hls(db: Session, settings: Settings) -> dict[str, Any]:
    videos = [cast(Video, row) for row in db.query(Video).order_by(Video.id.asc()).all()]
    summary = {
        "checked": 0,
        "valid_hls": 0,
        "missing_hls": 0,
        "db_repaired_to_completed": 0,
        "stale_completed_invalidated": 0,
        "stale_queued_reset": 0,
        "stale_running_reset": 0,
        "errors": [],
    }

    for raw_video in videos:
        video = cast(Video, raw_video)
        summary["checked"] += 1
        try:
            result = reconcile_video_hls(db, settings, video)
            if result["has_valid_hls"]:
                summary["valid_hls"] += 1
            else:
                summary["missing_hls"] += 1
            summary["db_repaired_to_completed"] += result["db_repaired_to_completed"]
            summary["stale_completed_invalidated"] += result["stale_completed_invalidated"]
            summary["stale_queued_reset"] += result["stale_queued_reset"]
            summary["stale_running_reset"] += result["stale_running_reset"]
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"video_id={video.id}: {exc}")

    now = _utcnow()
    active_batch_statuses = ["queued", "running"]
    stale_items = (
        db.query(HlsBatchItem)
        .join(HlsBatch, HlsBatch.id == HlsBatchItem.batch_id)
        .filter(HlsBatchItem.status.in_(["queued", "running"]))
        .filter(~HlsBatch.status.in_(active_batch_statuses))
        .all()
    )
    for item in stale_items:
        if item.status == "queued":
            summary["stale_queued_reset"] += 1
        else:
            summary["stale_running_reset"] += 1
        item.status = "failed"
        item.error_message = "Interrupted by application restart."
        item.finished_at = now

    stale_cutoff = now - timedelta(minutes=5)
    for job in db.query(HlsJob).filter(HlsJob.status.in_(["pending", "running"])):
        has_active_item = (
            db.query(HlsBatchItem)
            .join(HlsBatch, HlsBatch.id == HlsBatchItem.batch_id)
            .filter(HlsBatchItem.video_id == job.video_id)
            .filter(HlsBatchItem.status.in_(["queued", "running"]))
            .filter(HlsBatch.status.in_(active_batch_statuses))
            .first()
            is not None
        )
        if has_active_item:
            continue
        updated = job.updated_at or job.created_at
        if updated and updated >= stale_cutoff:
            continue
        if job.status == "pending":
            summary["stale_queued_reset"] += 1
        else:
            summary["stale_running_reset"] += 1
        job.status = "failed"
        job.error_message = "Interrupted by application restart."
        job.finished_at = now


    db.commit()
    return summary

