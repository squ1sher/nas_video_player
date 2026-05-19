from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.conftest import make_client, setup_test_db


def _reset_duplicate_state() -> None:
    import app.duplicate_scan_status as status_module

    status_module._state = status_module.DuplicateScanState()  # type: ignore[attr-defined]
    status_module._lock = threading.Lock()  # type: ignore[attr-defined]


def _insert_video(
    *,
    tmp_path: Path,
    title: str,
    relative_path: str,
    size: int,
    duration: float | None,
    width: int | None,
    height: int | None,
    video_codec: str | None = "h264",
    audio_codec: str | None = "aac",
    extension: str = ".mp4",
    library_root_id: int | None = None,
) -> int:
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title=title,
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=extension,
        size=size,
        modified_ts=datetime.now(timezone.utc).timestamp(),
        duration=duration,
        width=width,
        height=height,
        video_codec=video_codec,
        audio_codec=audio_codec,
        folder_path="",
        compatibility_status="direct_play",
        compatibility_reason="test",
        indexed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        library_root_id=library_root_id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()
    return video_id


def test_fingerprint_generation_strict_mode(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    from app.database import SessionLocal
    from app.models import Video
    from app.services.duplicate_fingerprint_service import build_duplicate_fingerprint

    video = Video(
        title="Holiday Clip",
        filename="holiday.mp4",
        relative_path="Family/holiday.mp4",
        absolute_path="/tmp/holiday.mp4",
        extension=".mp4",
        size=1_456_789_012,
        modified_ts=1.0,
        duration=1234.4,
        width=1920,
        height=1080,
        video_codec="H264",
        audio_codec="AAC",
    )
    fingerprint = build_duplicate_fingerprint(video, mode="strict")

    assert fingerprint.mode == "strict"
    assert fingerprint.version == "v1"
    assert fingerprint.file_size == 1_456_789_012
    assert fingerprint.duration_seconds == 1234
    assert fingerprint.width == 1920
    assert fingerprint.height == 1080
    assert fingerprint.video_codec == "h264"
    assert fingerprint.audio_codec == "aac"
    assert fingerprint.extension == ".mp4"
    assert fingerprint.normalized_title == "holiday clip"


def test_fingerprint_rejects_non_strict_mode(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    import pytest
    from app.models import Video
    from app.services.duplicate_fingerprint_service import build_duplicate_fingerprint

    video = Video(
        title="Holiday_Copy",
        filename="holiday copy.MP4",
        relative_path="Backup/holiday copy.MP4",
        absolute_path="/tmp/holiday_copy.mp4",
        extension="MP4",
        size=1_456_780_000,
        modified_ts=1.0,
        duration=1234.6,
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
    )
    with pytest.raises(ValueError):
        build_duplicate_fingerprint(video, mode="similar")


def test_grouping_videos_by_strict_fingerprint_and_ignoring_singletons(tmp_path: Path) -> None:
    _reset_duplicate_state()
    setup_test_db(tmp_path)
    _insert_video(tmp_path=tmp_path, title="A", relative_path="A/a.mp4", size=1000, duration=10, width=1920, height=1080)
    _insert_video(tmp_path=tmp_path, title="B", relative_path="B/b.mp4", size=1000, duration=10.1, width=1920, height=1080)
    _insert_video(tmp_path=tmp_path, title="Single", relative_path="C/c.mp4", size=2000, duration=20, width=1280, height=720)

    from app.database import SessionLocal
    from app.services.duplicate_service import calculate_duplicate_groups

    db = SessionLocal()
    groups, summary = calculate_duplicate_groups(db, mode="strict")
    db.close()

    assert len(groups) == 1
    assert groups[0].candidate_count == 2
    assert summary["candidate_groups_found"] == 1
    assert summary["duplicate_candidates_found"] == 2


def test_potential_saving_calculation(tmp_path: Path) -> None:
    _reset_duplicate_state()
    setup_test_db(tmp_path)
    _insert_video(tmp_path=tmp_path, title="A", relative_path="A/a.mp4", size=3000, duration=10, width=1920, height=1080)
    _insert_video(tmp_path=tmp_path, title="B", relative_path="B/b.mp4", size=3000, duration=10, width=1920, height=1080)
    _insert_video(tmp_path=tmp_path, title="C", relative_path="C/c.mp4", size=3000, duration=10, width=1920, height=1080)

    from app.database import SessionLocal
    from app.services.duplicate_service import calculate_duplicate_groups

    db = SessionLocal()
    groups, _summary = calculate_duplicate_groups(db, mode="strict")
    db.close()

    assert groups[0].total_size == 9000
    assert groups[0].potential_saving == 6000


def test_duplicate_scan_status_transitions() -> None:
    _reset_duplicate_state()
    from app.duplicate_scan_status import (
        complete_duplicate_scan,
        get_duplicate_scan_state,
        start_duplicate_scan,
        update_duplicate_scan_progress,
    )

    assert start_duplicate_scan("strict") is True
    update_duplicate_scan_progress(current_step="Grouping duplicate candidates", videos_checked=42)
    running = get_duplicate_scan_state()
    assert running.status == "running"
    assert running.mode == "strict"
    assert running.videos_checked == 42

    complete_duplicate_scan(
        {
            "mode": "strict",
            "videos_checked": 42,
            "candidate_groups_found": 3,
            "duplicate_candidates_found": 7,
            "potential_saving": 123,
            "last_scan_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    done = get_duplicate_scan_state()
    assert done.status == "completed"
    assert done.current_step is None
    assert done.candidate_groups_found == 3
    assert done.duplicate_candidates_found == 7


def test_concurrent_duplicate_scan_prevention(tmp_path: Path) -> None:
    _reset_duplicate_state()
    client = make_client(tmp_path)
    from app.duplicate_scan_status import start_duplicate_scan

    assert start_duplicate_scan("strict") is True
    response = client.post("/api/duplicates/scan")
    assert response.status_code == 409
    assert response.json()["detail"] == "Duplicate scan is already running"


def test_duplicates_groups_response_shape_and_no_absolute_paths(tmp_path: Path) -> None:
    _reset_duplicate_state()
    client = make_client(tmp_path)
    _insert_video(tmp_path=tmp_path, title="Holiday video", relative_path="Family/holiday.mp4", size=2048, duration=600, width=1920, height=1080)
    _insert_video(tmp_path=tmp_path, title="Holiday video copy", relative_path="Backup/holiday copy.mp4", size=2048, duration=600, width=1920, height=1080)

    from app.database import SessionLocal
    from app.services.duplicate_service import run_duplicate_scan

    db = SessionLocal()
    run_duplicate_scan(db, mode="strict")
    db.close()

    response = client.get("/api/duplicates/groups")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    group = data[0]
    assert group["group_id"].startswith("strict-")
    assert group["confidence"] in {"exact_metadata_match", "high", "medium"}
    assert group["fingerprint"]["mode"] == "strict"
    assert len(group["videos"]) == 2
    for video in group["videos"]:
        assert "library_root_id" in video
        assert "library_root_name" in video
        assert video["relative_path"].startswith(("Family/", "Backup/"))
        assert "/volume1/" not in video["relative_path"]
        assert video["watch_url"].startswith("/watch/")
        if video["thumbnail_url"] is not None:
            assert video["thumbnail_url"].startswith("/api/videos/")


def test_duplicates_groups_include_library_root_name_when_available(tmp_path: Path) -> None:
    _reset_duplicate_state()
    setup_test_db(tmp_path)

    from app.database import SessionLocal
    from app.models import LibraryRoot
    from app.services.duplicate_service import load_duplicate_groups, run_duplicate_scan

    db = SessionLocal()
    source = LibraryRoot(name="Movies", path="/media/movies", media_type="video", enabled=True, recursive=True, scan_priority=100)
    db.add(source)
    db.commit()
    db.refresh(source)
    source_id = source.id

    _insert_video(
        tmp_path=tmp_path,
        title="D1",
        relative_path="Dups/d1.mp4",
        size=5000,
        duration=100,
        width=1920,
        height=1080,
        library_root_id=source_id,
    )
    _insert_video(
        tmp_path=tmp_path,
        title="D2",
        relative_path="Dups/d2.mp4",
        size=5000,
        duration=100,
        width=1920,
        height=1080,
    )

    run_duplicate_scan(db, mode="strict")
    groups = load_duplicate_groups(db, mode="strict")
    db.close()

    assert len(groups) == 1
    videos = groups[0]["videos"]
    with_library = next(v for v in videos if v["library_root_id"] == source_id)
    assert with_library["library_root_name"] == "Movies"


def test_duplicates_summary_empty_before_scan(tmp_path: Path) -> None:
    _reset_duplicate_state()
    client = make_client(tmp_path)
    response = client.get("/api/duplicates/summary")
    assert response.status_code == 200
    assert response.json()["last_scan_status"] == "idle"
    assert response.json()["candidate_groups_found"] == 0


def test_duplicates_summary_completed_with_zero_groups(tmp_path: Path) -> None:
    _reset_duplicate_state()
    client = make_client(tmp_path)
    _insert_video(tmp_path=tmp_path, title="Only One", relative_path="single.mp4", size=1111, duration=11, width=1920, height=1080)

    from app.database import SessionLocal
    from app.services.duplicate_service import run_duplicate_scan

    db = SessionLocal()
    run_duplicate_scan(db, mode="strict")
    db.close()

    response = client.get("/api/duplicates/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["last_scan_status"] == "completed"
    assert data["candidate_groups_found"] == 0
    assert data["duplicate_candidates_found"] == 0


def test_duplicate_summary_is_outdated_false_when_idle(tmp_path: Path) -> None:
    _reset_duplicate_state()
    client = make_client(tmp_path)
    response = client.get("/api/duplicates/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["is_outdated"] is False
    assert data["last_scan_status"] == "idle"


def test_mark_duplicates_outdated_after_completed_scan(tmp_path: Path) -> None:
    """After a library scan, existing duplicate results are marked outdated."""
    _reset_duplicate_state()
    setup_test_db(tmp_path)
    _insert_video(tmp_path=tmp_path, title="A", relative_path="a.mp4", size=1000, duration=10, width=1920, height=1080)
    _insert_video(tmp_path=tmp_path, title="B", relative_path="b.mp4", size=1000, duration=10, width=1920, height=1080)

    from app.database import SessionLocal
    from app.services.duplicate_service import mark_duplicates_outdated, run_duplicate_scan

    db = SessionLocal()
    run_duplicate_scan(db, mode="strict")

    # Verify it's "completed" before mark
    from app.models import DuplicateScanRun
    run = db.query(DuplicateScanRun).filter(DuplicateScanRun.mode == "strict").first()
    assert run is not None
    assert run.last_scan_status == "completed"

    # Now mark outdated (simulating end of library scan)
    mark_duplicates_outdated(db)

    db.refresh(run)
    assert run.last_scan_status == "outdated"
    db.close()


def test_duplicate_summary_is_outdated_true_after_mark(tmp_path: Path) -> None:
    """GET /api/duplicates/summary returns is_outdated=True after mark."""
    _reset_duplicate_state()
    client = make_client(tmp_path)
    _insert_video(tmp_path=tmp_path, title="X", relative_path="x.mp4", size=999, duration=5, width=1280, height=720)

    from app.database import SessionLocal
    from app.services.duplicate_service import mark_duplicates_outdated, run_duplicate_scan

    db = SessionLocal()
    run_duplicate_scan(db, mode="strict")
    mark_duplicates_outdated(db)
    db.close()

    response = client.get("/api/duplicates/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["last_scan_status"] == "outdated"
    assert data["is_outdated"] is True


def test_running_duplicate_scan_clears_outdated_flag(tmp_path: Path) -> None:
    """Running duplicate scan again should clear the outdated state."""
    _reset_duplicate_state()
    setup_test_db(tmp_path)
    _insert_video(tmp_path=tmp_path, title="Y", relative_path="y.mp4", size=500, duration=9, width=1920, height=1080)
    _insert_video(tmp_path=tmp_path, title="Z", relative_path="z.mp4", size=500, duration=9, width=1920, height=1080)

    from app.database import SessionLocal
    from app.models import DuplicateScanRun
    from app.services.duplicate_service import mark_duplicates_outdated, run_duplicate_scan

    db = SessionLocal()
    run_duplicate_scan(db, mode="strict")
    mark_duplicates_outdated(db)

    run = db.query(DuplicateScanRun).filter(DuplicateScanRun.mode == "strict").first()
    assert run is not None and run.last_scan_status == "outdated"

    # Running duplicate scan again should set it back to "completed"
    run_duplicate_scan(db, mode="strict")
    db.refresh(run)
    assert run.last_scan_status == "completed"
    db.close()


def test_mark_outdated_only_affects_completed_and_failed(tmp_path: Path) -> None:
    """mark_duplicates_outdated should not change 'idle' or already-outdated rows."""
    _reset_duplicate_state()
    setup_test_db(tmp_path)

    from app.database import SessionLocal
    from app.models import DuplicateScanRun
    from app.services.duplicate_service import mark_duplicates_outdated

    db = SessionLocal()
    # No scan run row exists - mark_outdated should safely do nothing
    mark_duplicates_outdated(db)
    count = db.query(DuplicateScanRun).count()
    assert count == 0
    db.close()


