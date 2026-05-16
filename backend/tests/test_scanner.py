import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.media_probe import ProbeResult, probe_video
from app.scanner import iter_library_files, scan_video_library
from tests.conftest import make_client, setup_test_db


def test_scanner_iterates_all_regular_files(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"a")
    (tmp_path / "b.360").write_bytes(b"b")
    (tmp_path / "c.txt").write_bytes(b"c")

    results = iter_library_files(tmp_path)
    names = sorted(path.name for path in results)
    assert names == ["a.mp4", "b.360", "c.txt"]


def test_probe_video_fallback_on_error(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffprobe")

    monkeypatch.setattr("subprocess.run", _raise)
    result = probe_video(Path("/tmp/missing.mp4"))

    assert result.success is False
    assert result.error is not None
    assert result.duration is None
    assert result.width is None
    assert result.height is None
    assert result.video_codec is None
    assert result.audio_codec is None


def _insert_video_with_date(tmp_path, title, relative_path, created_at):
    from app.database import SessionLocal
    from app.models import Video
    db = SessionLocal()
    v = Video(
        title=title,
        filename=relative_path.split("/")[-1],
        relative_path=relative_path,
        absolute_path=str(tmp_path / "videos" / relative_path),
        extension=".mp4",
        size=1000,
        modified_ts=1000.0,
        folder_path="",
        compatibility_status="direct_play",
        compatibility_reason="test",
        media_status="detected_video",
        probe_status="success",
        indexed_at=created_at,
        created_at=created_at,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    db.close()
    return v.id


def _build_settings(tmp_path: Path):
    from app.config import Settings

    return Settings(
        VIDEO_LIBRARY_PATH=str(tmp_path / "videos"),
        DATABASE_PATH=str(tmp_path / "data" / "app.db"),
        THUMBNAILS_PATH=str(tmp_path / "thumbnails"),
        CACHE_PATH=str(tmp_path / "cache"),
        LOGS_PATH=str(tmp_path / "logs"),
        MEDIA_DISCOVERY_MODE="probe",
        PROBE_UNKNOWN_EXTENSIONS="true",
    )


def test_probe_unknown_extension_is_indexed(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "clip.360").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=True, duration=12.0, width=1920, height=1080, video_codec="h264", audio_codec="aac", container_format="mp4"),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *args, **kwargs: None)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    settings = _build_settings(tmp_path)
    result = scan_video_library(db, settings)
    videos = db.query(Video).all()
    db.close()

    assert result.detected_videos == 1
    assert len(videos) == 1
    assert videos[0].extension == ".360"
    assert videos[0].media_status == "detected_video"


def test_uppercase_mpg_extension_normalized(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "movie.MPG").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=True, duration=100.0, width=1280, height=720, video_codec="mpeg2video", audio_codec="mp2", container_format="mpeg"),
    )
    monkeypatch.setattr("app.scanner.ensure_thumbnail", lambda *args, **kwargs: None)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    scan_video_library(db, _build_settings(tmp_path))
    video = db.query(Video).first()
    db.close()

    assert video is not None
    assert video.extension == ".mpg"
    assert video.probe_status == "success"


def test_probe_failure_indexes_possible_video_when_allowed(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "unknown.360").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr("app.scanner.probe_video", lambda _p: ProbeResult(success=False, error="ffprobe failed"))

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    result = scan_video_library(db, _build_settings(tmp_path))
    video = db.query(Video).first()
    db.close()

    assert result.probe_failed == 1
    assert video is not None
    assert video.media_status == "probe_failed_possible_video"
    assert video.compatibility_status == "unknown"


def test_probe_success_without_video_stream_is_ignored(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "audio_only.flac").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=False, duration=60.0, audio_codec="flac", container_format="flac"),
    )

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    result = scan_video_library(db, _build_settings(tmp_path))
    count = db.query(Video).count()
    db.close()

    assert result.ignored_non_media >= 1
    assert count == 0


def test_excluded_extensions_are_skipped(tmp_path: Path) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "notes.txt").write_bytes(b"0" * 100)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    result = scan_video_library(db, _build_settings(tmp_path))
    count = db.query(Video).count()
    db.close()

    assert result.ignored_excluded >= 1
    assert count == 0


def test_thumbnail_failure_does_not_remove_indexed_video(tmp_path: Path, monkeypatch) -> None:
    setup_test_db(tmp_path)
    root = tmp_path / "videos"
    root.mkdir(parents=True)
    (root / "clip.mp4").write_bytes(b"0" * 2_000_000)

    monkeypatch.setattr(
        "app.scanner.probe_video",
        lambda _p: ProbeResult(success=True, has_video_stream=True, duration=12.0, width=1920, height=1080, video_codec="h264", audio_codec="aac", container_format="mp4"),
    )

    def _thumb_raise(*args, **kwargs):
        raise RuntimeError("thumbnail failed")

    monkeypatch.setattr("app.scanner.ensure_thumbnail", _thumb_raise)

    from app.database import SessionLocal
    from app.models import Video

    db = SessionLocal()
    result = scan_video_library(db, _build_settings(tmp_path))
    video = db.query(Video).first()
    db.close()

    assert result.thumbnail_errors == 1
    assert video is not None
    assert video.media_status == "detected_video"
    assert video.thumbnail_status == "failed"


def test_api_returns_media_and_compatibility_status(tmp_path: Path) -> None:
    from datetime import timedelta

    client = make_client(tmp_path)
    now = datetime.now(timezone.utc)
    _insert_video_with_date(tmp_path, "Old Video", "old.mp4", now - timedelta(days=10))

    response = client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["media_status"] == "detected_video"
    assert data[0]["compatibility_status"] is not None


def test_default_sort_newest_first(tmp_path: Path) -> None:
    """GET /api/videos must return newest videos first by default."""
    from datetime import timedelta

    client = make_client(tmp_path)

    now = datetime.now(timezone.utc)
    _insert_video_with_date(tmp_path, "Old Video", "old.mp4", now - timedelta(days=10))
    _insert_video_with_date(tmp_path, "New Video", "new.mp4", now - timedelta(days=1))

    response = client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "New Video"
    assert data[1]["title"] == "Old Video"


def test_sort_oldest_first(tmp_path: Path) -> None:
    """GET /api/videos?sort=created_at&order=asc must return oldest first."""
    from datetime import timedelta

    client = make_client(tmp_path)

    now = datetime.now(timezone.utc)
    _insert_video_with_date(tmp_path, "Old Video", "old2.mp4", now - timedelta(days=10))
    _insert_video_with_date(tmp_path, "New Video", "new2.mp4", now - timedelta(days=1))

    response = client.get("/api/videos?sort=created_at&order=asc")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["title"] == "Old Video"
    assert data[1]["title"] == "New Video"
