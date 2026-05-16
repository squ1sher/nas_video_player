from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from tests.conftest import make_client


def _create_video_with_file(tmp_path: Path, *, height: int = 1080, width: int = 1920) -> int:
    videos_dir = tmp_path / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    source_file = videos_dir / "sample.mp4"
    source_file.write_bytes(b"fake-media")

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    video = Video(
        title="Sample",
        filename="sample.mp4",
        relative_path="sample.mp4",
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
        playlist_path.write_text("#EXTM3U\n", encoding="utf-8")
        if segment_pattern is not None:
            segment_path = Path(str(segment_pattern).replace("%03d", "000"))
            segment_path.parent.mkdir(parents=True, exist_ok=True)
            segment_path.write_bytes(b"ts")
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


