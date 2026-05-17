from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client


def _create_video_with_file(
    tmp_path: Path,
    *,
    height: int = 1080,
    width: int = 1920,
    stem: str = "sample",
) -> int:
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    source_file = videos_dir / f"{stem}.mp4"
    source_file.write_bytes(b"fake-media")

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title=f"Sample {stem}",
        filename=f"{stem}.mp4",
        relative_path=f"{stem}.mp4",
        absolute_path=str(source_file),
        extension=".mp4",
        size=source_file.stat().st_size,
        modified_ts=time.time(),
        duration=90.0,
        width=width,
        height=height,
        video_codec="h264",
        audio_codec="aac",
        folder_path="",
        compatibility_status="direct_play",
        compatibility_reason="ok",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()
    return video_id


def _create_video_record_without_file(tmp_path: Path, name: str) -> int:
    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title=name,
        filename=f"{name}.mp4",
        relative_path=f"{name}.mp4",
        absolute_path=str(tmp_path / "videos" / f"{name}.mp4"),
        extension=".mp4",
        size=123,
        modified_ts=time.time(),
        duration=50.0,
        width=1280,
        height=720,
        video_codec="h264",
        audio_codec="aac",
        folder_path="",
        compatibility_status="direct_play",
        compatibility_reason="ok",
        indexed_at=datetime.now(timezone.utc),
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    vid = video.id
    db.close()
    return vid


def _mark_db_hls_completed_without_files(video_id: int) -> None:
    from app.database import SessionLocal
    from app.models import VideoVariant

    db = SessionLocal()
    db.add(VideoVariant(video_id=video_id, variant_type="hls_master", status="completed", quality_label="master"))
    db.add(VideoVariant(video_id=video_id, variant_type="hls_480p", status="completed", quality_label="480p"))
    db.commit()
    db.close()


def _hls_root(tmp_path: Path, video_id: int) -> Path:
    return tmp_path / "cache" / "hls" / str(video_id)


def _write_valid_hls_tree(tmp_path: Path, video_id: int, quality: str = "480p") -> None:
    root = _hls_root(tmp_path, video_id)
    qdir = root / quality
    qdir.mkdir(parents=True, exist_ok=True)
    (root / "master.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480\n480p/index.m3u8\n",
        encoding="utf-8",
    )
    (qdir / "index.m3u8").write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4.0,\nsegment_000.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    (qdir / "segment_000.ts").write_bytes(b"segment-data")


def _install_fake_ffmpeg(monkeypatch):
    import app.services.hls_service as hls_service

    class DummyResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text):
        playlist_path = Path(cmd[-1])
        segment_pattern = None
        for i, token in enumerate(cmd):
            if token == "-hls_segment_filename":
                segment_pattern = Path(cmd[i + 1])
                break

        playlist_path.parent.mkdir(parents=True, exist_ok=True)
        playlist_path.write_text(
            "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4.0,\nsegment_000.ts\n#EXT-X-ENDLIST\n",
            encoding="utf-8",
        )
        if segment_pattern is not None:
            segment_path = Path(str(segment_pattern).replace("%03d", "000"))
            segment_path.parent.mkdir(parents=True, exist_ok=True)
            segment_path.write_bytes(b"ts")
        return DummyResult()

    monkeypatch.setattr(hls_service.subprocess, "run", fake_run)


def _install_slow_fake_ffmpeg(monkeypatch, delay_sec: float = 0.5):
    import app.services.hls_service as hls_service

    class DummyResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text):
        time.sleep(delay_sec)
        playlist_path = Path(cmd[-1])
        playlist_path.parent.mkdir(parents=True, exist_ok=True)
        playlist_path.write_text(
            "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4.0,\nsegment_000.ts\n#EXT-X-ENDLIST\n",
            encoding="utf-8",
        )
        (playlist_path.parent / "segment_000.ts").write_bytes(b"ts")
        return DummyResult()

    monkeypatch.setattr(hls_service.subprocess, "run", fake_run)


def _wait_for_completion(client, video_id: int, timeout_sec: float = 4.0):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status = client.get(f"/api/videos/{video_id}/hls/status")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for HLS job")


def _wait_batch_done(client, batch_id: int, timeout_sec: float = 8.0):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        response = client.get(f"/api/hls/batches/{batch_id}?include_items=false")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
            return payload
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for HLS batch")


