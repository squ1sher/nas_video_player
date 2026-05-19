"""Tests for Phase 2.6 – Maintenance cleanup and video deletion cascade."""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.conftest import make_client, setup_test_db


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_video(tmp_path: Path, *, name: str = "sample", with_file: bool = True) -> int:
    """Insert a video row and optionally create the source file on disk."""
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    source_file = videos_dir / f"{name}.mp4"
    if with_file:
        source_file.write_bytes(b"fake-media-content")

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title=f"Test {name}",
        filename=f"{name}.mp4",
        relative_path=f"{name}.mp4",
        absolute_path=str(source_file),
        extension=".mp4",
        size=source_file.stat().st_size if with_file else 1024,
        modified_ts=time.time(),
        duration=60.0,
        width=1920,
        height=1080,
        video_codec="h264",
        audio_codec="aac",
        folder_path="",
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    vid_id = video.id
    db.close()
    return vid_id


def _make_hls_folder(tmp_path: Path, video_id: int) -> Path:
    """Create a fake HLS folder for *video_id*."""
    hls_root = tmp_path / "cache" / "hls"
    hls_dir = hls_root / str(video_id)
    hls_dir.mkdir(parents=True, exist_ok=True)
    (hls_dir / "master.m3u8").write_text("#EXTM3U\nmaster\n")
    q = hls_dir / "480p"
    q.mkdir(exist_ok=True)
    (q / "index.m3u8").write_text("#EXTM3U\nseg\n")
    (q / "segment_000.ts").write_bytes(b"\x00" * 1024)
    return hls_dir


def _make_thumbnail(tmp_path: Path, name: str) -> Path:
    """Create a fake thumbnail file and return its path."""
    thumb_dir = tmp_path / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb = thumb_dir / name
    thumb.write_bytes(b"fake-jpg")
    return thumb


def _add_thumbnail_to_video(video_id: int, thumb_name: str) -> None:
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    db.query(Video).filter(Video.id == video_id).update(
        {"thumbnail_path": thumb_name, "thumbnail_status": "generated"}
    )
    db.commit()
    db.close()


# ── Test: video delete removes HLS cache ──────────────────────────────────────

