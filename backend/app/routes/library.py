from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Video
from app.scan_status import get_scan_state
from app.schemas import LastDuplicateScanSummary, LastLibraryScanSummary, LibrarySummaryOut
from app.services.duplicate_service import load_duplicate_summary
from app.services.media_profile_service import media_profile_stats

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("/summary", response_model=LibrarySummaryOut)
def get_library_summary(db: Session = Depends(get_db)) -> LibrarySummaryOut:
    total_indexed = db.query(func.count(Video.id)).scalar() or 0
    total_size = db.query(func.coalesce(func.sum(Video.size), 0)).scalar() or 0

    detected_videos = db.query(func.count(Video.id)).filter(Video.media_status == "detected_video").scalar() or 0
    probe_failed_possible_video = (
        db.query(func.count(Video.id)).filter(Video.media_status == "probe_failed_possible_video").scalar() or 0
    )

    direct_play = db.query(func.count(Video.id)).filter(Video.compatibility_status == "direct_play").scalar() or 0
    may_play = db.query(func.count(Video.id)).filter(Video.compatibility_status == "may_play").scalar() or 0
    may_not_play = db.query(func.count(Video.id)).filter(Video.compatibility_status == "may_not_play").scalar() or 0
    needs_conversion = db.query(func.count(Video.id)).filter(Video.compatibility_status == "needs_conversion").scalar() or 0
    unknown_compatibility = db.query(func.count(Video.id)).filter(Video.compatibility_status == "unknown").scalar() or 0

    thumbnail_generated = db.query(func.count(Video.id)).filter(Video.thumbnail_status == "generated").scalar() or 0
    thumbnail_failed = db.query(func.count(Video.id)).filter(Video.thumbnail_status == "failed").scalar() or 0
    thumbnail_missing = max(0, total_indexed - thumbnail_generated - thumbnail_failed)

    scan_state = get_scan_state()
    last_library_scan = LastLibraryScanSummary(
        status=scan_state.status,
        started_at=scan_state.started_at,
        finished_at=scan_state.finished_at,
        scanned_files=scan_state.scanned_files,
        detected_videos=scan_state.detected_videos,
        probe_failed=scan_state.probe_failed,
        ignored_non_media=scan_state.ignored_non_media,
        ignored_excluded=scan_state.ignored_excluded,
        thumbnail_errors=scan_state.thumbnail_errors,
    )

    duplicate_summary = load_duplicate_summary(db, mode="strict")
    finished_at = duplicate_summary.get("last_scan_at")
    last_duplicate_scan = LastDuplicateScanSummary(
        status=str(duplicate_summary.get("last_scan_status", "idle")),
        candidate_groups_found=int(duplicate_summary.get("candidate_groups_found", 0) or 0),
        potential_saving=int(duplicate_summary.get("potential_saving", 0) or 0),
        finished_at=datetime.fromisoformat(str(finished_at)) if finished_at else None,
    )

    profile_stats = media_profile_stats(db)

    return LibrarySummaryOut(
        total_indexed=int(total_indexed),
        detected_videos=int(detected_videos),
        probe_failed_possible_video=int(probe_failed_possible_video),
        direct_play=int(direct_play),
        may_play=int(may_play),
        may_not_play=int(may_not_play),
        needs_conversion=int(needs_conversion),
        unknown_compatibility=int(unknown_compatibility),
        thumbnail_generated=int(thumbnail_generated),
        thumbnail_failed=int(thumbnail_failed),
        thumbnail_missing=int(thumbnail_missing),
        total_size=int(total_size),
        media_profiles_total=profile_stats["media_profiles_total"],
        media_profiles_manual_checked=profile_stats["media_profiles_manual_checked"],
        media_profiles_pending_manual_check=profile_stats["media_profiles_pending_manual_check"],
        media_profiles_playable=profile_stats["media_profiles_playable"],
        media_profiles_not_playable=profile_stats["media_profiles_not_playable"],
        media_profiles_partially_playable=profile_stats["media_profiles_partially_playable"],
        media_profiles_unknown=profile_stats["media_profiles_unknown"],
        last_library_scan=last_library_scan,
        last_duplicate_scan=last_duplicate_scan,
    )