def test_hls_job_creation_and_status_flow(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    response = client.post(
        f"/api/videos/{video_id}/hls/prepare",
        json={"force": False, "qualities": ["480p", "720p", "1080p"]},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "started"

    done = _wait_for_completion(client, video_id)
    assert done["status"] == "completed"
    assert done["master_playlist_url"] == f"/api/videos/{video_id}/hls/master.m3u8"


def test_prevent_duplicate_running_job(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    from app.database import SessionLocal
    from app.models import HlsJob

    db = SessionLocal()
    db.add(HlsJob(video_id=video_id, status="running"))
    db.commit()
    db.close()

    response = client.post(f"/api/videos/{video_id}/hls/prepare", json={"force": False, "qualities": ["480p"]})
    assert response.status_code == 409


def test_hls_does_not_upscale_above_source(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, height=720, width=1280)

    response = client.post(
        f"/api/videos/{video_id}/hls/prepare",
        json={"force": False, "qualities": ["480p", "720p", "1080p"]},
    )
    assert response.status_code == 202

    done = _wait_for_completion(client, video_id)
    assert done["status"] == "completed"
    assert done["available_qualities"] == ["480p", "720p"]


def test_hls_playlist_and_segment_content_types(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    client.post(f"/api/videos/{video_id}/hls/prepare", json={"force": False, "qualities": ["480p"]})
    done = _wait_for_completion(client, video_id)
    assert done["status"] == "completed"

    master = client.get(f"/api/videos/{video_id}/hls/master.m3u8")
    assert master.status_code == 200
    assert master.headers["content-type"].startswith("application/vnd.apple.mpegurl")

    index = client.get(f"/api/videos/{video_id}/hls/480p/index.m3u8")
    assert index.status_code == 200
    assert index.headers["content-type"].startswith("application/vnd.apple.mpegurl")

    seg = client.get(f"/api/videos/{video_id}/hls/480p/segment_000.ts")
    assert seg.status_code == 200
    assert seg.headers["content-type"].startswith("video/mp2t")


def test_hls_segment_path_validation(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    client.post(f"/api/videos/{video_id}/hls/prepare", json={"force": False, "qualities": ["480p"]})
    _wait_for_completion(client, video_id)

    invalid = client.get(f"/api/videos/{video_id}/hls/480p/evil.ts")
    assert invalid.status_code == 400


def test_playback_source_prefers_hls_when_ready(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    original = client.get(f"/api/videos/{video_id}/playback-source")
    assert original.status_code == 200
    assert original.json()["source_type"] == "original"

    client.post(f"/api/videos/{video_id}/hls/prepare", json={"force": False, "qualities": ["480p"]})
    done = _wait_for_completion(client, video_id)
    assert done["status"] == "completed"

    hls = client.get(f"/api/videos/{video_id}/playback-source")
    assert hls.status_code == 200
    assert hls.json()["source_type"] == "hls"


def test_playback_source_none_for_missing_source(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)
    source = tmp_path / "videos" / "sample.mp4"
    source.unlink()

    response = client.get(f"/api/videos/{video_id}/playback-source")
    assert response.status_code == 200
    assert response.json()["source_type"] == "none"


def test_hls_global_status_and_jobs_endpoints(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    client.post(f"/api/videos/{video_id}/hls/prepare", json={"force": False, "qualities": ["480p"]})
    _wait_for_completion(client, video_id)

    jobs = client.get("/api/hls/jobs")
    assert jobs.status_code == 200
    assert len(jobs.json()) >= 1

    status = client.get("/api/hls/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["max_concurrent"] == 1


def test_hls_force_reprepare_starts_new_job(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    first = client.post(
        f"/api/videos/{video_id}/hls/prepare",
        json={"force": False, "qualities": ["480p"]},
    )
    assert first.status_code == 202
    done_first = _wait_for_completion(client, video_id)
    assert done_first["status"] == "completed"

    second = client.post(
        f"/api/videos/{video_id}/hls/prepare",
        json={"force": False, "qualities": ["480p"]},
    )
    assert second.status_code == 202
    assert second.json()["status"] == "completed"

    forced = client.post(
        f"/api/videos/{video_id}/hls/prepare",
        json={"force": True, "qualities": ["480p"]},
    )
    assert forced.status_code == 202
    assert forced.json()["status"] == "started"

    done_forced = _wait_for_completion(client, video_id)
    assert done_forced["status"] == "completed"

    jobs = client.get("/api/hls/jobs")
    assert jobs.status_code == 200
    assert len(jobs.json()) >= 2


def test_library_batch_queues_missing_hls_and_skips_existing(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    with_hls = _create_video_with_file(tmp_path, stem="with_hls")
    missing_hls = _create_video_with_file(tmp_path, stem="missing_hls")

    client.post(f"/api/videos/{with_hls}/hls/prepare", json={"force": False, "qualities": ["480p"]})
    _wait_for_completion(client, with_hls)

    response = client.post(
        "/api/hls/batches/library",
        json={"qualities": ["480p"], "skip_existing": True, "force": False, "only_missing_hls": True},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["queued_count"] == 1
    assert payload["skipped_existing_hls"] >= 1

    done = _wait_batch_done(client, payload["batch_id"])
    assert done["completed_count"] == 1


def test_library_batch_force_true_enqueues_existing_hls(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    client.post(f"/api/videos/{video_id}/hls/prepare", json={"force": False, "qualities": ["480p"]})
    _wait_for_completion(client, video_id)

    response = client.post(
        "/api/hls/batches/library",
        json={"qualities": ["480p"], "skip_existing": False, "force": True, "only_missing_hls": False},
    )
    assert response.status_code == 202
    assert response.json()["queued_count"] >= 1


def test_library_batch_skips_missing_source(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    _create_video_with_file(tmp_path)
    _create_video_record_without_file(tmp_path, "missing")

    response = client.post("/api/hls/batches/library", json={"qualities": ["480p"]})
    assert response.status_code == 202
    payload = response.json()
    assert payload["skipped_missing_source"] >= 1


def test_library_batch_status_supports_include_items_false(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    _create_video_with_file(tmp_path)

    response = client.post("/api/hls/batches/library", json={"qualities": ["480p"]})
    batch_id = response.json()["batch_id"]
    assert batch_id is not None

    detail = client.get(f"/api/hls/batches/{batch_id}?include_items=false")
    assert detail.status_code == 200
    assert detail.json()["items"] == []


def test_hls_status_exposes_active_batch(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    _create_video_with_file(tmp_path)

    response = client.post("/api/hls/batches/library", json={"qualities": ["480p"]})
    batch_id = response.json()["batch_id"]
    assert batch_id is not None

    status = client.get("/api/hls/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["active_batch_id"] == batch_id


def test_library_batch_skips_already_running_video(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path)

    from app.database import SessionLocal
    from app.models import HlsJob

    db = SessionLocal()
    db.add(HlsJob(video_id=video_id, status="running"))
    db.commit()
    db.close()

    response = client.post("/api/hls/batches/library", json={"qualities": ["480p"]})
    assert response.status_code == 202
    assert response.json()["queued_count"] == 0
    assert response.json()["skipped_already_queued"] >= 1


def test_library_batch_does_not_skip_db_only_hls_without_files(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="db_only_hls")
    _mark_db_hls_completed_without_files(video_id)

    response = client.post(
        "/api/hls/batches/library",
        json={"qualities": ["480p"], "skip_existing": True, "force": False, "only_missing_hls": True},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["queued_count"] == 1
    assert payload["skipped_existing_hls"] == 0


def test_hls_diagnostics_reports_db_and_file_mismatch(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="diag_mismatch")
    _mark_db_hls_completed_without_files(video_id)

    response = client.get("/api/hls/diagnostics?details=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["db_completed_but_files_missing"] >= 1
    mismatch = next(item for item in payload["details"]["db_completed_but_files_missing"] if item["video_id"] == video_id)
    assert mismatch["reason"] == "db_completed_but_files_missing"


def test_cancel_library_batch_stops_queued_items(tmp_path: Path, monkeypatch) -> None:
    _install_slow_fake_ffmpeg(monkeypatch, delay_sec=0.6)
    client = make_client(tmp_path)
    _create_video_with_file(tmp_path, stem="cancel_a")
    _create_video_with_file(tmp_path, stem="cancel_b")

    response = client.post("/api/hls/batches/library", json={"qualities": ["480p"]})
    assert response.status_code == 202
    batch_id = response.json()["batch_id"]
    assert batch_id is not None

    time.sleep(0.1)
    cancelled = client.post(f"/api/hls/batches/{batch_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    done = _wait_batch_done(client, batch_id, timeout_sec=6.0)
    assert done["status"] == "cancelled"
    assert done["queued_count"] == 0
    assert done["skipped_count"] >= 1


def test_repair_stale_hls_endpoint_clears_db_only_flags(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="repair_stale")
    _mark_db_hls_completed_without_files(video_id)

    repaired = client.post("/api/hls/repair")
    assert repaired.status_code == 200
    payload = repaired.json()
    assert payload["stale_completed_invalidated"] >= 1

    response = client.post(
        "/api/hls/batches/library",
        json={"qualities": ["480p"], "skip_existing": True, "force": False, "only_missing_hls": True},
    )
    assert response.status_code == 202
    assert response.json()["queued_count"] >= 1


def test_library_batch_auto_repairs_stale_hls_flags(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="auto_repair")
    _mark_db_hls_completed_without_files(video_id)

    response = client.post(
        "/api/hls/batches/library",
        json={"qualities": ["480p"], "skip_existing": True, "force": False, "only_missing_hls": True},
    )
    assert response.status_code == 202
    payload = response.json()
    assert "Auto-repaired stale HLS flags" in payload["message"]
    assert payload["queued_count"] >= 1


def test_has_valid_hls_false_without_hls_folder(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="no_hls_folder")
    from app.config import get_settings
    from app.services.hls_reconciliation_service import has_valid_hls

    assert has_valid_hls(get_settings(), video_id) is False


def test_has_valid_hls_false_when_master_missing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="no_master")
    root = _hls_root(tmp_path, video_id)
    qdir = root / "480p"
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "index.m3u8").write_text("#EXTM3U\n#EXTINF:4.0,\nsegment_000.ts\n", encoding="utf-8")
    (qdir / "segment_000.ts").write_bytes(b"ts")

    from app.config import get_settings
    from app.services.hls_reconciliation_service import has_valid_hls

    assert has_valid_hls(get_settings(), video_id) is False


def test_has_valid_hls_false_when_segments_missing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="missing_segments")
    root = _hls_root(tmp_path, video_id)
    qdir = root / "480p"
    qdir.mkdir(parents=True, exist_ok=True)
    (root / "master.m3u8").write_text("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000\n480p/index.m3u8\n", encoding="utf-8")
    (qdir / "index.m3u8").write_text("#EXTM3U\n#EXTINF:4.0,\nsegment_000.ts\n", encoding="utf-8")

    from app.config import get_settings
    from app.services.hls_reconciliation_service import has_valid_hls

    assert has_valid_hls(get_settings(), video_id) is False


def test_has_valid_hls_true_when_master_index_segment_exist(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="valid_hls")
    _write_valid_hls_tree(tmp_path, video_id)

    from app.config import get_settings
    from app.services.hls_reconciliation_service import has_valid_hls

    assert has_valid_hls(get_settings(), video_id) is True


def test_files_valid_but_db_missing_repairs_status_to_completed(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="fs_valid_db_missing")
    _write_valid_hls_tree(tmp_path, video_id)

    status = client.get(f"/api/videos/{video_id}/hls/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "completed"
    assert payload["master_playlist_url"] == f"/api/videos/{video_id}/hls/master.m3u8"


def test_stale_queued_items_from_non_active_batch_do_not_block_new_batch(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="stale_queue")

    from app.database import SessionLocal
    from app.models import HlsBatch, HlsBatchItem

    db = SessionLocal()
    batch = HlsBatch(status="failed", request_type="library", qualities_csv="480p", skip_existing=True, force=False, only_missing_hls=True)
    db.add(batch)
    db.flush()
    db.add(HlsBatchItem(batch_id=batch.id, video_id=video_id, status="queued"))
    db.commit()
    db.close()

    response = client.post("/api/hls/batches/library", json={"qualities": ["480p"], "skip_existing": True, "force": False, "only_missing_hls": True})
    assert response.status_code == 202
    assert response.json()["queued_count"] >= 1


def test_startup_recovery_resets_pending_and_queued_runtime_rows(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    video_id = _create_video_with_file(tmp_path, stem="startup_recovery")

    from app.database import SessionLocal
    from app.models import HlsBatch, HlsBatchItem, HlsJob
    from app.services.hls_service import recover_hls_runtime_state

    db = SessionLocal()
    batch = HlsBatch(status="running", request_type="library", qualities_csv="480p", skip_existing=True, force=False, only_missing_hls=True)
    db.add(batch)
    db.flush()
    batch_id = batch.id
    db.add(HlsBatchItem(batch_id=batch.id, video_id=video_id, status="queued"))
    db.add(HlsBatchItem(batch_id=batch.id, video_id=video_id, status="running"))
    db.add(HlsJob(video_id=video_id, status="pending"))
    db.add(HlsJob(video_id=video_id, status="running"))
    db.commit()
    db.close()

    recover_hls_runtime_state()

    db = SessionLocal()
    assert db.query(HlsJob).filter(HlsJob.status.in_(["pending", "running"])).count() == 0
    assert db.query(HlsBatchItem).filter(HlsBatchItem.status.in_(["queued", "running"])).count() == 0
    restored_batch = db.query(HlsBatch).filter(HlsBatch.id == batch_id).first()
    assert restored_batch is not None
    assert restored_batch.status == "completed_with_errors"
    db.close()


def test_library_batch_item_status_filter(tmp_path: Path, monkeypatch) -> None:
    _install_fake_ffmpeg(monkeypatch)
    client = make_client(tmp_path)
    _create_video_with_file(tmp_path)
    _create_video_record_without_file(tmp_path, "missing_for_filter")

    response = client.post("/api/hls/batches/library", json={"qualities": ["480p"]})
    batch_id = response.json()["batch_id"]
    assert batch_id is not None
    _wait_batch_done(client, batch_id)

    skipped = client.get(f"/api/hls/batches/{batch_id}?include_items=true&item_status=skipped")
    assert skipped.status_code == 200
    assert all(item["status"] == "skipped" for item in skipped.json()["items"])


