from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.duplicate_scan_status import update_duplicate_scan_progress
from app.models import DuplicateCandidateGroup, DuplicateCandidateItem, DuplicateScanRun, Video
from app.services.duplicate_fingerprint_service import (
    build_duplicate_fingerprint,
    build_strict_group_key,
)

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroupResult:
    group_key: str
    confidence: str
    reason: str
    candidate_count: int
    total_size: int
    potential_saving: int
    fingerprint: dict[str, str | int | None]
    videos: list[Video]


def _video_sort_key(video: Video) -> tuple[str, str]:
    return (video.relative_path.lower(), video.filename.lower())


def _fingerprint_summary_from_videos(videos: list[Video], mode: str) -> dict[str, str | int | None]:
    first = sorted(videos, key=_video_sort_key)[0]
    return build_duplicate_fingerprint(first, mode=mode).to_dict()


def _build_group_result(
    *,
    videos: list[Video],
    mode: str,
    group_index: int,
    confidence: str,
    reason: str,
) -> DuplicateGroupResult:
    ordered_videos = sorted(videos, key=_video_sort_key)
    sizes = [video.size for video in ordered_videos]
    total_size = sum(sizes)
    largest = max(sizes)
    return DuplicateGroupResult(
        group_key=f"{mode}-{group_index:03d}",
        confidence=confidence,
        reason=reason,
        candidate_count=len(ordered_videos),
        total_size=total_size,
        potential_saving=total_size - largest,
        fingerprint=_fingerprint_summary_from_videos(ordered_videos, mode),
        videos=ordered_videos,
    )


def _group_videos_strict(videos: list[Video]) -> list[DuplicateGroupResult]:
    grouped: dict[str, list[Video]] = {}
    for video in videos:
        key = build_strict_group_key(video)
        if key is None:
            continue
        grouped.setdefault(key, []).append(video)

    results: list[DuplicateGroupResult] = []
    for index, (_key, group_videos) in enumerate(sorted(grouped.items()), start=1):
        if len(group_videos) < 2:
            continue
        confidence = "exact_metadata_match"
        reason = "Same file size, duration, and resolution."
        results.append(
            _build_group_result(
                videos=group_videos,
                mode="strict",
                group_index=index,
                confidence=confidence,
                reason=reason,
            )
        )
    return results


def calculate_duplicate_groups(db: Session, mode: str = "strict") -> tuple[list[DuplicateGroupResult], dict[str, int | str | None]]:
    if mode != "strict":
        raise ValueError("Only strict duplicate mode is supported")

    update_duplicate_scan_progress(current_step="Loading metadata")
    videos = db.query(Video).all()
    update_duplicate_scan_progress(videos_checked=len(videos), current_step="Grouping duplicate candidates")

    groups = _group_videos_strict(videos)

    potential_saving = sum(group.potential_saving for group in groups)
    duplicate_candidates_found = sum(group.candidate_count for group in groups)
    summary = {
        "status": "completed",
        "mode": mode,
        "videos_checked": len(videos),
        "candidate_groups_found": len(groups),
        "duplicate_candidates_found": duplicate_candidates_found,
        "potential_saving": potential_saving,
        "last_scan_at": datetime.now(timezone.utc).isoformat(),
    }
    update_duplicate_scan_progress(
        current_step="Saving results",
        candidate_groups_found=len(groups),
        duplicate_candidates_found=duplicate_candidates_found,
    )
    return groups, summary


def save_duplicate_groups(db: Session, mode: str, groups: list[DuplicateGroupResult]) -> None:
    existing_groups = db.query(DuplicateCandidateGroup).filter(DuplicateCandidateGroup.mode == mode).all()
    existing_group_ids = [group.id for group in existing_groups]
    if existing_group_ids:
        db.query(DuplicateCandidateItem).filter(DuplicateCandidateItem.group_id.in_(existing_group_ids)).delete(
            synchronize_session=False
        )
        db.query(DuplicateCandidateGroup).filter(DuplicateCandidateGroup.mode == mode).delete(synchronize_session=False)
        db.flush()

    for group in groups:
        record = DuplicateCandidateGroup(
            group_key=group.group_key,
            mode=mode,
            confidence=group.confidence,
            reason=group.reason,
            candidate_count=group.candidate_count,
            total_size=group.total_size,
            potential_saving=group.potential_saving,
            fingerprint_json=json.dumps(group.fingerprint, sort_keys=True),
        )
        db.add(record)
        db.flush()
        for video in group.videos:
            db.add(DuplicateCandidateItem(group_id=record.id, video_id=video.id))

    db.commit()


