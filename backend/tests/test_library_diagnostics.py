from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.thumbnails import ThumbnailResult
from tests.conftest import make_client


def _insert_video(
    tmp_path: Path,
    *,
    title: str,
    relative_path: str,
    created_at: datetime,
    compatibility_status: str = "unknown",
    media_status: str = "detected_video",
    probe_status: str = "success",
    thumbnail_status: str = "generated",
    probe_error: str | None = None,
    thumbnail_path: str | None = "thumb.jpg",
    thumbnail_error: str | None = None,
    extension: str = ".mp4",
    size: int = 1000,
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
        modified_ts=created_at.timestamp(),
        duration=42.0,
        width=1920,
        height=1080,
        video_codec="h264",
        pixel_format="yuv420p",
        audio_codec="aac",
        container_format="mov,mp4,m4a,3gp,3g2,mj2",
        thumbnail_path=thumbnail_path,
        thumbnail_status=thumbnail_status,
        thumbnail_error=thumbnail_error,
        folder_path="",
        compatibility_status=compatibility_status,
        compatibility_reason="test",
        media_status=media_status,
        probe_status=probe_status,
        probe_error=probe_error,
        indexed_at=created_at,
        created_at=created_at,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()
    return video_id


def test_library_summary_response_shape_and_counts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)

    _insert_video(
        tmp_path,
        title="A",
        relative_path="a.mp4",
        created_at=now,
        compatibility_status="direct_play",
        media_status="detected_video",
        thumbnail_status="generated",
        size=100,
    )
    _insert_video(
        tmp_path,
        title="B",
        relative_path="b.mkv",
        created_at=now,
        compatibility_status="needs_conversion",
        media_status="detected_video",
        thumbnail_status="failed",
        thumbnail_error="ffmpeg failed",
        thumbnail_path=None,
        size=200,
        extension=".mkv",
    )
    _insert_video(
        tmp_path,
        title="C",
        relative_path="c.360",
        created_at=now,
        compatibility_status="unknown",
        media_status="probe_failed_possible_video",
        probe_status="failed",
        probe_error="ffprobe failed",
        thumbnail_status="pending",
        thumbnail_path=None,
        size=300,
        extension=".360",
    )

    import app.scan_status as scan_status
    from app.database import SessionLocal
    from app.models import DuplicateScanRun

    scan_status._state = scan_status.ScanState(  # type: ignore[attr-defined]
        status="completed",
        started_at=now - timedelta(minutes=2),
        finished_at=now - timedelta(minutes=1),
        scanned_files=10,
        detected_videos=2,
        probe_failed=1,
        ignored_non_media=4,
        ignored_excluded=3,
        thumbnail_errors=1,
    )
    scan_status._lock = threading.Lock()  # type: ignore[attr-defined]

    db = SessionLocal()
    db.add(
        DuplicateScanRun(
            mode="strict",
            last_scan_status="completed",
            videos_checked=3,
            candidate_groups_found=2,
            duplicate_candidates_found=4,
            potential_saving=4096,
            last_scan_at=now,
        )
    )
    db.commit()
    db.close()

    response = client.get("/api/library/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["total_indexed"] == 3
    assert data["detected_videos"] == 2
    assert data["probe_failed_possible_video"] == 1
    assert data["direct_play"] == 1
    assert data["needs_conversion"] == 1
    assert data["unknown_compatibility"] == 1
    assert data["thumbnail_generated"] == 1
    assert data["thumbnail_failed"] == 1
    assert data["thumbnail_missing"] == 1
    assert data["total_size"] == 600
    assert data["last_library_scan"]["status"] == "completed"
    assert data["last_duplicate_scan"]["status"] == "completed"
    assert data["last_duplicate_scan"]["candidate_groups_found"] == 2


def test_videos_filter_by_compatibility_media_thumbnail_and_extension(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)

    _insert_video(
        tmp_path,
        title="Direct",
        relative_path="direct.mp4",
        created_at=now,
        compatibility_status="direct_play",
        media_status="detected_video",
        thumbnail_status="generated",
        extension=".mp4",
    )
    _insert_video(
        tmp_path,
        title="Needs conversion",
        relative_path="old.mpg",
        created_at=now,
        compatibility_status="needs_conversion",
        media_status="detected_video",
        thumbnail_status="failed",
        extension=".mpg",
    )
    _insert_video(
        tmp_path,
        title="Probe failed",
        relative_path="broken.360",
        created_at=now,
        compatibility_status="unknown",
        media_status="probe_failed_possible_video",
        probe_status="failed",
        probe_error="broken metadata",
        thumbnail_status="pending",
        thumbnail_path=None,
        extension=".360",
    )

    assert client.get("/api/videos?compatibility_status=needs_conversion").json()[0]["title"] == "Needs conversion"
    assert client.get("/api/videos?media_status=probe_failed_possible_video").json()[0]["title"] == "Probe failed"
    assert client.get("/api/videos?thumbnail_status=failed").json()[0]["title"] == "Needs conversion"
    assert client.get("/api/videos?extension=.mpg").json()[0]["title"] == "Needs conversion"


def test_reprobe_endpoint_updates_metadata(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)
    video_id = _insert_video(
        tmp_path,
        title="Reprobe",
        relative_path="reprobe.mp4",
        created_at=now,
        compatibility_status="unknown",
        media_status="probe_failed_possible_video",
        probe_status="failed",
        probe_error="old error",
    )

    video_file = tmp_path / "videos" / "reprobe.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    from app.media_probe import ProbeResult

    monkeypatch.setattr(
        "app.routes.videos.probe_video",
        lambda _path: ProbeResult(
            success=True,
            has_video_stream=True,
            duration=99.0,
            width=1280,
            height=720,
            video_codec="h264",
            pixel_format="yuv420p",
            audio_codec="aac",
            container_format="mov,mp4,m4a,3gp,3g2,mj2",
        ),
    )

    response = client.post(f"/api/videos/{video_id}/reprobe")
    assert response.status_code == 200
    data = response.json()
    assert data["probe_status"] == "success"
    assert data["media_status"] == "detected_video"
    assert data["video_codec"] == "h264"
    assert data["pixel_format"] == "yuv420p"
    assert data["compatibility_status"] == "direct_play"


def test_reprobe_handles_failure_safely(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)
    video_id = _insert_video(tmp_path, title="Broken", relative_path="broken.mp4", created_at=now)

    video_file = tmp_path / "videos" / "broken.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    from app.media_probe import ProbeResult

    monkeypatch.setattr("app.routes.videos.probe_video", lambda _path: ProbeResult(success=False, error="ffprobe failed"))

    response = client.post(f"/api/videos/{video_id}/reprobe")
    assert response.status_code == 200
    data = response.json()
    assert data["probe_status"] == "failed"
    assert data["media_status"] == "probe_failed_possible_video"
    assert data["compatibility_status"] == "unknown"


def test_thumbnail_regenerate_success(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)
    video_id = _insert_video(
        tmp_path,
        title="Thumb",
        relative_path="thumb.mp4",
        created_at=now,
        thumbnail_status="failed",
        thumbnail_path=None,
        thumbnail_error="old",
    )

    video_file = tmp_path / "videos" / "thumb.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    monkeypatch.setattr(
        "app.routes.videos.generate_thumbnail",
        lambda *_args, **_kwargs: ThumbnailResult(path=Path("thumb_new.jpg"), error=None),
    )

    response = client.post(f"/api/videos/{video_id}/thumbnail/regenerate")
    assert response.status_code == 200
    data = response.json()
    assert data["thumbnail_status"] == "generated"
    assert data["thumbnail_error"] is None
    assert data["thumbnail_url"] == f"/api/videos/{video_id}/thumbnail"


def test_thumbnail_regenerate_handles_ffmpeg_failure_safely(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)
    video_id = _insert_video(tmp_path, title="Thumb fail", relative_path="thumb_fail.mp4", created_at=now)

    video_file = tmp_path / "videos" / "thumb_fail.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    monkeypatch.setattr(
        "app.routes.videos.generate_thumbnail",
        lambda *_args, **_kwargs: ThumbnailResult(path=None, error="ffmpeg failed"),
    )

    response = client.post(f"/api/videos/{video_id}/thumbnail/regenerate")
    assert response.status_code == 200
    data = response.json()
    assert data["thumbnail_status"] == "failed"
    assert data["thumbnail_error"] == "ffmpeg failed"


def test_default_sort_newest_first(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)
    _insert_video(tmp_path, title="Old", relative_path="old.mp4", created_at=now - timedelta(days=2))
    _insert_video(tmp_path, title="New", relative_path="new.mp4", created_at=now - timedelta(hours=1))

    response = client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["title"] == "New"
    assert data[1]["title"] == "Old"

