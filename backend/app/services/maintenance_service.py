"""Maintenance / cleanup service – Phase 2.6.

Provides:
  - Cleanup summary (orphan HLS folders, thumbnail orphans, stale DB records, etc.)
  - Cleanup plan (dry-run, returns grouped items with IDs)
  - Cleanup apply  (executes selected items from a stored plan)

Safety rules:
  - Never deletes original media files.
  - By default does NOT delete HLS for source_removed / source_disabled / missing videos.
  - All destructive operations require an explicit apply step.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    DuplicateCandidateGroup,
    DuplicateCandidateItem,
    HlsJob,
    Video,
    VideoVariant,
)
from app.services.hls_reconciliation_service import has_valid_hls

logger = logging.getLogger(__name__)

# ── In-process plan store (ephemeral; lost on restart) ────────────────────────
# Keyed by plan_id; each value is a list of CleanupItem dicts
_cleanup_plans: dict[str, dict[str, Any]] = {}
_MAX_STORED_PLANS = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _folder_size(folder: Path) -> int:
    """Return total size of all files under *folder* in bytes."""
    total = 0
    if folder.exists() and folder.is_dir():
        for f in folder.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    return total


# ── Cleanup Summary ────────────────────────────────────────────────────────────

def get_cleanup_summary(db: Session, settings: Settings) -> dict[str, Any]:
    """Return a fast summary of stale / orphan data across HLS, thumbnails, and duplicates."""

    hls_root = settings.hls_output_path.resolve()
    thumbnails_root = settings.thumbnails_path.resolve()

    # ── Video availability breakdown ─────────────────────────────────────────
    all_videos = db.query(Video).all()
    video_ids: set[int] = {v.id for v in all_videos}

    available = 0
    missing_count = 0
    source_disabled_count = 0
    source_removed_count = 0
    deleted_count = 0

    for v in all_videos:
        av = v.availability_status
        if av == "source_removed":
            source_removed_count += 1
        elif av == "source_disabled":
            source_disabled_count += 1
        elif av == "deleted":
            deleted_count += 1
        elif av == "missing":
            missing_count += 1
        else:
            available += 1

    # ── HLS analysis ─────────────────────────────────────────────────────────
    valid_hls = 0
    orphan_hls_count = 0
    orphan_hls_size = 0
    db_completed_but_files_missing = 0
    files_exist_but_db_missing = 0

    # Gather HLS folders that exist on disk
    existing_hls_video_ids: set[int] = set()
    if hls_root.exists():
        for child in hls_root.iterdir():
            if not child.is_dir():
                continue
            try:
                fid = int(child.name)
            except ValueError:
                continue
            existing_hls_video_ids.add(fid)

    # Orphan HLS folders: numeric folder but no DB video
    for fid in existing_hls_video_ids:
        if fid not in video_ids:
            orphan_hls_count += 1
            orphan_hls_size += _folder_size(hls_root / str(fid))

    # Per-video DB vs filesystem consistency
    for v in all_videos:
        # Skip source_removed / source_disabled for DB consistency check
        # (their HLS may still be valid and useful if source is re-added)
        av = v.availability_status
        if av in ("source_removed", "source_disabled"):
            continue

        fs_valid = has_valid_hls(settings, v.id)
        db_completed = (
            db.query(VideoVariant)
            .filter(VideoVariant.video_id == v.id, VideoVariant.variant_type == "hls_master", VideoVariant.status == "completed")
            .first()
            is not None
        )

        if fs_valid:
            valid_hls += 1
        if db_completed and not fs_valid:
            db_completed_but_files_missing += 1
        if fs_valid and not db_completed:
            files_exist_but_db_missing += 1

    # Stale HLS jobs (old pending/running that are clearly stuck)
    old_cutoff = _utcnow() - timedelta(hours=2)
    stale_running_jobs = (
        db.query(HlsJob)
        .filter(HlsJob.status == "running", HlsJob.updated_at < old_cutoff)
        .count()
    )
    stale_queued_jobs = (
        db.query(HlsJob)
        .filter(HlsJob.status == "pending")
        .count()
    )
    failed_jobs_old = db.query(HlsJob).filter(HlsJob.status == "failed").count()

    # ── Thumbnail analysis ────────────────────────────────────────────────────
    known_thumbnails: set[str] = {v.thumbnail_path for v in all_videos if v.thumbnail_path}
    orphan_thumbnails = 0
    orphan_thumbnails_size = 0

    if thumbnails_root.exists():
        for f in thumbnails_root.iterdir():
            if f.is_file() and f.name not in known_thumbnails:
                orphan_thumbnails += 1
                try:
                    orphan_thumbnails_size += f.stat().st_size
                except OSError:
                    pass

    # ── Duplicate analysis ────────────────────────────────────────────────────
    if video_ids:
        stale_dup_items = (
            db.query(DuplicateCandidateItem)
            .filter(DuplicateCandidateItem.video_id.notin_(video_ids))
            .count()
        )
    else:
        stale_dup_items = db.query(DuplicateCandidateItem).count()

    stale_dup_groups = 0
    for grp in db.query(DuplicateCandidateGroup).all():
        items = (
            db.query(DuplicateCandidateItem)
            .filter(DuplicateCandidateItem.group_id == grp.id)
            .all()
        )
        valid_items = [i for i in items if i.video_id in video_ids]
        if len(valid_items) < 2:
            stale_dup_groups += 1

    potential_cleanup_size = orphan_hls_size + orphan_thumbnails_size

    return {
        "hls": {
            "valid_hls": valid_hls,
            "orphan_hls_folders": orphan_hls_count,
            "orphan_hls_size": orphan_hls_size,
            "db_completed_but_files_missing": db_completed_but_files_missing,
            "files_exist_but_db_missing": files_exist_but_db_missing,
            "stale_running_jobs": int(stale_running_jobs),
            "stale_queued_jobs": int(stale_queued_jobs),
            "failed_jobs_old": int(failed_jobs_old),
        },
        "videos": {
            "available": available,
            "missing": missing_count,
            "source_disabled": source_disabled_count,
            "source_removed": source_removed_count,
            "deleted": deleted_count,
        },
        "thumbnails": {
            "orphan_thumbnails": orphan_thumbnails,
            "orphan_thumbnails_size": orphan_thumbnails_size,
        },
        "duplicates": {
            "stale_duplicate_items": int(stale_dup_items),
            "stale_duplicate_groups": stale_dup_groups,
        },
        "potential_cleanup_size": potential_cleanup_size,
    }


# ── Cleanup Plan ───────────────────────────────────────────────────────────────

def create_cleanup_plan(
    db: Session,
    settings: Settings,
    include: dict[str, bool],
) -> dict[str, Any]:
    """Generate a dry-run cleanup plan based on the requested categories."""

    hls_root = settings.hls_output_path.resolve()
    thumbnails_root = settings.thumbnails_path.resolve()

    all_videos = db.query(Video).all()
    video_ids: set[int] = {v.id for v in all_videos}

    items: list[dict[str, Any]] = []
    total_size = 0

    # 1. Orphan HLS folders
    if include.get("orphan_hls_folders", False) and hls_root.exists():
        for child in hls_root.iterdir():
            if not child.is_dir():
                continue
            try:
                fid = int(child.name)
            except ValueError:
                continue
            if fid not in video_ids:
                size = _folder_size(child)
                total_size += size
                items.append({
                    "item_id": str(uuid.uuid4()),
                    "type": "orphan_hls_folder",
                    "video_id": fid,
                    "path": str(fid),
                    "_abs_path": str(child),
                    "size": size,
                    "action": "delete_folder",
                    "safe": True,
                    "reason": f"HLS folder '{fid}' exists but no video record found in database.",
                })

    # 2. HLS DB records that say completed but files are missing
    if include.get("hls_db_records_missing_files", False):
        for v in all_videos:
            av = v.availability_status
            if av in ("source_removed", "source_disabled"):
                continue
            fs_valid = has_valid_hls(settings, v.id)
            db_completed = (
                db.query(VideoVariant)
                .filter(VideoVariant.video_id == v.id, VideoVariant.variant_type == "hls_master", VideoVariant.status == "completed")
                .first()
                is not None
            )
            if db_completed and not fs_valid:
                items.append({
                    "item_id": str(uuid.uuid4()),
                    "type": "hls_db_record_missing_files",
                    "video_id": v.id,
                    "path": str(v.id),
                    "_abs_path": None,
                    "size": 0,
                    "action": "invalidate_db_record",
                    "safe": True,
                    "reason": (
                        f"DB says HLS is completed for video {v.id} ('{v.title}') "
                        "but master.m3u8 / segments are missing."
                    ),
                })

    # 3. Orphan thumbnails
    if include.get("orphan_thumbnails", False) and thumbnails_root.exists():
        known_thumbnails: set[str] = {v.thumbnail_path for v in all_videos if v.thumbnail_path}
        for f in thumbnails_root.iterdir():
            if f.is_file() and f.name not in known_thumbnails:
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                total_size += size
                items.append({
                    "item_id": str(uuid.uuid4()),
                    "type": "orphan_thumbnail",
                    "video_id": None,
                    "path": f"thumbnails/{f.name}",
                    "_abs_path": str(f),
                    "size": size,
                    "action": "delete_file",
                    "safe": True,
                    "reason": f"Thumbnail '{f.name}' exists but no video references it.",
                })

    # 4. Stale HLS jobs
    if include.get("stale_hls_jobs", False):
        old_cutoff = _utcnow() - timedelta(hours=2)
        stale_jobs = (
            db.query(HlsJob)
            .filter(HlsJob.status.in_(["pending", "running"]), HlsJob.updated_at < old_cutoff)
            .all()
        )
        for job in stale_jobs:
            items.append({
                "item_id": str(uuid.uuid4()),
                "type": "stale_hls_job",
                "video_id": job.video_id,
                "path": None,
                "_abs_path": None,
                "_job_id": job.id,
                "size": 0,
                "action": "mark_failed",
                "safe": True,
                "reason": (
                    f"HLS job {job.id} has been in '{job.status}' state "
                    f"since {job.updated_at} (> 2 h) with no activity."
                ),
            })

    # 5. Stale duplicate items (pointing to video_ids not in DB)
    if include.get("stale_duplicate_records", False):
        if video_ids:
            stale_items = (
                db.query(DuplicateCandidateItem)
                .filter(DuplicateCandidateItem.video_id.notin_(video_ids))
                .all()
            )
        else:
            stale_items = db.query(DuplicateCandidateItem).all()

        for di in stale_items:
            items.append({
                "item_id": str(uuid.uuid4()),
                "type": "stale_duplicate_item",
                "video_id": di.video_id,
                "path": None,
                "_abs_path": None,
                "_dup_item_id": di.id,
                "_dup_group_id": di.group_id,
                "size": 0,
                "action": "delete_db_record",
                "safe": True,
                "reason": f"Duplicate candidate item {di.id} points to video_id={di.video_id} which no longer exists.",
            })

        # Stale duplicate groups (fewer than 2 valid items)
        for grp in db.query(DuplicateCandidateGroup).all():
            grp_items = db.query(DuplicateCandidateItem).filter(DuplicateCandidateItem.group_id == grp.id).all()
            valid = [i for i in grp_items if i.video_id in video_ids]
            if len(valid) < 2:
                items.append({
                    "item_id": str(uuid.uuid4()),
                    "type": "stale_duplicate_group",
                    "video_id": None,
                    "path": None,
                    "_abs_path": None,
                    "_dup_group_id": grp.id,
                    "size": 0,
                    "action": "delete_db_record",
                    "safe": True,
                    "reason": (
                        f"Duplicate group {grp.id} has only {len(valid)} valid video(s) "
                        "(need ≥ 2). Will be removed."
                    ),
                })

    # 6. Optional: HLS for source_removed videos
    if include.get("source_removed_hls", False) and hls_root.exists():
        source_removed_ids = {v.id for v in all_videos if v.availability_status == "source_removed"}
        for vid_id in source_removed_ids:
            hls_dir = hls_root / str(vid_id)
            if hls_dir.exists() and hls_dir.is_dir():
                size = _folder_size(hls_dir)
                total_size += size
                items.append({
                    "item_id": str(uuid.uuid4()),
                    "type": "source_removed_hls",
                    "video_id": vid_id,
                    "path": str(vid_id),
                    "_abs_path": str(hls_dir),
                    "size": size,
                    "action": "delete_folder",
                    "safe": False,
                    "reason": (
                        f"HLS cache exists for video {vid_id} whose media source was removed. "
                        "The source may be re-added later."
                    ),
                })

    # 7. Optional: HLS for missing videos (source enabled but file gone)
    if include.get("missing_video_hls", False) and hls_root.exists():
        missing_ids = {v.id for v in all_videos if v.availability_status == "missing"}
        for vid_id in missing_ids:
            hls_dir = hls_root / str(vid_id)
            if hls_dir.exists() and hls_dir.is_dir():
                size = _folder_size(hls_dir)
                total_size += size
                items.append({
                    "item_id": str(uuid.uuid4()),
                    "type": "missing_video_hls",
                    "video_id": vid_id,
                    "path": str(vid_id),
                    "_abs_path": str(hls_dir),
                    "size": size,
                    "action": "delete_folder",
                    "safe": False,
                    "reason": (
                        f"HLS cache exists for video {vid_id} whose source file is missing. "
                        "The file may be temporarily unavailable."
                    ),
                })

    # Store the plan in memory
    plan_id = str(uuid.uuid4())
    plan = {
        "plan_id": plan_id,
        "created_at": _utcnow().isoformat(),
        "dry_run": True,
        "items": items,
        "total_items": len(items),
        "total_size_to_delete": total_size,
    }

    # Evict oldest plans if we have too many
    if len(_cleanup_plans) >= _MAX_STORED_PLANS:
        oldest = sorted(_cleanup_plans.keys(), key=lambda k: _cleanup_plans[k]["created_at"])
        del _cleanup_plans[oldest[0]]

    _cleanup_plans[plan_id] = plan

    # Return sanitised version (no _abs_path / internal fields)
    return _sanitise_plan(plan)


def _sanitise_plan(plan: dict[str, Any]) -> dict[str, Any]:
    sanitised_items = []
    for item in plan["items"]:
        sanitised_items.append({
            "item_id": item["item_id"],
            "type": item["type"],
            "video_id": item.get("video_id"),
            "path": item.get("path"),
            "size": item.get("size", 0),
            "action": item.get("action"),
            "safe": item.get("safe", True),
            "reason": item.get("reason", ""),
        })
    return {
        "plan_id": plan["plan_id"],
        "dry_run": plan["dry_run"],
        "items": sanitised_items,
        "total_items": plan["total_items"],
        "total_size_to_delete": plan["total_size_to_delete"],
    }


# ── Cleanup Apply ──────────────────────────────────────────────────────────────

def apply_cleanup_plan(
    db: Session,
    settings: Settings,  # noqa: ARG001 – reserved for future use
    plan_id: str,
    selected_item_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Apply selected items from a previously generated plan."""

    plan = _cleanup_plans.get(plan_id)
    if plan is None:
        return {"error": "Plan not found or expired. Run cleanup analysis again."}

    items = plan["items"]
    if selected_item_ids is not None:
        id_set = set(selected_item_ids)
        items = [i for i in items if i["item_id"] in id_set]

    deleted_files = 0
    deleted_folders = 0
    deleted_size = 0
    db_records_updated = 0
    errors: list[str] = []

    for item in items:
        try:
            itype = item["type"]

            if itype == "orphan_hls_folder":
                abs_path = item.get("_abs_path")
                if abs_path:
                    folder = Path(abs_path)
                    if folder.exists() and folder.is_dir():
                        size = _folder_size(folder)
                        shutil.rmtree(folder)
                        deleted_folders += 1
                        deleted_size += size
                        logger.info("Maintenance: deleted orphan HLS folder %s", folder)

            elif itype == "hls_db_record_missing_files":
                vid_id = item.get("video_id")
                if vid_id is not None:
                    updated = (
                        db.query(VideoVariant)
                        .filter(VideoVariant.video_id == vid_id)
                        .filter(VideoVariant.variant_type.in_(["hls_master", "hls_480p", "hls_720p", "hls_1080p"]))
                        .filter(VideoVariant.status == "completed")
                        .all()
                    )
                    for variant in updated:
                        variant.status = "failed"
                        variant.error_message = "Invalidated by maintenance cleanup: HLS files missing."
                        db_records_updated += 1
                    db.flush()

            elif itype == "orphan_thumbnail":
                abs_path = item.get("_abs_path")
                if abs_path:
                    f = Path(abs_path)
                    if f.exists() and f.is_file():
                        size = f.stat().st_size
                        f.unlink()
                        deleted_files += 1
                        deleted_size += size
                        logger.info("Maintenance: deleted orphan thumbnail %s", f)

            elif itype == "stale_hls_job":
                job_id = item.get("_job_id")
                if job_id is not None:
                    job = db.query(HlsJob).filter(HlsJob.id == job_id).first()
                    if job and job.status in ("pending", "running"):
                        job.status = "failed"
                        job.error_message = "Marked failed by maintenance cleanup."
                        job.finished_at = _utcnow()
                        db_records_updated += 1
                        db.flush()

            elif itype == "stale_duplicate_item":
                dup_item_id = item.get("_dup_item_id")
                if dup_item_id is not None:
                    di = db.query(DuplicateCandidateItem).filter(DuplicateCandidateItem.id == dup_item_id).first()
                    if di:
                        db.delete(di)
                        db_records_updated += 1
                        db.flush()

            elif itype == "stale_duplicate_group":
                grp_id = item.get("_dup_group_id")
                if grp_id is not None:
                    grp = db.query(DuplicateCandidateGroup).filter(DuplicateCandidateGroup.id == grp_id).first()
                    if grp:
                        # Delete items first (FK safety)
                        db.query(DuplicateCandidateItem).filter(
                            DuplicateCandidateItem.group_id == grp_id
                        ).delete()
                        db.delete(grp)
                        db_records_updated += 1
                        db.flush()

            elif itype in ("source_removed_hls", "missing_video_hls"):
                abs_path = item.get("_abs_path")
                if abs_path:
                    folder = Path(abs_path)
                    if folder.exists() and folder.is_dir():
                        size = _folder_size(folder)
                        shutil.rmtree(folder)
                        deleted_folders += 1
                        deleted_size += size
                        logger.info("Maintenance: deleted HLS folder for %s video: %s", itype, folder)

        except Exception as exc:  # noqa: BLE001
            errors.append(f"item {item.get('item_id', '?')}: {exc}")
            logger.warning("Maintenance cleanup error for item %s: %s", item.get("item_id"), exc)

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"DB commit error: {exc}")
        db.rollback()

    return {
        "status": "completed" if not errors else "completed_with_errors",
        "deleted_files": deleted_files,
        "deleted_folders": deleted_folders,
        "deleted_size": deleted_size,
        "db_records_updated": db_records_updated,
        "errors": errors,
    }