def save_duplicate_summary(db: Session, mode: str, summary: dict[str, int | str | None], errors: list[str] | None = None) -> None:
    run = db.query(DuplicateScanRun).filter(DuplicateScanRun.mode == mode).first()
    if run is None:
        run = DuplicateScanRun(mode=mode, last_scan_status=str(summary.get("status", "completed")))
        db.add(run)

    run.last_scan_status = str(summary.get("status", "completed"))
    run.videos_checked = int(summary.get("videos_checked", 0) or 0)
    run.candidate_groups_found = int(summary.get("candidate_groups_found", 0) or 0)
    run.duplicate_candidates_found = int(summary.get("duplicate_candidates_found", 0) or 0)
    run.potential_saving = int(summary.get("potential_saving", 0) or 0)
    last_scan_at = summary.get("last_scan_at")
    run.last_scan_at = datetime.fromisoformat(str(last_scan_at)) if last_scan_at else None
    run.errors_json = json.dumps(errors or [])
    db.commit()


def load_duplicate_groups(db: Session, mode: str = "strict") -> list[dict[str, object]]:
    groups = (
        db.query(DuplicateCandidateGroup)
        .filter(DuplicateCandidateGroup.mode == mode)
        .order_by(DuplicateCandidateGroup.group_key.asc())
        .all()
    )
    if not groups:
        return []

    group_ids = [group.id for group in groups]
    items = (
        db.query(DuplicateCandidateItem, Video)
        .join(Video, DuplicateCandidateItem.video_id == Video.id)
        .filter(DuplicateCandidateItem.group_id.in_(group_ids))
        .all()
    )

    grouped_items: dict[int, list[Video]] = {group.id: [] for group in groups}
    for item, video in items:
        grouped_items[item.group_id].append(video)

    result: list[dict[str, object]] = []
    for group in groups:
        videos = sorted(grouped_items[group.id], key=_video_sort_key)
        result.append(
            {
                "group_id": group.group_key,
                "confidence": group.confidence,
                "reason": group.reason,
                "candidate_count": group.candidate_count,
                "total_size": group.total_size,
                "potential_saving": group.potential_saving,
                "fingerprint": json.loads(group.fingerprint_json),
                "videos": [
                    {
                        "id": video.id,
                        "title": video.title,
                        "filename": video.filename,
                        "relative_path": video.relative_path,
                        "size": video.size,
                        "duration": video.duration,
                        "width": video.width,
                        "height": video.height,
                        "video_codec": video.video_codec,
                        "audio_codec": video.audio_codec,
                        "extension": video.extension,
                        "thumbnail_url": f"/api/videos/{video.id}/thumbnail" if video.thumbnail_path else None,
                        "watch_url": f"/watch/{video.id}",
                    }
                    for video in videos
                ],
            }
        )
    return result


def load_duplicate_summary(db: Session, mode: str = "strict") -> dict[str, object]:
    run = db.query(DuplicateScanRun).filter(DuplicateScanRun.mode == mode).first()
    if run is None:
        return {
            "last_scan_status": "idle",
            "candidate_groups_found": 0,
            "duplicate_candidates_found": 0,
            "potential_saving": 0,
            "last_scan_at": None,
            "mode": mode,
            "is_outdated": False,
        }

    return {
        "last_scan_status": run.last_scan_status,
        "candidate_groups_found": run.candidate_groups_found,
        "duplicate_candidates_found": run.duplicate_candidates_found,
        "potential_saving": run.potential_saving,
        "last_scan_at": run.last_scan_at.isoformat() if run.last_scan_at else None,
        "mode": mode,
        "is_outdated": run.last_scan_status == "outdated",
    }


def run_duplicate_scan(db: Session, mode: str = "strict") -> dict[str, int | str | None]:
    groups, summary = calculate_duplicate_groups(db, mode=mode)
    save_duplicate_groups(db, mode, groups)
    save_duplicate_summary(db, mode, summary)
    return summary


def mark_duplicates_outdated(db: Session) -> None:
    """Mark all duplicate scan results as outdated after a successful library scan.

    After the library scan finishes successfully, previously computed duplicate
    groups may no longer reflect the current library state.  This sets every
    DuplicateScanRun row to 'outdated' so the frontend can warn the user.
    The flag is cleared again when the user runs a new duplicate scan.
    """
    runs = db.query(DuplicateScanRun).all()
    for run in runs:
        if run.last_scan_status in {"completed", "failed"}:
            run.last_scan_status = "outdated"
    db.commit()