def test_delete_video_removes_hls_cache(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="vid1")
    hls_dir = _make_hls_folder(tmp_path, vid_id)

    assert hls_dir.exists()

    client = make_client(tmp_path)
    resp = client.delete(f"/api/videos/{vid_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert not hls_dir.exists(), "HLS folder should have been deleted"


# ── Test: video delete removes thumbnail ──────────────────────────────────────

def test_delete_video_removes_thumbnail(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="vid2")
    thumb = _make_thumbnail(tmp_path, "vid2.mp4.jpg")
    _add_thumbnail_to_video(vid_id, "vid2.mp4.jpg")

    assert thumb.exists()

    client = make_client(tmp_path)
    resp = client.delete(f"/api/videos/{vid_id}")
    assert resp.status_code == 200, resp.text
    assert not thumb.exists(), "Thumbnail should have been deleted"


# ── Test: video delete removes VideoVariant DB records ────────────────────────

def test_delete_video_removes_variant_records(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="vid3")

    from app.database import SessionLocal
    from app.models import VideoVariant

    db = SessionLocal()
    db.add(VideoVariant(video_id=vid_id, variant_type="hls_master", status="completed"))
    db.add(VideoVariant(video_id=vid_id, variant_type="hls_480p", status="completed", quality_label="480p"))
    db.commit()
    db.close()

    client = make_client(tmp_path)
    resp = client.delete(f"/api/videos/{vid_id}")
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    count = db.query(VideoVariant).filter(VideoVariant.video_id == vid_id).count()
    db.close()
    assert count == 0, "VideoVariant records should be deleted"


# ── Test: failed source deletion does not remove HLS cache or DB ──────────────

def test_delete_video_fails_gracefully_if_no_source(tmp_path: Path) -> None:
    """Source path doesn't exist, but delete_file=True: should succeed (no file to delete)."""
    setup_test_db(tmp_path)
    # Create video WITHOUT source file on disk
    vid_id = _make_video(tmp_path, name="ghost", with_file=False)
    hls_dir = _make_hls_folder(tmp_path, vid_id)

    client = make_client(tmp_path)
    # When source file doesn't exist, deletion should still proceed
    resp = client.delete(f"/api/videos/{vid_id}?delete_file=true")
    assert resp.status_code == 200, resp.text
    # HLS cache should be cleaned up even if source was already gone
    assert not hls_dir.exists()


# ── Test: cleanup summary detects orphan HLS folder ──────────────────────────

def test_cleanup_summary_detects_orphan_hls(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    # Create HLS folder for a video_id that doesn't exist in DB
    hls_root = tmp_path / "cache" / "hls"
    orphan_dir = hls_root / "99999"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "master.m3u8").write_text("fake")

    resp = client.get("/api/maintenance/cleanup/summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["hls"]["orphan_hls_folders"] >= 1


# ── Test: cleanup summary detects DB completed but missing HLS files ──────────

def test_cleanup_summary_detects_db_completed_missing_files(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="stale_hls")

    from app.database import SessionLocal
    from app.models import VideoVariant

    db = SessionLocal()
    db.add(VideoVariant(video_id=vid_id, variant_type="hls_master", status="completed", quality_label="master"))
    db.commit()
    db.close()

    client = make_client(tmp_path)
    resp = client.get("/api/maintenance/cleanup/summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # DB says completed but no HLS files exist → should be flagged
    assert data["hls"]["db_completed_but_files_missing"] >= 1


# ── Test: cleanup plan includes safe orphan HLS ───────────────────────────────

def test_cleanup_plan_includes_orphan_hls(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    hls_root = tmp_path / "cache" / "hls"
    orphan_dir = hls_root / "88888"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "master.m3u8").write_text("fake")

    resp = client.post("/api/maintenance/cleanup/plan", json={"include": {"orphan_hls_folders": True}})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plan_id"]
    assert data["dry_run"] is True
    types = [i["type"] for i in data["items"]]
    assert "orphan_hls_folder" in types


# ── Test: cleanup apply deletes selected orphan HLS folder ────────────────────

def test_cleanup_apply_deletes_orphan_hls(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    hls_root = tmp_path / "cache" / "hls"
    orphan_dir = hls_root / "77777"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "master.m3u8").write_text("fake")

    assert orphan_dir.exists()

    # Plan
    plan_resp = client.post("/api/maintenance/cleanup/plan", json={"include": {"orphan_hls_folders": True}})
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    plan_id = plan["plan_id"]
    item_ids = [i["item_id"] for i in plan["items"] if i["type"] == "orphan_hls_folder"]
    assert item_ids

    # Apply
    apply_resp = client.post("/api/maintenance/cleanup/apply", json={"plan_id": plan_id, "items": item_ids})
    assert apply_resp.status_code == 200, apply_resp.text
    result = apply_resp.json()
    assert result["deleted_folders"] >= 1
    assert not orphan_dir.exists()


# ── Test: cleanup does NOT delete original media files ────────────────────────

def test_cleanup_apply_never_deletes_original_media(tmp_path: Path) -> None:
    """Generic cleanup should never touch original video files."""
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="precious")
    source_file = tmp_path / "videos" / "precious.mp4"
    assert source_file.exists()

    client = make_client(tmp_path)
    plan_resp = client.post(
        "/api/maintenance/cleanup/plan",
        json={"include": {"orphan_hls_folders": True, "orphan_thumbnails": True, "stale_hls_jobs": True}},
    )
    assert plan_resp.status_code == 200
    plan = plan_resp.json()
    plan_id = plan["plan_id"]

    apply_resp = client.post("/api/maintenance/cleanup/apply", json={"plan_id": plan_id})
    assert apply_resp.status_code == 200
    assert source_file.exists(), "Original media file MUST NOT be deleted by generic cleanup"
    _ = vid_id  # suppress unused


# ── Test: cleanup does NOT delete HLS for source_removed by default ───────────

def test_cleanup_plan_excludes_source_removed_hls_by_default(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="removed")
    _make_hls_folder(tmp_path, vid_id)

    # Mark video as source_removed
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    db.query(Video).filter(Video.id == vid_id).update({"availability_status": "source_removed"})
    db.commit()
    db.close()

    client = make_client(tmp_path)
    # Default plan: source_removed_hls is False
    plan_resp = client.post(
        "/api/maintenance/cleanup/plan",
        json={"include": {"orphan_hls_folders": True, "source_removed_hls": False}},
    )
    assert plan_resp.status_code == 200
    plan = plan_resp.json()
    types = [i["type"] for i in plan["items"]]
    # The source_removed video's HLS should NOT appear as an orphan or source_removed_hls
    source_removed_items = [i for i in plan["items"] if i.get("video_id") == vid_id]
    assert not source_removed_items, "source_removed video HLS should not be in default plan"


# ── Test: removing media source marks videos source_removed ───────────────────

def test_delete_media_source_marks_videos_source_removed(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import LibraryRoot, Video

    # Create a library root
    db = SessionLocal()
    root = LibraryRoot(name="Test Source", path="/tmp/test_src", media_type="video", enabled=True, recursive=True, scan_priority=100)
    db.add(root)
    db.commit()
    db.refresh(root)
    root_id = root.id

    # Create a video under this root
    video = Video(
        title="Source Video",
        filename="src.mp4",
        relative_path="src.mp4",
        absolute_path="/tmp/test_src/src.mp4",
        extension=".mp4",
        size=1024,
        modified_ts=time.time(),
        library_root_id=root_id,
        folder_path="",
    )
    db.add(video)
    db.commit()
    vid_id = video.id
    db.close()

    # Delete the media source
    resp = client.delete(f"/api/settings/media-sources/{root_id}")
    assert resp.status_code == 200, resp.text

    # Video should be marked source_removed
    db = SessionLocal()
    v = db.query(Video).filter(Video.id == vid_id).first()
    assert v is not None
    assert v.availability_status == "source_removed"
    assert v.library_root_id is None
    db.close()


# ── Test: source_removed videos hidden from normal library ────────────────────

def test_source_removed_videos_hidden_from_library(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="hidden_vid")

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    db.query(Video).filter(Video.id == vid_id).update({"availability_status": "source_removed"})
    db.commit()
    db.close()

    client = make_client(tmp_path)
    resp = client.get("/api/videos")
    assert resp.status_code == 200
    ids = [v["id"] for v in resp.json()]
    assert vid_id not in ids, "source_removed video should not appear in normal library"


# ── Test: stale duplicate items are cleaned up ────────────────────────────────

def test_stale_duplicate_items_cleaned_up(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    client = make_client(tmp_path)

    from app.database import SessionLocal
    from app.models import DuplicateCandidateGroup, DuplicateCandidateItem

    # Create a duplicate group pointing to a non-existent video_id
    db = SessionLocal()
    grp = DuplicateCandidateGroup(
        group_key="orphan_key",
        mode="strict",
        confidence="high",
        reason="test",
        candidate_count=1,
        total_size=0,
        potential_saving=0,
        fingerprint_json="{}",
    )
    db.add(grp)
    db.commit()
    db.refresh(grp)

    orphan_item = DuplicateCandidateItem(group_id=grp.id, video_id=999999)
    db.add(orphan_item)
    db.commit()
    orphan_item_id = orphan_item.id
    db.close()

    # Plan and apply stale duplicate cleanup
    plan_resp = client.post(
        "/api/maintenance/cleanup/plan",
        json={"include": {"stale_duplicate_records": True}},
    )
    assert plan_resp.status_code == 200
    plan = plan_resp.json()
    plan_id = plan["plan_id"]
    item_ids = [i["item_id"] for i in plan["items"]]

    apply_resp = client.post("/api/maintenance/cleanup/apply", json={"plan_id": plan_id, "items": item_ids})
    assert apply_resp.status_code == 200

    db = SessionLocal()
    remaining = db.query(DuplicateCandidateItem).filter(DuplicateCandidateItem.id == orphan_item_id).first()
    db.close()
    assert remaining is None, "Stale duplicate item should have been deleted"


# ── Test: video delete removes duplicate candidate records ────────────────────

def test_delete_video_removes_duplicate_records(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="dup_vid")
    vid_id2 = _make_video(tmp_path, name="dup_vid2")

    from app.database import SessionLocal
    from app.models import DuplicateCandidateGroup, DuplicateCandidateItem

    db = SessionLocal()
    grp = DuplicateCandidateGroup(
        group_key="dup_test",
        mode="strict",
        confidence="high",
        reason="test dup",
        candidate_count=2,
        total_size=2048,
        potential_saving=1024,
        fingerprint_json="{}",
    )
    db.add(grp)
    db.commit()
    db.refresh(grp)
    db.add(DuplicateCandidateItem(group_id=grp.id, video_id=vid_id))
    db.add(DuplicateCandidateItem(group_id=grp.id, video_id=vid_id2))
    db.commit()
    db.close()

    client = make_client(tmp_path)
    resp = client.delete(f"/api/videos/{vid_id}")
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    remaining = db.query(DuplicateCandidateItem).filter(DuplicateCandidateItem.video_id == vid_id).all()
    db.close()
    assert len(remaining) == 0, "DuplicateCandidateItem rows should be removed when video is deleted"


# ── Test: HLS repair does not delete files ────────────────────────────────────

def test_hls_repair_does_not_delete_files(tmp_path: Path) -> None:
    """Repair reconciles DB/FS state but never removes HLS files."""
    setup_test_db(tmp_path)
    vid_id = _make_video(tmp_path, name="repair_test")
    hls_dir = _make_hls_folder(tmp_path, vid_id)

    client = make_client(tmp_path)
    resp = client.post("/api/hls/repair")
    assert resp.status_code == 200, resp.text

    # HLS files must still be there
    assert hls_dir.exists(), "Repair must not delete HLS files"
    assert (hls_dir / "master.m3u8").exists()

